@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Сначала запусти УСТАНОВИТЬ.bat
  pause
  exit /b 1
)
.venv\Scripts\python.exe scripts\run_ui.py
pause
