"""
simulate_chat_long.py — จำลองการคุย 18 รอบ ดูว่า summaries ตรงเรื่องไหม

หัวข้อแบ่งเป็น 3 ช่วง:
  รอบ  1– 6 : หนังสือ / sci-fi
  รอบ  7–12 : งาน / โปรแกรมมิ่ง
  รอบ 13–18 : อาหาร / ร้านค้า

trigger สรุป (ระบบใหม่):
  Condition A (เปลี่ยนหัวข้อ) — คาดว่าจะ fire รอบ ~7 และ ~13
  Condition B (บทเต็ม 8 คู่)   — fire ถ้าหัวข้อไม่เปลี่ยนแต่บทยาวถึง 8 คู่
  flush ตอนจบ              — สรุปบทสุดท้ายที่ค้างอยู่

รอบ 1–6  : รันเร็ว (ไม่น่ามี background task ให้รอ)
รอบ 7–18 : drain ทุกรอบ เพราะ Condition A อาจ fire ตั้งแต่รอบ 7

รัน: python simulate_chat_long.py
(ต้อง Ollama กำลังทำงาน localhost:11434)
"""
import asyncio
import os
import pathlib
import sys

# Windows console อาจใช้ cp874 — บังคับ UTF-8 เพื่อให้ emoji/ภาษาไทยออกถูก
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.chdir(pathlib.Path(__file__).parent)

import bot     # noqa: E402 — หลัง chdir เพื่อให้ config/memory paths ถูกต้อง
import memory  # noqa: E402

# ── ค่าคงที่ ──────────────────────────────────────────────────────────────────
TEST_USER_ID   = 222_222_222_222_222_222
TEST_USER_NAME = "ผู้ทดสอบ"
DRAIN_TIMEOUT  = 180   # วินาที รอ background task แต่ละรอบ

# ── 18 ข้อความ แบ่ง 3 ช่วงหัวข้อ ────────────────────────────────────────────
MESSAGES = [
    # ── ช่วงที่ 1: หนังสือ / sci-fi (รอบ 1–6) ──────────────────────────────
    "สวัสดีค่ะ ฉันชอบอ่านหนังสือมากเลย โดยเฉพาะแนว sci-fi",
    "ชอบ Isaac Asimov มากเป็นพิเศษเลย อ่าน Foundation จบแล้ว",
    "มีนิยาย sci-fi เรื่องไหนอีกที่คิดว่าน่าอ่านบ้าง",
    "Frank Herbert เขียน Dune ดีไหม เคยได้ยินชื่อแต่ยังไม่ได้อ่าน",
    "โอ้ ฟังดูน่าสนใจมาก จดชื่อไว้แล้ว ขอบคุณนะคะ",
    "แล้วถ้าอยากอ่านแนว hard sci-fi จริงๆ ควรเริ่มจากเล่มไหนดี",

    # ── ช่วงที่ 2: งาน / โปรแกรมมิ่ง (รอบ 7–12) ─────────────────────────
    "เปลี่ยนเรื่องหน่อยนะคะ ฉันทำงานเป็นโปรแกรมเมอร์ Python",
    "กำลังพัฒนา chatbot ที่ใช้ asyncio จัดการหลาย user พร้อมกัน",
    "เจอปัญหา race condition ตอน memory หลาย coroutine เข้าพร้อมกัน",  # ← รอบ 9 trigger!
    "ใช้ asyncio.Lock ต่อ user_id แก้ได้ไหม หรือมีวิธีดีกว่า",
    "เขียน unit test ด้วย pytest แล้วก็ผ่านหมดเลย รู้สึกดีมาก",
    "ขอบคุณสำหรับคำแนะนำด้าน async programming นะคะ",

    # ── ช่วงที่ 3: อาหาร / ร้านค้า (รอบ 13–18) ─────────────────────────
    # หลีกเลี่ยงการระบุจังหวัด เพื่อกัน simulate trigger Google Maps (ต้องการ requests)
    "หิวข้าวแล้วค่ะ ชอบกินอาหารทะเลเป็นพิเศษเลย",
    "ชอบก๋วยเตี๋ยวต้มยำทะเลมากเลย แต่หาร้านอร่อยยากจัง",
    "อาหารทะเลสดๆ กับข้าวผัดทะเลอะ อย่างไหนโดนใจกว่ากัน",
    "ราคาพอสมควรก็พอนะคะ ไม่ต้องหรูมาก แค่อร่อยและสด",
    "โอเค ขอบคุณสำหรับคำแนะนำเรื่องอาหารนะคะ",
    "วันนี้ได้คุยหลายเรื่องมากเลยนะ ทั้งหนังสือ งาน และอาหาร",  # ← รอบ 18
]

# ── helper ────────────────────────────────────────────────────────────────────

