@echo off
title Project Ash — Stack Launcher

echo [ASH] Starting tactical map tile server (port 8081)...
start "Ash - Map Tile Server" /min cmd /k "npx http-server C:\Users\richa\Desktop\planetpiler -p 8081 --cors"

echo [ASH] Starting TTS server (port 8000)...
start "Ash - TTS Server" /min cmd /k "cd /d %~dp0tech-priest-tts && .venv\Scripts\activate && uvicorn ash_tts_server:app --host 0.0.0.0 --port 8000"

echo [ASH] Starting WebSocket / chat server (port 8080)...
start "Ash - Chat Server" /min cmd /k "cd /d %~dp0 && .venv\Scripts\activate && uvicorn ash_main_server:app --host 127.0.0.1 --port 8080"

echo [ASH] Starting frontend dev server (port 5173)...
start "Ash - Frontend" /min cmd /k "cd /d %~dp0 && npm run dev"

echo.
echo [ASH] All services launching.
echo [ASH] Frontend: http://localhost:5173
echo [ASH] LM Studio must be started separately on port 1234.
pause