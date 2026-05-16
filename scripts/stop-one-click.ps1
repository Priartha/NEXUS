$ErrorActionPreference = "SilentlyContinue"

$root = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $root ".runtime"

function Write-Step($message) {
  Write-Host "[NEXUS] $message" -ForegroundColor Yellow
}

# Stop NEXUS.exe process
$nexusProc = Get-Process -Name "NEXUS" -ErrorAction SilentlyContinue
if ($nexusProc) {
  Write-Step "Stopping NEXUS.exe (PID $($nexusProc.Id))"
  Stop-Process -Id $nexusProc.Id -Force
  Start-Sleep -Seconds 2
  Write-Step "NEXUS stopped"
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
