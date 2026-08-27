@echo off
setlocal

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_3d.ps1"
if not errorlevel 1 exit /b 0

echo.
echo Stop failed. Check the message above.
pause
exit /b 1
