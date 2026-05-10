$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $root ".runtime"

function Stop-ProjectListener($port, $matchText) {
  $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (-not $listener) {
    return
  }

  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
  $commandLine = if ($process) { $process.CommandLine } else { "" }

  if ($commandLine -and ($commandLine -like "*$matchText*" -or $commandLine -like "*$root*")) {
    Write-Host "Stopping process on port $port (PID $($listener.OwningProcess))" -ForegroundColor Cyan
    Stop-Process -Id $listener.OwningProcess -Force
  }
}

function Stop-PidFile($name) {
  $pidFile = Join-Path $runtimeDir "$name.pid"
  if (-not (Test-Path $pidFile)) {
    return
  }

  $processId = [int](Get-Content $pidFile -Raw)
  if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
    Write-Host "Stopping $name (PID $processId)" -ForegroundColor Cyan
    Stop-Process -Id $processId -Force
  }
  Remove-Item $pidFile -Force
}

function Stop-ProjectProcesses() {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and
      $_.CommandLine -like "*$root*" -and
      ($_.CommandLine -like "*uvicorn backend.main*" -or $_.CommandLine -like "*npm.cmd*run*dev*" -or $_.CommandLine -like "*vite*--host*127.0.0.1*")
    } |
    ForEach-Object {
      Write-Host "Stopping project process (PID $($_.ProcessId))" -ForegroundColor Cyan
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Stop-PidFile "backend"
Stop-PidFile "frontend"
Stop-ProjectListener 8000 "uvicorn"
Stop-ProjectListener 5173 "vite"
Stop-ProjectProcesses

Write-Host "NEXUS stopped." -ForegroundColor Green
