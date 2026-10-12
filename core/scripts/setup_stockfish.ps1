# One-time setup of Irene's chess engine (core/irene/chess_game.py drives it over UCI).
#
#   powershell -ExecutionPolicy Bypass -File core\scripts\setup_stockfish.ps1
#
# Stockfish, the official Windows x86-64 universal build (it picks AVX2/AVX-512 itself),
# into C:\irene\stockfish - beside SearXNG, outside the repo: it is ~100 MB with its
# network inside. Downloaded once, here; at runtime it is a local process, never a
# network call. config\chess.yaml names the path and her strength.

$ErrorActionPreference = "Stop"
$tag = "sf_19"
$dir = "C:\irene\stockfish"
$exe = "$dir\stockfish.exe"
$url = "https://github.com/official-stockfish/Stockfish/releases/download/$tag/stockfish-windows-x86-64-universal.zip"

if (-not (Test-Path $exe)) {
    New-Item -ItemType Directory -Force $dir | Out-Null
    $zip = Join-Path $env:TEMP "stockfish-$tag.zip"
    Write-Host "downloading Stockfish ($tag)..."
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $unpacked = Join-Path $env:TEMP "stockfish-$tag"
    if (Test-Path $unpacked) { Remove-Item -Recurse -Force $unpacked }
    Expand-Archive -Path $zip -DestinationPath $unpacked
    $found = Get-ChildItem -Path $unpacked -Recurse -Filter "stockfish*.exe" | Select-Object -First 1
    if (-not $found) { throw "no stockfish*.exe in $url" }
    Copy-Item $found.FullName $exe
    Remove-Item -Recurse -Force $unpacked
    Remove-Item -Force $zip
}

# it must answer UCI and play a move, through the same driver core uses (PowerShell's
# pipe into a native exe adds an encoding prefix, and Stockfish rejects the command)
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
& $python -c "import chess, chess.engine; e = chess.engine.SimpleEngine.popen_uci(r'$exe'); m = e.play(chess.Board(), chess.engine.Limit(time=0.1)).move; print('Stockfish ready:', r'$exe', '(' + e.id['name'] + ', first move ' + str(m) + ')'); e.quit()"
if ($LASTEXITCODE -ne 0) { throw "$exe did not answer UCI" }
