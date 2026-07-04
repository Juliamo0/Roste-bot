"""
simulate_toolcalling.py — ทดสอบ LLM tool calling แบบ end-to-end กับ Ollama จริง

ขั้นตอน:
  Phase 1: ยิงคำถามที่ไม่มี keyword ตรงตัว (เช่น "พรุ่งนี้ต้องพกร่มไหม" ที่ keyword dispatch
           เดิมเคยพลาด) ผ่าน bot._chat_once จริง (ใช้ TOOLS ตัวจริงจาก bot.py ไม่ใช่ก็อปมา)
           ตรวจว่าโมเดลเลือกเครื่องมือถูกต้อง
  Phase 2: ทดสอบ multi-turn place-search ผ่าน bot.ask_ollama จริง — ถามหาร้านไม่บอกจังหวัด
           (ควรถามกลับ) → ตอบจังหวัดในข้อความถัดไป (ควรค้นและได้ผลจริง) ยืนยันว่าการลบ
           _pending_place ทิ้ง (ใช้ conversation history แทน) ยังทำงานถูกต้อง

รัน: python simulate_toolcalling.py
(ต้อง Ollama กำลังทำงานที่ localhost:11434 และมีโมเดล MODEL ใน bot.py อยู่แล้ว)
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

TEST_USER_ID = 555_555_555_555_555_555   # ไม่ชนกับ test user ของสคริปต์อื่น (111/222/333/444)
TEST_USER_NAME = "ผู้ทดสอบ"


def hr(char="─", w=66):
    print(char * w)


# ============================================================
#  📞 Phase 1 — โมเดลเลือกเครื่องมือถูกไหม (ไม่มี keyword ตรงตัว)
# ============================================================
TOOL_SELECTION_CASES = [
    {
        "msg": "พรุ่งนี้ต้องพกร่มไหม",
        "expect_tool": "get_weather",
        "note": "เคสที่ keyword dispatch เดิมพลาด — ไม่มีคำว่า 'อากาศ'/'ฝน' เลย",
    },
    {"msg": "วันนี้วันอะไร", "expect_tool": "get_current_time", "note": ""},
    {"msg": "น้ำมันวันนี้ราคาเท่าไหร่", "expect_tool": "get_oil_price", "note": ""},
    {"msg": "มีไฟดับแถวบ้านไหมวันนี้", "expect_tool": "get_power_outage", "note": ""},
    {
        "msg": "สวัสดีค่ะ วันนี้เป็นไงบ้าง",
        "expect_tool": None,
        "note": "ทักทายทั่วไป ไม่ควรเรียกเครื่องมือใดๆ (กันเรียกฟุ่มเฟือย)",
    },
]


async def phase1_tool_selection():
    hr("═")
    print("  Phase 1: โมเดลเลือกเครื่องมือถูกไหม (ไม่มี keyword ตรงตัว)")
    hr("═")

    passed = failed = 0
    for case in TOOL_SELECTION_CASES:
        msg = await bot._chat_once([{"role": "user", "content": case["msg"]}], tools=bot.TOOLS)
        tool_calls = msg.get("tool_calls") or []
        got_tool = tool_calls[0]["function"]["name"] if tool_calls else None
        ok = got_tool == case["expect_tool"]
        status = "✅ PASS" if ok else "❌ FAIL"
        passed += ok
        failed += not ok

        hr()
        print(f"  {status}  {case['msg']!r}")
        if case["note"]:
            print(f"  หมายเหตุ: {case['note']}")
        print(f"  คาดหวัง: {case['expect_tool']}  |  ได้จริง: {got_tool}")
        if tool_calls:
            print(f"    args: {tool_calls[0]['function'].get('arguments')}")
        print()

    hr("═")
    print(f"  Phase 1 สรุป: {passed}/{len(TOOL_SELECTION_CASES)} passed")
    hr("═")
    print()
    return passed, failed


# ============================================================
#  🍜 Phase 2 — multi-turn place-search (แทน _pending_place เดิม)
# ============================================================
async def phase2_multiturn_place_search():
    hr("═")
    print("  Phase 2: multi-turn place-search (ไม่มี _pending_place แล้ว ใช้ history แทน)")
    hr("═")

    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")
    if os.path.exists(mem_path):
        os.remove(mem_path)
        print("🗑️  ลบ memory เก่าของ test user แล้ว")

    hr()
    turn1 = "หาร้านก๋วยเตี๋ยวอร่อยๆให้หน่อย"
    print(f"  รอบ 1: {turn1!r} (ไม่บอกจังหวัด — ควรถามกลับ ห้ามเดาชื่อร้าน)")
    reply1 = await bot.ask_ollama(TEST_USER_ID, TEST_USER_NAME, turn1)
    print(f"  🤖 {reply1}")
    asked_back = ("จังหวัด" in reply1 or "อำเภอ" in reply1 or "แถวไหน" in reply1 or "?" in reply1 or "ไหม" in reply1)
    print(f"  {'✅ PASS' if asked_back else '❌ FAIL'} — ดูเหมือนถามกลับ: {asked_back}")

    hr()
    turn2 = "ชุมพรค่ะ"
    print(f"  รอบ 2: {turn2!r} (ตอบจังหวัด — โมเดลควรเรียก search_places ซ้ำเองจาก history)")
    reply2 = await bot.ask_ollama(TEST_USER_ID, TEST_USER_NAME, turn2)
    print(f"  🤖 {reply2}")
    still_asking = ("จังหวัด" in reply2 and "?" in reply2)
    print(f"  {'✅ PASS' if not still_asking else '❌ FAIL'} — ไม่ได้ถามจังหวัดซ้ำ: {not still_asking}")

    hr("═")
    passed = int(asked_back) + int(not still_asking)
    print(f"  Phase 2 สรุป: {passed}/2 passed")
    hr("═")
    print()

    if os.path.exists(mem_path):
        os.remove(mem_path)
        print("🗑️  ลบ memory ทดสอบแล้ว")

    return passed, 2 - passed


async def main():
    hr("═")
    print("  จำลองทดสอบ LLM tool calling (bot.py TOOLS จริง + Ollama จริง)")
    hr("═")
    print()

    p1_pass, p1_fail = await phase1_tool_selection()
    p2_pass, p2_fail = await phase2_multiturn_place_search()

    total_pass = p1_pass + p2_pass
    total_fail = p1_fail + p2_fail
    hr("═")
    print(f"  🏁 รวมทั้งหมด: {total_pass}/{total_pass + total_fail} passed"
          f"{'  ✅ ทั้งหมดผ่าน' if total_fail == 0 else f'  ❌ {total_fail} ไม่ผ่าน'}")
    hr("═")


if __name__ == "__main__":
    asyncio.run(main())
