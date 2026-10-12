r"""Word error rate on the held-out voice corpus, with the current Whisper setup.

    .venv\Scripts\python scripts\voice_wer.py            the held-out test set
    .venv\Scripts\python scripts\voice_wer.py --all      every recorded take
    .venv\Scripts\python scripts\voice_wer.py --no-hotwords

The test set is config/corpus.yaml's `split: test` (every 5th sentence, fixed,
never trained on). Every recorded take of those sentences is transcribed exactly
as a live turn is (irene/stt.py: large-v3-turbo, float16, his vocabulary as
hotwords), normalised (irene/wer.py) and compared. Run it before any fine-tuning
for the baseline, and after, on the same takes.

Writes core/logs/wer-<timestamp>.json with every take's transcript and error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from irene.corpus import DIR, load_sentences  # noqa: E402
from irene.stt import Transcriber  # noqa: E402
from irene.wer import distance, normalize  # noqa: E402

LOGS = HERE.parent / "logs"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="every recorded take, not just the held-out set")
    parser.add_argument("--no-hotwords", action="store_true", help="measure without his vocabulary")
    parser.add_argument("--vocab", help="another vocabulary file (e.g. the previous one, for a before/after)")
    parser.add_argument("--model", help="another Whisper model dir (e.g. a fine-tuned one, for a before/after)")
    args = parser.parse_args()

    sentences = [s for s in load_sentences() if args.all or s["split"] == "test"]
    takes = [(s, path) for s in sentences for path in sorted((DIR / s["id"]).glob("take*.wav"))]
    if not takes:
        print(f"no recorded takes yet for the {'corpus' if args.all else 'held-out set'} - record with Ctrl+Alt+Shift+R first")
        return 1
    stt = Transcriber()
    if args.vocab:
        from irene.stt import vocabulary

        stt.hotwords = " ".join(vocabulary(Path(args.vocab)))
    if args.model:
        stt.model_dir = Path(args.model).resolve()
    if args.no_hotwords:
        stt.hotwords, stt.prompt = None, None
    stt.load()

    errors = words = 0
    by_topic: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    rows = []
    started = time.perf_counter()
    for sentence, path in takes:
        audio, rate = sf.read(path, dtype="float32")
        assert rate == 16000, f"{path}: {rate} Hz"
        heard = stt.transcribe(audio, prompt=not args.no_hotwords)
        ref, hyp = normalize(sentence["text"]), normalize(heard.text)
        e = distance(ref, hyp)
        errors += e
        words += len(ref)
        by_topic[sentence["topic"]][0] += e
        by_topic[sentence["topic"]][1] += len(ref)
        rows.append({"id": sentence["id"], "take": path.stem, "text": sentence["text"], "heard": heard.text, "errors": e, "words": len(ref)})
        if e:
            print(f"  {sentence['id']:10s} {path.stem}: {heard.text!r}  ({e} of {len(ref)})")

    rate = errors / max(1, words)
    print(f"\nWER {rate:.1%} over {len(takes)} takes of {len({s['id'] for s, _ in takes})} sentences ({words} words) - {'all takes' if args.all else 'held-out test set'}, hotwords {'off' if args.no_hotwords else 'on'}")
    for topic, (e, n) in sorted(by_topic.items(), key=lambda kv: -kv[1][0] / max(1, kv[1][1])):
        print(f"  {topic:13s} {e / max(1, n):6.1%}  ({n} words)")
    print(f"({time.perf_counter() - started:.0f} s)")
    LOGS.mkdir(exist_ok=True)
    out = LOGS / f"wer-{time.strftime('%Y-%m-%dT%H-%M-%S')}.json"
    out.write_text(json.dumps({"wer": rate, "takes": len(takes), "words": words, "hotwords": not args.no_hotwords, "vocab": args.vocab, "model": str(stt.model_dir), "rows": rows}, indent=1), encoding="utf-8")
    print(f"log: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
