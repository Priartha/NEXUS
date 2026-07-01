$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $root ".runtime"

function Write-Step($message) {
  Write-Host "[NEXUS] $message" -ForegroundColor Yellow
}

# Stop python and node processes tied to the project
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -and
    $_.ProcessName -in @("python.exe", "node.exe") -and
    $_.CommandLine -like "*$root*" -and
    $_.ProcessId -ne $pid
  }
if ($procs) {
  $procs | ForEach-Object {
    Write-Step "Stopping $($_.ProcessName) (PID $($_.ProcessId))"
    Stop-Process -Id $_.ProcessId -Force
  }
  Start-Sleep -Seconds 2
  Write-Step "NEXUS processes stopped"
} else {
  Write-Step "NEXUS is not running"
}

# Clean up PID files
if (Test-Path $runtimeDir) {
  Remove-Item -Path (Join-Path $runtimeDir "*.pid") -Force -ErrorAction SilentlyContinue
}

# Kill any leftover python/uvicorn processes tied to this project
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -like "*$root*" } |
  ForEach-Object {
    Write-Step "Stopping leftover process (PID $($_.ProcessId))"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

Write-Host ""
Write-Host "NEXUS has been stopped." -ForegroundColor Green
