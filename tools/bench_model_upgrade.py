"""
bench_model_upgrade.py — เทียบ 3 โมเดล (qwen3:8b / qwen3:14b / gemma3:12b) กับ scenario
จริงที่เจอบั๊กจากการใช้งานสด ก่อนตัดสินใจอัปเกรดสมองบอท

เทียบ 4 มิติ:
  A) tool selection พื้นฐาน (ของเดิมจาก simulate_toolcalling.py แบบย่อ)
  B) "กินอะไรดีเย็นนี้" ต้องไม่เรียก search_places (เจอจริง 18:49 — ควรตอบเล่นๆ ไม่ใช่ถามจังหวัด)
  C) multi-turn clarify: บอทถามจังหวัด → ตอบ "จังหวัดชุมพร" → ต้องไปหาร้าน ไม่ใช่หลุดไปไฟดับ
     (เจอจริง 18:51 — เพิ่งแก้ด้วย _CLARIFY_QUESTION_RE ใน chat.py แต่ guard นั้นแก้แค่
     "ไม่ล้าง history" ไม่ได้การันตีว่าโมเดลเลือก tool ถูกหลัง context ยาวขึ้น)
  D) history ยาว (จำลอง 15+ เทิร์น) แล้วเรียก tool อีกครั้ง — เช็ค plaintext-leak bug ที่รู้จัก
     ใน qwen3:14b (ollama/ollama#11538: tool call หลุดเป็น plaintext แทน JSON เมื่อ history ยาว)

รัน: python tools/bench_model_upgrade.py
ใช้ TOOLS/chat.py/llm_tools.py ตัวจริงจากโปรเจค ไม่ก็อปมา — วัดของจริงที่จะรันในโปรดักชัน
"""
import asyncio
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import chat           # noqa: E402
import llm_tools      # noqa: E402
import memory         # noqa: E402
import ollama_client  # noqa: E402

MODELS_TO_TEST = ["qwen3:8b", "qwen3:14b", "gemma3:12b"]
TEST_USER_ID = 777_777_777_777_777_777


def hr(char="─", w=70):
    print(char * w)


def _reset_memory():
    mem_path = os.path.join(memory.MEMORY_DIR, f"{TEST_USER_ID}.json")
    if os.path.exists(mem_path):
        os.remove(mem_path)


# ============================================================
#  A) tool selection พื้นฐาน — ต้องยังผ่านเหมือนเดิม ไม่ regress
# ============================================================
BASIC_CASES = [
    {"msg": "พรุ่งนี้ต้องพกร่มไหม", "expect_tool": "get_weather"},
    {"msg": "น้ำมันวันนี้ราคาเท่าไหร่", "expect_tool": "get_oil_price"},
    {"msg": "มีไฟดับแถวบ้านไหมวันนี้", "expect_tool": "get_power_outage"},
    {"msg": "สวัสดีค่ะ วันนี้เป็นไงบ้าง", "expect_tool": None},
]


async def check_a_basic_tool_selection():
    results = []
    for case in BASIC_CASES:
        msg = await ollama_client._chat_once(
            [{"role": "user", "content": case["msg"]}], tools=llm_tools.TOOLS
        )
        tool_calls = msg.get("tool_calls") or []
        got = tool_calls[0]["function"]["name"] if tool_calls else None
        ok = got == case["expect_tool"]
        results.append((ok, case["msg"], case["expect_tool"], got))
    return results


# ============================================================
#  B) "กินอะไรดีเย็นนี้" — ขอความเห็นเล่นๆ ต้องไม่เรียก search_places
#     (เจอจริง 18:49: โดนลากเข้า search_places แล้วเด้งถามจังหวัด)
# ============================================================
CASUAL_FOOD_CASES = [
    "กินอะไรดีเย็นนี้",
    "มีเมนูอะไรแนะนำไหมรอสเต้",
    "อยากรู้ว่ามื้อเย็นกินอะไรดี",
]


