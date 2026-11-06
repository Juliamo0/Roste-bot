#!/usr/bin/env bash
# รันบอทบน RunPod — เทียบเท่า start.bat
#
# ใช้ DISCORD_TOKEN ตัวเดียวกับเครื่องบ้าน → ห้ามรันพร้อมกัน ไม่งั้นตอบซ้ำสองรอบทุกข้อความ
# bot.lock กันซ้อนได้แค่ในเครื่องเดียวกัน มองไม่เห็นอีกเครื่อง จึงต้องให้คนยืนยันเอง
# รันแบบไม่มีคนกด (nohup/tmux script) ให้ตั้ง ROSTE_HOME_BOT_STOPPED=1 แทนการพิมพ์
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source runpod/env.sh

[[ -x venv/bin/python ]] || { echo "[X] ไม่มี venv — รัน bash runpod/setup.sh ก่อน"; exit 1; }
# token มาได้ 2 ทาง: RunPod Secrets → env var (แนะนำ ไม่มีไฟล์ token ค้างบน volume)
# หรือ .env แบบเดิม — config.py อ่านทั้งสองทาง (load_dotenv + os.getenv)
if [[ -z "${DISCORD_TOKEN:-}" && ! -f .env ]]; then
    echo "[X] ไม่มี DISCORD_TOKEN — ตั้งใน RunPod Secrets หรือ cp .env.example .env"
    exit 1
fi

if [[ "${ROSTE_HOME_BOT_STOPPED:-}" != "1" ]]; then
    echo "⚠️  รอสเต้ที่เครื่องบ้านปิดแล้วใช่ไหม? (token เดียวกัน รันสองที่ = ตอบซ้ำ)"
    read -r -p "   พิมพ์ yes ถ้าปิดแล้ว: " ok
    [[ "$ok" == "yes" ]] || { echo "ยกเลิก — ปิดบอทที่บ้านก่อน"; exit 1; }
fi

# pod ใหม่/ที่ stop แล้ว start ใหม่ Ollama จะไม่ขึ้นเอง (ไม่มี systemd)
command -v ollama >/dev/null || { echo "[X] ไม่เจอ ollama ใน volume — รัน setup.sh"; exit 1; }
command -v ffmpeg >/dev/null || { echo "[X] ไม่มี ffmpeg (container disk ถูกล้าง) — รัน setup.sh"; exit 1; }
start_ollama

exec venv/bin/python bot.py
