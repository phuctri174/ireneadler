r"""Where the time goes, stage by stage, with the real models - no microphone, no
running core, no OS input.

  .venv\Scripts\python scripts\profile_latency.py [label] [--no-tts] [--long]

  VAD tail / STT    his saved voice turns (voice_data/turns) replayed block by
                    block through Silero and the real Endpointer, with Whisper's
                    real first look at the check - under the old rules (check at
                    0.45 s, wait out the tail) and the new (check at 0.3 s, answer
                    from that look when the sentence clearly ended): how long after
                    his last voiced block his words are known
  LLM               a scripted conversation through Conversation's own prompt
                    builder against the running Ollama: prefill, first token, first
                    spoken phrase (clause), and for tool calls the moment the tool's
                    name is known and the call is complete. Small talk that quick.py
                    answers, and commands fast.direct_call takes, skip the model.
  TTS               the live engine (Chatterbox-Turbo) on each first phrase
  --long            a 24-turn session: prefill at the end vs the start

Writes core/logs/profile-<label>.json and prints the summary.
"""
from __future__ import annotations

import asyncio
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

CORE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CORE))
LOGS = CORE / "logs"
TURNS = CORE / "voice_data" / "turns"

# (what he says, kind)
SCRIPT = [
    ("Hey Irene, how's it going?", "small"),
    ("What are you doing?", "small"),
    ("Haha, nice.", "chat"),
    ("What's the capital of Japan?", "chat"),
    ("Why is the sky blue?", "chat"),
    ("What time is it?", "command"),
    ("Set a timer for ten minutes for the tea.", "command"),
    ("Turn it up a bit.", "command"),
    ("Thanks, Irene.", "small"),
    ("Research how kendo dan grades work.", "research"),
    ("I'm a bit tired today.", "chat"),
    ("Tell me a joke.", "chat"),
    ("Good night.", "small"),
]
_NAME = re.compile(r'"name"\s*:\s*"(\w+)"')


def vram() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return -1


def med(values) -> float:
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 1) if values else float("nan")


def p90(values) -> float:
    values = sorted(v for v in values if v is not None)
    return round(values[min(len(values) - 1, int(0.9 * len(values)))], 1) if values else float("nan")


# ---- wake, VAD tail, STT ------------------------------------------------------


def endpoint(audio, probs, t, check_after: float, early_rules: bool, quick) -> dict:
    """One saved turn through the real Endpointer, the check answered by a real
    Whisper first look (its time counts: the mic keeps running meanwhile)."""
    from irene import wake
    from irene.listen import BLOCK, Endpointer, complete_phrase, pitch_falls

    ep = Endpointer(max_silence_s=3.0, min_silence_s=0.9, check_after_s=check_after)
    blocks = [audio[i : i + BLOCK] for i in range(0, len(audio) - BLOCK + 1, BLOCK)]
    # silence after what was saved, in case the rules wait longer than the recording
    blocks += [np.zeros(BLOCK, np.float32)] * 100
    probs = list(probs) + [0.0] * 100
    last_voiced = max((i for i, p in enumerate(probs) if p >= 0.5), default=0)
    pending = None  # (block index the verdict lands at, ended, early, heard)
    draft = None
    for i, (block, prob) in enumerate(zip(blocks, probs)):
        if pending and i >= pending[0]:
            ep.verdict(pending[1] or pending[2], ep.generation, now=pending[2])
            draft = pending[3] if pending[2] else None
            pending = None
        for e in ep.feed(block, prob):
            if e.kind == "check":
                heard = t.transcribe(e.audio, beam_size=1)
                complete = complete_phrase(heard.text)
                ended = complete and (heard.text.rstrip().endswith("?") or pitch_falls(e.audio))
                found = wake.find(heard.text, awake=True)
                small = quick.match(found.rest if found and found.rest else heard.text) is not None
                early = early_rules and complete and t.confident(heard) and (ended or small)
                pending = (i + 1 + int(heard.ms / 1000 / (BLOCK / 16000)), ended, early, heard)
            if e.kind == "end":
                end_ms = (i + 1 - (last_voiced + 1)) * BLOCK / 16000 * 1000
                if draft is not None:
                    return {"words_known_ms": end_ms, "early": True, "small": quick.match(draft.text) is not None, "text": draft.text}
                final = t.transcribe(e.audio)
                return {"words_known_ms": end_ms + final.ms, "early": False, "small": quick.match(final.text) is not None, "text": final.text}
    return {"words_known_ms": None, "early": False, "small": False, "text": ""}


