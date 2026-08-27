@echo off
setlocal
cd /d "%~dp0"

docker compose --env-file .env.example down
if errorlevel 1 (
  echo [ERROR] Failed to stop the platform cleanly.
  pause
  exit /b 1
)

echo Platform stopped. Database and other named-volume data were preserved.
pause
