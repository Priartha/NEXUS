$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root "backend"
$frontendDir = Join-Path $root "frontend"
$logDir = Join-Path $root "logs"
$runtimeDir = Join-Path $root ".runtime"
$rootPython = Join-Path $root ".venv\Scripts\python.exe"
$backendPython = Join-Path $backendDir ".venv\Scripts\python.exe"
$python = if (Test-Path $rootPython) { $rootPython } elseif (Test-Path $backendPython) { $backendPython } else { "python" }

function Write-Step($message) {
  Write-Host "[NEXUS] $message" -ForegroundColor Cyan
}

function Require-Command($name, $hint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "$name was not found. $hint"
  }
}

function Stop-PidFile($name) {
  $pidPath = Join-Path $runtimeDir "$name.pid"
  if (-not (Test-Path $pidPath)) {
    return
  }

  $rawPid = Get-Content $pidPath -Raw
  $processId = 0
  if ([int]::TryParse($rawPid.Trim(), [ref]$processId)) {
    $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Step "Stopping previous $name process (PID $processId)"
      Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
      Start-Sleep -Milliseconds 500
    }
  }
  Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

function Stop-ProjectProcesses() {
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      $_.CommandLine -and
      $_.CommandLine -like "*$root*" -and
      ($_.CommandLine -like "*uvicorn*backend.main:app*" -or $_.CommandLine -like "*vite*--host*127.0.0.1*")
    } |
    ForEach-Object {
      Write-Step "Stopping existing NEXUS process (PID $($_.ProcessId))"
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ProjectListener($port, $matchText) {
  $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if (-not $listener) {
    return
  }

  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
  $commandLine = if ($proc) { $proc.CommandLine } else { "" }
  if ($commandLine -and ($commandLine -like "*$root*" -or $commandLine -like "*$matchText*")) {
    Write-Step "Stopping listener on port $port (PID $($listener.OwningProcess))"
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 500
    return
  }

  throw "Port $port is already in use by PID $($listener.OwningProcess). Stop it or change the NEXUS port."
}

function Wait-ForHttp($url, $name) {
  for ($i = 0; $i -lt 60; $i++) {
    try {
      $null = Invoke-WebRequest -Uri $url -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
      return
    } catch {
      if ($i -gt 0 -and $i % 15 -eq 0) {
        Write-Step "Still waiting for $name... ($($i)s elapsed)"
      }
      Start-Sleep -Milliseconds 1000
    }
  }
  throw "$name did not become ready at $url. Check logs in $logDir."
}

function Normalize-ProcessPathEnvironment() {
  $pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
  if (-not $pathValue) {
    $pathValue = [Environment]::GetEnvironmentVariable("PATH", "Process")
  }
  if ($pathValue) {
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
  }
}

New-Item -ItemType Directory -Force -Path $logDir, $runtimeDir | Out-Null
Normalize-ProcessPathEnvironment

Write-Step "Checking local toolchain"
Require-Command "python" "Install Python 3.12+ and reopen PowerShell."
Require-Command "node" "Install Node.js 20+ and reopen PowerShell."
Require-Command "npm.cmd" "Install Node.js 20+ and reopen PowerShell."

if (-not (Test-Path $python)) {
  Write-Step "Creating backend virtual environment"
  python -m venv (Join-Path $backendDir ".venv")
  $python = $backendPython
}

Write-Step "Installing backend requirements"
$pipOut = Join-Path $logDir "pip-install.out.log"
$pipErr = Join-Path $logDir "pip-install.err.log"
& $python -m pip install -r (Join-Path $backendDir "requirements.txt") 2>&1 | ForEach-Object {
  if ($_ -is [System.Management.Automation.ErrorRecord]) {
    $_ | Out-File -FilePath $pipErr -Append
    Write-Host "[pip] $_" -ForegroundColor DarkYellow
  } else {
    $_ | Out-File -FilePath $pipOut -Append
  }
}

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
$backendPort = if ($env:NEXUS_BACKEND_PORT) { $env:NEXUS_BACKEND_PORT } else { "8000" }
$frontendPort = if ($env:NEXUS_FRONTEND_PORT) { $env:NEXUS_FRONTEND_PORT } else { "5173" }

Stop-ProjectListener $backendPort "uvicorn"
Stop-ProjectListener $frontendPort "vite"
Stop-ProjectProcesses

$env:PYTHONPATH = $root
$env:NEXUS_ROOT = $root

$backendOut = Join-Path $logDir "backend.out.log"
$backendErr = Join-Path $logDir "backend.err.log"
$frontendOut = Join-Path $logDir "frontend.out.log"
$frontendErr = Join-Path $logDir "frontend.err.log"

Write-Step "Starting backend on port $backendPort"
$backendProc = Start-Process -FilePath $python `
  -ArgumentList @("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", $backendPort) `
  -WorkingDirectory $root `
  -RedirectStandardOutput $backendOut `
  -RedirectStandardError $backendErr `
  -WindowStyle Hidden `
  -PassThru
Set-Content -Path (Join-Path $runtimeDir "backend.pid") -Value $backendProc.Id
Write-Step "Backend PID: $($backendProc.Id)"

Wait-ForHttp "http://127.0.0.1:$backendPort/health" "Backend"
Write-Step "Backend live at http://127.0.0.1:$backendPort"

$viteJs = Join-Path (Join-Path (Join-Path (Join-Path $frontendDir "node_modules") "vite") "bin") "vite.js"
if (-not (Test-Path $viteJs)) {
  throw "Vite was not found. Run npm install in $frontendDir."
}

Write-Step "Starting frontend on port $frontendPort"
$viteArgs = "`"$viteJs`" --host 127.0.0.1 --port $frontendPort"
$frontendProc = Start-Process -FilePath "node" `
  -ArgumentList $viteArgs `
  -WorkingDirectory $frontendDir `
  -RedirectStandardOutput $frontendOut `
  -RedirectStandardError $frontendErr `
  -WindowStyle Hidden `
  -PassThru
Set-Content -Path (Join-Path $runtimeDir "frontend.pid") -Value $frontendProc.Id
Write-Step "Frontend PID: $($frontendProc.Id)"

Wait-ForHttp "http://127.0.0.1:$frontendPort" "Frontend"
Write-Step "Frontend live at http://127.0.0.1:$frontendPort"

Write-Host ""
Write-Host "NEXUS is LIVE!" -ForegroundColor Green
Write-Host "  App:     http://127.0.0.1:$frontendPort" -ForegroundColor Green
Write-Host "  Backend: http://127.0.0.1:$backendPort" -ForegroundColor Green
Write-Host "  Logs:    $logDir" -ForegroundColor Green

Start-Sleep -Seconds 2
& cmd.exe /d /s /c "start `"`" `"http://127.0.0.1:$frontendPort`""
