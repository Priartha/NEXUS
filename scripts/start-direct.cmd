@echo off
setlocal

set "ROOT=%~dp0.."
cd /d "%ROOT%"

if not exist "logs" mkdir "logs"
if not exist ".runtime" mkdir ".runtime"
if not exist "data" mkdir "data"

:: Detect venv location (root .venv or backend\.venv)
if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else if exist "backend\.venv\Scripts\python.exe" (
  set "PYTHON=backend\.venv\Scripts\python.exe"
) else (
  echo [NEXUS] No Python venv found. Run 'python -m venv .venv' first.
  exit /b 1
)

echo [NEXUS] Starting backend on port 8080...
start "" /b "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8080 >> "%ROOT%\logs\backend.out.log" 2>> "%ROOT%\logs\backend.err.log"

echo [NEXUS] Waiting for backend...
timeout /t 6 >nul

echo [NEXUS] Starting frontend on port 5173 (proxying to 8080)...
cd /d "%ROOT%\frontend"
if exist "node_modules\.bin\vite.cmd" (
  start "" /b node node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173 >> "%ROOT%\logs\frontend.out.log" 2>> "%ROOT%\logs\frontend.err.log"
) else if exist "node_modules\.bin\vite" (
  start "" /b node node_modules\.bin\vite --host 127.0.0.1 --port 5173 >> "%ROOT%\logs\frontend.out.log" 2>> "%ROOT%\logs\frontend.err.log"
) else (
  echo [NEXUS] Frontend packages not installed. Run 'npm install' in frontend/ first.
  exit /b 1
)

echo.
echo [NEXUS] Both servers started.
echo   Backend: http://127.0.0.1:8080
echo   Frontend: http://127.0.0.1:5173
echo.
echo Opening browser...
start "" "http://127.0.0.1:5173"
