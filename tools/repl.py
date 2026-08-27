"""REPL คุยกับรอสเต้ผ่าน terminal — ไม่ต้องเปิด Discord

ที่มา: chat.ask_ollama เรียกตรงได้แล้ว (Discord-free ตาม invariant ของ chat.py) แต่
debug/ทดสอบ prompt ทุกครั้งต้องเปิด Discord จริง รอ bot online ถึงจะคุยได้ ช้าและ
ปนกับ TTS/karaoke ที่ไม่เกี่ยวกับที่กำลังแก้ REPL นี้ตัดส่วนที่ไม่เกี่ยวออกให้เหลือ
แค่ ask_ollama ตรงๆ เป็นฐานให้ eval harness (tools/eval_roste.py) ต่อได้ด้วย

memory แยกไปที่ tools/_repl_memory/ — ไม่มีการอ่าน/เขียนไฟล์ความจำใดๆ ลง memory/ จริง
(ตั้ง memory.MEMORY_DIR ก่อน import chat เสมอ เผื่อโค้ดในอนาคตอ่านค่านั้นตอน import)
ข้อยกเว้นเดียว: import memory เองมี os.makedirs("memory") เป็น module-level side effect
เดิมของไฟล์นั้น (มีมาก่อน repl.py) จึงอาจสร้างโฟลเดอร์ memory/ เปล่าๆ ถ้ายังไม่มีอยู่ก่อน
— ไม่มีไฟล์ถูกเขียนลงไปข้างในเลย

vector recall (chroma_db) ยังยิงของจริง — ยอมรับได้สำหรับเครื่องมือ dev เดี่ยวๆ
ถ้าอยากให้ pure ไม่แตะอะไรนอก _repl_memory ใช้ --no-recall

ใช้:
    python tools/repl.py                  # โหมดคุยสด พิมพ์ /quit ออก /reset ล้างความจำ
    python tools/repl.py --no-recall       # ปิด PDF/vector recall กันยิง chroma_db จริง
    python tools/repl.py --replay q.txt    # ป้อนทีละบรรทัดจากไฟล์ พิมพ์คู่ Q/A ออก แล้วจบ
"""
import argparse
import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import memory

memory.MEMORY_DIR = os.path.join(os.path.dirname(__file__), "_repl_memory")
os.makedirs(memory.MEMORY_DIR, exist_ok=True)

import chat
import vectormemory

UID, NAME = 111111, "นักพัฒนา"


def _reset_memory() -> None:
    p = memory._memory_path(UID)
    if os.path.exists(p):
        os.remove(p)
    print("(ล้างความจำแล้ว)")


async def _chat_mode() -> None:
    print("คุยกับรอสเต้ (พิมพ์ /quit ออก, /reset ล้างความจำ)")
    while True:
        try:
            line = input("คุณ > ").strip()
        except EOFError:
            break
        if line == "/quit":
            break
        if line == "/reset":
            _reset_memory()
            continue
        if not line:
            continue
        reply = await chat.ask_ollama(UID, NAME, line)
        print(f"รอสเต้ > {reply}\n")


async def _replay_mode(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    for line in lines:
        print(f"คุณ > {line}")
        reply = await chat.ask_ollama(UID, NAME, line)
        print(f"รอสเต้ > {reply}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", metavar="FILE",
                    help="อ่านคำถามทีละบรรทัดจากไฟล์แทนโหมดคุยสด")
    ap.add_argument("--no-recall", action="store_true",
                    help="patch vectormemory.query_pdf/query_conversation_memory เป็น [] กันยิง chroma_db จริง")
    args = ap.parse_args()

    coro = _replay_mode(args.replay) if args.replay else _chat_mode()
    if args.no_recall:
        with patch.object(vectormemory, "query_pdf", AsyncMock(return_value=[])), \
             patch.object(vectormemory, "query_conversation_memory", AsyncMock(return_value=[])):
            asyncio.run(coro)
    else:
        asyncio.run(coro)
    return 0


if __name__ == "__main__":
    sys.exit(main())
