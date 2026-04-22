@echo off
cd /d "%~dp0"
pip install flask -q
python app.py
pause
