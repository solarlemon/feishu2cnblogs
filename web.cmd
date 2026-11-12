@echo off
rem 双击启动网页版：自动打开浏览器
setlocal
set "PYTHONUTF8=1"
python "%~dp0run.py" web %*
if errorlevel 1 pause
