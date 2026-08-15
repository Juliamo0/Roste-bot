"""จำลองข้อมูลที่ "เปลี่ยนใจตามเวลา" แล้วดูว่าระบบจัดการ staleness ได้จริงไหม

ที่มา (ผู้ใช้สั่ง): ความจำจริงมี 0 คู่ขัดแย้ง เพราะสะสมแค่ 5 วัน
-> staleness/conflict resolution วัดกับของจริงไม่ได้เลย ต้องจำลองให้มันทำงานสักครั้ง

⚠️ ต่างจาก tools/memory_conflict_fixture.py ตรงไหน:
   fixture เดิม = summary ที่ **เขียนด้วยมือ** แล้ววัดเฉพาะชั้น retrieval
   ไฟล์นี้     = ปล่อยบทสนทนาผ่าน **pipeline จริง** (4B สรุป -> เขียนลงไฟล์ -> ค้นจริง)
                 และควบคุม *วันที่* ให้ห่างกันจริง เพื่อให้ decay/recency มีผล
   = วัดทั้งเส้น ไม่ใช่แค่ชั้นเดียว

สถานการณ์: 3 เรื่องที่ผู้ใช้เปลี่ยนใจ ห่างกันเรื่องละ ~30 วัน
    ที่อยู่      ชุมพร      -> เชียงใหม่
    กีฬา        แบดมินตัน  -> ว่ายน้ำ
    แนวหนังสือ  สืบสวน     -> ไซไฟ

วัด 3 อย่าง:
    current     ถาม "ตอนนี้..." ต้องได้ค่า **ใหม่**
    historical  ถาม "เมื่อก่อน..." ต้องได้ค่า **เก่า**  <- ตัวที่ recency-wins มักพัง
    conflict    ค่าเก่า+ใหม่โผล่พร้อมกันใน context ไหม (= โมเดลต้องเลือกเอง)
"""
import argparse
import asyncio
import json
import logging
import os
import pathlib
import shutil
import sys
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import memory  # noqa: E402
from bench_write_schema import post  # noqa: E402
from config import OLLAMA_EXTRACT_MODEL, OLLAMA_MODEL  # noqa: E402

logging.disable(logging.CRITICAL)

SIM_UID = 999900000000000900

# (วันที่ย้อนหลังกี่วัน, บทสนทนา)
TIMELINE = [
    (90, [{"role": "user", "content": "ผมอยู่ชุมพรครับ อยู่มาตั้งแต่เด็ก"},
          {"role": "assistant", "content": "ชุมพรทะเลสวยนะคะ"}]),
    (85, [{"role": "user", "content": "ผมเล่นแบดมินตันทุกเย็นเลย สนุกมาก"},
          {"role": "assistant", "content": "ออกกำลังกายดีค่ะ"}]),
    (80, [{"role": "user", "content": "ผมชอบอ่านนิยายสืบสวนมาก ชอบตอนเฉลยปม"},
          {"role": "assistant", "content": "น่าสนใจค่ะ"}]),
    # ── เปลี่ยนใจ ──
    (30, [{"role": "user", "content": "ผมย้ายมาอยู่เชียงใหม่แล้วนะ ไม่ได้อยู่ชุมพรแล้ว"},
          {"role": "assistant", "content": "เชียงใหม่อากาศดีค่ะ"}]),
    (20, [{"role": "user", "content": "เลิกเล่นแบดแล้ว เปลี่ยนมาว่ายน้ำแทน เข่าไม่ไหว"},
          {"role": "assistant", "content": "ว่ายน้ำเบาข้อดีค่ะ"}]),
    (10, [{"role": "user", "content": "เบื่อนิยายสืบสวนแล้ว ตอนนี้ชอบไซไฟมากกว่า"},
          {"role": "assistant", "content": "ไซไฟสนุกค่ะ"}]),
]

PROBES = [
    ("current", "ตอนนี้ผมอยู่จังหวัดอะไร", "เชียงใหม่", "ชุมพร"),
    ("current", "ตอนนี้ผมออกกำลังกายยังไง", "ว่ายน้ำ", "แบด"),
    ("current", "ตอนนี้ผมชอบอ่านแนวไหน", "ไซไฟ", "สืบสวน"),
    ("historical", "เมื่อก่อนผมอยู่ที่ไหน", "ชุมพร", None),
    ("historical", "เมื่อก่อนผมเล่นกีฬาอะไร", "แบด", None),
    ("historical", "เมื่อก่อนผมชอบอ่านแนวไหน", "สืบสวน", None),
]


