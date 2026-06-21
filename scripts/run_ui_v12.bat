@echo off
setlocal
cd /d "%~dp0\.."
python -m pip install -r requirements.txt || exit /b 1
python run_ui_v12.py %*
