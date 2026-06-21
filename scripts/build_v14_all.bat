@echo off
cd /d %~dp0\..
set PYTHONPATH=%CD%\src;%PYTHONPATH%
python scripts\generate_v14_illustrations.py || exit /b 1
pytest -q || exit /b 1
python scripts\build_v14_preview.py || exit /b 1
python scripts\build_v14_acceptance.py || exit /b 1
echo V1.4 全部构建与验收完成。
