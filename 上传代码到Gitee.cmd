@echo off
chcp 65001 >nul
title 校园网助手 - 代码备份到 Gitee
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" "%~dp0gitee_push.py"
echo.
pause
