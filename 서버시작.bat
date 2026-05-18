@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "scripts\start_web.ps1"
pause
