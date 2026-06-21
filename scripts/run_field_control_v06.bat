@echo off
cd /d %~dp0\..
set PYTHONPATH=src
python run_field_control_v06.py %*
