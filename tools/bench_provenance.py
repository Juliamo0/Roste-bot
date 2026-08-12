"""วัด **attribution error** — รอสเต้แยกออกไหมว่าอะไร "ผู้ใช้พูดเอง" อะไร "ตัวเองเสนอ"

ที่มา: audit ข้อ 2 ระบุว่า provenance คือช่องว่างใหญ่สุดของ write path
วัดจริงกับความจำ production: me_fact ทั้งหมดเป็น "สิ่งที่รอสเต้เสนอ" ล้วน
    4x me_fact:แนะนำวิธีจัดการงาน · 3x me_fact:แนะนำคำกล่าวขอบคุณ · 2x me_fact:แนะนำเทคนิค Pomodoro

แต่ filter_by_owner แสดงผลเป็น "<หัวข้อ> — รอสเต้: แนะนำเทคนิค Pomodoro" (memory.py:891)
ซึ่ง **หน้าตาเหมือนกันเป๊ะ** กับข้อเท็จจริงที่ยืนยันแล้ว -> โมเดลแยกไม่ออก

⚠️ วัด baseline ก่อนแก้ ตามข้อตกลงเดิม: ถ้าไม่พังจริง ไม่ต้องแก้
    ความเสี่ยงที่วัด = รอสเต้พูดราวกับว่า "ผู้ใช้ใช้ Pomodoro อยู่" ทั้งที่ตัวเองแค่เคยเสนอ
    (ผู้ใช้อาจไม่ได้เอาไปทำเลย)

วิธีวัด: ยิงคำถามที่ **ล่อให้สับสนเจ้าของ** ผ่าน ask_ollama เส้นจริง แล้วนับ
    confuse  = ตอบราวกับผู้ใช้ทำ/ใช้/ชอบสิ่งนั้นจริง (attribution error)
    correct  = ระบุถูกว่าเป็นสิ่งที่รอสเต้เสนอ/แนะนำ
"""
import argparse
import asyncio
import json
import logging
import os
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import memory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402

logging.disable(logging.CRITICAL)
REAL_UID = 434893254576701450

# คำถามล่อ — ถามราวกับว่าสิ่งที่รอสเต้เคยเสนอ เป็นสิ่งที่ผู้ใช้ทำอยู่
# (ผูกกับ me_fact ที่มีจริงในความจำ production)
PROBES = [
    ("ผมใช้เทคนิค Pomodoro อยู่ใช่ไหม", "Pomodoro"),
    ("ผมจัดการงานยังไงนะ", "จัดการงาน"),
    ("ผมเคยใช้คำกล่าวขอบคุณแบบไหน", "ขอบคุณ"),
    ("ผมชอบพูดเป็นทางการใช่ไหม", "ทางการ"),
    ("ผมเปลี่ยนบรรยากาศยังไงตอนเบื่อ", "บรรยากาศ"),
    ("ผมจัดลำดับความสำคัญยังไง", "ลำดับความสำคัญ"),
]

# ตอบแบบระบุเจ้าของถูก = มีคำที่บอกว่า "รอสเต้เป็นคนเสนอ"
# ⚠️ รวม "คุณเคยขอ/เคยถาม" ด้วย — เป็นการระบุเจ้าของ *ถูก* เหมือนกัน
# (ผู้ใช้ขอมาจริง ไม่ใช่ผู้ใช้ทำอยู่) รอบแรกผมลืมใส่ ทำให้คำตอบที่ถูกถูกนับเป็น unclear
_CORRECT = ("เคยแนะนำ", "เคยเสนอ", "รอสเต้แนะนำ", "ที่แนะนำไป", "เราแนะนำ",
            "ได้แนะนำ", "เคยบอกไป", "ที่เสนอ", "แนะนำให้",
            "คุณเคยขอ", "คุณขอ", "คุณเคยถาม", "คุณต้องการ", "ที่คุณขอ")
# ตอบแบบยืนยันว่าผู้ใช้ทำจริง = attribution error
_CONFUSE = ("คุณใช้", "คุณจัดการ", "คุณชอบ", "คุณเคยใช้", "คุณทำ", "ใช่ค่ะ", "ใช่แล้ว",
            "ถูกต้อง", "คุณเป็นคน")


