"""คุยกับรอสเต้ผ่าน CLI — ใช้ pipeline เดียวกับ Discord ทุกขั้น ไม่ผ่าน Discord

ทำไมต้องมี: การทดสอบที่ผ่านมาวัดที่ชั้น retrieval เป็นหลัก (n=117) แต่ผ่าน ask_ollama
จริงแค่ 5 ครั้ง และ **write path (B2 dedup / B3 กันลอกตัวอย่าง) ยังไม่เคยเห็นของจริงเลย**
เพราะต้องรอให้มีคนคุยจนครบ MAX_HISTORY_PAIRS แล้วระบบถึงจะสรุปเก็บ

ไฟล์นี้จำลอง bot.py:871-892 เป๊ะๆ:
    reply = await chat.ask_ollama(user_id, user_name, text)   # ← สมองทั้งหมดอยู่ตรงนี้
    chat._enqueue_bg(chat.auto_remember(...))                 # ← จำเอง (เบื้องหลัง)
สิ่งเดียวที่ไม่มีคือชั้น Discord (typing indicator, ตัด 2000 ตัวอักษร, TTS)
ซึ่งไม่เกี่ยวกับระบบความจำเลย

⚠️ ค่าเริ่มต้นใช้ user id ทดสอบ ไม่แตะความจำผู้ใช้จริง — ต้องใส่ --uid เองถ้าจะใช้ของจริง
"""
import argparse
import asyncio
import io
import logging
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import chat  # noqa: E402
import memory  # noqa: E402

TEST_UID = 999900000000000100


def _setup_logging(verbose: bool):
    if verbose:
        logging.basicConfig(level=logging.INFO, format="   %(message)s")
        logging.getLogger("aiohttp").setLevel(logging.WARNING)
    else:
        logging.disable(logging.CRITICAL)


async def say(uid: int, name: str, text: str, show_mem: bool = False) -> str:
    """หนึ่งเทิร์น — ตรงกับ bot.py:871-892"""
    if show_mem:
        mem = memory.load_memory(uid)
        recalled = memory.recall_summaries(mem, text)
        if recalled:
            print(f"   [ความทรงจำที่ดึงมา {len(recalled)} อัน]")
            for r in recalled:
                print(f"     · {r[:88]}")

    # คำสั่งความจำตรงๆ ("จำไว้ว่า…") — bot.py เช็คก่อนเรียก ask_ollama
    handled = memory.handle_memory_command(uid, name, text)
    if handled:
        return handled

    reply = await chat.ask_ollama(uid, name, text)
    chat._enqueue_bg(chat.auto_remember(uid, name, text))
    return reply


async def run_script(uid: int, name: str, lines: list, show_mem: bool):
    for i, line in enumerate(lines, 1):
        print(f"\n\033[36m[{i}] คุณ:\033[0m {line}")
        reply = await say(uid, name, line, show_mem)
        print(f"\033[35m    รอสเต้:\033[0m {reply}")
    print("\n(รอให้งานเบื้องหลังเสร็จ — สรุปบท/จำเอง)")
    await chat.flush_user_history(uid)


async def run_interactive(uid: int, name: str, show_mem: bool):
    print("พิมพ์คุยกับรอสเต้ได้เลย (พิมพ์ /quit เพื่อออก, /mem ดูความจำ)")
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = (await loop.run_in_executor(None, input, "\n\033[36mคุณ:\033[0m ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("/quit", "/exit"):
            break
        if line == "/mem":
            mem = memory.load_memory(uid)
            print(f"  summary {len(mem.get('summaries', []))} · "
                  f"facts {len(mem.get('facts', []))} · history {len(mem.get('history', []))}")
            for s in mem.get("summaries", [])[-5:]:
                print(f"   · {s['text'][:92]}")
            continue
        reply = await say(uid, name, line, show_mem)
        print(f"\033[35mรอสเต้:\033[0m {reply}")
    print("\n(รอให้งานเบื้องหลังเสร็จ...)")
    await chat.flush_user_history(uid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", type=int, default=TEST_UID,
                    help="user id (ค่าเริ่มต้น = id ทดสอบ ไม่แตะความจำผู้ใช้จริง)")
    ap.add_argument("--name", default="ผู้ทดสอบ")
    ap.add_argument("--script", help="ไฟล์ข้อความ บรรทัดละ 1 เทิร์น (ไม่ใส่ = คุยสด)")
    ap.add_argument("--show-mem", action="store_true", help="โชว์ความทรงจำที่ดึงมาแต่ละเทิร์น")
    ap.add_argument("--verbose", action="store_true", help="โชว์ log ของระบบ")
    ap.add_argument("--reset", action="store_true", help="ล้างความจำของ uid นี้ก่อนเริ่ม")
    args = ap.parse_args()

    _setup_logging(args.verbose)

    if args.reset:
        p = memory._memory_path(args.uid)
        if os.path.exists(p):
            os.remove(p)
        print(f"(ล้างความจำของ uid {args.uid} แล้ว)")

    print(f"uid={args.uid}  ชื่อ={args.name}")
    if args.script:
        lines = [ln.strip() for ln in open(args.script, encoding="utf-8")
                 if ln.strip() and not ln.startswith("#")]
        asyncio.run(run_script(args.uid, args.name, lines, args.show_mem))
    else:
        asyncio.run(run_interactive(args.uid, args.name, args.show_mem))


if __name__ == "__main__":
    main()
