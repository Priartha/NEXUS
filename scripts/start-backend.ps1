$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
  python -m venv (Join-Path $root "backend\.venv")
  & $venvPython -m pip install --upgrade pip
  & $venvPython -m pip install -r (Join-Path $root "backend\requirements.txt")
}

& $venvPython -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

