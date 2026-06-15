@echo off
REM Quick start script for Windows
REM Double-click this file to start the server

echo ========================================
echo AI Fitness Trainer API - Starting...
echo ========================================
echo.

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Start the server
echo Starting FastAPI server on http://localhost:8000
echo Press CTRL+C to stop the server
echo.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

pause
