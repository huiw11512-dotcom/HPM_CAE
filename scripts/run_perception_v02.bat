@echo off
set ROOT=%~dp0\..
cd /d "%ROOT%"
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python run_perception_v02.py %*
