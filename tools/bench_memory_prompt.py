"""วัด pass^k ว่าการเปลี่ยนถ้อยคำที่แนบ summary ลดอัตราพลาดจริงไหม

เคสจริงจาก Discord (31 ก.ค. 13:50): recall ส่ง summary ถูกต้องแล้ว แต่โมเดลตอบ
"ไม่ใช่ค่ะ ฉันเป็น AI ที่เพิ่งเริ่มทำงานและยังไม่ได้มีประวัติ"

เทียบ 2 ถ้อยคำบน context ชุดเดียวกัน (history จริง + summary จริง + facts จริง):
  เดิม: "ใช้เป็น context เฉยๆ ไม่ต้องพูดถึงโดยตรง"   ← เป็นคำสั่งห้ามพูดถึง
  ใหม่: "รอสเต้จำได้จริง ... ถ้าถูกถามให้ยืนยัน"      ← บอกวิธีใช้เมื่อถูกถาม

นับว่า "ผ่าน" เมื่อคำตอบ (ก) ยืนยันว่าเคยคุย และ (ข) ไม่หลุดว่าเป็น AI
"""
import asyncio
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(r"C:\Users\User\Roste-bot")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402
import ollama_client  # noqa: E402
import persona  # noqa: E402

MEM_FILE = "memory/387387058638815243.json"
N = 6

CASES = [
    ("เราเคยคุยเรื่องการอ่านอะไรกันบ้างไหมก่อนหน้านี้", ["นิยาย", "หนังสือ", "อ่าน"]),
    ("จำได้ไหมว่าเคยคุยเรื่องของหวานอะไรกัน", ["เจลาโต้", "ไอศกรีม", "ของหวาน", "หวาน"]),
]

OLD_TMPL = (
    "\n\nเรื่องที่เคยคุยกันก่อนหน้า (บทสนทนาเก่า ใช้เป็น context เฉยๆ ไม่ต้องพูดถึงโดยตรง):\n"
)
NEW_TMPL = (
    "\n\nเรื่องที่เคยคุยกันก่อนหน้า (รอสเต้จำได้จริง — รายการนี้คือความทรงจำของคุณเอง):\n"
)
NEW_SUFFIX = (
    "\nวิธีใช้: ปกติไม่ต้องท่องออกมาเอง แต่ถ้าผู้ใช้ถามว่าเคยคุยเรื่องนี้กันไหม/จำได้ไหม "
    "และเรื่องนั้นอยู่ในรายการข้างบน แปลว่าเคยคุยกันจริง ให้ตอบยืนยันแล้วเล่าเท่าที่จำได้ "
    "ห้ามตอบว่าไม่เคยคุยหรือจำไม่ได้"
)

DENIAL = ["ไม่เคย", "ไม่ได้คุย", "จำไม่ได้", "ไม่มีประวัติ", "ครั้งแรก", "ไม่ค่ะ", "ไม่ใช่ค่ะ"]


def build_prompt(mem, question, new_style: bool):
    sp = persona.SYSTEM_PROMPT
    facts = memory.recall_facts(mem, question)
    if facts:
        sp += ("\n\nสิ่งที่คุณ (รอสเต้) จำได้เกี่ยวกับคนที่กำลังคุยด้วย "
               "(ใช้ให้เป็นธรรมชาติ ไม่ต้องท่องออกมาเอง):\n"
               + "\n".join(f"- {f}" for f in facts))
    sums = memory.recall_summaries(mem, question)
    if sums:
        body = "\n".join(f"- {s}" for s in sums)
        sp += (NEW_TMPL + body + NEW_SUFFIX) if new_style else (OLD_TMPL + body)
    return sp, len(sums)


async def run(mem, history, question, must_have, new_style, label):
    ok = 0
    leaks = 0
    denials = 0
    samples = []
    sp, n_sums = build_prompt(mem, question, new_style)
    for i in range(N):
        msgs = [{"role": "system", "content": sp}] + history + [
            {"role": "user", "content": question}]
        m = await ollama_client._chat_once(msgs)
        c = (m.get("content") or "").split("</think>")[-1].strip()
        leaked = persona.reply_claims_to_be_ai(c)
        denied = any(d in c for d in DENIAL)
        hit = any(k in c for k in must_have)
        passed = hit and not leaked and not denied
        ok += passed
        leaks += leaked
        denials += denied
        if len(samples) < 2:
            samples.append(("PASS" if passed else "FAIL", c[:95]))
    print(f"    {label:<10} ผ่าน {ok}/{N}  (หลุดเป็น AI {leaks}, ปฏิเสธ {denials})")
    for st, s in samples:
        print(f"        [{st}] {s}")
    return ok


async def main():
    mem = json.load(open(MEM_FILE, encoding="utf-8"))
    history = mem.get("history", [])[:-2]
    print("=" * 78)
    print(f" pass^{N} — ถ้อยคำที่แนบ summary มีผลต่ออัตราพลาดไหม")
    print(f" context: history {len(history)} ข้อความ + summary + facts (สภาพเดียวกับของจริง)")
    print("=" * 78)

    tot_old = tot_new = 0
    for q, must in CASES:
        sp, n = build_prompt(mem, q, False)
        print(f"\n  ❓ {q}")
        print(f"     (recall ส่ง summary ให้ {n} อัน)")
        tot_old += await run(mem, history, q, must, False, "เดิม")
        tot_new += await run(mem, history, q, must, True, "ใหม่")

    total = len(CASES) * N
    print("\n" + "=" * 78)
    print(f" รวม:  เดิม {tot_old}/{total}   →   ใหม่ {tot_new}/{total}")
    if tot_new > tot_old:
        print(f" ✅ ถ้อยคำใหม่ดีขึ้น {tot_new - tot_old} รอบ")
    elif tot_new == tot_old:
        print(" ⚠️ ไม่ต่างกัน — ถ้อยคำไม่ใช่ตัวแปรหลัก")
    else:
        print(f" ❌ ถ้อยคำใหม่แย่ลง {tot_old - tot_new} รอบ")
    print("=" * 78)


if __name__ == "__main__":
    asyncio.run(main())
