@echo off
title Roste Bot - Running
cd /d "%~dp0"

echo ============================================
echo            Starting Roste Bot
echo ============================================
echo.

REM --- Check project venv (run setup.bat first if missing) ---
REM ตั้งใจไม่เรียก `python` เฉยๆ อีกต่อไป — เดิม start.bat ใช้ python จาก PATH ซึ่งอาจไม่ใช่
REM ตัวเดียวกับที่ setup.bat/dev ใช้ตอนติดตั้ง library ทำให้ dependency ไม่ตรงกันแบบเงียบๆ
if not exist "venv\Scripts\python.exe" (
    echo [X] venv\ not found. Run setup.bat first to create it and install libraries.
    echo.
    pause
    exit /b
)

REM --- Check main files exist ---
if not exist "bot.py" (
    echo [X] bot.py not found. Put all files in the same folder as start.bat
    echo.
    pause
    exit /b
)
if not exist "printing.py" echo [!] Warning: printing.py missing (printing will not work)
if not exist "music.py" echo [!] Warning: music.py missing (music will not work)

REM --- Check Ollama running, start if not ---
ollama list >nul 2>&1
if errorlevel 1 (
    echo [!] Ollama not running - trying to start it...
    start "" ollama serve
    echo     Waiting 5 seconds for Ollama...
    timeout /t 5 /nobreak >nul
)

echo [OK] Starting bot... (To stop: press Ctrl+C here, or just close this window)
echo.

venv\Scripts\python.exe bot.py

echo.
echo ============================================
echo  Bot stopped. (Read any error message above)
echo ============================================
pause
