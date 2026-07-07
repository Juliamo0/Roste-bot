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

REM --- สร้าง project venv แยกต่างหาก (venv\) ถ้ายังไม่มี ---
REM กัน "python resolves differently than start.bat" — เดิม start.bat/setup.bat เรียก python
REM เฉยๆ ซึ่งอาจไม่ใช่ python เดียวกับที่ใช้ตอน dev/เทส ทำให้ dependency ไม่ตรงกันแบบเงียบๆ
if not exist "venv\Scripts\python.exe" (
    echo Creating project venv (venv\)...
    python -m venv venv
)

echo Installing... (this may take a while)
echo.

venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r requirements.txt
REM หมายเหตุ: pythainlp + python-crfsuite ใช้ตัดประโยคไทย (crfcut) สำหรับ streaming TTS
REM ถ้าขาด python-crfsuite ตัว crfcut จะพังเงียบ — เสียงจะไม่แบ่งประโยค (requirements.txt มีให้ครบแล้ว)

echo.
echo ============================================
echo  Python libraries installed.
echo.
echo  ** You also need these installed separately (if not yet) **
echo   1) Ollama     : https://ollama.com   then run:  ollama pull qwen3:14b
echo   2) FFmpeg     : winget install ffmpeg        (for playing songs in voice)
echo   3) SumatraPDF : https://www.sumatrapdfreader.org   (for silent printing)
echo   4) Embedding model (RAG PDF + vector memory): ollama pull bge-m3
echo ============================================
echo.
pause