PHASE_LABELS = {
    1: "📚 หนังสือ", 2: "📚 หนังสือ", 3: "📚 หนังสือ",
    4: "📚 หนังสือ", 5: "📚 หนังสือ", 6: "📚 หนังสือ",
    7: "💻 โปรแกรมมิ่ง", 8: "💻 โปรแกรมมิ่ง", 9: "💻 โปรแกรมมิ่ง",
    10: "💻 โปรแกรมมิ่ง", 11: "💻 โปรแกรมมิ่ง", 12: "💻 โปรแกรมมิ่ง",
    13: "🍜 อาหาร", 14: "🍜 อาหาร", 15: "🍜 อาหาร",
    16: "🍜 อาหาร", 17: "🍜 อาหาร", 18: "🍜 อาหาร",
}

def hr(char="─", w=64):
    print(char * w)

def _sum_text(s) -> str:
    """คืน text จาก summary ไม่ว่าจะเป็น dict ใหม่หรือ string เก่า"""
    return s["text"] if isinstance(s, dict) else s

def show_summaries(summaries, prev_count=0):
    """ปริ้น summaries โดย highlight รายการใหม่ที่เพิ่งเพิ่มเข้ามา"""
    if not summaries:
        print("   (ยังไม่มี summary)")
        return
    for idx, s in enumerate(summaries):
        marker = "🆕" if idx >= prev_count else "  "
        print(f"   {marker} {idx+1:2d}. {_sum_text(s)}")


