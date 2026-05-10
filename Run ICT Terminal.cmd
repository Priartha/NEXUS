@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-one-click.ps1"
if errorlevel 1 (
  echo.
  echo ICT Terminal failed to start. Check the message above.
  pause
)
