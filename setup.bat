@echo off
title Roste Bot - Setup
cd /d "%~dp0"

echo ============================================
echo      Installing Python libraries for Roste
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [X] Python not found. Install from https://www.python.org/downloads/
    pause
    exit /b
)

echo Installing... (this may take a while)
echo.

python -m pip install --upgrade pip
python -m pip install discord.py aiohttp ddgs pypdf pywin32 PyNaCl

echo.
echo ============================================
echo  Python libraries installed.
echo.
echo  ** You also need these 3 installed separately (if not yet) **
echo   1) Ollama     : https://ollama.com   then run:  ollama pull qwen3:14b
echo   2) FFmpeg     : winget install ffmpeg        (for playing songs in voice)
echo   3) SumatraPDF : https://www.sumatrapdfreader.org   (for silent printing)
echo ============================================
echo.
pause