async def drain(label="", timeout=DRAIN_TIMEOUT):
    """รอ background queue ว่างจนงานเสร็จหมด (ใช้ queue.join แทน all_tasks)"""
    tag = f" ({label})" if label else ""
    # ไม่มีงานค้างใน queue — return ทันที
    if bot._bg_queue.empty() and bot._bg_queue._unfinished_tasks == 0:
        return 0
    print(f"   ⏳ รอ background queue{tag}...")
    try:
        await asyncio.wait_for(bot._bg_queue.join(), timeout=timeout)
        print(f"   ✅ background queue ว่างแล้ว")
    except asyncio.TimeoutError:
        print(f"   ⚠️  timeout {timeout}s — queue อาจยังไม่ว่าง ดำเนินต่อ")
    return 1


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    bot._ensure_bg_worker()   # เริ่ม background queue worker ก่อนรอบแรก

    # simulate ทดสอบ memory/summarization เท่านั้น — ปิด realtime (maps/weather/oil)
    # เพื่อกัน requests/SerpAPI ที่อาจไม่ได้ติดตั้งใน environment นี้
    async def _no_realtime(user_message, mem, user_id):
        return None
    bot.get_realtime_context = _no_realtime

    MAX      = bot.MAX_HISTORY_PAIRS          # 8 คู่ = 16 msgs
    DRAIN_FROM = 7                            # drain ตั้งแต่รอบที่ 7 (Condition A คาดว่า fire)
    N        = len(MESSAGES)
    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")

    if os.path.exists(mem_path):
        os.remove(mem_path)
        print(f"🗑️  ลบ memory เก่าของ test user แล้ว")

    hr("═")
    print(f"  จำลองการคุย {N} รอบ  |  Cond-A คาดที่รอบ ~7 และ ~13  |  Cond-B ที่รอบ 8+")
    print(f"  MAX_HISTORY_PAIRS={MAX}  MAX_SUMMARIES={memory.MAX_SUMMARIES}")
    hr("═")

    prev_sum_count = 0   # ติดตามจำนวน summaries รอบก่อน

    for i, msg in enumerate(MESSAGES, 1):
        is_trigger = (i >= DRAIN_FROM)
        phase = PHASE_LABELS[i]

        hr()
        expected_cond = ""
        if i == 7:  expected_cond = "  ◀ Cond-A คาดว่า fire (หนังสือ→งาน)"
        elif i == 13: expected_cond = "  ◀ Cond-A คาดว่า fire (งาน→อาหาร)"
        elif is_trigger: expected_cond = "  ◀ drain"
        flag = expected_cond
        print(f"รอบ {i:2d}/{N}  {phase}{flag}")
        print(f"  👤  {msg}")

        reply = await bot.ask_ollama(TEST_USER_ID, TEST_USER_NAME, msg)

        # แสดงตอบ (ตัดสั้นถ้ายาว) + ตรวจว่ามี notice phrase ท้ายตอบไหม
        has_notice = "\n\n" in reply and any(
            p in reply for p in bot._SUMMARY_NOTICE_PHRASES
        )
        if has_notice:
            main_part, notice_part = reply.rsplit("\n\n", 1)
            short = main_part[:80] + ("…" if len(main_part) > 80 else "")
            print(f"  🤖  {short}")
            print(f"  📢  [notice] {notice_part}")
        else:
            short = reply[:100] + ("…" if len(reply) > 100 else "")
            print(f"  🤖  {short}")

        # เลียนแบบ on_message: ส่ง auto_remember เข้า background queue
        bot._enqueue_bg(bot.auto_remember(TEST_USER_ID, TEST_USER_NAME, msg))

        if is_trigger:
            # drain ก่อน snapshot — กัน summarize_and_verify ยังไม่เขียนลงไฟล์
            await drain("auto_remember + summarize_and_verify")

        snap  = memory.load_memory(TEST_USER_ID)
        h_len = len(snap.get("history",   []))
        sums  = snap.get("summaries", [])
        facts = snap.get("facts", [])

        print(f"  📊 history={h_len}  summaries={len(sums)}  facts={len(facts)}")

        if is_trigger and sums:
            show_summaries(sums, prev_sum_count)
            prev_sum_count = len(sums)

        print()

    # ── flush history ที่ค้างอยู่ (บทสุดท้าย = phase 3) ──────────────────────
    hr("═")
    print("  🔒 flush history ที่ค้าง (บทสุดท้าย)...")
    await bot.flush_user_history(TEST_USER_ID)
    # flush_user_history จัดการ queue.join เองแล้ว — drain เป็น safety net
    await drain("cleanup รอบสุดท้าย")

    # ── ผลลัพธ์สุดท้าย ────────────────────────────────────────────────────────
    hr("═")
    final = memory.load_memory(TEST_USER_ID)
    sums  = final.get("summaries", [])
    facts = final.get("facts", [])

    print()
    print("📋  ผลลัพธ์สุดท้าย — summaries ทั้งหมดเรียงตามลำดับ")
    hr()
    print(f"  history  : {len(final.get('history', []))} messages  (เก็บสูงสุด {MAX*2})")
    print(f"  facts    : {facts if facts else '(ยังไม่มี)'}")
    print(f"  summaries: {len(sums)} รายการ")
    print()

    if sums:
        for idx, s in enumerate(sums, 1):
            print(f"  {idx:2d}. 📝  {_sum_text(s)}")
    else:
        print("  (ไม่มี summary — ตรวจสอบ: Ollama รันอยู่ไหม? โมเดลตอบว่างเปล่าไหม?)")

    hr()
    # วิเคราะห์ topic accuracy — แต่ละ phase ควรได้ ≥1 summary ที่ตรงหัวข้อ
    phases = {"📚 หนังสือ": 0, "💻 โปรแกรมมิ่ง": 0, "🍜 อาหาร": 0}
    BOOK_KW  = ["หนังสือ", "sci-fi", "อ่าน", "asimov", "dune", "เล่ม", "นิยาย",
                "แนะนำ", "วรรณกรรม", "นักเขียน", "fantasy", "herbert", "foundation"]
    PROG_KW  = ["โปรแกรม", "python", "async", "asyncio", "chatbot", "memory",
                "test", "pytest", "unit test", "lock", "race", "race condition",
                "coroutine", "bug", "code", "coding", "developer", "programmer"]
    FOOD_KW  = ["อาหาร", "ก๋วยเตี๋ยว", "ร้านอาหาร", "ร้าน", "ทะเล", "ชุมพร",
                "กิน", "หิว", "ราคา", "เมนู", "อร่อย", "seafood", "ข้าว"]
    for s in sums:
        low = _sum_text(s).lower()
        if any(w in low for w in BOOK_KW):
            phases["📚 หนังสือ"] += 1
        elif any(w in low for w in PROG_KW):
            phases["💻 โปรแกรมมิ่ง"] += 1
        elif any(w in low for w in FOOD_KW):
            phases["🍜 อาหาร"] += 1
    unmatched = len(sums) - sum(phases.values())
    print("  📊 topic accuracy (keyword match) — แต่ละหัวข้อควรได้ ≥1:")
    all_pass = True
    for p, c in phases.items():
        ok = "✅" if c >= 1 else "❌"
        if c < 1: all_pass = False
        bar = "█" * min(c, 5) + "░" * max(0, 5 - c)
        print(f"     {ok} {p}   {bar}  ({c} รายการ)")
    if unmatched:
        print(f"        ❓ ไม่ระบุหัวข้อ ({unmatched} รายการ)")
    print()
    if all_pass:
        print("  ✅ ทุกหัวข้อได้รับ summary อย่างน้อย 1 รายการ")
    else:
        print("  ❌ บางหัวข้อยังไม่ได้รับ summary — ลอง re-run หรือตรวจ Ollama")
    hr("═")

    # ── cleanup ────────────────────────────────────────────────────────────────
    print()
    print(f"ไฟล์ memory test: {mem_path}")
    print("ลบออกไหม? (y/n) ", end="", flush=True)
    try:
        ans = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "y"
    if ans != "n":
        if os.path.exists(mem_path):
            os.remove(mem_path)
        print("  ลบแล้ว")
    else:
        print("  เก็บไว้")


if __name__ == "__main__":
    asyncio.run(main())
