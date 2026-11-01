@echo off
title Complete Windows & MetaTrader 5 Automated Setup
echo ==================================================================
echo   Institutional Gold and Bitcoin Bot: Full Windows Setup
echo ==================================================================
cd /d "%~dp0"

echo [*] Launching automated PowerShell setup script...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy_aws_windows.ps1"

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Setup encountered an issue. See details above.
    pause
    exit /b %errorlevel%
)

echo.
echo ==================================================================
echo   Setup script finished successfully!
echo ==================================================================
pause

