"""
simulate_recall.py — ทดสอบ recall_summaries กับ summaries จริงจาก Ollama

ขั้นตอน:
  1. จำลองคุย 18 รอบ (หนังสือ/งาน/อาหาร) เพื่อสะสม summaries
  2. drain background tasks จนครบ
  3. ยิง test cases หลายแบบ → ปริ้น recall_summaries คืนอะไร

รัน: python simulate_recall.py
(ต้อง Ollama กำลังทำงาน localhost:11434)
"""
import asyncio
import os
import pathlib
import sys

os.chdir(pathlib.Path(__file__).parent)

import bot     # noqa: E402 — หลัง chdir เพื่อให้ config/memory paths ถูกต้อง
import memory  # noqa: E402

TEST_USER_ID   = 333_333_333_333_333_333
TEST_USER_NAME = "ผู้ทดสอบ"
DRAIN_TIMEOUT  = 180

# ── 18 ข้อความเดียวกับ simulate_chat_long.py ─────────────────────────────────
SETUP_MESSAGES = [
    # ช่วงที่ 1: หนังสือ / sci-fi (รอบ 1–6)
    "สวัสดีค่ะ ฉันชอบอ่านหนังสือมากเลย โดยเฉพาะแนว sci-fi",
    "ชอบ Isaac Asimov มากเป็นพิเศษเลย อ่าน Foundation จบแล้ว",
    "มีนิยาย sci-fi เรื่องไหนอีกที่คิดว่าน่าอ่านบ้าง",
    "Frank Herbert เขียน Dune ดีไหม เคยได้ยินชื่อแต่ยังไม่ได้อ่าน",
    "โอ้ ฟังดูน่าสนใจมาก จดชื่อไว้แล้ว ขอบคุณนะคะ",
    "แล้วถ้าอยากอ่านแนว hard sci-fi จริงๆ ควรเริ่มจากเล่มไหนดี",
    # ช่วงที่ 2: งาน / โปรแกรมมิ่ง (รอบ 7–12)
    "เปลี่ยนเรื่องหน่อยนะคะ ฉันทำงานเป็นโปรแกรมเมอร์ Python",
    "กำลังพัฒนา chatbot ที่ใช้ asyncio จัดการหลาย user พร้อมกัน",
    "เจอปัญหา race condition ตอน memory หลาย coroutine เข้าพร้อมกัน",
    "ใช้ asyncio.Lock ต่อ user_id แก้ได้ไหม หรือมีวิธีดีกว่า",
    "เขียน unit test ด้วย pytest แล้วก็ผ่านหมดเลย รู้สึกดีมาก",
    "ขอบคุณสำหรับคำแนะนำด้าน async programming นะคะ",
    # ช่วงที่ 3: อาหาร / ร้านค้า (รอบ 13–18)
    "หิวข้าวแล้วค่ะ ตอนนี้อยู่แถวชุมพร",
    "มีร้านก๋วยเตี๋ยวอร่อยๆ แถวชุมพรแนะนำได้บ้างไหม",
    "อาหารทะเลสดๆ ล่ะ ชุมพรน่าจะมีเยอะนะคะ ร้านไหนดี",
    "ราคาพอสมควรไหม ไม่ต้องหรูมาก แค่อร่อยและสดก็พอ",
    "โอเค ขอบคุณมากเลยนะคะ แวะไปลองดูแล้วกัน",
    "วันนี้ได้คุยหลายเรื่องมากเลยนะ ทั้งหนังสือ งาน และอาหาร",
]

# ── test cases สำหรับทดสอบ recall ────────────────────────────────────────────
RECALL_CASES = [
    {
        "label": "1. ถามอดีตตรงๆ (keyword ตรง)",
        "msg": "จำได้ไหมที่เคยคุยเรื่อง Dune",
        "expect": "ควรดึง summary หนังสือ/Dune มา",
        "should_recall": True,
    },
    {
        "label": "2. ถามอดีตกว้างๆ (ไม่มี keyword เฉพาะ)",
        "msg": "เมื่อก่อนเราคุยเรื่องอะไรบ้าง",
        "expect": "มี PAST_HINT แต่ไม่มี keyword match → คืน []",
        "should_recall": False,
    },
    {
        "label": "3. ถามอดีต + keyword งาน",
        "msg": "ก่อนหน้านี้ที่บอกว่าเขียน Python อยู่นั้น ทำงานที่ไหน",
        "expect": "ควรดึง summary งาน/Python มา",
        "should_recall": True,
    },
    {
        "label": "4. คุยปกติ ไม่ถามอดีต",
        "msg": "อยากกินก๋วยเตี๋ยว",
        "expect": "ไม่มี PAST_HINT → คืน [] ทุกกรณี",
        "should_recall": False,
    },
    {
        "label": "5. ก้ำกึ่ง: มี 'จำได้ไหม' แต่ถามอนาคต",
        "msg": "จำได้ไหมว่าพรุ่งนี้ต้องทำอะไร",
        "expect": "มี PAST_HINT แต่ไม่มี keyword match กับ summaries → คืน []",
        "should_recall": False,
    },
    {
        "label": "6. ถามอดีตด้วย 'เคยคุย'",
        "msg": "เคยคุยเรื่องอาหารทะเลกันไหม",
        "expect": "ควรดึง summary อาหาร/ทะเล มา",
        "should_recall": True,
    },
    {
        "label": "7. ถามอดีต + keyword หนังสือ",
        "msg": "ที่เคยบอกว่าชอบอ่านหนังสือ sci-fi อยากรู้ว่าเล่มไหนดีที่สุด",
        "expect": "ควรดึง summary หนังสือ/sci-fi มา",
        "should_recall": True,
    },
    {
        "label": "8. คุยปกติ keyword ตรงกับ summary แต่ไม่มี PAST_HINT",
        "msg": "แนะนำร้านก๋วยเตี๋ยวแถวชุมพรหน่อย",
        "expect": "ไม่มี PAST_HINT → คืน [] แม้มีคำตรง summary",
        "should_recall": False,
    },
]