def voice_stages(t, quick, limit: int = 40) -> dict:
    from irene.listen import BLOCK, SAMPLE_RATE, Vad

    wavs = sorted(TURNS.glob("*/*.wav"))[-limit:]
    if not wavs:
        return {"n": 0}
    vad = Vad()
    runs = []
    for path in wavs:
        audio, sr = sf.read(path, dtype="float32")
        assert sr == SAMPLE_RATE
        vad.reset()
        probs = [vad(audio[i : i + BLOCK]) for i in range(0, len(audio) - BLOCK + 1, BLOCK)]
        full = t.transcribe(audio)
        old = endpoint(audio, probs, t, 0.45, False, quick)
        new = endpoint(audio, probs, t, 0.3, True, quick)
        runs.append({"file": path.name, "stt_ms": full.ms, "old": old, "new": new})
    out = {"n": len(runs), "stt_ms": med(r["stt_ms"] for r in runs), "stt_p90_ms": p90(r["stt_ms"] for r in runs)}
    for rules in ("old", "new"):
        known = [r[rules]["words_known_ms"] for r in runs]
        out[f"{rules}_words_known_ms"] = med(known)
        out[f"{rules}_words_known_p90_ms"] = p90(known)
        small = [r[rules]["words_known_ms"] for r in runs if r[rules]["small"]]
        out[f"{rules}_small_talk_words_known_ms"] = med(small)
    out["new_early_share"] = f"{sum(r['new']['early'] for r in runs)}/{len(runs)}"
    out["runs"] = runs
    return out


# ---- LLM ----------------------------------------------------------------------


async def llm_stage(voice=None, script=SCRIPT) -> list[dict]:
    from irene import fast, quick as quick_mod
    from irene.brain import Conversation, StreamingReply
    from irene.llm import Ollama

    llm = Ollama()
    await llm.warm()
    conv = Conversation(llm)
    conv.entered({"name": "chess", "doing": "playing chess against myself", "scene": "a chessboard", "backstory": ["x", "y", "z"]})
    q = quick_mod.QuickReplies([{"name": "chess", "doing": "playing chess against myself"}])
    q.audio = {line: None for line in q.lines()}
    rows = []
    for text, kind in script:
        if q.match(text) and q.answer(text, 20, entrance="chess"):
            rows.append({"said": text, "kind": kind, "path": "quick"})
            print(f"  {text[:40]:40} quick reply, no model", flush=True)
            continue
        direct = fast.direct_call(text)
        if direct:
            rows.append({"said": text, "kind": kind, "path": "direct", "tool": _NAME.search(direct).group(1)})
            print(f"  {text[:40]:40} direct -> {rows[-1]['tool']}, no model", flush=True)
            continue
        messages = conv.begin(text)
        stream = StreamingReply()
        t0 = time.perf_counter()
        first_token = first_line = named = None
        first_text = ""
        async for chunk in llm.chat_stream(messages):
            now = time.perf_counter()
            first_token = first_token or now
            lines = stream.feed(chunk)
            if lines and first_line is None:
                first_line, first_text = now, lines[0].text
            if named is None and stream.is_tool_call and _NAME.search(stream.raw):
                named = now
        done = time.perf_counter()
        if first_line is None and (rest := stream.finish()):
            first_line, first_text = done, rest[0].text
        conv.history.append({"role": "assistant", "content": stream.raw})
        s = llm.last
        ms = lambda x: round((x - t0) * 1000) if x else None  # noqa: E731
        rows.append({
            "said": text, "kind": kind, "path": "model",
            "prompt_tokens": s.get("prompt_tokens"), "prefill_ms": s.get("prefill_ms"),
            "first_token_ms": ms(first_token), "first_phrase_ms": ms(first_line), "first_phrase": first_text,
            "tool_named_ms": ms(named), "call_done_ms": ms(done) if stream.is_tool_call else None,
            "tool": (_NAME.search(stream.raw).group(1) if stream.is_tool_call and _NAME.search(stream.raw) else None),
            "out_tokens": s.get("output_tokens"), "tok_s": s.get("tok_s"),
        })
        r = rows[-1]
        print(f"  {text[:40]:40} prefill {r['prefill_ms']:>4} ms  first phrase {r['first_phrase_ms']} ms  tool {r['tool']} named {r['tool_named_ms']} done {r['call_done_ms']}  {r['tok_s']} tok/s", flush=True)
        if stream.is_tool_call:
            # the tool's result, as a turn would get it (not run: no OS actions here)
            conv.history.append({"role": "user", "content": f"[tool result for {r['tool']}] ok"})
            conv.history.append({"role": "assistant", "content": "<speak>Done!</speak>"})
        # as a real turn ends: the history read ahead while she talks
        conv.compact()
        conv.warm_cache()
        await conv._warm
    await llm.close()
    return rows


