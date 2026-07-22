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

รัน: python tools/bench_model_upgrade.py [model_name] [--repeat N]
  ไม่ใส่ argument = รันทุกโมเดลใน MODELS_TO_TEST, repeat=1 (เดิม)
  ใส่ model_name = รันเฉพาะโมเดลนั้น (เช่น qwen3:8b)
  --repeat N = รันแต่ละเคสซ้ำ N รอบ รายงาน "ผ่านกี่ใน N" (pass^k) แทน pass/fail ครั้งเดียว
               อิงจาก ReliabilityBench (arXiv:2601.06112) ที่ชี้ว่า pass@1 (รันครั้งเดียว)
               ซ่อนความไม่แน่นอนของ LLM ไว้

ผลจริงที่เจอจากการรัน pass^3 บน qwen3:8b (2026-07): scenario C วัดได้ 9/9 ตอนรันครั้งเดียว
(pass@1) แต่พอรันซ้ำ pass^3 สามรอบติดกันได้ 0/3, 1/3 FLAKY, 0/3 ตามลำดับ — ไม่เคยผ่านเกินครึ่ง
เลยสักครั้ง แปลว่า pass@1 เดิมที่เคยรายงานว่า "แก้หายแล้ว 9/9" เป็นเพียงความบังเอิญของการรัน
ครั้งเดียว ไม่ใช่หลักฐานว่า flow นี้เชื่อถือได้จริง — ต้นเหตุคือโมเดลชอบตอบ "ข้อมูลทั่วไปของ
จังหวัด" (ความรู้ทั่วไปที่มีอยู่แล้วในตัวโมเดล ไม่ใช่ hallucination อันตราย) แทนที่จะเรียก
search_places หรือถามกลับ เมื่อได้รับแค่ชื่อจังหวัดเปล่าๆ ("จังหวัดชุมพร") เป็นข้อความทั้งหมด
— ยังไม่มี fix สำหรับจุดนี้ (ทิ้งไว้เป็น known issue เพื่อให้ pass^k ยังคงสะท้อนสภาพจริง)

หมายเหตุการวัด: power_leak/asked_province เดิมตรวจด้วย substring match ธรรมดา ("ไฟดับ" in reply)
ซึ่งเป็น false-positive ได้ง่าย (โมเดลแค่ "เสนอตัวเลือก" เช่น "ถามเรื่องไฟดับได้นะ" ก็ถูกนับผิดว่า
หลุด) แก้เป็น _is_real_power_leak() ที่เช็คเฉพาะ pattern ที่มาจากเนื้อหา tool result จริง
(เช่น "ประกาศตัดไฟ", "ไม่มีประกาศตัดไฟ") — ยืนยันด้วย pass^3 ว่า power_leak=False ทุกรอบเสมอ
(guard เดิมจาก _CLARIFY_QUESTION_RE ยังทำงานถูกต้อง 100% ไม่เคยหลุดไปเรียก get_power_outage ผิดเลย)

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


async def _run_case_a_once(case):
    msg = await ollama_client._chat_once(
        [{"role": "user", "content": case["msg"]}], tools=llm_tools.TOOLS
    )
    tool_calls = msg.get("tool_calls") or []
    got = tool_calls[0]["function"]["name"] if tool_calls else None
    return got == case["expect_tool"], got


async def check_a_basic_tool_selection(repeat: int = 1):
    """คืน list ของ (pass_count, repeat, msg, expect, last_got) ต่อเคส — pass^k แบบง่าย"""
    results = []
    for case in BASIC_CASES:
        pass_count = 0
        last_got = None
        for _ in range(repeat):
            ok, got = await _run_case_a_once(case)
            pass_count += int(ok)
            last_got = got
        results.append((pass_count, repeat, case["msg"], case["expect_tool"], last_got))
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


async def _run_case_b_once(msg_text):
    msg = await ollama_client._chat_once(
        [{"role": "user", "content": msg_text}], tools=llm_tools.TOOLS
    )
    tool_calls = msg.get("tool_calls") or []
    got = tool_calls[0]["function"]["name"] if tool_calls else None
    ok = got is None or got == "search_web"  # แนะนำเล่นๆ หรือค้นเว็บทั่วไป ยังพอรับได้
    return ok, got


async def check_b_casual_food_no_tool(repeat: int = 1):
    results = []
    for msg_text in CASUAL_FOOD_CASES:
        pass_count = 0
        last_got = None
        for _ in range(repeat):
            ok, got = await _run_case_b_once(msg_text)
            pass_count += int(ok)
            last_got = got
        results.append((pass_count, repeat, msg_text, "ไม่ใช้ tool (หรือ search_web)", last_got))
    return results


