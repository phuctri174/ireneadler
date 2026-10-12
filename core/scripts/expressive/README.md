# Expressive voice candidates

Six lines (`lines.json`: a question, excitement, a joke, sympathy, a surprised
reaction, a calm explanation) rendered by each candidate to
`core/voice_samples/expressive/<model>/` (gitignored), then measured by
`metrics.py`: F0 standard deviation (Hz and semitones, Praat pitch, voiced frames)
as the "not monotone" number, time to first audio, peak VRAM.

Nothing here is used at runtime - Irene still speaks with Kokoro until one is picked.

| script | model | where it runs |
|---|---|---|
| `render_kokoro.py` | Kokoro af_bella, before and with the quick wins | core venv |
| `render_chatterbox.py chatterbox` | Chatterbox 0.5B, cloned from `voice_samples/af_bella.wav`, emotion dial per line | candidates venv |
| `render_chatterbox.py chatterbox_turbo` | Chatterbox-Turbo 350M, cloned, `[laugh]`/`[sigh]`/`[gasp]` tags | candidates venv |
| `render_orpheus.py` | Orpheus 3B Q4_K_M via local Ollama + SNAC, voice "tara", `<laugh>` tags | candidates venv |
| `cartoon.py` | original cartoon mode: af_bella, pitch + formant shift | core venv |
| `metrics.py` | the table | core venv |

## Candidates venv (outside the repo, `%USERPROFILE%\irene-tts\chatterbox`)

```
py -3.12 -m venv chatterbox
chatterbox\Scripts\python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
chatterbox\Scripts\python -m pip install chatterbox-tts --no-deps
chatterbox\Scripts\python -m pip install conformer diffusers librosa numpy omegaconf pyloudnorm resemble-perth s3tokenizer safetensors soundfile transformers==5.2.0 snac httpx
```

`--no-deps` because chatterbox-tts pins torch 2.6, which has no sm_120 (RTX 50) kernels.

## Orpheus in Ollama

```
huggingface-cli download isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF orpheus-3b-0.1-ft-q4_k_m.gguf --local-dir orpheus
# Modelfile: FROM ./orpheus-3b-0.1-ft-q4_k_m.gguf / TEMPLATE """{{ .Prompt }}"""
ollama create orpheus-3b-q4 -f Modelfile
```
