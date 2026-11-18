@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
where python.exe >nul 2>&1
if errorlevel 1 goto launcher
python.exe "%~dp0ggufly.py"
goto done
:launcher
py.exe -3 "%~dp0ggufly.py"
:done
if errorlevel 1 pause
