@echo off
setlocal
cd /d "%~dp0"
docker compose --env-file .env.example logs --tail 300
pause