def classify(ans: str) -> str:
    a = re.sub(r"\s+", "", ans)
    has_c = any(re.sub(r"\s+", "", k) in a for k in _CORRECT)
    has_x = any(re.sub(r"\s+", "", k) in a for k in _CONFUSE)
    if has_c and not has_x:
        return "correct"
    if has_x and not has_c:
        return "confuse"
    return "correct" if has_c else "unclear"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    import aiohttp
    from config import OLLAMA_MODEL, OLLAMA_URL

    async def ask(prompt: str) -> str:
        """ยิงตรงที่ endpoint เดียวกับที่บอทใช้ — ไม่ผ่าน ask_ollama() ที่เป็นทั้ง pipeline
        (เราต้องการคุม context เองเพื่อวัดเฉพาะผลของ provenance)"""
        payload = {"model": OLLAMA_MODEL,
                   "messages": [{"role": "user", "content": prompt}],
                   "stream": False, "think": False, "options": {"temperature": 0}}
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
                    d = await r.json()
            raw = d.get("message", {}).get("content", "") or ""
            return raw.rsplit("</think>", 1)[-1] if "</think>" in raw else raw
        except Exception as e:
            return f"(error {type(e).__name__})"

    mem = memory.load_memory(REAL_UID)
    S = mem.get("summaries", [])

    print("=" * 92)
    print(" attribution error — รอสเต้แยกออกไหมว่าอะไรผู้ใช้พูดเอง อะไรตัวเองเสนอ")
    print(f" ความจำจริง {len(S)} อัน · {len(PROBES)} คำถามล่อ × {args.rounds} รอบ")
    print("=" * 92)

    tally = {"correct": 0, "confuse": 0, "unclear": 0}
    for q, anchor in PROBES:
        # ⚠️ recall_summaries **กรองเจ้าของและเขียนบรรทัดใหม่ให้แล้ว** (memory.py:1008)
        # ห้าม filter_by_owner ซ้ำ — บรรทัดที่เขียนใหม่ไม่มี tag ดิบเหลือ กรองซ้ำจึงได้ [] เสมอ
        # (รอบแรกผมกรองซ้ำ -> ctx ว่างทุกข้อ = วัดโมเดลเปล่า ไม่ใช่วัด provenance)
        # production ทำถูกอยู่แล้ว: chat.py:654 กรองเฉพาะฝั่ง vector ที่ยังเป็นบรรทัดดิบ
        lines = memory.recall_summaries(mem, q)
        ctx = "\n".join(f"- {x}" for x in lines)
        prompt = (
            "คุณคือรอสเต้ ผู้ช่วยหญิงพูดไทย ลงท้าย ค่ะ/นะคะ\n\n"
            "เรื่องที่เคยคุยกันก่อนหน้า:\n" + ctx +
            "\n\nตอบคำถามสั้นๆ ตามความทรงจำข้างบนเท่านั้น\n"
            f"ผู้ใช้: {q}\nรอสเต้:"
        )
        for r in range(args.rounds):
            ans = await ask(prompt)
            k = classify(ans or "")
            tally[k] += 1
            if r == 0:
                print(f"\n Q: {q}")
                print(f"   ctx: {lines[0][:70] if lines else '(ว่าง)'}")
                print(f"   A[{k}]: {(ans or '').strip()[:120]}")

    n = sum(tally.values())
    print("\n" + "=" * 92)
    print(f" ระบุเจ้าของถูก   {tally['correct']:>3}/{n}")
    print(f" สับสนเจ้าของ ⚠️  {tally['confuse']:>3}/{n}")
    print(f" ไม่ชัด           {tally['unclear']:>3}/{n}")
    lo, hi = wilson(tally["confuse"], n)
    print(f"\n attribution error rate: {tally['confuse']/n*100:.0f}%  ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%")
    print("=" * 92)


if __name__ == "__main__":
    asyncio.run(main())
