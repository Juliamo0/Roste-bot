"""
bench_model_upgrade.py — เทียบ 3 โมเดล (qwen3:8b / qwen3:14b / gemma3:12b) กับ scenario
จริงที่เจอบั๊กจากการใช้งานสด ก่อนตัดสินใจอัปเกรดสมองบอท

เทียบ 5 มิติ:
  A) tool selection พื้นฐาน (ของเดิมจาก simulate_toolcalling.py แบบย่อ)
  B) "กินอะไรดีเย็นนี้" ต้องไม่เรียก search_places (เจอจริง 18:49 — ควรตอบเล่นๆ ไม่ใช่ถามจังหวัด)
  C) multi-turn clarify: บอทถามจังหวัด → ตอบ "จังหวัดชุมพร" → ต้องไปหาร้าน ไม่ใช่หลุดไปไฟดับ
     (เจอจริง 18:51 — เพิ่งแก้ด้วย _CLARIFY_QUESTION_RE ใน chat.py แต่ guard นั้นแก้แค่
     "ไม่ล้าง history" ไม่ได้การันตีว่าโมเดลเลือก tool ถูกหลัง context ยาวขึ้น)
  D) history ยาว (จำลอง 15+ เทิร์น) แล้วเรียก tool อีกครั้ง — เช็ค plaintext-leak bug ที่รู้จัก
     ใน qwen3:14b (ollama/ollama#11538: tool call หลุดเป็น plaintext แทน JSON เมื่อ history ยาว)
  E) แยกวัด UTR (เรียก tool ทั้งที่ไม่ควรเรียก) กับ selection accuracy (ควรเรียก แต่เลือกผิดตัว)
     — A/B เดิมวัด "ผ่าน/ไม่ผ่าน" รวมกัน ทำให้ไม่รู้ว่าควรลงแรงแก้ที่ prompt (invocation)
     หรือที่ deterministic guard (selection) ดู docstring ของ scenario E ด้านล่าง

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
import re
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
        _POWER_LEAK_RE = re.compile(
            r"ประกาศ(ตัด|งด)ไฟ|มีกำหนด(การ)?ตัดไฟ|จะ(มี|ถูก)ตัดไฟ|ไม่มีประกาศตัดไฟ"
        )
    return bool(_POWER_LEAK_RE.search(reply))


# เจอจริงตอนแก้ scenario C: assertion เดิมบังคับว่าเทิร์น 1 ต้อง "ถามจังหวัดกลับ" ถึงจะนับผ่าน
# แต่หลัง fix B ("กินอะไรดี" ไม่ควรเรียก tool) เทิร์น 1 มักตอบแนะนำเมนูเล่นๆ แทน ไม่ถามจังหวัดเลย
# ทั้งที่พฤติกรรมนั้นถูกต้องแล้ว (ตรงกับ B) — สิ่งที่ต้องวัดจริงคือเทิร์น 2 ("จังหวัดชุมพร") ต้องได้
# ข้อมูลร้านจริง (มีชื่อร้าน/เรตติ้งจาก search_places) หรือถามจังหวัดกลับอย่างสมเหตุสมผล ไม่ใช่บังคับ
# pattern ของเทิร์น 1 ที่ไม่ตรงกับพฤติกรรมที่ถูกต้องอีกต่อไป
_GOT_PLACES_RE = re.compile(r"⭐|รีวิว|ที่อยู่:|ถ\.\s")


async def _run_case_c_once():
    _reset_memory()
    turn1 = "อยากรู้ว่ามื้อเย็นกินอะไรดี"
    reply1 = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", turn1)

    turn2 = "จังหวัดชุมพร"
    reply2 = await chat.ask_ollama(TEST_USER_ID, "ผู้ทดสอบ", turn2)
    got_places = bool(_GOT_PLACES_RE.search(reply2))
    asked_province = any(k in reply2 for k in ("จังหวัด", "แถวไหน", "อยู่ที่ไหน")) and not got_places
    power_leak = _is_real_power_leak(reply2)
    ok = (got_places or asked_province) and not power_leak
    _reset_memory()
    return ok, asked_province or got_places, power_leak, reply2


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


# ============================================================
#  E) แยกวัด 2 เมตริกที่ A/B รวมกันไว้ — invocation vs selection
#
#  ทำไมต้องแยก: scenario A/B วัดแค่ "ผ่าน/ไม่ผ่าน" ต่อเคส พอไม่ผ่านก็ไม่รู้ว่าเพราะ
#  (1) โมเดลเรียก tool ทั้งที่ไม่ควรเรียกเลย  หรือ (2) รู้ว่าต้องเรียกแต่หยิบผิดตัว
#  สองอย่างนี้แก้ด้วยวิธีต่างกันคนละทาง: (1) แก้ที่ prompt/tool description
#  (2) แก้ที่ deterministic guard ใน chat.py — ถ้าไม่แยกวัดก็เดาผิดได้ว่าควรลงแรงที่ไหน
#
#  เมตริก (ตั้งชื่อตาม ToolFailBench arXiv:2607.04686 เพื่อเทียบกับตัวเลขในงานวิจัยได้ตรงๆ):
#    UTR (Unnecessary Tool-use Rate) = เรียก tool / เคสที่ "ไม่ควรเรียกเลย"  ยิ่งต่ำยิ่งดี
#    SelAcc (Selection Accuracy)     = เลือกถูกตัว / เคสที่ "ควรเรียก"        ยิ่งสูงยิ่งดี
#    MissRate (under-invocation)     = ไม่เรียกเลย / เคสที่ "ควรเรียก"        ยิ่งต่ำยิ่งดี
#
#  ตัวเลขอ้างอิงจาก ToolFailBench (โมเดลระดับ 8B, benchmark ภาษาอังกฤษ):
#    Qwen2.5-7B-Instruct : UTR 0.00%  / clean tool-use 65.28%
#    Llama-3.1-8B        : UTR 98.39% / clean tool-use 47.32%  ← "Always-Call pattern"
#  งานวิจัยชี้ว่า tool discipline ขึ้นกับ model family มากกว่าขนาด (70B ต่างกันได้ 89 จุด)
#  ตระกูล Qwen มีวินัยสูง (UTR ต่ำ) — จุดอ่อนที่คาดว่าจะเจอคือ MissRate/SelAcc ไม่ใช่ UTR
#
#  ⚠️ ข้อจำกัดที่ต้องรู้ก่อนอ่านผล: benchmark ทั้งหมดข้างบนวัดบน prompt ภาษาอังกฤษ แต่ tool
#  description ของบอทนี้เป็นไทยล้วน — ตัวเลขที่ได้จากที่นี่เทียบ "ทิศทาง" กับงานวิจัยได้
#  แต่เทียบ "ค่าสัมบูรณ์" ไม่ได้ ใช้เป็น baseline ของโปรเจกต์นี้เองเป็นหลัก
#
#  วัดที่ระดับ _chat_once ตรงๆ (เหมือน A/B) ไม่ผ่าน chat.ask_ollama — เพื่อวัด "การตัดสินใจ
#  ของโมเดลเปล่าๆ" แยกจากผลของ deterministic guard ใน chat.py ถ้าอยากรู้ว่า guard ช่วย
#  ได้แค่ไหน ให้เทียบ E กับ C (C วิ่งผ่าน ask_ollama เต็ม pipeline)
# ============================================================

# เคสที่ "ไม่ควรเรียก tool เลย" — คุยเล่น/ขอความเห็น/เรื่องของตัวละคร ไม่มีข้อเท็จจริงต้องดึง
# (ตรงกับ control task ของ ToolFailBench: วัดว่าโมเดลยับยั้งการเรียกได้ไหม)
NO_TOOL_CASES = [
    "สวัสดีค่ะ วันนี้เป็นไงบ้าง",
    "กินอะไรดีเย็นนี้",
    "เหงาจังเลยวันนี้",
    "รอสเต้ชอบอ่านหนังสือแนวไหน",
    "ขอบคุณนะคะ วันนี้คุยสนุกมาก",
    "เล่ามุกอะไรให้ฟังหน่อยสิ",
    "ร้อนจังเลยเนอะ",              # โทนบ่น ไม่ใช่ถามอุณหภูมิ (ระบุใน tool description แล้ว)
    "หนาวจัง อยากกอด",             # เคสที่ tool description เขียนกันไว้ตรงๆ
    "แนะนำตัวหน่อย",                # เคสที่กำลังจะแก้ด้วย prefill — ต้องไม่เรียก tool
    "เธอเป็นใครเหรอ",
]

# เคสที่ "ควรเรียก tool" + ตัวที่ถูกต้อง — วัด selection accuracy กับ miss rate
# ครอบทั้ง 6 tool ที่มีจริง เน้นเคสที่เคยสับสนกันในอดีต (เวลา vs อากาศ, ร้าน vs ค้นเว็บ)
SHOULD_CALL_CASES = [
    {"msg": "ตอนนี้กี่โมงแล้ว", "expect": "get_current_time"},
    {"msg": "วันนี้วันอะไร", "expect": "get_current_time"},
    {"msg": "พรุ่งนี้ต้องพกร่มไหม", "expect": "get_weather"},
    {"msg": "เชียงใหม่หนาวไหม", "expect": "get_weather"},
    {"msg": "วันนี้ฝนตกไหม", "expect": "get_weather"},          # มี "วันนี้" แต่ไม่ใช่ get_current_time
    {"msg": "น้ำมันวันนี้ราคาเท่าไหร่", "expect": "get_oil_price"},
    {"msg": "ดีเซลบางจากลิตรละเท่าไหร่", "expect": "get_oil_price"},
    {"msg": "มีไฟดับแถวบ้านไหมวันนี้", "expect": "get_power_outage"},
    {"msg": "พรุ่งนี้ตัดไฟที่นครศรีธรรมราชไหม", "expect": "get_power_outage"},
    {"msg": "หาร้านก๋วยเตี๋ยวแถวชุมพรให้หน่อย", "expect": "search_places"},
    {"msg": "แนะนำที่เที่ยวในภูเก็ตหน่อย", "expect": "search_places"},
    {"msg": "นายกรัฐมนตรีคนปัจจุบันชื่ออะไร", "expect": "search_web"},
]


async def _probe_tool_call(msg_text: str):
    """ยิงคำถามเดียวแบบไม่มี history/system prompt แล้วคืน (ชื่อ tool, args)
    ชื่อ = None แปลว่าไม่เรียก tool เลย — คืนดิบๆ ให้ผู้เรียกไปตัดสินเอง (ไม่ตัดสิน pass/fail ในนี้)"""
    msg = await ollama_client._chat_once(
        [{"role": "user", "content": msg_text}], tools=llm_tools.TOOLS
    )
    tool_calls = msg.get("tool_calls") or []
    if not tool_calls:
        return None, {}
    func = tool_calls[0].get("function") if isinstance(tool_calls[0], dict) else None
    if not isinstance(func, dict):
        return "<malformed>", {}   # โครงสร้างเพี้ยน (chat.py ก็ข้ามทิ้ง) นับเป็น "เรียกแต่ใช้ไม่ได้"
    args = func.get("arguments")
    return (func.get("name") or "<malformed>"), (args if isinstance(args, dict) else {})


async def _probe_tool_choice(msg_text: str):
    """คืนแค่ชื่อ tool — wrapper ของ _probe_tool_call ไว้ให้ตรงกับที่ scenario E เดิมใช้"""
    name, _ = await _probe_tool_call(msg_text)
    return name


async def check_e_utr_and_selection(repeat: int = 1):
    """คืน dict สรุป UTR / SelAcc / MissRate + รายละเอียดต่อเคสสำหรับพิมพ์

    นับเป็น "รอบ" (case × repeat) ไม่ใช่ "เคส" — เคสที่ผ่าน 2/3 ต้องสะท้อนใน metric ด้วย
    ไม่ใช่ปัดเป็นผ่าน/ไม่ผ่านแล้วกลบความแกว่งที่ pass^k ตั้งใจเปิดเผย"""
    # ── ฝั่งไม่ควรเรียก (UTR) ──
    utr_calls = 0
    utr_runs = 0
    utr_detail = []          # (called_count, repeat, msg, tool ที่หลุดล่าสุด)
    for msg_text in NO_TOOL_CASES:
        called = 0
        last_tool = None
        for _ in range(repeat):
            got = await _probe_tool_choice(msg_text)
            if got is not None:
                called += 1
                last_tool = got
        utr_calls += called
        utr_runs += repeat
        utr_detail.append((called, repeat, msg_text, last_tool))

    # ── ฝั่งควรเรียก (SelAcc / MissRate) ──
    correct = 0
    wrong = 0
    missed = 0
    sel_runs = 0
    sel_detail = []          # (correct_count, repeat, msg, expect, got ล่าสุด)
    for case in SHOULD_CALL_CASES:
        ok_count = 0
        last_got = None
        for _ in range(repeat):
            got = await _probe_tool_choice(case["msg"])
            if got is None:
                missed += 1
            elif got == case["expect"]:
                correct += 1
                ok_count += 1
            else:
                wrong += 1
            last_got = got
        sel_runs += repeat
        sel_detail.append((ok_count, repeat, case["msg"], case["expect"], last_got))

    return {
        "utr": utr_calls / utr_runs if utr_runs else 0.0,
        "utr_calls": utr_calls,
        "utr_runs": utr_runs,
        "utr_detail": utr_detail,
        # SelAcc หารด้วยรอบทั้งหมดที่ควรเรียก (รวมรอบที่ไม่เรียกเลย) — "เลือกถูกจากทุกโอกาส"
        "sel_acc": correct / sel_runs if sel_runs else 0.0,
        # SelAcc* หารด้วยรอบที่ "เรียกจริง" เท่านั้น — แยกความสามารถเลือกตัว ออกจากการตัดสินใจว่าจะเรียกไหม
        "sel_acc_called": correct / (correct + wrong) if (correct + wrong) else 0.0,
        "miss_rate": missed / sel_runs if sel_runs else 0.0,
        "correct": correct,
        "wrong": wrong,
        "missed": missed,
        "sel_runs": sel_runs,
        "sel_detail": sel_detail,
    }


# ============================================================
#  F) parameter accuracy — มิติที่สามที่ E ยังไม่วัด
#
#  ทำไมต้องมี: E วัดแค่ "เลือก tool ตัวไหน" แต่ Docker (21 โมเดล 3,570 เคส) แยกวัด 3 มิติ
#  คือ invocation / selection / *parameter accuracy* — และการรัน bench รอบก่อนก็เห็น log
#  "⚠️ tool get_weather: parameter 'province'='ไม่ระบุ' ไม่มีที่มาในบทสนทนา — ตัดทิ้ง" ขึ้น
#  3 ครั้งจาก scenario C เพียงรอบเดียว ทั้งที่ E รายงาน SelAcc 100% — แปลว่าโมเดล "เลือก
#  tool ถูกแต่ใส่ argument ผิด" อยู่จริง และเป็นจุดอ่อนที่ metric เดิมทั้งหมดมองไม่เห็นเลย
#
#  วัด 3 อย่าง:
#    ParamAcc    = args ถูกต้องครบ / รอบที่เลือก tool ถูก        ↑ ยิ่งสูงยิ่งดี
#    HallucRate  = ใส่ค่าที่ผู้ใช้ไม่เคยพูดถึง / รอบที่เลือกถูก   ↓ ยิ่งต่ำยิ่งดี
#    PlaceholderRate = ใส่ค่าขยะ ('ไม่ระบุ'/'<nil>'/'string')    ↓ ยิ่งต่ำยิ่งดี
#
#  HallucRate คือตัวที่ _strip_ungrounded_optional_args ใน llm_tools.py ต้องคอยตามเก็บ —
#  ตัวเลขนี้บอกว่า guard ตัวนั้น "ทำงานหนักแค่ไหน" ถ้าสูงแปลว่ายังต้องมี guard อยู่ ถ้าเข้าใกล้ 0
#  แล้ว (หลังปรับ tool description) ก็พอจะพิจารณาลดความซับซ้อนของ guard ได้
#
#  หมายเหตุ: วัดที่ระดับ _chat_once ดิบๆ เหมือน E — คือวัด "ก่อน" guard ทำงาน จึงเห็นค่าที่
#  โมเดลเดาเองจริงๆ ไม่ใช่ค่าหลังถูกตัดทิ้งแล้ว
# ============================================================

# ค่าขยะที่โมเดลชอบใส่แทนการเว้นว่าง — เจอจริงจาก log การรัน bench รอบก่อน
#   ไม่รวม "" ในเซ็ตนี้ — ค่าว่างเทียบเท่ากับ "ไม่ใส่ param มาเลย" ซึ่งถูกต้องอยู่แล้ว
#   (handler มี fallback รออยู่) ต่างจาก 'ไม่ระบุ'/'<nil>' ที่เป็น "ค่าจริง" ที่ใช้ไม่ได้
_PLACEHOLDER_VALUES = {
    "ไม่ระบุ", "ไม่ทราบ", "ไม่มี", "<nil>", "nil", "null", "none", "string",
    "จังหวัดบ้าน", "ไม่ระบุจังหวัด", "n/a", "-",
}

# เคสวัด parameter: expect_args = ค่าที่ "ควรมี" (substring match พอ — โมเดลเติมชื่อเต็มได้)
# forbid_extra = True แปลว่าผู้ใช้ไม่ได้ระบุ optional param เลย โมเดลจึงห้ามใส่มาเอง
PARAM_CASES = [
    # ผู้ใช้ระบุจังหวัดชัดเจน → ต้องใส่ province ให้ตรง
    {"msg": "เชียงใหม่หนาวไหม", "tool": "get_weather",
     "expect_args": {"province": "เชียงใหม่"}, "forbid_extra": False},
    {"msg": "พรุ่งนี้ตัดไฟที่นครศรีธรรมราชไหม", "tool": "get_power_outage",
     "expect_args": {"province": "นครศรีธรรมราช"}, "forbid_extra": False},
    {"msg": "หาร้านก๋วยเตี๋ยวแถวชุมพรให้หน่อย", "tool": "search_places",
     "expect_args": {"province": "ชุมพร"}, "forbid_extra": False},
    # ผู้ใช้ระบุยี่ห้อน้ำมัน → ต้อง map เป็นรหัสถูก (bcp = บางจาก)
    {"msg": "ดีเซลบางจากลิตรละเท่าไหร่", "tool": "get_oil_price",
     "expect_args": {"brand": "bcp"}, "forbid_extra": False},
    # ── ไม่ระบุจังหวัด/ยี่ห้อ → ห้ามเดาใส่มาเอง (นี่คือเคสที่ guard ต้องตามเก็บ) ──
    {"msg": "พรุ่งนี้ต้องพกร่มไหม", "tool": "get_weather",
     "expect_args": {}, "forbid_extra": True},
    {"msg": "วันนี้ฝนตกไหม", "tool": "get_weather",
     "expect_args": {}, "forbid_extra": True},
    {"msg": "มีไฟดับแถวบ้านไหมวันนี้", "tool": "get_power_outage",
     "expect_args": {}, "forbid_extra": True},
    {"msg": "น้ำมันวันนี้ราคาเท่าไหร่", "tool": "get_oil_price",
     "expect_args": {}, "forbid_extra": True},
]

# optional param ที่ต้องเฝ้าต่อ tool (ตรงกับ schema ใน llm_tools.TOOLS)
_OPTIONAL_KEYS = {
    "get_weather": ["province"],
    "get_power_outage": ["province"],
    "get_oil_price": ["brand"],
    "search_places": ["province"],
}


def _judge_args(case: dict, args: dict) -> tuple:
    """คืน (ok, hallucinated, placeholder) สำหรับ args ที่โมเดลส่งมาในเคสนี้

    ok           = ครบตามที่ควรมี และไม่มีค่าเกินที่ห้าม
    hallucinated = ใส่ optional param ที่ผู้ใช้ไม่เคยพูดถึง (ค่าจริงๆ ไม่ใช่ placeholder)
    placeholder  = ใส่ค่าขยะแทนการเว้นว่าง"""
    hallucinated = False
    placeholder = False
    ok = True

    for key, want in case["expect_args"].items():
        got = str(args.get(key, "") or "")
        # substring 2 ทาง: 'เชียงใหม่' ใน 'จังหวัดเชียงใหม่' หรือกลับกัน ถือว่าตรง
        if not (want in got or got in want) or not got:
            ok = False

    if case["forbid_extra"]:
        for key in _OPTIONAL_KEYS.get(case["tool"], []):
            if key not in args:
                continue
            val = str(args.get(key) or "").strip()
            if val.lower() in _PLACEHOLDER_VALUES:
                placeholder = True
                ok = False
            elif val:
                hallucinated = True   # ค่าจริงที่ผู้ใช้ไม่เคยพูดถึง = เดาเอง
                ok = False
    return ok, hallucinated, placeholder


async def check_f_param_accuracy(repeat: int = 1):
    """คืน dict สรุป ParamAcc / HallucRate / PlaceholderRate + รายละเอียดต่อเคส

    นับเฉพาะรอบที่ "เลือก tool ถูกตัว" — ถ้าเลือกผิดตัวตั้งแต่ต้น การวัด argument ไม่มีความหมาย
    (รอบที่เลือกผิด/ไม่เรียก นับแยกเป็น skipped เพื่อไม่ให้ ParamAcc ดูดีขึ้นเพราะกลุ่มตัวอย่างหด)"""
    good = halluc = placeholder = judged = skipped = 0
    detail = []
    for case in PARAM_CASES:
        ok_count = 0
        last_args = None
        last_tool = None
        for _ in range(repeat):
            tool, args = await _probe_tool_call(case["msg"])
            last_tool, last_args = tool, args
            if tool != case["tool"]:
                skipped += 1
                continue
            judged += 1
            ok, h, p = _judge_args(case, args)
            good += int(ok)
            halluc += int(h)
            placeholder += int(p)
            ok_count += int(ok)
        detail.append((ok_count, repeat, case["msg"], case["expect_args"],
                       case["forbid_extra"], last_tool, last_args))
    return {
        "param_acc": good / judged if judged else 0.0,
        "halluc_rate": halluc / judged if judged else 0.0,
        "placeholder_rate": placeholder / judged if judged else 0.0,
        "good": good, "halluc": halluc, "placeholder": placeholder,
        "judged": judged, "skipped": skipped, "detail": detail,
    }


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

    t0 = time.monotonic()
    e = await check_e_utr_and_selection(repeat)
    e_time = time.monotonic() - t0
    print(f"\n  [E] แยกวัด invocation vs selection ({e_time:.1f}s)")
    print(f"      UTR      {e['utr']:6.1%}  ({e['utr_calls']}/{e['utr_runs']} รอบที่เรียก tool ทั้งที่ไม่ควรเรียก)  ↓ ยิ่งต่ำยิ่งดี")
    print(f"      SelAcc   {e['sel_acc']:6.1%}  ({e['correct']}/{e['sel_runs']} รอบที่เลือกถูกตัว)  ↑ ยิ่งสูงยิ่งดี")
    print(f"      SelAcc*  {e['sel_acc_called']:6.1%}  (เฉพาะรอบที่เรียกจริง — ตัดรอบที่ไม่เรียกเลยออก)")
    print(f"      MissRate {e['miss_rate']:6.1%}  ({e['missed']}/{e['sel_runs']} รอบที่ควรเรียกแต่ไม่เรียก)  ↓ ยิ่งต่ำยิ่งดี")
    print(f"      เลือกผิดตัว {e['wrong']} รอบ")
    if e["utr_calls"]:
        print("      ── เคสที่ไม่ควรเรียกแต่เรียก:")
        for called, r, msg_text, tool in e["utr_detail"]:
            if called:
                print(f"         {_fmt_pk(r - called, r)} {msg_text!r} → เรียก {tool} {called}/{r} รอบ")
    imperfect = [d for d in e["sel_detail"] if d[0] < d[1]]
    if imperfect:
        print("      ── เคสที่ควรเรียกแต่พลาด (ไม่เรียก/เลือกผิด):")
        for ok_count, r, msg_text, expect, got in imperfect:
            print(f"         {_fmt_pk(ok_count, r)} {msg_text!r} → คาดหวัง={expect} ได้จริงล่าสุด={got}")

    t0 = time.monotonic()
    f = await check_f_param_accuracy(repeat)
    f_time = time.monotonic() - t0
    print(f"\n  [F] parameter accuracy ({f_time:.1f}s)")
    print(f"      ParamAcc    {f['param_acc']:6.1%}  ({f['good']}/{f['judged']} รอบที่ args ถูกครบ)  ↑ ยิ่งสูงยิ่งดี")
    print(f"      Halluc      {f['halluc_rate']:6.1%}  ({f['halluc']}/{f['judged']} รอบที่เดา param ที่ผู้ใช้ไม่ได้บอก)  ↓")
    print(f"      Placeholder {f['placeholder_rate']:6.1%}  ({f['placeholder']}/{f['judged']} รอบที่ใส่ค่าขยะ เช่น 'ไม่ระบุ'/'<nil>')  ↓")
    if f["skipped"]:
        print(f"      (ข้าม {f['skipped']} รอบ เพราะเลือก tool ผิดตัว/ไม่เรียก — วัด arg ไม่ได้)")
    f_imperfect = [d for d in f["detail"] if d[0] < d[1]]
    if f_imperfect:
        print("      ── เคสที่ args ไม่ผ่านครบทุกรอบ:")
        for ok_count, r, msg_text, expect, forbid, tool, args in f_imperfect:
            want = f"ห้ามใส่ optional" if forbid else f"ต้องมี {expect}"
            print(f"         {_fmt_pk(ok_count, r)} {msg_text!r}")
            print(f"            {want} | ได้จริงล่าสุด: {tool} args={args}")

    a_pass_total = sum(pc for pc, r, *_ in a_results)
    b_pass_total = sum(pc for pc, r, *_ in b_results)
    # E/F ไม่รวมใน total_pass — เป็น metric เชิงอัตราส่วน ไม่ใช่ pass/fail แบบ A-D
    # ถ้าเอามารวมจะทำให้ตัวเลข "รวมรอบผ่าน" เทียบกับการรันครั้งก่อนๆ ไม่ได้
    total_pass = a_pass_total + b_pass_total + c_pass + d_pass
    total_runs = len(a_results) * repeat + len(b_results) * repeat + repeat + repeat
    total_time = a_time + b_time + c_time + d_time + e_time + f_time
    hr()
    print(f"  🏁 {model_name} รวม A-D: {total_pass}/{total_runs} รอบผ่าน | รวมเวลา {total_time:.1f}s")
    print(f"     E: UTR {e['utr']:.1%} | SelAcc {e['sel_acc']:.1%} | MissRate {e['miss_rate']:.1%}")
    print(f"     F: ParamAcc {f['param_acc']:.1%} | Halluc {f['halluc_rate']:.1%} | Placeholder {f['placeholder_rate']:.1%}")
    hr("═")
    print()
    return model_name, total_pass, total_runs, total_time, e, f


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
    print(f"  {'โมเดล':18s} {'A-D':>10s} {'UTR↓':>6s} {'SelAcc↑':>8s} {'Miss↓':>6s} "
          f"{'Param↑':>7s} {'Halluc↓':>8s} {'เวลา':>7s}")
    for model_name, p, t, dur, e, f in summary:
        print(f"  {model_name:18s} {f'{p}/{t}':>10s} {e['utr']:5.1%} {e['sel_acc']:7.1%} "
              f"{e['miss_rate']:5.1%} {f['param_acc']:6.1%} {f['halluc_rate']:7.1%} {dur:6.1f}s")
    hr("═")
    print("  UTR = เรียก tool ทั้งที่ไม่ควรเรียก | SelAcc = เลือกถูกตัวจากเคสที่ควรเรียก")
    print("  Miss = ควรเรียกแต่ไม่เรียก | Param = args ถูกครบ | Halluc = เดา param ที่ผู้ใช้ไม่ได้บอก")
    print("  เทียบ ToolFailBench: Qwen2.5-7B UTR 0.0%, Llama-3.1-8B UTR 98.4%")
    hr("═")


if __name__ == "__main__":
    asyncio.run(main())
