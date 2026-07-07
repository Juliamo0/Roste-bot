# restart_bot.ps1 — kill old bot + start fresh
# รันด้วย: powershell -ExecutionPolicy Bypass -File restart_bot.ps1

$botDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $botDir

$venvPython = Join-Path $botDir "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[X] venv\ not found. Run setup.bat first to create it and install libraries."
    exit 1
}

# kill process เก่าทั้งหมดที่รัน bot.py หรือ worker ที่มันสปอว์น (RVC/F5) — เจาะจาก CommandLine
# ไม่ใช่ชื่อ process เพราะ python ตัวเดียวกันโผล่มาได้หลายชื่อ (python.exe ปกติ, python3.13.exe
# ตอน WindowsApps launcher re-exec ตัวเอง) เจอมาแล้วหลายรอบว่า filter จากชื่อ process อย่างเดียว
# พลาด orphan ไปได้ — ใช้ CommandLine เป็นเกณฑ์เดียวจับได้ทุกกรณี
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "bot\.py|voice_rvc_worker|f5_worker"
} | ForEach-Object {
    Write-Host "killing PID $($_.ProcessId) ($($_.CommandLine))"
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2

# start bot ใหม่ — ต้องผ่าน venv\Scripts\python.exe เท่านั้น (ไม่ใช่ python เฉยๆ จาก PATH)
# กัน "python resolves differently than start.bat" — เดิม restart_bot.ps1 เรียก python ตรงๆ
# ซึ่งอาจไม่ใช่ตัวเดียวกับที่ใช้รันเทส/dev ทำให้ dependency ไม่ตรงกันแบบเงียบๆ
Write-Host "Starting bot..."
Start-Process -FilePath $venvPython -ArgumentList "bot.py" `
    -RedirectStandardOutput "bot_out.log" `
    -RedirectStandardError  "bot_err.log" `
    -WindowStyle Hidden

Write-Host "Bot started. Logs: bot_out.log / bot_err.log"
