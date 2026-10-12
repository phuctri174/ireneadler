# One-time download of every model Irene runs. None of them is in the repo (they are
# gigabytes, and each has its own licence); after this, nothing is fetched at runtime.
#
#   powershell -ExecutionPolicy Bypass -File core\scripts\setup_models.ps1
#
# Needs: core\.venv with requirements.txt installed (see README), Ollama installed.
#
#   Whisper large-v3-turbo (CTranslate2, float16)  -> core\models\whisper-large-v3-turbo   ~1.6 GB
#   ECAPA-TDNN speaker embeddings (SpeechBrain)     -> core\models\ecapa-voxceleb           ~86 MB
#   Kokoro-82M (fallback voice)                     -> Hugging Face cache                   ~330 MB
#   Chatterbox-Turbo (her voice)                    -> Hugging Face cache                   ~1.5 GB
#   gemma3:12b (the language model)                 -> Ollama                               ~8 GB
#   Stockfish 19 (her chess engine)                 -> C:\irene\stockfish   (setup_stockfish.ps1)
#   SearXNG (her search engine, optional)           -> C:\irene\searxng-*   (setup_searxng.ps1)
# The MediaPipe hand and pose models and their WASM ARE committed (hud\public\mediapipe):
# the HUD never loads them from a CDN.

$ErrorActionPreference = "Stop"
$core = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $core ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "no core\.venv yet - create it and install requirements.txt first (README)" }

function Fetch([string]$repo, [string]$dir) {
    $target = Join-Path $core $dir
    if (Test-Path (Join-Path $target "*")) { Write-Host "have $dir"; return }
    Write-Host "downloading $repo -> $dir"
    & $python -c "from huggingface_hub import snapshot_download; snapshot_download('$repo', local_dir=r'$target')"
    if ($LASTEXITCODE -ne 0) { throw "download of $repo failed" }
}

Fetch "mobiuslabsgmbh/faster-whisper-large-v3-turbo" "models\whisper-large-v3-turbo"
Fetch "speechbrain/spkrec-ecapa-voxceleb" "models\ecapa-voxceleb"

Write-Host "caching Kokoro-82M and Chatterbox-Turbo (Hugging Face cache)"
& $python -c "from huggingface_hub import snapshot_download as s; s('hexgrad/Kokoro-82M'); s('ResembleAI/chatterbox-turbo')"
if ($LASTEXITCODE -ne 0) { throw "voice model download failed" }

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "pulling gemma3:12b"
    ollama pull gemma3:12b
} else {
    Write-Warning "Ollama isn't installed (https://ollama.com) - install it, then: ollama pull gemma3:12b"
}

& (Join-Path $PSScriptRoot "setup_stockfish.ps1")
Write-Host "Models ready. Optional: core\scripts\setup_searxng.ps1 for her own search engine."
