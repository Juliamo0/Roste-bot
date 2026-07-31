"""เทียบ 3 ทางแก้ปัญหา attention dilution บนเคสที่พังจริง

ปัญหาที่วัดได้: tool schema รวมเกิน ~3,700 ตัวอักษร → โมเดลละเลย summary ที่อยู่ท้าย
system prompt แล้วตอบว่า "ไม่ได้คุยกัน" ทั้งที่ข้อมูลอยู่ใน context ครบ
(พิสูจน์แล้วว่าไม่เกี่ยวกับเนื้อหา tool — filler ที่เป็นตัว 'x' ล้วนก็ทำให้พังเท่ากัน)

ทางแก้ที่เทียบ:
  A ปัจจุบัน        — summary ท้าย system prompt + tools ครบ 6
  B ไม่ส่ง tools     — ต้องเดาว่าคำถามเป็นเรื่องความจำ (เปราะ: "เมื่อวานอากาศเป็นไง")
  C ย้าย summary     — แทรกใกล้คำถาม (ตำแหน่งเดียวกับ author note) ไม่ต้องเดาเจตนา
  D ย้าย + ไม่ส่ง    — ทำทั้งสองอย่าง (เพดานบนว่าดีสุดได้แค่ไหน)

วัดทั้ง 2 ฝั่ง เพราะทางแก้ต้องไม่ทำให้ฝั่งอื่นพัง:
  ฝั่งความจำ  — ต้องยืนยันว่าเคยคุย
  ฝั่งข้อมูลสด — ต้องยังเรียก tool ได้ถูก (กันแก้แล้วพังอีกทาง)
"""
import asyncio
import copy
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(r"C:\Users\User\Roste-bot")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import llm_tools  # noqa: E402
import logging  # noqa: E402
import memory  # noqa: E402
import ollama_client  # noqa: E402
import persona  # noqa: E402

logging.disable(logging.CRITICAL)

MEM = json.load(open("memory/387387058638815243.json", encoding="utf-8"))
N = 8

DENIAL = ["ไม่เคย", "ไม่ได้คุย", "จำไม่ได้", "ไม่ค่ะ", "ไม่ใช่ค่ะ", "ยังไม่ได้", "ไม่มีประวัติ"]

# ฝั่งความจำ: (คำถาม, คำที่ต้องมี)
MEM_CASES = [
    ("เคยคุยเรื่องอากาศกันหรือเปล่า", ["อากาศ"]),
    ("เราเคยคุยเรื่องการอ่านอะไรกันบ้างไหมก่อนหน้านี้", ["นิยาย", "หนังสือ", "อ่าน"]),
    ("จำได้ไหมว่าเคยคุยเรื่องของหวานอะไรกัน", ["ของหวาน", "หวาน", "ไอศกรีม", "เจลาโต้"]),
]

# ฝั่งข้อมูลสด: (คำถาม, tool ที่ควรเรียก)
LIVE_CASES = [
    ("พรุ่งนี้ฝนตกไหม", "get_weather"),
    ("ราคาน้ำมันวันนี้เท่าไหร่", "get_oil_price"),
    ("ตอนนี้กี่โมงแล้ว", "get_current_time"),
    ("หาร้านก๋วยเตี๋ยวแถวชุมพรให้หน่อย", "search_places"),
]


