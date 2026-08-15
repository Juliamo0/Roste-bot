"""query rewriting คุ้มไหม — วัด **ผลที่ได้** เทียบกับ **latency ที่จ่าย**

ที่มา: audit ข้อ 4 ระบุว่าไม่มี query rewriting และเป็นต้นเหตุ 3/8 เคสที่ oracle พลาด
(คำถามกับ summary ไม่มีคำร่วมกันเลย) เจอซ้ำในบททดสอบ:
    "ผมเลี้ยงสัตว์อะไร" ไม่แมตช์ "เลี้ยงแมวชื่อโมจิ"   (สัตว์ vs แมว)
    "ตอนนี้ออกกำลังกายยังไง" ไม่แมตช์ "เลิกแบด หันมาว่ายน้ำ"

⚠️ แต่ read path มีราคา — ต่างจาก write path ที่อยู่ใน _bg_queue แพงได้
   ต้องวัดก่อนว่าคุ้มไหม ไม่ใช่ทำเพราะงานวิจัยบอกว่าดี

เทียบ 3 วิธี:
    baseline   ค้นด้วยคำถามดิบ (ปัจจุบัน)
    expand     ขยายคำพ้องแบบ rule-based (ฟรี ไม่ยิง LLM) — _keywords(expand=True) ทำอยู่แล้ว
    llm        ให้ 4B เขียนคำถามใหม่ก่อนค้น (แพง +1 LLM call/คำถาม)

วัดทั้ง recall และเวลา — ตัดสินด้วยทั้งสองอย่าง ไม่ใช่ recall อย่างเดียว
"""
import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import memory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from bench_write_schema import post  # noqa: E402
from config import OLLAMA_EXTRACT_MODEL  # noqa: E402
from thai_recall_cases import load as load_thai  # noqa: E402

logging.disable(logging.CRITICAL)
# uid ที่ใช้วัดกับความจำจริง — อ่านจาก env ไม่ฮาร์ดโค้ด
# (repo เป็น public — Discord user ID เป็นข้อมูลระบุตัวตน ไม่ควรติดมากับโค้ด)
# ตั้งใน .env: BENCH_REAL_UID=<discord user id>
REAL_UID = int(os.getenv("BENCH_REAL_UID") or 0)

REWRITE_PROMPT = (
    "เขียนคำถามนี้ใหม่ให้ค้นความทรงจำได้ง่ายขึ้น ตอบเป็น JSON เท่านั้น\n"
    '{"q": "<คำถามที่เขียนใหม่ พร้อมคำพ้องที่น่าจะอยู่ในบันทึก>"}\n'
    "กฎ:\n"
    "- เติม*คำที่มีความหมายใกล้เคียง* ที่บันทึกอาจใช้แทน "
    "(สัตว์เลี้ยง -> แมว หมา · ออกกำลังกาย -> วิ่ง ว่ายน้ำ แบด)\n"
    "- ห้ามเปลี่ยนเจ้าของคำถาม (ผม/รอสเต้ ต้องคงเดิม)\n"
    "- ห้ามแต่งข้อมูลที่ไม่ได้ถาม\n"
    "ตอบ JSON อย่างเดียว:\n\n"
)


async def rewrite(q: str) -> str:
    raw = await post(OLLAMA_EXTRACT_MODEL, REWRITE_PROMPT + q, True)
    try:
        txt = raw[raw.find("{"):raw.rfind("}") + 1]
        new = (json.loads(txt).get("q") or "").strip()
        return new or q
    except Exception:
        return q


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="baseline,llm")
    args = ap.parse_args()

    mem = memory.load_memory(REAL_UID)
    cases = load_thai(mem.get("summaries", []))
    modes = [m.strip() for m in args.modes.split(",")]

    print("=" * 92)
    print(" query rewriting คุ้มไหม — วัดผลเทียบ latency")
    print(f" ความจำจริง {len(mem.get('summaries', []))} summary · {len(cases)} คำถามไทย")
    print("=" * 92)

    res = {}
    for m in modes:
        t0 = time.perf_counter()
        hit = silent = 0
        for q, must in cases:
            qq = await rewrite(q) if m == "llm" else q
            got = memory.recall_summaries(mem, qq)
            if not got:
                silent += 1
            if any(x in " ".join(got) for x in must):
                hit += 1
        dt = time.perf_counter() - t0
        res[m] = {"hit": hit, "silent": silent, "per": dt / len(cases)}
        print(f"   {m:<10} {hit}/{len(cases)} · เงียบ {silent} · {dt/len(cases)*1000:.0f}ms/คำถาม")

    n = len(cases)
    print("\n" + "=" * 92)
    print(f" {'วิธี':<12}{'ตอบถูก':>12}{'ช่วง 95%':>18}{'เงียบ':>8}{'latency':>14}")
    print("-" * 92)
    for m in modes:
        r = res[m]
        lo, hi = wilson(r["hit"], n)
        print(f" {m:<12}{r['hit']:>6}/{n:<5}{lo*100:>9.0f}-{hi*100:<7.0f}%"
              f"{r['silent']:>8}{r['per']*1000:>11.0f}ms")
    print("=" * 92)

    if "baseline" in res and len(modes) > 1:
        b = res["baseline"]
        lb, hb = wilson(b["hit"], n)
        for m in modes:
            if m == "baseline":
                continue
            r = res[m]
            lo, hi = wilson(r["hit"], n)
            ov = not (lo > hb or lb > hi)
            extra = (r["per"] - b["per"]) * 1000
            print(f"\n {m} vs baseline: {'ซ้อนทับ = แยกไม่ออก' if ov else 'ต่างจริง ✅'}"
                  f"  ({r['hit']} vs {b['hit']})  จ่ายเพิ่ม {extra:.0f}ms/คำถาม")


if __name__ == "__main__":
    asyncio.run(main())