# ── helpers ───────────────────────────────────────────────────────────────────

def hr(char="─", w=66):
    print(char * w)

def _sum_text(s) -> str:
    return s["text"] if isinstance(s, dict) else s


async def drain(label="", timeout=DRAIN_TIMEOUT):
    """รอ background queue ว่างจนงานเสร็จหมด"""
    tag = f" ({label})" if label else ""
    if bot._bg_queue.empty() and bot._bg_queue._unfinished_tasks == 0:
        return
    print(f"   ⏳ รอ background queue{tag}...")
    try:
        await asyncio.wait_for(bot._bg_queue.join(), timeout=timeout)
        print("   ✅ background queue ว่างแล้ว")
    except asyncio.TimeoutError:
        print(f"   ⚠️  timeout {timeout}s — ดำเนินต่อ")


# ── phase 1: สร้าง summaries ─────────────────────────────────────────────────

async def build_summaries():
    bot._ensure_bg_worker()

    MAX     = bot.MAX_HISTORY_PAIRS
    TRIGGER = MAX + 1
    N       = len(SETUP_MESSAGES)
    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")

    if os.path.exists(mem_path):
        os.remove(mem_path)
        print(f"🗑️  ลบ memory เก่าแล้ว")

    hr("═")
    print(f"  Phase 1: สร้าง summaries — จำลองคุย {N} รอบ")
    print(f"  MAX_HISTORY_PAIRS={MAX}  trigger เริ่มรอบ {TRIGGER}")
    hr("═")

    for i, msg in enumerate(SETUP_MESSAGES, 1):
        is_trigger = (i >= TRIGGER)
        flag = "  ◀ trigger" if is_trigger else ""
        short_msg = msg[:55] + ("…" if len(msg) > 55 else "")
        print(f"  รอบ {i:2d}/{N}{flag}  {short_msg}")

        reply = await bot.ask_ollama(TEST_USER_ID, TEST_USER_NAME, msg)
        bot._enqueue_bg(bot.auto_remember(TEST_USER_ID, TEST_USER_NAME, msg))

        if is_trigger:
            await drain()

    # drain ครั้งสุดท้าย
    await drain("cleanup")

    snap = memory.load_memory(TEST_USER_ID)
    sums = snap.get("summaries", [])
    print()
    hr()
    print(f"  ✅ สร้างเสร็จ — summaries = {len(sums)} รายการ")
    if sums:
        for idx, s in enumerate(sums, 1):
            print(f"     {idx:2d}. {_sum_text(s)}")
    else:
        print("     (ไม่มี — ตรวจว่า Ollama รันอยู่ไหม)")
    hr()
    print()
    return sums


# ── phase 2: ทดสอบ recall ─────────────────────────────────────────────────────

def run_recall_tests(sums):
    if not sums:
        print("⚠️  ไม่มี summaries — ข้าม phase 2")
        return

    mem = memory.load_memory(TEST_USER_ID)

    hr("═")
    print(f"  Phase 2: ทดสอบ recall_summaries — {len(RECALL_CASES)} เคส")
    hr("═")
    print()

    passed = 0
    failed = 0

    for case in RECALL_CASES:
        label      = case["label"]
        msg        = case["msg"]
        expect_txt = case["expect"]
        should     = case["should_recall"]

        result = memory.recall_summaries(mem, msg)
        got    = len(result) > 0

        # ตรวจว่าตรงกับที่คาดหวัง
        if got == should:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1

        hr()
        print(f"  {status}  {label}")
        print(f"  ข้อความ : \"{msg}\"")
        print(f"  คาดหวัง: {expect_txt}")

        # ตรวจ PAST_HINT ที่ trigger
        triggered_hints = [h for h in memory.PAST_HINTS if h in msg]
        if triggered_hints:
            print(f"  PAST_HINT ที่จับได้: {triggered_hints}")
        else:
            print(f"  PAST_HINT: ไม่พบ (ไม่ trigger การค้น)")

        if result:
            print(f"  recall คืน {len(result)} รายการ:")
            for r in result:
                print(f"    📝 {r}")
        else:
            print(f"  recall คืน [] (ไม่ inject)")
        print()

    hr("═")
    total = len(RECALL_CASES)
    print(f"  ผลรวม: {passed}/{total} passed  {'✅ ทั้งหมดผ่าน' if failed == 0 else f'❌ {failed} ไม่ผ่าน'}")
    hr("═")


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")

    try:
        sums = await build_summaries()
        run_recall_tests(sums)
    finally:
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
