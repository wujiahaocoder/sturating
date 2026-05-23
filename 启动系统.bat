@echo off
title Student Rating System

cd /d "%~dp0"

echo ============================================================
echo  Student Rating System
echo ============================================================

if not exist "venv\Scripts\python.exe" (
    echo [*] First run - setting up environment...
    python -m venv venv
    if errorlevel 1 (
        echo [!] Python not found. Please install Python 3.10+
        pause
        exit /b 1
    )
    echo [*] Installing dependencies...
    venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        pause
        exit /b 1
    )
)

echo [*] Starting server...
echo Visit: http://localhost:8501

start http://localhost:8501

venv\Scripts\streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --server.fileWatcherType none --server.maxUploadSize 200 --browser.gatherUsageStats false --global.developmentMode false

echo.
pause
