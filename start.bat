@echo off
title Roste Bot - Running
cd /d "%~dp0"

echo ============================================
echo            Starting Roste Bot
echo ============================================
echo.

REM --- Check Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found.
    echo     Install Python from https://www.python.org/downloads/
    echo     Remember to tick "Add Python to PATH" during install.
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

python bot.py

echo.
echo ============================================
echo  Bot stopped. (Read any error message above)
echo ============================================
pause
