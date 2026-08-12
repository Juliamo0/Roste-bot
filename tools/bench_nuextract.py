"""ทดสอบ NuExtract (3.8B ออกแบบมาเพื่อ extraction โดยเฉพาะ) บนชุด 80 เคสเดียวกัน

ผู้ใช้ถามหาโมเดลที่ *ออกแบบมาเพื่อสรุป/สกัด* ไม่ใช่โมเดลแชตทั่วไป — NuExtract ตรงที่สุด

⚠️ ต้องเขียน adapter แยกเพราะมันต่างจากตัวอื่นสิ้นเชิง:
    - capability = completion อย่างเดียว (ไม่มี chat) → ต้องใช้ /api/generate ไม่ใช่ /api/chat
    - ต้องใช้ template 3 ส่วนของมันเอง: ### Template / ### Example / ### Text
    - รับ **JSON schema** เป็น input ไม่ใช่คำสั่งภาษาธรรมชาติ
    - เอกสารระบุว่า "purely extractive — all text output is present as is in the original"
      → คัดลอกข้อความจากต้นทางเท่านั้น **สร้างชื่อหมวดใหม่เองไม่ได้**

ข้อสุดท้ายสำคัญมากกับงานเรา: open schema ที่เพิ่ง merge ไปต้องให้โมเดล *ตั้งชื่อหมวดเอง*
ซึ่งขัดกับธรรมชาติของ NuExtract โดยตรง — ทดสอบ 2 แบบเพื่อดูว่าใช้ได้แค่ไหน:

    A) schema แบบหมวดตายตัว   — เล่นตามจุดแข็งมัน (แต่กลับไปเป็น closed set ที่วัดแล้วว่าแย่)
    B) schema แบบ list อิสระ   — ขอ fact ล้วนๆ ไม่มีหมวด (ดูว่าจับข้อมูลได้กว้างแค่ไหน)
"""
import argparse
import asyncio
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
from memory_coverage_fixture import CASES  # noqa: E402

logging.disable(logging.CRITICAL)

GENERATE_URL = "http://localhost:11434/api/generate"
MODEL = "nuextract"

# แบบ A — หมวดตายตัวตาม 10 กลุ่มที่สำรวจไว้ (เล่นตามจุดแข็ง NuExtract)
SCHEMA_FIXED = {
    "สุขภาพ": [], "ครอบครัว": [], "วันสำคัญ": [], "ข้อจำกัด": [], "ทักษะ": [],
    "ความเชื่อ": [], "เป้าหมาย": [], "กิจวัตร": [], "ประสบการณ์": [], "ของที่มี": [],
}

# แบบ B — ขอ fact ล้วนไม่มีหมวด
SCHEMA_FLAT = {"ข้อเท็จจริงเกี่ยวกับผู้ใช้": []}


def build_prompt(schema: dict, text: str) -> str:
    """template 3 ส่วนของ NuExtract — ไม่ใช่ chat format"""
    return (f"<|input|>\n### Template:\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n"
            f"### Text:\n{text}\n<|output|>\n")


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


async def extract(schema: dict, text: str) -> tuple:
    payload = {"model": MODEL, "prompt": build_prompt(schema, text),
               "stream": False, "options": {"temperature": 0}}
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(GENERATE_URL, json=payload, timeout=300) as r:
                data = await r.json()
        raw = data.get("response", "") or ""
    except Exception as e:
        return [], time.perf_counter() - t0, f"ERR {type(e).__name__}"
    dt = time.perf_counter() - t0

    # แปลงผลเป็นรายการ fact — NuExtract คืน JSON ตาม schema ที่ให้ไป
    try:
        obj = json.loads(raw.strip())
    except Exception:
        import re as _re
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if not m:
            return [], dt, raw[:60]
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return [], dt, raw[:60]

    facts = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list):
                facts += [{"category": k, "text": str(x).strip()}
                          for x in v if str(x).strip()]
            elif isinstance(v, str) and v.strip():
                facts.append({"category": k, "text": v.strip()})
    return facts, dt, raw[:60]


def remembered(must: list, facts: list) -> bool:
    blob = " ".join(f["text"] for f in facts)
    return any(m in blob for m in must)


async def run(schema: dict, label: str) -> dict:
    rows, secs = [], []
    for text, must, group, note in CASES:
        facts, dt, _ = await extract(schema, text)
        secs.append(dt)
        rows.append((group, text, remembered(must, facts), facts, note))
    return {"label": label, "rows": rows, "secs": secs}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save")
    args = ap.parse_args()

    print("=" * 96)
    print(" NuExtract 3.8B — โมเดลที่ออกแบบมาเพื่อ extraction โดยเฉพาะ")
    print(f" เคส {len(CASES)} (ชุดเดียวกับที่วัดโมเดลอื่น)")
    print(" ⚠️ ใช้ /api/generate + template ของมันเอง ไม่ใช่ chat format")
    print("=" * 96)

    out = {}
    for key, schema, label in [("fixed", SCHEMA_FIXED, "A: schema หมวดตายตัว 10 หมวด"),
                               ("flat", SCHEMA_FLAT, "B: schema แบน (ไม่มีหมวด)")]:
        print(f"\n กำลังรัน {label} ...")
        t0 = time.perf_counter()
        out[key] = await run(schema, label)
        print(f"   เสร็จใน {time.perf_counter() - t0:.0f}s")

    print("\n" + "=" * 96)
    print(f" {'แบบ':<30} {'จำได้':>10} {'ช่วง 95%':>13} {'แต่ง':>7} {'latency':>9}")
    print("-" * 96)
    for key in out:
        rows = out[key]["rows"]
        ok = sum(1 for r in rows if r[2])
        lo, hi = wilson(ok, len(rows))
        tot = hal = 0
        for r in rows:
            toks = set(memory._keywords(r[1], expand=False))
            for f in r[3]:
                tot += 1
                ft = set(memory._keywords(f["text"], expand=False))
                if ft and not (ft & toks):
                    hal += 1
        med = statistics.median(out[key]["secs"])
        print(f" {out[key]['label']:<30} {ok:>4}/{len(rows):<4} {lo*100:>5.0f}-{hi*100:<5.0f}%"
              f" {hal*100//tot if tot else 0:>5}% {med:>8.1f}s")
    print("=" * 96)

    print("\n ตัวอย่างผลจากแบบที่ดีกว่า:")
    best = max(out, key=lambda k: sum(1 for r in out[k]["rows"] if r[2]))
    for r in out[best]["rows"][:8]:
        mark = "OK  " if r[2] else "MISS"
        print(f"   {mark} {r[1][:34]:<36} {[(f['category'], f['text']) for f in r[3]][:2]}")

    if args.save:
        json.dump({k: {"label": v["label"],
                       "rows": [{"group": r[0], "text": r[1], "ok": r[2],
                                 "facts": r[3], "note": r[4]} for r in v["rows"]],
                       "median_s": statistics.median(v["secs"])}
                   for k, v in out.items()},
                  open(args.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n เซฟผลไว้ที่ {args.save}")


if __name__ == "__main__":
    asyncio.run(main())
