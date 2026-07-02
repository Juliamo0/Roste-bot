"""
simulate_fact_consolidation.py — ทดสอบ fact supersede/consolidation แบบ end-to-end กับ Ollama จริง

ทำไมต้องมีสคริปต์นี้แยกจาก test_memory.py: unit tests ทั้งหมดป้อน {category, text} มือ
(ควบคุมได้เต็มที่) แต่ไม่เคยพิสูจน์ว่า "โมเดลจริง" (qwen3:8b) จะออก category ตรงกับ
FACT_CATEGORIES จริงๆ ผ่าน build_extract_prompt ที่เพิ่งแก้ — อันนี้คือจุดเสี่ยงที่สุดของ
งานนี้ (เหมือนที่ tool-calling เจอปัญหาโมเดลออกฟอร์แมตไม่ตรงมาก่อน)

ขั้นตอน:
  1. คุยบอกที่อยู่ครั้งแรก ("อยู่ชุมพร") → auto_remember ควรสกัด category="ที่อยู่" จริง
  2. คุยบอกว่าย้ายที่อยู่ ("ย้ายไปกรุงเทพแล้ว") → ต้อง supersede อันเก่า ไม่ใช่เพิ่มซ้อน
  3. เช็คว่า recall_facts คืนเฉพาะที่อยู่ปัจจุบัน (กรุงเทพ) ไม่ใช่ทั้งคู่
  4. เช็คว่าของเก่า (ชุมพร) ยังอยู่ใน mem จริง (ไม่ถูกลบ) แค่ superseded=True

รัน: python simulate_fact_consolidation.py
(ต้อง Ollama กำลังทำงานที่ localhost:11434)
"""
import asyncio
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import bot      # noqa: E402
import memory   # noqa: E402

TEST_USER_ID = 666_666_666_666_666_666   # ไม่ชนกับ test user สคริปต์อื่น (111/222/333/444/555)
TEST_USER_NAME = "ผู้ทดสอบ"


def hr(char="─", w=66):
    print(char * w)


async def main():
    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")
    if os.path.exists(mem_path):
        os.remove(mem_path)
        print("🗑️  ลบ memory เก่าของ test user แล้ว")

    hr("═")
    print("  จำลองทดสอบ fact supersede/consolidation กับ Ollama จริง")
    hr("═")
    print()

    msgs = [
        "สวัสดีค่ะ ฉันอยู่ชุมพรนะ",
        "อ้อ ลืมบอกไป ตอนนี้ย้ายไปอยู่กรุงเทพแล้วนะ ไม่ได้อยู่ชุมพรแล้ว",
    ]
    for i, msg in enumerate(msgs, 1):
        hr()
        print(f"  รอบ {i}: {msg!r}")
        await bot.auto_remember(TEST_USER_ID, TEST_USER_NAME, msg)
        mem = memory.load_memory(TEST_USER_ID)
        for f in mem["facts"]:
            tag = "❌ superseded" if isinstance(f, dict) and f.get("superseded") else "✅ current"
            print(f"    {tag}  {f}")

    hr("═")
    print("  ผลตรวจ")
    hr("═")

    mem = memory.load_memory(TEST_USER_ID)
    facts = mem["facts"]
    passed = failed = 0

    # 1) มี fact category="ที่อยู่" อย่างน้อย 1 อัน (โมเดลจัดหมวดถูกจริง)
    address_facts = [f for f in facts if isinstance(f, dict) and f.get("category") == "ที่อยู่"]
    ok = len(address_facts) >= 1
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  มี fact category='ที่อยู่' อย่างน้อย 1 อัน (โมเดลจัดหมวดถูก)")
    passed += ok
    failed += not ok

    # 2) มีอย่างน้อย 1 อันที่ superseded (การย้ายที่อยู่ถูกจับเป็น supersede ไม่ใช่แค่เพิ่มซ้อน)
    superseded = [f for f in address_facts if f.get("superseded")]
    ok = len(superseded) >= 1
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  ที่อยู่เก่าถูก mark superseded (ไม่ใช่แค่เพิ่มซ้อนกัน)")
    passed += ok
    failed += not ok

    # 3) recall_facts คืนเฉพาะที่อยู่ปัจจุบัน ไม่ใช่ทั้งคู่พร้อมกัน
    recalled = memory.recall_facts(mem, "ตอนนี้อยู่จังหวัดไหน")
    recalled_text = " | ".join(recalled)
    has_bkk = "กรุงเทพ" in recalled_text
    has_both = "ชุมพร" in recalled_text and "กรุงเทพ" in recalled_text
    ok = has_bkk and not has_both
    print(f"  {'✅ PASS' if ok else '❌ FAIL'}  recall_facts คืนที่อยู่ปัจจุบันเดียว ไม่ใช่ทั้งเก่า+ใหม่พร้อมกัน")
    print(f"    recall_facts('ตอนนี้อยู่จังหวัดไหน') = {recalled}")
    passed += ok
    failed += not ok

    # 4) ของเก่ายังอยู่ใน mem จริง (ไม่ถูกลบ) — เปิดดูตรงๆ ไม่ผ่าน recall
    old_still_present = any(
        isinstance(f, dict) and "ชุมพร" in f.get("text", "") for f in facts
    )
    print(f"  {'✅ PASS' if old_still_present else '❌ FAIL'}  ที่อยู่เก่า (ชุมพร) ยังอยู่ใน mem จริง ไม่ถูกลบถาวร")
    passed += old_still_present
    failed += not old_still_present

    hr("═")
    print(f"  🏁 รวม: {passed}/{passed + failed} passed")
    hr("═")

    if os.path.exists(mem_path):
        os.remove(mem_path)
        print("🗑️  ลบ memory ทดสอบแล้ว")


if __name__ == "__main__":
    asyncio.run(main())
