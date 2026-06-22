"""
simulate_chat_long.py — จำลองการคุย 18 รอบ เพื่อดูว่า summaries สะสมยังไง

หัวข้อแบ่งเป็น 3 ช่วง:
  รอบ  1– 6 : หนังสือ / sci-fi
  รอบ  7–12 : งาน / โปรแกรมมิ่ง
  รอบ 13–18 : อาหาร / ร้านค้า

trigger สรุปเริ่มที่รอบ 9 (ทุกรอบหลังจากนั้น) → ควรได้ 10 summaries
รอบ 1–8  : รันเร็ว ไม่รอ background
รอบ 9–18 : drain background tasks ก่อน snapshot ทุกรอบ

รัน: python simulate_chat_long.py
(ต้อง Ollama กำลังทำงาน localhost:11434)
"""
import asyncio
import os
import pathlib
import sys

os.chdir(pathlib.Path(__file__).parent)

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
    "หิวข้าวแล้วค่ะ ตอนนี้อยู่แถวชุมพร",
    "มีร้านก๋วยเตี๋ยวอร่อยๆ แถวชุมพรแนะนำได้บ้างไหม",
    "อาหารทะเลสดๆ ล่ะ ชุมพรน่าจะมีเยอะนะคะ ร้านไหนดี",
    "ราคาพอสมควรไหม ไม่ต้องหรูมาก แค่อร่อยและสดก็พอ",
    "โอเค ขอบคุณมากเลยนะคะ แวะไปลองดูแล้วกัน",
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

def show_summaries(summaries, prev_count=0):
    """ปริ้น summaries โดย highlight รายการใหม่ที่เพิ่งเพิ่มเข้ามา"""
    if not summaries:
        print("   (ยังไม่มี summary)")
        return
    for idx, s in enumerate(summaries):
        marker = "🆕" if idx >= prev_count else "  "
        print(f"   {marker} {idx+1:2d}. {s}")


async def drain(label="", timeout=DRAIN_TIMEOUT):
    """รอ background tasks ทั้งหมดจนเสร็จ คืนจำนวน tasks ที่รอ"""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if not pending:
        return 0
    tag = f" ({label})" if label else ""
    print(f"   ⏳ รอ {len(pending)} background task(s){tag}...")
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
        print(f"   ✅ background tasks เสร็จแล้ว")
    except asyncio.TimeoutError:
        print(f"   ⚠️  timeout {timeout}s — task อาจยังไม่เสร็จ ดำเนินต่อ")
    return len(pending)


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    import bot
    import memory

    MAX      = bot.MAX_HISTORY_PAIRS          # 8 คู่ = 16 msgs
    TRIGGER  = MAX + 1                        # รอบที่ 9 trigger แรก
    N        = len(MESSAGES)
    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")

    if os.path.exists(mem_path):
        os.remove(mem_path)
        print(f"🗑️  ลบ memory เก่าของ test user แล้ว")

    hr("═")
    print(f"  จำลองการคุย {N} รอบ  |  trigger ที่รอบ {TRIGGER}–{N}  (= {N-TRIGGER+1} summaries)")
    print(f"  MAX_HISTORY_PAIRS={MAX}  MAX_SUMMARIES={memory.MAX_SUMMARIES}")
    hr("═")

    prev_sum_count = 0   # ติดตามจำนวน summaries รอบก่อน

    for i, msg in enumerate(MESSAGES, 1):
        is_trigger = (i >= TRIGGER)
        phase = PHASE_LABELS[i]

        hr()
        flag = "  ◀ trigger" if is_trigger else ""
        print(f"รอบ {i:2d}/{N}  {phase}{flag}")
        print(f"  👤  {msg}")

        reply = await bot.ask_ollama(TEST_USER_ID, TEST_USER_NAME, msg)
        short = reply[:100] + ("…" if len(reply) > 100 else "")
        print(f"  🤖  {short}")

        # เลียนแบบ on_message: ยิง auto_remember เบื้องหลัง
        asyncio.create_task(bot.auto_remember(TEST_USER_ID, TEST_USER_NAME, msg))

        if is_trigger:
            # drain ก่อน snapshot — กัน summaries ยังไม่เขียนลงไฟล์
            await drain("auto_remember + summarize_old_history")

        snap  = memory.load_memory(TEST_USER_ID)
        h_len = len(snap.get("history",   []))
        sums  = snap.get("summaries", [])
        facts = snap.get("facts", [])

        print(f"  📊 history={h_len}  summaries={len(sums)}  facts={len(facts)}")

        if is_trigger and sums:
            show_summaries(sums, prev_sum_count)
            prev_sum_count = len(sums)

        print()

    # ── รอ tasks ค้างสุดท้าย (ถ้ายังมี) ──────────────────────────────────────
    remaining = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if remaining:
        hr("═")
        await drain("cleanup รอบสุดท้าย")

    # ── ผลลัพธ์สุดท้าย ────────────────────────────────────────────────────────
    hr("═")
    final = memory.load_memory(TEST_USER_ID)
    sums  = final.get("summaries", [])
    facts = final.get("facts", [])

    print()
    print("📋  ผลลัพธ์สุดท้าย — summaries ทั้งหมดเรียงตามลำดับ")
    hr()
    print(f"  history : {len(final.get('history', []))} messages  (เก็บสูงสุด {MAX*2})")
    print(f"  facts   : {facts if facts else '(ยังไม่มี)'}")
    print(f"  summaries: {len(sums)} / {N - TRIGGER + 1} รายการที่ควรได้")
    print()

    if sums:
        for idx, s in enumerate(sums, 1):
            print(f"  {idx:2d}. 📝  {s}")
    else:
        print("  (ไม่มี summary — ตรวจสอบ: Ollama รันอยู่ไหม? โมเดลตอบว่างเปล่าไหม?)")

    hr()
    # วิเคราะห์ coverage
    phases = {"📚 หนังสือ": 0, "💻 โปรแกรมมิ่ง": 0, "🍜 อาหาร": 0}
    for s in sums:
        low = s.lower()
        if any(w in low for w in ["หนังสือ", "sci-fi", "อ่าน", "asimov", "dune", "เล่ม", "นิยาย", "แนะนำหนังสือ"]):
            phases["📚 หนังสือ"] += 1
        elif any(w in low for w in ["โปรแกรม", "python", "async", "chatbot", "memory", "test", "lock", "code", "coding", "race"]):
            phases["💻 โปรแกรมมิ่ง"] += 1
        elif any(w in low for w in ["อาหาร", "ก๋วยเตี๋ยว", "ร้าน", "ทะเล", "ชุมพร", "กิน", "หิว", "ราคา"]):
            phases["🍜 อาหาร"] += 1
    total_matched = sum(phases.values())
    unmatched = len(sums) - total_matched
    print("  📊 coverage ของ summaries (keyword match):")
    for p, c in phases.items():
        bar = "█" * c + "░" * (5 - c)
        print(f"     {p}      {bar}  ({c} รายการ)")
    if unmatched:
        print(f"     ❓ ไม่ระบุหัวข้อ            ({unmatched} รายการ)")
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
