"""เทียบ 3 ทางเลือก บนบทสนทนาชุดเดียวกัน — ผู้ใช้สั่ง "ทำทั้ง 1-2 เลยมาเทียบกัน"

    baseline  schema เก่า (pref/fact เท่านั้น) = ถอย user_ask/me_suggest ออก  [ทางที่ 1]
    schema    schema ใหม่ อย่างเดียว (ไม่กู้ฝั่งอ่าน)
    both      schema ใหม่ + กู้ _fact ที่ขึ้นต้นด้วย "ชอบ" ตอนถามความชอบ      [ทางที่ 2]

⚠️ ทำไมต้องวัด 3 ไม่ใช่ 2: ทางที่ 2 สร้างบน schema ใหม่ ถ้าไม่มี 'schema' เดี่ยวๆ
   จะแยกไม่ออกว่าผลที่ดีขึ้นมาจาก schema หรือมาจากการกู้ฝั่งอ่าน

วัด 3 อย่างต่อทางเลือก:
    attribution  ตอบถูกเจ้าของไหม (สับสน = ตอบราวกับผู้ใช้ทำสิ่งที่รอสเต้แค่เสนอ)
    pref_recall  ถามความชอบแล้วหาเจอไหม  <- ตัวที่ regression ตอนคุยจริง
    mistag       tag ติดผิดชนิดกี่อัน

ทุกทางใช้บทสนทนาเดียวกัน เขียนด้วย 4B จริง ตอบด้วย 8B จริง
"""
import argparse
import asyncio
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

import aiohttp  # noqa: E402

import memory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from bench_write_schema import CASES, classify, post, strip_new_tags  # noqa: E402
from config import OLLAMA_EXTRACT_MODEL, OLLAMA_MODEL  # noqa: E402

logging.disable(logging.CRITICAL)

# บทที่มี "ความชอบจริง" + คำถามความชอบ — ชุดที่จับ regression ที่เจอตอนคุยจริง
PREF_CASES = [
    ([{"role": "user", "content": "ผมชอบอ่านนิยายสืบสวนมากเลยนะ ชอบตอนที่เฉลยปม"},
      {"role": "assistant", "content": "น่าสนใจค่ะ รอสเต้ชอบช่วงท้ายเหมือนกัน"}],
     "ผมชอบอ่านหนังสือแนวไหน", "สืบสวน"),
    ([{"role": "user", "content": "ผมไม่ค่อยชอบกินของหวานเท่าไหร่ ชอบของเผ็ดมากกว่า"},
      {"role": "assistant", "content": "เผ็ดนี่สนุกดีนะคะ"}],
     "ผมชอบกินอะไร", "เผ็ด"),
    ([{"role": "user", "content": "ผมชอบฟังเพลงแจ๊สตอนทำงาน"},
      {"role": "assistant", "content": "แจ๊สช่วยให้สมาธิดีนะคะ"}],
     "ผมชอบฟังเพลงแนวไหน", "แจ๊ส"),
    ([{"role": "user", "content": "ช่วงนี้งานเยอะ ขอวิธีจัดการเวลาหน่อย"},
      {"role": "assistant", "content": "ลอง Pomodoro ดูไหมคะ"}],
     "ผมชอบทำอะไรตอนว่าง", None),          # ไม่มีความชอบในบท -> ต้องไม่ตอบมั่ว
]


async def write_line(pairs: list, old_schema: bool) -> str:
    p = memory.build_summary_prompt(pairs)
    if old_schema:
        p = strip_new_tags(p)
    return memory.parse_summary_json(await post(OLLAMA_EXTRACT_MODEL, p, True))


def count_mistag(parts: dict) -> int:
    n = 0
    for v in parts["user_pref"]:
        if v.startswith(("ต้องการ", "ขอ", "อยาก", "สนใจ")):
            n += 1
    for v in parts["me_pref"]:
        if v.startswith(("แนะนำ", "ลอง", "วิธี", "เทคนิค")):
            n += 1
    return n


