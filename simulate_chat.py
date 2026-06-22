"""
simulate_chat.py — จำลองการคุย 9 รอบเพื่อ trigger การสรุป history

รัน: python simulate_chat.py
(ต้อง Ollama กำลังทำงานอยู่ที่ localhost:11434)
"""
import asyncio
import os
import pathlib
import sys

# ── ตั้งค่า working dir ให้ชี้มาที่โฟลเดอร์ mybot เสมอ ──────────────────────
os.chdir(pathlib.Path(__file__).parent)

# ── ตั้งค่าการทดสอบ ───────────────────────────────────────────────────────────
TEST_USER_ID   = 111_111_111_111_111_111   # ไม่ชนกับ user จริง
TEST_USER_NAME = "ผู้ทดสอบ"

# 9 ข้อความ — รอบที่ 9 จะ trigger เพราะ history เต็ม (8 คู่) แล้วล้น
MESSAGES = [
    "สวัสดีค่ะ วันนี้อากาศดีมากเลยนะ",
    "ฉันชื่อจูเลียนะ ทำงานเป็นโปรแกรมเมอร์",
    "ฉันชอบอ่านหนังสือนิยายวิทยาศาสตร์มากเลย",
    "แนะนำหนังสือ sci-fi ดีๆ ให้หน่อยได้ไหม",
    "โอ้โห เยอะมากเลย ขอบคุณนะคะ",
    "แล้วรอสเต้ชอบแนวหนังสือไหนบ้าง",
    "น่าสนใจมากเลยนะ ชอบเหมือนกันเลย",
    "ถ้าอยากเริ่มอ่าน sci-fi ควรเริ่มจากเล่มไหนดี",
    "โอเค ขอบคุณมากนะคะ ลองดูแล้วกัน",   # รอบ 9 → trigger!
]

# ─────────────────────────────────────────────────────────────────────────────

def hr(char="─", w=62):
    print(char * w)

def snapshot(mem_module, label=""):
    m = mem_module.load_memory(TEST_USER_ID)
    h = len(m.get("history", []))
    s = len(m.get("summaries", []))
    f = len(m.get("facts", []))
    tag = f"  {label}" if label else ""
    print(f"   📊 history={h} msgs  summaries={s}  facts={f}{tag}")
    return m


async def main():
    import bot
    import memory

    MAX       = bot.MAX_HISTORY_PAIRS           # 8
    TRIGGER   = MAX + 1                         # 9
    mem_path  = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")

    # เคลียร์ memory ทดสอบเก่า
    if os.path.exists(mem_path):
        os.remove(mem_path)
        print(f"🗑️  ลบ memory เก่าของ test user แล้ว")

    hr("═")
    print(f"  จำลองการคุย {len(MESSAGES)} รอบ  |  trigger ที่รอบ {TRIGGER}")
    print(f"  MAX_HISTORY_PAIRS={MAX}  MAX_SUMMARIES={memory.MAX_SUMMARIES}")
    hr("═")
    print()

    background_tasks = []

    for i, msg in enumerate(MESSAGES, 1):
        is_trigger = (i == TRIGGER)
        hr()
        flag = "  ◀ history เต็ม → trigger summarize!" if is_trigger else ""
        print(f"รอบที่ {i}/{len(MESSAGES)}{flag}")
        print(f"  👤  {msg}")

        # เรียก ask_ollama (สร้าง background task summarize เองถ้า history ล้น)
        reply = await bot.ask_ollama(TEST_USER_ID, TEST_USER_NAME, msg)
        short = reply[:110] + ("…" if len(reply) > 110 else "")
        print(f"  🤖  {short}")

        # เลียนแบบ on_message: ยิง auto_remember เบื้องหลัง
        t = asyncio.create_task(bot.auto_remember(TEST_USER_ID, TEST_USER_NAME, msg))
        background_tasks.append(t)

        # snapshot ทันที (background อาจยังไม่เสร็จ)
        snapshot(memory, "(ก่อน background เสร็จ)")
        print()

    # รอ background tasks ทั้งหมด (auto_remember + summarize_old_history)
    hr("═")
    all_pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if all_pending:
        print(f"⏳ รอ {len(all_pending)} background task(s) เสร็จ...")
        try:
            await asyncio.wait_for(
                asyncio.gather(*all_pending, return_exceptions=True),
                timeout=180,
            )
            print("   ✅ เสร็จสมบูรณ์")
        except asyncio.TimeoutError:
            print("   ⚠️ timeout 180s — โมเดลอาจช้ามาก ลองรันใหม่")
    else:
        print("ℹ️  ไม่มี background tasks ค้างอยู่")

    # ──── ผลลัพธ์สุดท้าย ──────────────────────────────────────────────────────
    hr("═")
    final = memory.load_memory(TEST_USER_ID)
    print()
    print("📋  ผลลัพธ์สุดท้าย")
    hr()
    print(f"  history   : {len(final.get('history', []))} messages (เก็บสูงสุด {MAX*2})")
    facts = final.get("facts", [])
    print(f"  facts     : {facts if facts else '(ยังไม่มี)'}")

    summaries = final.get("summaries", [])
    print(f"  summaries : {len(summaries)} รายการ")
    if summaries:
        print()
        for s in summaries:
            print(f"    📝  {s}")
    else:
        print("    (ยังไม่มี — อาจเกิดจาก: โมเดลตอบว่างเปล่า / background task ยังไม่เสร็จ)")
    hr("═")

    # ──── ถามว่าจะเก็บ memory ไว้ไหม ─────────────────────────────────────────
    print()
    print(f"ไฟล์ memory test อยู่ที่: {mem_path}")
    print("ลบออกไหม? (y/n) ", end="", flush=True)
    try:
        ans = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "y"

    if ans != "n":
        if os.path.exists(mem_path):
            os.remove(mem_path)
        print("   ลบแล้ว")
    else:
        print("   เก็บไว้")


if __name__ == "__main__":
    asyncio.run(main())
