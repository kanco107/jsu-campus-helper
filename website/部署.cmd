@echo off
chcp 65001 >nul
title 校园网助手官网 - Cloudflare 部署
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" "%~dp0deploy_cf.py"
echo.
pause
