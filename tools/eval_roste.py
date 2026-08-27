"""Eval harness + LLM-as-judge — ตาข่ายนิรภัยก่อนแตะ prompt/model routing/streaming ต่อ

ที่มา: บอทถูกจูนด้วยการแก้ prompt ตลอด (ดู CHANGELOG.md — bench เฉพาะเรื่องแยกกันหลายรอบ)
แต่ไม่มีตัววัดรวมว่าแก้แล้วดีขึ้นหรือแย่ลงจุดอื่น งาน C ตาม docs/UPGRADE_PLAN.md

รันเคสจาก tools/eval_cases.jsonl ผ่าน chat.ask_ollama เส้นจริง (uid ต่างกันต่อเคส กัน
history ปน, memory แยกไป tools/_eval_memory/ ไม่แตะ memory/ จริง, vector recall patch
เป็น [] กันยิง chroma_db จริงและกันผลไม่ deterministic) เช็ค assertion แข็ง (tool ที่ถูก
เรียกจริง/lang/contain) เอง ส่วนเคสที่มี "judge" ยิง Ollama อีกรอบให้ตัดสิน PASS/FAIL

ตรวจว่า tool ไหนถูกเรียกจริงด้วยการห่อ llm_tools.TOOL_HANDLERS[name] แต่ละตัวด้วย spy
counter ก่อนรัน (แก้ค่าใน dict ตรงๆ — chat.py ทำ "from llm_tools import TOOL_HANDLERS"
ตอน import ได้ reference เดียวกับ object เดิม แก้ค่า *ใน* dict จึงเห็นผลทั้งสองชื่อ โดยไม่ต้อง
monkeypatch สองที่ ดู tools/eval_roste.py::_spy_tool_handlers)

ใช้:
    python tools/eval_roste.py                    # รันทุกเคส
    python tools/eval_roste.py --filter time-01    # รันเฉพาะเคสที่ id ตรง/มีคำนี้
    EVAL_JUDGE_MODEL=qwen3:14b python tools/eval_roste.py   # เปลี่ยนโมเดลกรรมการ
"""
import argparse
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import memory

memory.MEMORY_DIR = os.path.join(os.path.dirname(__file__), "_eval_memory")
os.makedirs(memory.MEMORY_DIR, exist_ok=True)

import chat
import llm_tools
import persona
import vectormemory
from ollama_client import _get_json_post, MODEL as OLLAMA_MODEL

CASES_PATH = os.path.join(os.path.dirname(__file__), "eval_cases.jsonl")
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", OLLAMA_MODEL)

# uid เริ่มจากช่วงที่ไม่ชนกับ REPL (tools/repl.py ใช้ 111111) กันไฟล์ความจำปนกันถ้ารันคู่กัน
_BASE_UID = 900_000


def _load_cases(filter_str: str | None) -> list[dict]:
    cases = []
    with open(CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    if filter_str:
        cases = [c for c in cases if filter_str in c["id"]]
    return cases


def _spy_tool_handlers() -> dict:
    """ห่อ handler แต่ละตัวด้วยตัวนับ — คืน dict ชื่อ tool -> จำนวนครั้งที่ถูกเรียก (นับสะสม
    ทุกเคสในโปรเซสนี้ ผู้เรียกต้องอ่านค่าก่อน/หลังรันแต่ละเคสเองเพื่อรู้ diff ต่อเคส)"""
    call_counts: dict[str, int] = {name: 0 for name in llm_tools.TOOL_HANDLERS}

    def _wrap(name, fn):
        async def wrapped(args, mem):
            call_counts[name] += 1
            return await fn(args, mem)
        return wrapped

    for name, fn in list(llm_tools.TOOL_HANDLERS.items()):
        llm_tools.TOOL_HANDLERS[name] = _wrap(name, fn)
    return call_counts


_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}


