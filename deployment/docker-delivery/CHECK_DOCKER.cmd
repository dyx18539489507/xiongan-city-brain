@echo off
setlocal
cd /d "%~dp0"

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop is not installed or docker.exe is not in PATH.
  echo Install Docker Desktop, restart Windows, and run this file again.
  pause
  exit /b 1
)

docker compose version
if errorlevel 1 (
  echo [ERROR] Docker Compose is unavailable. Update Docker Desktop.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Engine is not running. Start Docker Desktop first.
  pause
  exit /b 1
)

docker compose --env-file .env.example config --quiet
if errorlevel 1 (
  echo [ERROR] The Docker Compose configuration is invalid.
  pause
  exit /b 1
)

echo [OK] Docker and the delivery package are ready.
pause