async def long_session() -> dict:
    from irene.brain import Conversation
    from irene.llm import Ollama

    llm = Ollama()
    conv = Conversation(llm)
    prefill = []
    for n in range(24):
        messages = conv.begin(f"Tell me one fun fact about the number {n + 3}, in one sentence.")
        raw = ""
        async for chunk in llm.chat_stream(messages):
            raw += chunk
        conv.history.append({"role": "assistant", "content": raw})
        prefill.append(llm.last.get("prefill_ms"))
        conv.compact()
        conv.warm_cache()
        await conv._warm
    await llm.close()
    return {"first_5_prefill_ms": med(prefill[:5]), "last_5_prefill_ms": med(prefill[-5:]), "all": prefill}


# ---- TTS ----------------------------------------------------------------------


def tts_stage(voice, phrases: list[str]) -> dict:
    from irene.tts import chunks

    firsts = []
    for text in phrases:
        chunk = chunks(text, first=True)[0]
        s = time.perf_counter()
        voice.all(chunk)
        firsts.append((time.perf_counter() - s) * 1000)
    return {"first_chunk_ms": med(firsts), "first_chunk_p90_ms": p90(firsts), "n": len(firsts)}


def main() -> None:
    from irene import entrances, quick as quick_mod, stt

    label = next((a for a in sys.argv[1:] if not a.startswith("--")), "now")
    report: dict = {"label": label, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    t = stt.Transcriber()
    t.load()
    q = quick_mod.QuickReplies(entrances.load_registry())
    print("VAD tail / STT: replaying saved voice turns (old rules and new)...", flush=True)
    report["voice"] = voice_stages(t, q)
    voice = None
    if "--no-tts" not in sys.argv:
        from irene.voice import Voice

        voice = Voice("turbo")
    report["vram_all_mb"] = vram()
    print("LLM: a scripted conversation...", flush=True)
    rows = asyncio.run(llm_stage(voice))
    report["llm"] = rows
    model = [r for r in rows if r["path"] == "model"]
    talk = [r for r in model if not r["tool"]]
    report["llm_summary"] = {
        "prefill_ms": med(r["prefill_ms"] for r in model),
        "first_token_ms": med(r["first_token_ms"] for r in model),
        "first_phrase_ms": med(r["first_phrase_ms"] for r in talk),
        "tool_named_ms": med(r["tool_named_ms"] for r in model if r["tool"]),
        "call_done_ms": med(r["call_done_ms"] for r in model if r["tool"]),
        "tok_s": med(r["tok_s"] for r in model),
        "skipped_model": sum(r["path"] != "model" for r in rows),
    }
    if voice is not None:
        report["tts_first_phrases"] = tts_stage(voice, [r["first_phrase"] for r in talk if r.get("first_phrase")])
    if "--long" in sys.argv:
        print("a 24-turn session...", flush=True)
        report["long_session"] = asyncio.run(long_session())
    LOGS.mkdir(exist_ok=True)
    (LOGS / f"profile-{label}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("llm",)}
    summary["voice"] = {k: v for k, v in report["voice"].items() if k != "runs"}
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