async def run(variant: str, rounds: int) -> dict:
    old = variant == "baseline"
    rescue = variant == "both"
    tally = {"correct": 0, "confuse": 0, "unclear": 0}
    mistag = 0

    # ── attribution (ใช้บทชุดเดียวกับ bench_write_schema) ──
    for pairs, probe in CASES:
        line = await write_line(pairs, old)
        if not line:
            continue
        mistag += count_mistag(memory.split_owner_tags(line))
        whose = memory.guess_owner(probe)
        ctx = "\n".join(f"- {x}" for x in memory.filter_by_owner([line], whose))
        ask = ("คุณคือรอสเต้ ผู้ช่วยหญิงพูดไทย ลงท้าย ค่ะ/นะคะ\n\n"
               "เรื่องที่เคยคุยกันก่อนหน้า:\n" + ctx +
               "\n\nตอบคำถามสั้นๆ ตามความทรงจำข้างบนเท่านั้น\n"
               f"ผู้ใช้: {probe}\nรอสเต้:")
        for _ in range(rounds):
            tally[classify(await post(OLLAMA_MODEL, ask, False))] += 1

    # ── pref recall: ถามความชอบแล้วหาเจอไหม ──
    hit = tot = 0
    false_pos = 0
    for pairs, q, must in PREF_CASES:
        line = await write_line(pairs, old)
        if not line:
            continue
        mem = {"summaries": [{"text": line, "date": "2026-08-12"}]}
        # ปิด/เปิดการกู้ฝั่งอ่านตามตัวแปร
        saved = memory._LIKE_PREFIXES
        if not rescue:
            memory._LIKE_PREFIXES = ("\0ไม่มีทางตรง",)   # ปิดการกู้
        try:
            got = " ".join(memory.recall_summaries(mem, q))
        finally:
            memory._LIKE_PREFIXES = saved
        if must is None:
            if got.strip():
                false_pos += 1          # ไม่มีความชอบในบท แต่ดันคืนของมา
            continue
        tot += 1
        hit += must in got
    return {"tally": tally, "mistag": mistag,
            "pref": (hit, tot), "false_pos": false_pos}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--variants", default="baseline,schema,both")
    args = ap.parse_args()

    variants = [v.strip() for v in args.variants.split(",")]
    print("=" * 96)
    print(" เทียบ 3 ทางเลือก บนบทเดียวกัน — เขียนด้วย 4B ตอบด้วย 8B")
    print(f" attribution {len(CASES)} บท × {args.rounds} รอบ · pref recall {len(PREF_CASES)} บท")
    print("   baseline = ถอย schema ใหม่ออก (ทางที่ 1)")
    print("   schema   = schema ใหม่อย่างเดียว")
    print("   both     = schema ใหม่ + กู้ฝั่งอ่าน (ทางที่ 2)")
    print("=" * 96)

    res = {}
    for v in variants:
        res[v] = await run(v, args.rounds)
        r = res[v]
        h, t = r["pref"]
        print(f"   {v:<10} สับสน {r['tally']['confuse']:>2} · ถูก {r['tally']['correct']:>2}"
              f" · pref {h}/{t} · mistag {r['mistag']} · ตอบมั่ว {r['false_pos']}")

    print("\n" + "=" * 96)
    print(f" {'ทางเลือก':<12}{'attribution error':>22}{'ช่วง 95%':>16}"
          f"{'pref recall':>14}{'mistag':>9}{'ตอบมั่ว':>9}")
    print("-" * 96)
    for v in variants:
        r = res[v]
        n = sum(r["tally"].values()) or 1
        lo, hi = wilson(r["tally"]["confuse"], n)
        h, t = r["pref"]
        print(f" {v:<12}{r['tally']['confuse']:>10}/{n:<5}{r['tally']['confuse']/n*100:>5.0f}%"
              f"{lo*100:>8.0f}-{hi*100:<6.0f}%{h:>8}/{t:<4}{r['mistag']:>8}{r['false_pos']:>9}")
    print("=" * 96)


if __name__ == "__main__":
    asyncio.run(main())
