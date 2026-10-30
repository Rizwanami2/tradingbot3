@echo off
title Institutional Gold and Bitcoin Quantitative Trading Bot
echo ==================================================================
echo   Institutional Gold and Bitcoin Trading Engine (Windows VPS)
echo ==================================================================
cd /d "%~dp0"

REM 1. Check for Virtual Environment Python
if exist "%~dp0venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0venv\Scripts\python.exe"
    goto found_py
)

REM 2. Check for py launcher with 3.11
py -3.11 --version >nul 2>&1
if %errorlevel% == 0 (
    set "PYTHON_EXE=py -3.11"
    goto found_py
)

REM 3. Fallback to default python
python --version >nul 2>&1
if %errorlevel% == 0 (
    set "PYTHON_EXE=python"
    goto found_py
)

echo [ERROR] Python was not found on PATH or in venv!
echo Please install Python 3.11 or run deploy_aws_windows.ps1 first.
pause
exit /b 1

:found_py
echo [*] Using Python: %PYTHON_EXE%
echo [*] Launching 24/7 background engine with auto-restart protection...
echo.

:loop
%PYTHON_EXE% telegram_bot.py
echo.
echo [!] Bot process terminated or restarted at %date% %time%
echo [!] Auto-restarting in 5 seconds...
timeout /t 5 >nul
goto loop
