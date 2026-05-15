$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$logsDir = Join-Path $root "logs"
$runtimeDir = Join-Path $root ".runtime"
$rootVenv = Join-Path $root ".venv\Scripts\python.exe"
$backendPython = if (Test-Path $rootVenv) { $rootVenv } else { Join-Path $backendDir ".venv\Scripts\python.exe" }
$appUrl = "http://127.0.0.1:5173"

function Write-Step($message) {
  Write-Host "[NEXUS] $message" -ForegroundColor Cyan
}

function Require-Command($name, $installHint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "$name was not found. $installHint"
  }
}

function Get-Listener($port) {
  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
}

function Stop-ProjectListener($port, $matchText) {
  $listener = Get-Listener $port
  if (-not $listener) {
    return
  }

  $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
  $commandLine = if ($process) { $process.CommandLine } else { "" }

  if ($commandLine -and ($commandLine -like "*$matchText*" -or $commandLine -like "*$root*")) {
    Write-Step "Stopping existing project process on port $port (PID $($listener.OwningProcess))"
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Milliseconds 600
    return
  }

  throw "Port $port is already in use by PID $($listener.OwningProcess). Close that process or change the app port."
}

function Stop-ProjectProcesses() {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and
      $_.CommandLine -like "*$root*" -and
      ($_.CommandLine -like "*uvicorn backend.main*" -or $_.CommandLine -like "*npm.cmd*run*dev*" -or $_.CommandLine -like "*vite*--host*127.0.0.1*")
    } |
    ForEach-Object {
      Write-Step "Stopping previous project process (PID $($_.ProcessId))"
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-PidFile($name) {
  $pidFile = Join-Path $runtimeDir "$name.pid"
  if (-not (Test-Path $pidFile)) {
    return
  }

  $processId = [int](Get-Content $pidFile -Raw)
  if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
    Write-Step "Stopping previous $name launcher process (PID $processId)"
    Stop-Process -Id $processId -Force
    Start-Sleep -Milliseconds 300
  }
  Remove-Item $pidFile -Force
}

function Wait-ForTcp($port, $name) {
  for ($i = 0; $i -lt 90; $i++) {
    $client = $null
    try {
      $client = [System.Net.Sockets.TcpClient]::new()
      $connected = $client.BeginConnect("127.0.0.1", $port, $null, $null)
      if ($connected.AsyncWaitHandle.WaitOne(1000)) {
        $client.EndConnect($connected)
        return
      }
    } catch {
      Start-Sleep -Milliseconds 750
    } finally {
      if ($client) {
        $client.Dispose()
      }
    }
  }
  throw "$name did not become ready on port $port. Check logs in $logsDir."
}

New-Item -ItemType Directory -Force -Path $logsDir, $runtimeDir, (Join-Path $root "data") | Out-Null

Write-Step "Checking local toolchain"
Require-Command "python" "Install Python 3.12+ and reopen PowerShell."
Require-Command "node" "Install Node.js 20+ and reopen PowerShell."
Require-Command "npm.cmd" "Install Node.js 20+ and reopen PowerShell."

$geminiKey = $env:GEMINI_API_KEY
if (-not $geminiKey) {
  $geminiKey = [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
}
if ($geminiKey) {
  $env:GEMINI_API_KEY = $geminiKey
  if (-not $env:ICT_SENTIMENT_PROVIDER) {
    $env:ICT_SENTIMENT_PROVIDER = "gemini"
  }
  if (-not $env:ICT_AI_ICT_PROVIDER) {
    $env:ICT_AI_ICT_PROVIDER = "gemini"
  }
}

if (-not (Test-Path $backendPython)) {
  Write-Step "Creating backend virtual environment"
  python -m venv (Join-Path $backendDir ".venv")
}

Write-Step "Installing backend requirements"
& $backendPython -m pip install --upgrade pip | Out-Host
& $backendPython -m pip install -r (Join-Path $backendDir "requirements.txt") | Out-Host

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
  Write-Step "Installing frontend packages"
  Push-Location $frontendDir
  try {
    npm.cmd install | Out-Host
  } finally {
    Pop-Location
  }
}

Stop-PidFile "backend"
Stop-PidFile "frontend"
Stop-ProjectListener 8080 "uvicorn"
Stop-ProjectListener 5173 "vite"
Stop-ProjectProcesses

Write-Step "Starting backend and frontend"
$backendErrLog = Join-Path $logsDir "backend.err.log"
$backendOutLog = Join-Path $logsDir "backend.out.log"
$frontendErrLog = Join-Path $logsDir "frontend.err.log"
$frontendOutLog = Join-Path $logsDir "frontend.out.log"
$backendLogDir = Join-Path $root "logs"

Write-Step "Starting backend on port 8080..."
$env:NEXUS_ROOT = $root
$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $backendPython
$startInfo.Arguments = "-m uvicorn backend.main:app --host 127.0.0.1 --port 8080"
$startInfo.WorkingDirectory = $root
$startInfo.RedirectStandardOutput = $backendOutLog
$startInfo.RedirectStandardError = $backendErrLog
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$backendProc = [System.Diagnostics.Process]::Start($startInfo)
Write-Step "Backend PID: $($backendProc.Id)"

Write-Step "Waiting for backend to initialize..."
$backendReady = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:8080/health" -TimeoutSec 1 -UseBasicParsing -ErrorAction SilentlyContinue
    $backendReady = $true
    break
  } catch {}
  Start-Sleep -Milliseconds 1000
}
if (-not $backendReady) {
  throw "Backend did not become ready. Check $backendLogDir\backend.err.log"
}
Write-Step "Backend is live on http://127.0.0.1:8080"

Write-Step "Starting frontend on port 5173..."
$viteBin = Join-Path $frontendDir "node_modules\vite\bin\vite.js"
if (-not (Test-Path $viteBin)) {
  $viteBin = Join-Path $frontendDir "node_modules\.bin\vite.cmd"
}
if (-not (Test-Path $viteBin)) {
  throw "Vite not found. Run 'npm install' in frontend/ first."
}
$feStartInfo = New-Object System.Diagnostics.ProcessStartInfo
$feStartInfo.FileName = "node"
$feStartInfo.Arguments = "`"$viteBin`" --host 127.0.0.1 --port 5173"
$feStartInfo.WorkingDirectory = $frontendDir
$feStartInfo.RedirectStandardOutput = $frontendOutLog
$feStartInfo.RedirectStandardError = $frontendErrLog
$feStartInfo.UseShellExecute = $false
$feStartInfo.CreateNoWindow = $true
$frontendProc = [System.Diagnostics.Process]::Start($feStartInfo)
Write-Step "Frontend PID: $($frontendProc.Id)"

Write-Step "Waiting for frontend to initialize..."
$frontendReady = $false
for ($i = 0; $i -lt 90; $i++) {
  try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 1 -UseBasicParsing -ErrorAction SilentlyContinue
    $frontendReady = $true
    break
  } catch {}
  Start-Sleep -Milliseconds 1000
}
if (-not $frontendReady) {
  Write-Step "WARNING: Frontend did not respond yet. It may still be starting."
}
Write-Step "Frontend is live on http://127.0.0.1:5173"

Write-Step "Opening app"
& cmd.exe /d /s /c ('start "" "' + $appUrl + '"')

Write-Host ""
Write-Host "NEXUS is running." -ForegroundColor Green
Write-Host "App:     $appUrl"
Write-Host "Backend: http://127.0.0.1:8080"
Write-Host "Logs:    $logsDir"
Write-Host ""
Write-Host "You can close this window. The app processes will keep running."