async def build_memory(rounds: int) -> dict:
    """สร้างความจำจำลองผ่าน pipeline จริง — 4B สรุปเอง ไม่ได้เขียนมือ"""
    path = f"memory/{SIM_UID}.json"
    if os.path.exists(path):
        os.remove(path)
    mem = {"summaries": [], "facts": [], "history": []}
    today = date.today()

    for days_ago, pairs in TIMELINE:
        when = today - timedelta(days=days_ago)
        line = ""
        for _ in range(rounds):        # ลองหลายรอบ เอาอันที่มี tag
            raw = await post(OLLAMA_EXTRACT_MODEL,
                             memory.build_summary_prompt(pairs), True)
            line = memory.parse_summary_json(raw)
            line = memory.fix_owner_slips(line, pairs)
            line, _ = memory.strip_sensitive_tags(line)
            if line and memory.split_owner_tags(line)["user"]:
                break
        if not line:
            continue
        line = memory.dedupe_tags_against(line, mem["summaries"])
        d = when
        mem["summaries"].append({
            "date": str(d),
            "text": f"{d.day} {['','ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'][d.month]}: {line}",
        })
    json.dump(mem, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return mem


async def ask(ctx: str, q: str) -> str:
    prompt = ("คุณคือรอสเต้ ผู้ช่วยหญิงพูดไทย ลงท้าย ค่ะ/นะคะ\n\n"
              "เรื่องที่เคยคุยกันก่อนหน้า:\n" + ctx +
              "\n\nตอบคำถามสั้นๆ ตามความทรงจำข้างบนเท่านั้น\n"
              f"ผู้ใช้: {q}\nรอสเต้:")
    return await post(OLLAMA_MODEL, prompt, False)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3, help="ลองสรุปกี่รอบต่อบท")
    ap.add_argument("--keep", action="store_true", help="ไม่ลบความจำจำลองทิ้ง")
    args = ap.parse_args()

    print("=" * 96)
    print(" จำลอง staleness — ผู้ใช้เปลี่ยนใจ 3 เรื่อง ห่างกัน ~60-80 วัน")
    print(" ผ่าน pipeline จริง (4B สรุป -> เขียนไฟล์ -> recall_summaries จริง)")
    print("=" * 96)

    mem = await build_memory(args.rounds)
    print(f"\n สร้างความจำได้ {len(mem['summaries'])} อัน:")
    for e in mem["summaries"]:
        print(f"   {e['date']}  {e['text'][:88]}")

    print("\n" + "=" * 96)
    print(f" {'ชนิด':<12}{'คำถาม':<30}{'ต้องได้':<12}{'ผล':<10}{'ค่าเก่าปนมา?':<14}")
    print("-" * 96)

    score = {"current": [0, 0], "historical": [0, 0]}
    both = 0
    for kind, q, want, avoid in PROBES:
        got = memory.recall_summaries(mem, q)
        ctx = "\n".join(f"- {x}" for x in got)
        ans = await ask(ctx, q)
        ok = want in ans
        score[kind][0] += ok
        score[kind][1] += 1
        # ค่าเก่ากับใหม่โผล่พร้อมกันใน context ไหม
        mixed = bool(avoid) and (want in ctx) and (avoid in ctx)
        both += mixed
        print(f" {kind:<12}{q:<30}{want:<12}{'ถูก' if ok else 'ผิด':<10}"
              f"{'ปนมา' if mixed else '-':<14}")
        if not ok:
            print(f"              ตอบ: {ans.strip()[:80]}")

    print("=" * 96)
    for k, (a, b) in score.items():
        print(f" {k:<12} {a}/{b}")
    print(f" context ที่มีทั้งค่าเก่าและใหม่พร้อมกัน: {both}/3")
    print("\n อ่านผล: current ผิด = staleness (ตอบด้วยค่าเก่า)")
    print("         historical ผิด = ลืมของเก่า (recency-wins มากเกินไป)")
    print("         ปนมาเยอะ = โมเดลต้องเลือกเอง ซึ่ง §7 วัดแล้วว่ามันชอบเอามารวมกัน")

    if not args.keep:
        os.remove(f"memory/{SIM_UID}.json")
        print("\n (ลบความจำจำลองแล้ว — ใส่ --keep ถ้าจะเก็บไว้ดู)")


if __name__ == "__main__":
    asyncio.run(main())
