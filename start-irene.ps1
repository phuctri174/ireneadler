# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 phuctri174
# Start Irene: core (Python backend) and the HUD (Tauri dev), each in its own window.
#
#   powershell -ExecutionPolicy Bypass -File .\start-irene.ps1        normal
#   powershell -ExecutionPolicy Bypass -File .\start-irene.ps1 -Dev   test hooks on
#
# Stops any previous run first: whatever listens on the HUD's dev port (1420) or
# core's socket (8765), any python still running irene.app, plus a leftover HUD
# process - a stale HUD keeps holding the global hotkeys and the new one then fails
# with "HotKey already registered". Logs RAM/VRAM before and after core starts.

param([switch]$Dev)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$corePort = 8765
$hudPort = 1420

function Stop-PortOwner([int]$port) {
    $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $owners) {
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  port $port held by $($proc.ProcessName) (pid $id) - stopping"
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }
}

function Write-StoppedRecord([string]$who, [int]$id) {
    # its exit record, written for it: a core or HUD this script stops is not a crash. Without
    # it the next start finds "unknown - no exit record" - the verdict a real, unexplained
    # death gets (irene/lifeline.py) - and a launch looked exactly like one
    $record = '{"at": "' + (Get-Date -Format "yyyy-MM-ddTHH:mm:ss") + '", "who": "' + $who + '", "pid": ' + $id +
        ', "event": "exit", "reason": "stopped by start-irene.ps1 (a new run)"}'
    $exits = Join-Path $root "core\logs\exits.jsonl"
    try {
        [System.IO.File]::AppendAllText($exits, $record + "`n", (New-Object System.Text.UTF8Encoding($false)))
    } catch {}
}

function Wait-Port([int]$port, [int]$seconds) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Write-Memory([string]$when) {
    # RAM from Windows; VRAM from the GPU adapter counter (nvidia-smi misreads under WDDM)
    $os = Get-CimInstance Win32_OperatingSystem
    $totalGb = $os.TotalVisibleMemorySize / 1MB
    $usedGb = $totalGb - $os.FreePhysicalMemory / 1MB
    $vram = "?"
    try {
        $bytes = (Get-Counter "\GPU Adapter Memory(*)\Dedicated Usage" -ErrorAction Stop).CounterSamples |
            Measure-Object -Property CookedValue -Maximum | Select-Object -ExpandProperty Maximum
        $vram = "{0:N1} GB" -f ($bytes / 1GB)
    } catch {}
    $top = Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 3 |
        ForEach-Object { "$($_.ProcessName) $([int]($_.WorkingSet64 / 1MB)) MB" }
    Write-Host ("  memory {0}: RAM {1:N1}/{2:N0} GB, VRAM {3} (top: {4})" -f $when, $usedGb, $totalGb, $vram, ($top -join ", "))
}

function Test-Ollama {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

Write-Host "Irene: stopping any previous run"
# the windows a previous run opened (they stay open to show their logs); matched by
# the command this script gave them, since a terminal host hides their titles
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "WindowTitle = 'Irene (core|HUD)'" } |
    ForEach-Object {
        Write-Host "  old Irene window (pid $($_.ProcessId)) - closing"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
# the keeper first (core/scripts/keeper.py): it would start a stopped core again
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "keeper\.py" } |
    ForEach-Object {
        Write-Host "  old core keeper (pid $($_.ProcessId)) - stopping"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Get-Process -Name "tauri-app" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  leftover HUD (pid $($_.Id)) - stopping"
    Write-StoppedRecord "hud" $_.Id
    Stop-Process -Id $_.Id -Force
}
# every core process (the venv's python.exe is a launcher with the real interpreter as
# its child - both carry the command line) gets its exit record before it goes
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "-m irene\.app" } |
    ForEach-Object { Write-StoppedRecord "core" $_.ProcessId }
Stop-PortOwner $hudPort
Stop-PortOwner $corePort
# a core that never got its port (still loading, or wedged) holds GBs of RAM and
# VRAM without listening anywhere: match it by its command line
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "-m irene\.app" } |
    ForEach-Object {
        Write-Host "  stale core (pid $($_.ProcessId), $([int]($_.WorkingSetSize / 1MB)) MB) - stopping"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
foreach ($port in $hudPort, $corePort) {
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
    }
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "port $port is still in use; close whatever holds it and run again"
    }
}

Write-Memory "before start"

Write-Host "Irene: checking Ollama"
# An Ollama left running from before loaded its model when the card was fuller:
# twice (Rounds 6, 7) it had spilled out of VRAM - first audio 4 s instead of
# 0.9 s. A fresh one every launch places the model while there is room, and with
# the flash-attention/q8 settings below. Costs a few seconds of model load.
if (Test-Ollama) {
    Write-Host "  restarting it, so the model loads fresh into VRAM"
    Get-Process -Name "ollama app", "ollama", "llama-server" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddSeconds(10)
    while ((Test-Ollama) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
}
if (-not (Test-Ollama)) {
    Write-Host "  not answering - starting 'ollama serve'"
    # flash attention + an 8-bit KV cache: about half the cache's VRAM. With
    # Whisper, the voice and the HUD all on the GPU, the card was full (15.3 of
    # 16 GB) and generation halved; also set for the user, so the tray app has them
    $env:OLLAMA_FLASH_ATTENTION = "1"
    $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
    Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(30)
    while (-not (Test-Ollama) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (-not (Test-Ollama)) {
        Write-Warning "Ollama still not answering; core will start without a warm model"
    }
}

$python = Join-Path $root "core\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "core venv missing: $python" }

Write-Host "Irene: starting core (its own window)"
$devFlag = if ($Dev) { "`$env:IRENE_DEV = '1'; " } else { "" }
# core runs under its keeper (core/scripts/keeper.py): if it dies of anything but a chosen
# exit (Ctrl+C, this window closed), it is started again - and a lecture capture resumes
$coreCommand = "`$Host.UI.RawUI.WindowTitle = 'Irene core'; `$env:PYTHONIOENCODING = 'utf-8'; $devFlag& '$python' scripts\keeper.py"
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-NoProfile", "-Command", $coreCommand -WorkingDirectory (Join-Path $root "core")
if (Wait-Port $corePort 120) {
    Write-Host "  core listening on ws://127.0.0.1:$corePort/ws"
    Write-Memory "with core up"
} else {
    Write-Warning "core did not open port $corePort within 120s - check the 'Irene core' window"
}

Write-Host "Irene: starting HUD (its own window)"
$hudCommand = "`$Host.UI.RawUI.WindowTitle = 'Irene HUD'; npm run tauri dev"
Start-Process -FilePath "powershell.exe" -ArgumentList "-NoExit", "-NoProfile", "-Command", $hudCommand -WorkingDirectory (Join-Path $root "hud")
if (Wait-Port $hudPort 60) {
    Write-Host "  HUD dev server on http://localhost:$hudPort - the app window follows once it compiles"
} else {
    Write-Warning "HUD dev server did not open port $hudPort within 60s - check the 'Irene HUD' window"
}

Write-Host "Irene: up. Ctrl+Alt+I summons, Ctrl+Alt+T types to her, Ctrl+Alt+Shift+S study mode, Ctrl+Alt+Shift+M shiai, Ctrl+Alt+Shift+C / +1..9 / +0 run the gesture captures (6-7, 9: keiko, 8: zoom at the panel, 0: hits, a measurement of the desk), Ctrl+Alt+Shift+R the voice corpus."
