@echo off
title Ash Stack Launcher

echo [ASH] Starting tile server (port 8080)...
start "Ash - Tile Server" cmd /k "npx http-server C:\Users\richa\Desktop\planetpiler -p 8080 --cors"

echo [ASH] Starting TTS server (port 8000)...
start "Ash - TTS Server" cmd /k "cd /d %~dp0tech-priest-tts && .venv\Scripts\activate && uvicorn server:app --host 0.0.0.0 --port 8000"

echo [ASH] Starting Vite dev server (port 5173)...
start "Ash - Frontend" cmd /k "cd /d %~dp0 && npm run dev"

echo.
echo [ASH] All services launching. Open http://localhost:5173
echo [ASH] LM Studio must be started separately on port 1234.
pause
