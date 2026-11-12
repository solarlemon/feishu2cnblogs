@echo off
rem 便捷启动脚本：双击或在命令行运行  f2c publish <飞书文档链接> --publish
setlocal
set "PYTHONUTF8=1"
python "%~dp0run.py" %*
