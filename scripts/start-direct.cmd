@echo off
setlocal

set "ROOT=%~dp0.."
cd /d "%ROOT%"

if not exist "logs" mkdir "logs"
if not exist ".runtime" mkdir ".runtime"

start "" /b "%ROOT%\backend\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 > "%ROOT%\logs\backend.out.log" 2> "%ROOT%\logs\backend.err.log"

cd /d "%ROOT%\frontend"
start "" /b node node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173 > "%ROOT%\logs\frontend.out.log" 2> "%ROOT%\logs\frontend.err.log"