async def _judge(user_msg: str, reply: str, criterion: str) -> tuple[bool, str]:
    """ยิง Ollama อีกครั้งให้ตัดสิน PASS/FAIL ตามเกณฑ์ที่ระบุ — บังคับรูปร่าง JSON ผ่าน
    "format" (ไม่ใช่แค่ขอในข้อความ) แพทเทิร์นเดียวกับ vectormemory.rerank_with_llm ที่พบว่า
    ขอในข้อความเปล่าๆ ให้โมเดลตอบหลุดฟอร์แมตได้ราว 30% ของครั้ง ตัดสินใจกันชัดกว่า "parse
    token แรก" เพราะโมเดล reasoning มักมี preamble ก่อนคำตอบสุดท้ายเสมอ"""
    prompt = (
        f"ข้อความผู้ใช้: {user_msg}\n"
        f"คำตอบของรอสเต้: {reply}\n\n"
        f"เกณฑ์ตัดสิน: {criterion}\n\n"
        "คำตอบนี้ผ่านเกณฑ์ข้างต้นไหม ตอบ JSON เท่านั้น"
    )
    payload = {
        "model": JUDGE_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False, "think": False,
        "format": _JUDGE_SCHEMA,
        "options": {"temperature": 0},
    }
    try:
        data = await _get_json_post(payload, timeout=60)
        raw = data.get("message", {}).get("content", "") or ""
        result = json.loads(raw)
        return result.get("verdict") == "PASS", result.get("reason", "")
    except Exception as e:
        return False, f"judge พัง: {type(e).__name__}: {e}"


async def _run_case(case: dict, uid: int, call_counts: dict) -> dict:
    expect = case.get("expect", {})
    entry = case.get("entry", "ask_ollama")

    before = dict(call_counts)
    try:
        if entry == "handle_memory_command":
            reply = memory.handle_memory_command(uid, "eval", case["msg"])
            if reply is None:
                reply = ""  # ไม่ใช่คำสั่งความจำที่รู้จัก — ปกติของ mock uid ที่ไม่มี fact เดิม
        else:
            reply = await chat.ask_ollama(uid, "eval", case["msg"])
    except Exception as e:
        return {"id": case["id"], "pass": False, "reply": "",
               "detail": f"exception: {type(e).__name__}: {e}"}

    problems = []

    must_tool = expect.get("must_call_tool")
    if must_tool:
        called = {name for name, cnt in call_counts.items() if cnt > before.get(name, 0)}
        if must_tool not in called:
            problems.append(f"ต้องเรียก tool {must_tool!r} แต่เรียกจริง: {called or 'ไม่มีเลย'}")

    if expect.get("lang") == "th":
        if persona.reply_broke_character(reply):
            problems.append("คำตอบหลุดเป็นภาษาอื่นล้วน (persona.reply_broke_character=True)")

    for bad in expect.get("must_not_contain", []):
        if bad in reply:
            problems.append(f"คำตอบมีคำต้องห้าม {bad!r}")

    for good in expect.get("must_contain", []):
        if good not in reply:
            problems.append(f"คำตอบขาดคำที่ต้องมี {good!r}")

    if expect.get("judge"):
        ok, reason = await _judge(case["msg"], reply, expect["judge"])
        if not ok:
            problems.append(f"judge FAIL: {reason}")

    return {"id": case["id"], "pass": not problems, "reply": reply, "detail": "; ".join(problems)}


async def main_async(filter_str: str | None) -> int:
    cases = _load_cases(filter_str)
    if not cases:
        print(f"ไม่พบเคส (filter={filter_str!r})")
        return 1

    call_counts = _spy_tool_handlers()
    results = []
    with patch.object(vectormemory, "query_pdf", AsyncMock(return_value=[])), \
         patch.object(vectormemory, "query_conversation_memory", AsyncMock(return_value=[])):
        for i, case in enumerate(cases):
            uid = _BASE_UID + i
            result = await _run_case(case, uid, call_counts)
            results.append(result)
            mark = "PASS" if result["pass"] else "FAIL"
            print(f"[{mark}] {result['id']}" + (f" — {result['detail']}" if result["detail"] else ""))

    n_pass = sum(1 for r in results if r["pass"])
    print(f"\n{n_pass}/{len(results)} ผ่าน (judge model: {JUDGE_MODEL})")
    return 0 if n_pass == len(results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", help="รันเฉพาะเคสที่ id มีคำนี้เป็นส่วนหนึ่ง")
    args = ap.parse_args()
    return asyncio.run(main_async(args.filter))


if __name__ == "__main__":
    sys.exit(main())
