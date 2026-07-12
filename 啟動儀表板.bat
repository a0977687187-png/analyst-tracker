@echo off
cd /d %~dp0
set PY=C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
start "" http://127.0.0.1:5177
"%PY%" dashboard\app.py
pause
