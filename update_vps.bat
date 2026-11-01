@echo off
title Update tradingbot3 on Windows VPS
echo ==================================================================
echo   Updating tradingbot3 on Windows VPS
echo ==================================================================
cd /d "%~dp0"

echo [*] Pulling latest code from GitHub...
git pull origin main
if %errorlevel% neq 0 (
    echo [ERROR] Git pull failed! Please check your network or git credentials.
    pause
    exit /b %errorlevel%
)

echo [*] Updating dependencies...
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -m pip install -r requirements.txt
    venv\Scripts\python.exe test_suite.py
) else (
    py -3.11 -m pip install -r requirements.txt
    py -3.11 test_suite.py
)

echo.
echo ==================================================================
echo   Update completed successfully!
echo   You can now run: run_bot.bat
echo ==================================================================
pause

