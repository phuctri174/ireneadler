# One-time setup of Irene's own SearXNG (tools/research.py starts it on demand).
#
#   powershell -ExecutionPolicy Bypass -File core\scripts\setup_searxng.ps1
#
# Native Python, no Docker (Docker Desktop needs WSL for Linux containers). Source
# in C:\irene\searxng-src, its own venv in C:\irene\searxng-venv - never core's venv.
# Settings: config\searxng\settings.yml (127.0.0.1:8888 only, JSON on). The pwd
# stub in config\searxng\shim lets it import on Windows.

$ErrorActionPreference = "Stop"
$src = "C:\irene\searxng-src"
$venv = "C:\irene\searxng-venv"
$python = (Get-Command python -ErrorAction Stop).Source

if (-not (Test-Path "$src\searx")) {
    # a few Unix-only template files have ':' in their names; they aren't needed
    git -c core.longpaths=true -c core.protectNTFS=false clone --depth 1 https://github.com/searxng/searxng.git $src
}
if (-not (Test-Path "$venv\Scripts\python.exe")) {
    & $python -m venv $venv
}
& "$venv\Scripts\python.exe" -m pip install --quiet -r "$src\requirements.txt" tzdata
Write-Host "SearXNG ready: $src (venv $venv). Irene starts it on 127.0.0.1:8888 when she first researches."
