@echo off
set ROOT=%~dp0..\
cd /d %ROOT%
set PYTHONPATH=src
python run_effect_twin_v08.py %*
