@echo off
chcp 65001 >nul
title 校园网助手 - 代码同步到 GitHub
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" "%~dp0ghub_sync.py"
echo.
pause
