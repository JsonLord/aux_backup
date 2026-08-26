@echo off
echo Starting UX Analyst AI Development Environment...
echo.

echo Starting Backend Server...
start "UX Analyst Backend" cmd /k "cd /d %~dp0..\backend && npm run dev"

echo Waiting 3 seconds for backend to start...
timeout /t 3 /nobreak >nul

echo Starting Frontend Server...
start "UX Analyst Frontend" cmd /k "cd /d %~dp0..\frontend && npm run dev"

echo.
echo Both servers are starting...
echo Backend: http://localhost:3005
echo Frontend: http://localhost:5173
echo.
echo Press any key to exit this script (servers will continue running)
pause >nul