# ============================================================
#  C) multi-turn clarify: ถามเมนู → บอทถามจังหวัด → "จังหวัดชุมพร" → ต้องหาร้าน
#     ไม่ใช่หลุดไปเรียก get_power_outage (เจอจริง 18:51)
# ============================================================
# เจอจริงตอนรัน pass^3: substring match ธรรมดา ("ไฟดับ" in reply) เป็น false-positive ได้ง่าย
# เพราะโมเดลตอบแบบ "ถ้าอยากรู้เรื่องอากาศ ไฟดับ หรือน้ำมัน บอกได้เลย" ซึ่งแค่ "เสนอตัวเลือก"
# ไม่ใช่ "ตอบข้อมูลไฟดับจริง" — ต้องแยก 2 กรณีนี้ด้วย pattern ที่เฉพาะเจาะจงกว่า (คำที่โผล่มาจาก
# เนื้อหา tool result จริงเท่านั้น เช่น "ประกาศ"/"งดจ่ายไฟ...น." ไม่ใช่แค่ชื่อหัวข้อเฉยๆ)
_POWER_LEAK_RE = None


def _is_real_power_leak(reply: str) -> bool:
    """True เฉพาะตอนคำตอบดูเหมือนดึงข้อมูลไฟดับจริงมาตอบ (เนื้อหาจาก get_power_outage)
    ไม่ใช่แค่เอ่ยคำว่า 'ไฟดับ' ลอยๆ ตอนเสนอตัวเลือกให้ผู้ใช้เลือกถาม"""
    global _POWER_LEAK_RE
    if _POWER_LEAK_RE is None:
        import re
        _POWER_LEAK_RE = re.compile(
            r"ประกาศ(ตัด|งด)ไฟ|มีกำหนด(การ)?ตัดไฟ|จะ(มี|ถูก)ตัดไฟ|ไม่มีประกาศตัดไฟ"
        )
    return bool(_POWER_LEAK_RE.search(reply))


async def _run_case_c_once():
    _reset_memory()
    turn1 = "อยากรู้ว่ามื้อเย็นกินอะไรดี"
    reply1 = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", turn1)
    asked_province = any(k in reply1 for k in ("จังหวัด", "แถวไหน", "อยู่ที่ไหน"))

    turn2 = "จังหวัดชุมพร"
    reply2 = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", turn2)
    power_leak = _is_real_power_leak(reply2)
    ok = asked_province and not power_leak
    _reset_memory()
    return ok, asked_province, power_leak, reply2


async def check_c_clarify_then_correct_tool(repeat: int = 1):
    """คืน (pass_count, repeat, last_asked, last_leak, last_reply)
    หมายเหตุ: power_leak=False สำคัญกว่า asked_province — ไม่หลุดไปตอบไฟดับคือ safety
    ตัวจริง ส่วนถามจังหวัดหรือเรียก search_places ตรงเลยทั้งคู่ถือว่าใช้ได้ (ดู scenario B)"""
    pass_count = 0
    last_asked = last_leak = None
    last_reply = ""
    for _ in range(repeat):
        ok, asked, leak, reply = await _run_case_c_once()
        pass_count += int(ok)
        last_asked, last_leak, last_reply = asked, leak, reply
    return pass_count, repeat, last_asked, last_leak, last_reply


# ============================================================
#  D) history ยาว (15 เทิร์นสะสม) แล้วยิง tool call อีกครั้ง
#     เช็ค plaintext-leak (ollama/ollama#11538) — tool_calls ต้องเป็น list ที่ parse ได้
#     ไม่ใช่ข้อความ plaintext ที่มี "get_weather(" ปนอยู่ใน content
# ============================================================
async def _run_case_d_once():
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


async def check_d_long_history_plaintext_leak(repeat: int = 1):
    pass_count = 0
    last_reply = ""
    for _ in range(repeat):
        ok, reply = await _run_case_d_once()
        pass_count += int(ok)
        last_reply = reply
    return pass_count, repeat, last_reply


def _fmt_pk(pass_count: int, repeat: int) -> str:
    """แสดงผลแบบ pass^k: 'N/K' ธรรมดาถ้า repeat=1 (เหมือนเดิม), 'N/K ⚠️ FLAKY' ถ้าแกว่ง
    (ผ่านบ้างไม่ผ่านบ้างใน K รอบ — ไม่ใช่ 0/K หรือ K/K เป๊ะ) ตาม pass^k concept จาก
    ReliabilityBench (arXiv:2601.06112): ผ่านครั้งเดียว (pass@1) ไม่การันตีว่าน่าเชื่อถือ"""
    if repeat == 1:
        return "✅" if pass_count == repeat else "❌"
    if pass_count == repeat:
        return f"✅ {pass_count}/{repeat}"
    if pass_count == 0:
        return f"❌ {pass_count}/{repeat}"
    return f"⚠️ {pass_count}/{repeat} FLAKY"


