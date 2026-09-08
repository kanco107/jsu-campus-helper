@echo off
chcp 65001 >nul
title 校园网助手官网 - 安装包发布 GitHub
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=python
"%PY%" "%~dp0deploy_gh.py"
echo.
pause
