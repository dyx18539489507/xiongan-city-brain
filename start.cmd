@echo off
setlocal

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_3d.ps1" -BackendPort 8014 -FrontendPort 5178 -SkipExperiment
if not errorlevel 1 exit /b 0

echo.
echo Start failed. Run stop.cmd, then try again.
pause
exit /b 1
