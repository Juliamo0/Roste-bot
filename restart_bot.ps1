# restart_bot.ps1 — kill old bot + start fresh
# รันด้วย: powershell -ExecutionPolicy Bypass -File restart_bot.ps1

$botDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $botDir

# kill process เก่าทั้งหมดที่รัน bot.py หรือ voice_rvc_worker.py
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    $id  = $_.Id
    $cmd = (Get-WmiObject Win32_Process -Filter "ProcessId=$id").CommandLine
    if ($cmd -match "bot\.py|voice_rvc_worker") {
        Write-Host "killing PID $id ($cmd)"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 2

# start bot ใหม่
Write-Host "Starting bot..."
Start-Process -FilePath "python" -ArgumentList "bot.py" `
    -RedirectStandardOutput "bot_out.log" `
    -RedirectStandardError  "bot_err.log" `
    -WindowStyle Hidden

Write-Host "Bot started. Logs: bot_out.log / bot_err.log"
