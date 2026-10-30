@echo off
title Institutional Gold and Bitcoin Quantitative Trading Bot
echo ==================================================================
echo   Starting Institutional Gold and Bitcoin Trading Engine...
echo ==================================================================

:loop
py -3.11 telegram_bot.py
echo.
echo [!] Bot process terminated or crashed at %date% %time%
echo [!] Auto-restarting in 5 seconds...
timeout /t 5 >nul
goto loop
