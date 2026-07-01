$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "frontend")

if (-not (Test-Path "node_modules")) {
  npm.cmd install
}

npm.cmd run dev -- --host 127.0.0.1 --port 5173

