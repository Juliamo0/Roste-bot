"""โมเดลใหญ่ขึ้นช่วยให้จำข้อมูลผู้ใช้ได้ดีขึ้นไหม — วัดบนชุดเดียวกับ baseline

ที่มา: หลังเปิด open schema แล้วได้ 51/80 (64%) ที่เหลือ 36% ตกที่ "โมเดลตัดสินเองว่า
ไม่มีอะไรน่าจำ" ซึ่งเป็นข้อจำกัดของโมเดล ไม่ใช่ของ schema แล้ว → คำถามต่อคือโมเดลใหญ่ช่วยไหม

วัดทุกตัวด้วย **prompt เดียวกัน (open schema ที่ merge เข้า production แล้ว)** และ
**ชุดเคสเดียวกัน 80 เคส** — ต่างกันแค่โมเดล จึงเทียบกันได้ตรงๆ

วัด 2 อย่างคู่กัน เพราะการเลือกโมเดลคือการแลก:
    - จำได้กี่ % (Wilson CI)
    - latency ต่อ call — เอกสารโปรเจกต์ระบุว่า main_llm กิน 73.5% ของเวลาตอบอยู่แล้ว
      ถ้า auto_remember ช้าขึ้นมาก จะไปเบียดคิว _bg_queue (worker เดี่ยว ทำทีละตัว)

⚠️ ไม่แตะ production — อ่าน prompt จาก memory.build_extract_prompt ตัวจริงมาใช้
"""
import argparse
import asyncio
import collections
import io
import json
import logging
import math
import os
import pathlib
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

import memory  # noqa: E402
from memory_coverage_fixture import CASES, SUPPORTED_GROUPS  # noqa: E402
from ollama_client import OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)

MODELS = ["qwen3:1.7b", "qwen3:8b", "gemma3:12b", "qwen3:14b"]


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


async def extract(model: str, text: str) -> tuple:
    """คืน (facts, วินาที) — ใช้ prompt ตัวจริงจาก production"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": memory.build_extract_prompt(text)}],
        "stream": False, "think": False,
        "options": {"temperature": 0.2},
    }
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=payload, timeout=300) as r:
                data = await r.json()
        raw = data.get("message", {}).get("content", "") or ""
    except Exception:
        return [], time.perf_counter() - t0
    return memory.parse_extracted_facts(raw), time.perf_counter() - t0


def remembered(must: list, facts: list) -> bool:
    blob = " ".join(f["text"] for f in facts)
    return any(m in blob for m in must)


async def run_model(model: str) -> dict:
    rows, secs = [], []
    for text, must, group, note in CASES:
        if not memory.should_try_extract(text):
            rows.append((group, text, False, [], note))
            continue
        facts, dt = await extract(model, text)
        secs.append(dt)
        rows.append((group, text, remembered(must, facts), facts, note))
    return {"rows": rows, "secs": secs}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--save")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",")]

    gate_n = sum(1 for c in CASES if memory.should_try_extract(c[0]))
    print("=" * 104)
    print(" โมเดลใหญ่ขึ้นช่วยไหม — prompt เดียวกัน (open schema) ชุดเคสเดียวกัน")
    print(f" เคส {len(CASES)} · เรียกโมเดล {gate_n} ครั้งต่อรุ่น")
    print("=" * 104)

    out = {}
    for m in models:
        print(f"\n กำลังรัน {m} ...")
        t0 = time.perf_counter()
        out[m] = await run_model(m)
        print(f"   เสร็จใน {time.perf_counter() - t0:.0f}s")

    print("\n" + "=" * 104)
    print(f" {'โมเดล':<14} {'จำได้':>11} {'ช่วง 95%':>13} {'latency/call':>14}"
          f" {'ปฏิเสธ':>9} {'คนอื่น':>8}")
    print("-" * 104)
    for m in models:
        rows = out[m]["rows"]
        secs = out[m]["secs"]
        ok = sum(1 for r in rows if r[2])
        lo, hi = wilson(ok, len(rows))
        neg = [r for r in rows if "ปฏิเสธ" in r[4]]
        oth = [r for r in rows if "คนอื่น" in r[4]]
        med = statistics.median(secs) if secs else 0
        print(f" {m:<14} {ok:>4}/{len(rows):<5} {lo*100:>5.0f}-{hi*100:<5.0f}%"
              f" {med:>10.1f}s   {sum(1 for r in neg if r[2]):>3}/{len(neg):<4}"
              f" {sum(1 for r in oth if r[2]):>3}/{len(oth)}")
    print("=" * 104)

    # เทียบกับ baseline เดิม (closed set + qwen3:8b) ถ้ามีไฟล์
    bp = pathlib.Path("tools/coverage_baseline.json")
    if bp.exists():
        b = json.load(open(bp, encoding="utf-8"))
        bok = sum(1 for r in b if r["ok"])
        print(f"\n อ้างอิง: baseline เดิม (closed set + qwen3:8b) = {bok}/80"
              f" ({bok/80*100:.0f}%)")

    # กลุ่มที่ยังพังเหมือนกันทุกรุ่น = ไม่ใช่เรื่องขนาดโมเดล
    always_fail = []
    for i, (text, must, group, note) in enumerate(CASES):
        if all(not out[m]["rows"][i][2] for m in models):
            always_fail.append((group, text))
    print(f"\n เคสที่ *ทุกรุ่น* จำไม่ได้: {len(always_fail)}/{len(CASES)}"
          f" ← ไม่ใช่เรื่องขนาดโมเดล")
    byg = collections.Counter(g for g, _ in always_fail)
    for g, v in byg.most_common(6):
        print(f"    {v:>2}x {g}")

    if args.save:
        json.dump({m: {"rows": [{"group": r[0], "text": r[1], "ok": r[2],
                                 "facts": r[3], "note": r[4]} for r in out[m]["rows"]],
                       "median_s": statistics.median(out[m]["secs"]) if out[m]["secs"] else 0}
                   for m in models},
                  open(args.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n เซฟผลดิบไว้ที่ {args.save}")


if __name__ == "__main__":
    asyncio.run(main())