async def check_b_casual_food_no_tool():
    results = []
    for msg_text in CASUAL_FOOD_CASES:
        msg = await ollama_client._chat_once(
            [{"role": "user", "content": msg_text}], tools=llm_tools.TOOLS
        )
        tool_calls = msg.get("tool_calls") or []
        got = tool_calls[0]["function"]["name"] if tool_calls else None
        ok = got is None or got == "search_web"  # แนะนำเล่นๆ หรือค้นเว็บทั่วไป ยังพอรับได้
        results.append((ok, msg_text, "ไม่ใช้ tool (หรือ search_web)", got))
    return results


# ============================================================
#  C) multi-turn clarify: ถามเมนู → บอทถามจังหวัด → "จังหวัดชุมพร" → ต้องหาร้าน
#     ไม่ใช่หลุดไปเรียก get_power_outage (เจอจริง 18:51)
# ============================================================
async def check_c_clarify_then_correct_tool():
    _reset_memory()
    turn1 = "อยากรู้ว่ามื้อเย็นกินอะไรดี"
    reply1 = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", turn1)
    asked_province = any(k in reply1 for k in ("จังหวัด", "แถวไหน", "อยู่ที่ไหน"))

    turn2 = "จังหวัดชุมพร"
    reply2 = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", turn2)
    power_leak = ("ไฟดับ" in reply2 or "ตัดไฟ" in reply2 or "งดจ่ายไฟ" in reply2)
    ok = asked_province and not power_leak
    _reset_memory()
    return ok, asked_province, power_leak, reply2


# ============================================================
#  D) history ยาว (15 เทิร์นสะสม) แล้วยิง tool call อีกครั้ง
#     เช็ค plaintext-leak (ollama/ollama#11538) — tool_calls ต้องเป็น list ที่ parse ได้
#     ไม่ใช่ข้อความ plaintext ที่มี "get_weather(" ปนอยู่ใน content
# ============================================================
async def check_d_long_history_plaintext_leak():
    filler_pairs = [
        ("ชอบอ่านหนังสือแนวไหน", "แนว sci-fi ค่ะ ชอบโลกสมมติซับซ้อนๆ"),
        ("แนะนำเล่มไหนดี", "Dune ของ Frank Herbert น่าอ่านมากค่ะ"),
        ("มีเล่มอื่นอีกไหม", "Foundation ก็คลาสสิกดีนะคะ"),
        ("ทำไมชอบแนวนี้", "ชอบจินตนาการโลกที่ต่างจากปัจจุบันมากๆ ค่ะ"),
        ("เธอเคยเขียนโปรแกรมไหม", "ลองเล่น Python นิดหน่อยค่ะ สนุกดี"),
        ("Python ยากไหม", "เริ่มต้นไม่ยากค่ะ แต่ลึกๆ ก็มีอะไรให้เรียนรู้เยอะ"),
        ("แนะนำ library อะไรดี", "requests กับ pandas เริ่มต้นดีค่ะ"),
        ("เธอชอบเพลงแนวไหน", "แนว lo-fi เบาๆ ฟังตอนอ่านหนังสือค่ะ"),
        ("มีศิลปินที่ชอบไหม", "ไม่ได้ติดตามเป็นคนๆ ค่ะ ฟังตามอารมณ์มากกว่า"),
        ("วันนี้ทำอะไรมาบ้าง", "อยู่ห้องสมุดอ่านหนังสือทั้งวันเลยค่ะ"),
        ("เหนื่อยไหม", "นิดหน่อยค่ะ แต่ก็สนุกดี"),
        ("พักผ่อนบ้างไหม", "พักบ้างค่ะ ไม่งั้นล้าเกินไป"),
        ("ชอบกาแฟไหม", "ชอบค่ะ โดยเฉพาะกาแฟดำ"),
        ("ชาล่ะ", "ก็ชอบค่ะ แต่กาแฟชนะนิดหน่อย"),
        ("โอเคขอบคุณนะคะ", "ยินดีค่ะ มีอะไรถามได้อีกนะคะ"),
    ]
    _reset_memory()
    mem = memory.load_memory(TEST_USER_ID)
    mem["history"] = []
    for u, a in filler_pairs:
        mem["history"].append({"role": "user", "content": u})
        mem["history"].append({"role": "assistant", "content": a})
    memory.save_memory(TEST_USER_ID, mem)

    reply = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", "วันนี้อากาศเป็นยังไงบ้าง")

    # สัญญาณ plaintext-leak: เนื้อคำตอบมีชื่อ tool/syntax เรียกฟังก์ชันโผล่มาดิบๆ
    leak_markers = ("get_weather(", "<tool_call>", "function_call", "tool_call>", "```json")
    leaked = any(m in reply for m in leak_markers)
    _reset_memory()
    return not leaked, reply


