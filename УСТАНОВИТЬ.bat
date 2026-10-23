@echo off
cd /d "%~dp0"
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -U pip
pip install -e .
if not exist .env copy .env.example .env
echo.
echo OK. Activate:  .venv\Scripts\activate
echo Run:           edgebot analytics --top 15
pause
