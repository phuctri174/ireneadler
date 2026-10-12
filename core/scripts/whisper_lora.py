r"""LoRA fine-tune of whisper-large-v3-turbo on his voice corpus - adopted only if it wins.

    .venv\Scripts\python scripts\whisper_lora.py                 train, convert, measure
    .venv\Scripts\python scripts\whisper_lora.py --adopt         ... and switch to it if it wins
    .venv\Scripts\python scripts\whisper_lora.py --max-steps 3   a smoke run of the pipeline

1. Trains a LoRA adapter on every recorded take of the TRAINING sentences
   (config/corpus.yaml split: train). The held-out test sentences are never read.
2. Merges it into the base weights and converts to CTranslate2 float16 (the only
   compute type sm_120 runs) in core/models/whisper-large-v3-turbo-his.
3. Measures WER on the held-out set with the current model and with the new one,
   both through scripts/voice_wer.py - the same transcription path as a live turn
   (hotwords on). --adopt points config/voice.yaml at the new model only if its WER
   is lower; otherwise nothing changes.

The base weights for training (Hugging Face format) are fetched once, at setup, into
core/models/whisper-large-v3-turbo-hf - never at runtime.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = HERE.parent
sys.path.insert(0, str(CORE))

from irene.corpus import DIR, load_sentences  # noqa: E402

HF_DIR = CORE / "models" / "whisper-large-v3-turbo-hf"
OUT_DIR = CORE / "models" / "whisper-large-v3-turbo-his"
VOICE_YAML = CORE.parent / "config" / "voice.yaml"
LOGS = CORE / "logs"


def train_takes() -> list[tuple[Path, str]]:
    """(wav, its sentence) for every take of a TRAINING sentence - never a test one."""
    out = []
    for s in load_sentences():
        if s.get("split") != "train":
            continue
        out += [(p, s["text"]) for p in sorted((DIR / s["id"]).glob("take*.wav"))]
    return out


def fetch_base() -> None:
    if (HF_DIR / "model.safetensors").exists():
        return
    import os

    # the core keeps the hub offline once imported: this one-time setup fetch runs apart
    print("fetching openai/whisper-large-v3-turbo (HF weights, once) ...")
    code = (
        "from huggingface_hub import snapshot_download; "
        f"snapshot_download('openai/whisper-large-v3-turbo', local_dir={str(HF_DIR)!r}, allow_patterns=['*.json', '*.safetensors', '*.txt'])"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ, "HF_HUB_OFFLINE": "0"})


def train(args) -> Path:
    import numpy as np
    import soundfile as sf
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    takes = train_takes()
    if not takes:
        raise SystemExit("no recorded training takes - record with Ctrl+Alt+Shift+R first")
    print(f"training on {len(takes)} takes of {len({t for _, t in takes})} training sentences (held-out set untouched)")
    random.seed(0)
    processor = WhisperProcessor.from_pretrained(HF_DIR, language="en", task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(HF_DIR, torch_dtype=torch.float32)
    model.config.forced_decoder_ids = None
    model.generation_config.forced_decoder_ids = None
    lora = LoraConfig(r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.05, target_modules=["q_proj", "k_proj", "v_proj", "out_proj"], bias="none")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    model.to("cuda")
    model.train()

    prefix = processor.tokenizer.convert_tokens_to_ids(["<|startoftranscript|>", "<|en|>", "<|transcribe|>", "<|notimestamps|>"])
    eot = processor.tokenizer.eos_token_id

    def batch(items):
        feats, labels = [], []
        for path, text in items:
            audio, rate = sf.read(path, dtype="float32")
            assert rate == 16000, path
            if args.augment:
                audio = audio * np.float32(random.uniform(0.5, 1.3))
                audio = audio + np.random.normal(0, random.uniform(0, 0.004), audio.shape).astype(np.float32)
            feats.append(processor.feature_extractor(audio, sampling_rate=16000, return_tensors="pt").input_features[0])
            labels.append(prefix + processor.tokenizer.encode(" " + text.strip(), add_special_tokens=False) + [eot])
        width = max(len(l) for l in labels)
        dec_in = torch.full((len(labels), width - 1), eot, dtype=torch.long)
        target = torch.full((len(labels), width - 1), -100, dtype=torch.long)
        for k, l in enumerate(labels):
            dec_in[k, : len(l) - 1] = torch.tensor(l[:-1])
            target[k, : len(l) - 1] = torch.tensor(l[1:])
            target[k, : len(prefix) - 1] = -100  # the prompt tokens are given, not learned
        return torch.stack(feats).to("cuda"), dec_in.to("cuda"), target.to("cuda")

    optim = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.01)
    steps = args.max_steps or args.epochs * ((len(takes) + args.batch - 1) // args.batch)
    sched = torch.optim.lr_scheduler.OneCycleLR(optim, max_lr=args.lr, total_steps=steps, pct_start=0.1)
    started = time.perf_counter()
    step = 0
    while step < steps:
        random.shuffle(takes)
        for i in range(0, len(takes), args.batch):
            feats, dec_in, target = batch(takes[i : i + args.batch])
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = model(input_features=feats, decoder_input_ids=dec_in, labels=None).logits
                loss = torch.nn.functional.cross_entropy(loss.float().transpose(1, 2), target, ignore_index=-100)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optim.step()
            sched.step()
            optim.zero_grad(set_to_none=True)
            step += 1
            if step % 10 == 0 or step == steps:
                print(f"  step {step}/{steps}  loss {loss.item():.3f}  ({time.perf_counter() - started:.0f} s)")
            if step >= steps:
                break

    merged_dir = CORE / "models" / "whisper-lora-merged"
    shutil.rmtree(merged_dir, ignore_errors=True)
    model = model.merge_and_unload()
    model.save_pretrained(merged_dir)
    processor.save_pretrained(merged_dir)
    return merged_dir


def convert(merged_dir: Path) -> None:
    from ctranslate2.converters import TransformersConverter

    shutil.rmtree(OUT_DIR, ignore_errors=True)
    TransformersConverter(str(merged_dir), copy_files=["tokenizer.json", "preprocessor_config.json"]).convert(str(OUT_DIR), quantization="float16")
    shutil.rmtree(merged_dir, ignore_errors=True)
    print(f"converted: {OUT_DIR}")


def wer(model: Path | None) -> float:
    cmd = [sys.executable, str(HERE / "voice_wer.py")] + (["--model", str(model)] if model else [])
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}).stdout
    line = next(l for l in out.splitlines() if l.startswith("WER "))
    print("  " + line)
    return float(re.match(r"WER ([\d.]+)%", line).group(1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--max-steps", type=int, default=0, help="stop after this many steps (a smoke run)")
    parser.add_argument("--augment", action="store_true", help="random gain and a little noise per take")
    parser.add_argument("--adopt", action="store_true", help="switch config/voice.yaml to the new model if its WER is lower")
    args = parser.parse_args()

    fetch_base()
    convert(train(args))
    print("held-out WER, current model:")
    before = wer(None)
    print("held-out WER, fine-tuned:")
    after = wer(OUT_DIR)
    wins = after < before
    LOGS.mkdir(exist_ok=True)
    (LOGS / f"lora-{time.strftime('%Y-%m-%dT%H-%M-%S')}.json").write_text(
        json.dumps({"before": before, "after": after, "wins": wins, "args": vars(args), "takes": len(train_takes())}, indent=1), encoding="utf-8")
    print(f"\nWER {before:.1f}% -> {after:.1f}%: {'the fine-tune WINS' if wins else 'no better - keeping the current model'}")
    if wins and args.adopt:
        text = VOICE_YAML.read_text(encoding="utf-8")
        text = re.sub(r"(?m)^(\s*model_dir:\s*).*$", r"\1models/whisper-large-v3-turbo-his", text, count=1)
        VOICE_YAML.write_text(text, encoding="utf-8")
        print("adopted: config/voice.yaml stt.model_dir -> models/whisper-large-v3-turbo-his (restart Irene)")
    elif wins:
        print("run again with --adopt to switch to it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