async def run_all_for_model(model_name: str, repeat: int = 1):
    ollama_client.MODEL = model_name
    hr("═")
    label = f"  🧪 ทดสอบโมเดล: {model_name}" + (f"  (repeat={repeat}, pass^{repeat})" if repeat > 1 else "")
    print(label)
    hr("═")

    t0 = time.monotonic()
    a_results = await check_a_basic_tool_selection(repeat)
    a_time = time.monotonic() - t0
    a_full_pass = sum(1 for pc, r, *_ in a_results if pc == r)
    print(f"\n  [A] Basic tool selection: {a_full_pass}/{len(a_results)} เคสผ่านครบทุกรอบ ({a_time:.1f}s)")
    for pc, r, msg_text, expect, got in a_results:
        print(f"      {_fmt_pk(pc, r)} {msg_text!r} → คาดหวัง={expect} ได้จริงล่าสุด={got}")

    t0 = time.monotonic()
    b_results = await check_b_casual_food_no_tool(repeat)
    b_time = time.monotonic() - t0
    b_full_pass = sum(1 for pc, r, *_ in b_results if pc == r)
    print(f"\n  [B] คำถามกินข้าวลอยๆ ไม่ควรค้นร้าน: {b_full_pass}/{len(b_results)} เคสผ่านครบทุกรอบ ({b_time:.1f}s)")
    for pc, r, msg_text, expect, got in b_results:
        print(f"      {_fmt_pk(pc, r)} {msg_text!r} → คาดหวัง={expect} ได้จริงล่าสุด={got}")

    t0 = time.monotonic()
    c_pass, c_repeat, c_asked, c_leak, c_reply = await check_c_clarify_then_correct_tool(repeat)
    c_time = time.monotonic() - t0
    print(f"\n  [C] Clarify จังหวัด → ตอบร้านถูก ไม่หลุดไฟดับ: {_fmt_pk(c_pass, c_repeat)} ({c_time:.1f}s)")
    print(f"      รอบล่าสุด — ถามจังหวัดกลับ={c_asked}  หลุดไปไฟดับ={c_leak}")
    print(f"      🤖 {c_reply[:150]!r}")

    t0 = time.monotonic()
    d_pass, d_repeat, d_reply = await check_d_long_history_plaintext_leak(repeat)
    d_time = time.monotonic() - t0
    print(f"\n  [D] History ยาว 15 เทิร์น + tool call — ไม่หลุด plaintext: {_fmt_pk(d_pass, d_repeat)} ({d_time:.1f}s)")
    print(f"      🤖 {d_reply[:150]!r}")

    a_pass_total = sum(pc for pc, r, *_ in a_results)
    b_pass_total = sum(pc for pc, r, *_ in b_results)
    total_pass = a_pass_total + b_pass_total + c_pass + d_pass
    total_runs = len(a_results) * repeat + len(b_results) * repeat + repeat + repeat
    total_time = a_time + b_time + c_time + d_time
    hr()
    print(f"  🏁 {model_name} รวม: {total_pass}/{total_runs} รอบผ่าน | รวมเวลา {total_time:.1f}s")
    hr("═")
    print()
    return model_name, total_pass, total_runs, total_time


async def main():
    repeat = 1
    models = list(MODELS_TO_TEST)
    args = sys.argv[1:]
    if "--repeat" in args:
        idx = args.index("--repeat")
        repeat = int(args[idx + 1])
        del args[idx:idx + 2]
    if args:
        models = args  # ระบุชื่อโมเดลมาตรงๆ = รันเฉพาะตัวนั้น (ไม่ต้องรันทั้ง 3 ตัว)

    summary = []
    for model_name in models:
        result = await run_all_for_model(model_name, repeat)
        summary.append(result)

    hr("═")
    print(f"  📊 สรุปเทียบทุกโมเดล" + (f" (pass^{repeat})" if repeat > 1 else ""))
    hr("═")
    for model_name, p, t, dur in summary:
        print(f"  {model_name:20s}  {p}/{t} รอบผ่าน  |  {dur:.1f}s รวม")
    hr("═")


if __name__ == "__main__":
    asyncio.run(main())
