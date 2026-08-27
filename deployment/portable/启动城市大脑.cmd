@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_portable.ps1" %*
if errorlevel 1 (
  echo.
  echo Start failed. See runtime-state\logs\server.stderr.log
  pause
)
endlocal