async def run_all_for_model(model_name: str):
    ollama_client.MODEL = model_name
    hr("═")
    print(f"  🧪 ทดสอบโมเดล: {model_name}")
    hr("═")

    t0 = time.monotonic()
    a_results = await check_a_basic_tool_selection()
    a_time = time.monotonic() - t0
    a_pass = sum(1 for ok, *_ in a_results if ok)
    print(f"\n  [A] Basic tool selection: {a_pass}/{len(a_results)} passed ({a_time:.1f}s)")
    for ok, msg_text, expect, got in a_results:
        status = "✅" if ok else "❌"
        print(f"      {status} {msg_text!r} → คาดหวัง={expect} ได้จริง={got}")

    t0 = time.monotonic()
    b_results = await check_b_casual_food_no_tool()
    b_time = time.monotonic() - t0
    b_pass = sum(1 for ok, *_ in b_results if ok)
    print(f"\n  [B] คำถามกินข้าวลอยๆ ไม่ควรค้นร้าน: {b_pass}/{len(b_results)} passed ({b_time:.1f}s)")
    for ok, msg_text, expect, got in b_results:
        status = "✅" if ok else "❌"
        print(f"      {status} {msg_text!r} → คาดหวัง={expect} ได้จริง={got}")

    t0 = time.monotonic()
    c_ok, c_asked, c_leak, c_reply = await check_c_clarify_then_correct_tool()
    c_time = time.monotonic() - t0
    print(f"\n  [C] Clarify จังหวัด → ตอบร้านถูก ไม่หลุดไฟดับ: {'✅ PASS' if c_ok else '❌ FAIL'} ({c_time:.1f}s)")
    print(f"      ถามจังหวัดกลับ={c_asked}  หลุดไปไฟดับ={c_leak}")
    print(f"      🤖 {c_reply[:150]!r}")

    t0 = time.monotonic()
    d_ok, d_reply = await check_d_long_history_plaintext_leak()
    d_time = time.monotonic() - t0
    print(f"\n  [D] History ยาว 15 เทิร์น + tool call — ไม่หลุด plaintext: {'✅ PASS' if d_ok else '❌ FAIL'} ({d_time:.1f}s)")
    print(f"      🤖 {d_reply[:150]!r}")

    total_pass = a_pass + b_pass + int(c_ok) + int(d_ok)
    total = len(a_results) + len(b_results) + 2
    total_time = a_time + b_time + c_time + d_time
    hr()
    print(f"  🏁 {model_name} รวม: {total_pass}/{total} passed | รวมเวลา {total_time:.1f}s")
    hr("═")
    print()
    return model_name, total_pass, total, total_time


async def main():
    summary = []
    for model_name in MODELS_TO_TEST:
        result = await run_all_for_model(model_name)
        summary.append(result)

    hr("═")
    print("  📊 สรุปเทียบทุกโมเดล")
    hr("═")
    for model_name, p, t, dur in summary:
        print(f"  {model_name:20s}  {p}/{t} passed  |  {dur:.1f}s รวม")
    hr("═")


if __name__ == "__main__":
    asyncio.run(main())
