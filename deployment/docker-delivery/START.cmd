@echo off
setlocal EnableExtensions
cd /d "%~dp0"

powershell.exe -NoProfile -Command "if ((Get-Location).Path -match '[^\x00-\x7F]') { exit 1 }"
if errorlevel 1 (
  echo [ERROR] The package path contains non-ASCII characters.
  echo Move it to a short English path such as D:\xiongan-city-brain and retry.
  pause
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Install Docker Desktop before starting the platform.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
    echo Starting Docker Desktop...
    start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  )
  echo Waiting for Docker Engine. This can take up to two minutes...
  for /l %%I in (1,1,60) do (
    docker info >nul 2>&1 && goto docker_ready
    timeout /t 2 /nobreak >nul
  )
  echo [ERROR] Docker Engine did not become ready. Open Docker Desktop and retry.
  pause
  exit /b 1
)

:docker_ready
echo Building and starting the platform...
docker compose --env-file .env.example up -d --build --wait --wait-timeout 300
if errorlevel 1 (
  echo [ERROR] Startup failed. Recent container status follows:
  docker compose --env-file .env.example ps
  echo Run LOGS.cmd for detailed diagnostics.
  pause
  exit /b 1
)

docker compose --env-file .env.example ps
echo.
echo Platform:   http://127.0.0.1:5173/?view=2d
echo API docs:   http://127.0.0.1:5173/docs
echo Prometheus: http://127.0.0.1:9090
start "" "http://127.0.0.1:5173/?view=2d"
pause