def build(question, summary_position, with_tools):
    """สร้าง message list ตามแบบที่ ask_ollama ทำจริง

    summary_position: 'system' = ท้าย system prompt (ปัจจุบัน)
                      'near'   = แทรกใกล้คำถาม (ก่อน author note)
                      'none'   = ไม่ใส่เลย
    """
    facts = memory.recall_facts(MEM, question)
    sums = memory.recall_summaries(MEM, question)

    sp = persona.SYSTEM_PROMPT
    if facts:
        sp += ("\n\nสิ่งที่คุณ (รอสเต้) จำได้เกี่ยวกับคนที่กำลังคุยด้วย "
               "(ใช้ให้เป็นธรรมชาติ ไม่ต้องท่องออกมาเอง):\n"
               + "\n".join(f"- {f}" for f in facts))

    summary_block = ""
    if sums:
        summary_block = (
            "เรื่องที่เคยคุยกันก่อนหน้า (รอสเต้จำได้จริง — นี่คือความทรงจำของคุณเอง):\n"
            + "\n".join(f"- {s}" for s in sums)
            + "\nถ้าผู้ใช้ถามว่าเคยคุยเรื่องนี้กันไหม/จำได้ไหม แล้วเรื่องนั้นอยู่ในรายการข้างบน "
              "= เคยคุยกันจริง ให้ตอบยืนยันแล้วเล่าเท่าที่จำได้ ห้ามตอบว่าไม่เคยคุย"
        )

    if summary_block and summary_position == "system":
        sp += "\n\n" + summary_block

    msgs = [{"role": "system", "content": sp}] + copy.deepcopy(persona.FEWSHOT_EXAMPLES)
    if summary_block and summary_position == "near":
        msgs.append({"role": "system", "content": summary_block})
    msgs.append({"role": "system", "content": persona.build_author_note()})
    msgs.append({"role": "user", "content": question})

    kw = {"temperature": 0.8}
    if with_tools:
        kw["tools"] = llm_tools.TOOLS
    return msgs, kw


async def eval_memory(pos, tools):
    total = ok = 0
    for q, keys in MEM_CASES:
        for _ in range(N):
            msgs, kw = build(q, pos, tools)
            m = await ollama_client._chat_once(msgs, **kw)
            c = (m.get("content") or "").split("</think>")[-1].strip()
            good = any(k in c for k in keys) and not any(d in c for d in DENIAL)
            ok += good
            total += 1
    return ok, total


async def eval_live(pos, tools):
    """ต้องเรียก tool ถูกตัว — ถ้าไม่ส่ง tools เลยก็ถือว่าพังทั้งหมด"""
    total = ok = 0
    for q, want in LIVE_CASES:
        for _ in range(N // 2):
            msgs, kw = build(q, pos, tools)
            m = await ollama_client._chat_once(msgs, **kw)
            calls = m.get("tool_calls") or []
            got = None
            if calls:
                fn = calls[0].get("function") if isinstance(calls[0], dict) else None
                got = fn.get("name") if isinstance(fn, dict) else None
            ok += (got == want)
            total += 1
    return ok, total


async def main():
    print("=" * 78)
    print(f" เทียบทางแก้ attention dilution (pass^{N})")
    print("=" * 78)

    variants = [
        ("A ปัจจุบัน (summary ท้าย system + tools)", "system", True),
        ("B ไม่ส่ง tools                          ", "system", False),
        ("C ย้าย summary ใกล้คำถาม (+tools)       ", "near", True),
        ("D ย้าย + ไม่ส่ง tools                    ", "near", False),
    ]

    rows = []
    for label, pos, tools in variants:
        mo, mt = await eval_memory(pos, tools)
        lo, lt = await eval_live(pos, tools)
        rows.append((label, mo, mt, lo, lt))
        print(f"\n  {label}")
        print(f"     ความจำ  {mo}/{mt} ({mo/mt*100:.0f}%)   "
              f"ข้อมูลสด {lo}/{lt} ({lo/lt*100:.0f}%)")

    print("\n" + "=" * 78)
    print(f" {'ทางแก้':<42} {'ความจำ':>10} {'ข้อมูลสด':>12}")
    print("-" * 78)
    for label, mo, mt, lo, lt in rows:
        print(f" {label:<42} {mo}/{mt:<8} {lo}/{lt:<10}")
    print("=" * 78)
    print(" หมายเหตุ: ทางแก้ที่ดีต้องได้ทั้งสองฝั่ง — ไม่ใช่แก้ทางหนึ่งแล้วพังอีกทาง")


if __name__ == "__main__":
    asyncio.run(main())
