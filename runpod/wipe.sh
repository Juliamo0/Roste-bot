#!/usr/bin/env bash
# ลบข้อมูลผู้ใช้ที่บอทสร้างระหว่างรันบน pod — รันเมื่อเลิกเทสรอบนั้น
# repo อยู่บน network volume ซึ่ง *ไม่หาย* ตอน terminate pod — ความจำของ user Discord
# จริง (บอทตัวเดียวกับที่บ้าน) จะค้างอยู่ในเครื่องผู้ให้บริการจนกว่าจะลบเองหรือลบ volume
# ลบเฉพาะสิ่งที่ .gitignore ระบุว่าเป็นข้อมูลส่วนตัว — ไม่แตะโค้ด, venv, โมเดล Ollama
set -euo pipefail
cd "$(dirname "$0")/.."

TARGETS=(memory chroma_db data logs print_jobs song_requests.json .env bot.lock bot.pid
         tools/_repl_memory tools/_eval_memory)
echo "จะลบ: ${TARGETS[*]}"
read -r -p "พิมพ์ yes เพื่อยืนยัน: " ok
[[ "$ok" == "yes" ]] || { echo "ยกเลิก"; exit 1; }
rm -rf -- "${TARGETS[@]}"
echo "ลบแล้ว"
