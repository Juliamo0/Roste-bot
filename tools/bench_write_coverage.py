"""วัด baseline: write path จำข้อมูลผู้ใช้ได้กี่ % และ **ตกด่านไหน**

ตอบคำถาม "รูมีกี่รู" ที่ผู้ใช้ถาม — และสำคัญกว่านั้นคือ **รูอยู่ตรงไหน**
เพราะการรู้ว่า "จำได้ 30%" ไม่บอกว่าต้องแก้อะไร แต่ "ตกด่าน 1 ไป 60%" บอกได้ทันที

วัดแยก 4 ด่านตามลำดับจริงของ write path (chat.auto_remember):

    ด่าน 1  should_try_extract      กรองหยาบด้วยคำใบ้ 20 คำ (ไม่เรียก LLM)
    ด่าน 2  โมเดลสกัด               ต้องเลือกหมวดจาก closed set 7 หมวด
    ด่าน 3  parse_extracted_facts   หมวดนอกลิสต์ → None
    ด่าน 4  add_fact                กันซ้ำ + supersede + เพดาน

ข้อมูลที่ตกด่านไหนก็ตาม = ผู้ใช้บอกแล้วแต่บอทจำไม่ได้

⚠️ ด่าน 2 เรียก LLM จริง (ผลแกว่ง) → รองรับ --rounds และรายงาน Wilson CI
⚠️ ไม่แตะความจำผู้ใช้จริงเลย — ทดสอบ add_fact บน dict ในหน่วยความจำ
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
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

import memory  # noqa: E402
from memory_coverage_fixture import CASES, GROUPS, SUPPORTED_GROUPS  # noqa: E402
from ollama_client import MODEL, OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


async def extract(text: str) -> list:
    """ด่าน 2+3 — เรียกโมเดลสกัดจริง แล้ว parse ตามเส้นทาง production"""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": memory.build_extract_prompt(text)}],
        "stream": False, "think": False,
        "options": {"temperature": 0.2},
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
                data = await r.json()
        raw = data.get("message", {}).get("content", "") or ""
    except Exception:
        return []
    return memory.parse_extracted_facts(raw)


def remembered(must: list, facts: list) -> bool:
    """ข้อมูลนี้ถูกจำไว้ไหม — เทียบแบบหลวมที่สุด (substring ตัวใดตัวหนึ่ง)

    วัด "จำได้ไหม" ไม่ใช่ "เขียนเหมือนเป๊ะไหม" — ไม่ลงโทษระบบเรื่องการใช้คำต่างกัน
    """
    blob = " ".join(f["text"] if isinstance(f, dict) else str(f) for f in facts)
    return any(m in blob for m in must)


async def run_round(verbose: bool) -> list:
    """คืนผลรายเคส: (กลุ่ม, ข้อความ, ผ่านด่าน1, สกัดได้, จำได้, หมวดที่ได้)"""
    rows = []
    for text, must, group, note in CASES:
        gate = memory.should_try_extract(text)
        facts, kept = [], []
        if gate:
            facts = await extract(text)
            # ด่าน 4 — add_fact จริง (บน dict ในหน่วยความจำ ไม่แตะไฟล์)
            mem = {"facts": []}
            for f in facts:
                memory.add_fact(mem, f["text"], f.get("category"))
            kept = [f for f in mem["facts"] if not f.get("superseded")]
        ok = remembered(must, kept)
        cats = [f.get("category") for f in facts]
        rows.append((group, text, gate, bool(facts), ok, cats, must, note))
        if verbose:
            mark = "✅" if ok else ("⛔ด่าน1" if not gate else ("⛔ด่าน2" if not facts else "❌"))
            print(f"  {mark} [{group}] {text[:38]:<40} {cats}")
    return rows


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--save", help="เซฟผลดิบเป็น json ไว้เทียบรอบหลัง")
    args = ap.parse_args()

    print("=" * 100)
    print(" baseline: write path จำข้อมูลผู้ใช้ได้กี่ % และตกด่านไหน")
    print(f" เคส {len(CASES)} · กลุ่มข้อมูล {len(GROUPS)} · รอบ {args.rounds}"
          f" → n = {len(CASES) * args.rounds}")
    print(f" กลุ่มที่ระบบมีหมวดรองรับ: {sorted(SUPPORTED_GROUPS)} (ที่เหลือไม่มี)")
    print("=" * 100)

    t0 = time.perf_counter()
    all_rows = []
    for r in range(args.rounds):
        print(f"\n รอบ {r + 1}/{args.rounds} (เรียกโมเดล {sum(1 for c in CASES if memory.should_try_extract(c[0]))} ครั้ง)...")
        all_rows += await run_round(args.verbose)
    secs = time.perf_counter() - t0

    n = len(all_rows)
    gate_pass = sum(1 for r in all_rows if r[2])
    extracted = sum(1 for r in all_rows if r[3])
    ok = sum(1 for r in all_rows if r[4])

    print("\n" + "=" * 100)
    print(" ข้อมูลหายที่ด่านไหน (สะสม)")
    print("-" * 100)
    lo, hi = wilson(ok, n)
    print(f" ทั้งหมด                       {n:>4} เคส")
    print(f" ผ่านด่าน 1 (should_try_extract) {gate_pass:>4}  ({gate_pass/n*100:>3.0f}%)"
          f"   ← ตกที่นี่ {n - gate_pass} เคส ไม่ถึงโมเดลเลย")
    print(f" ด่าน 2 สกัดได้อย่างน้อย 1 fact  {extracted:>4}  ({extracted/n*100:>3.0f}%)"
          f"   ← ตกเพิ่ม {gate_pass - extracted} เคส")
    print(f" **จำได้ถูกต้องจริง**           {ok:>4}  ({ok/n*100:>3.0f}%)"
          f"   ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%")
    print("=" * 100)

    # แยกตามกลุ่ม — บอกว่ากลุ่มไหนพังหนักสุด
    print("\n แยกตามกลุ่มข้อมูล:")
    print(f" {'กลุ่ม':<14} {'ผ่านด่าน1':>10} {'สกัดได้':>9} {'จำได้':>9}   หมายเหตุ")
    print("-" * 100)
    by = collections.defaultdict(list)
    for r in all_rows:
        by[r[0]].append(r)
    for g in sorted(by, key=lambda x: sum(1 for r in by[x] if r[4])):
        rs = by[g]
        gp = sum(1 for r in rs if r[2])
        ex = sum(1 for r in rs if r[3])
        okg = sum(1 for r in rs if r[4])
        tag = "(มีหมวดรองรับ)" if g in SUPPORTED_GROUPS else ""
        print(f" {g:<14} {gp:>4}/{len(rs):<5} {ex:>4}/{len(rs):<4} {okg:>4}/{len(rs):<4}   {tag}")

    # แยกตามลักษณะสำนวน — บอกว่าสำนวนแบบไหนพัง
    print("\n แยกตามลักษณะสำนวน:")
    byn = collections.defaultdict(list)
    for r in all_rows:
        key = "ปฏิเสธ" if "ปฏิเสธ" in r[7] else (
            "ไม่มีสรรพนาม" if "ไม่มีสรรพนาม" in r[7] else (
                "พูดถึงคนอื่น" if "คนอื่น" in r[7] else "มีสรรพนาม"))
        byn[key].append(r)
    for k in sorted(byn, key=lambda x: sum(1 for r in byn[x] if r[4]) / len(byn[x])):
        rs = byn[k]
        gp = sum(1 for r in rs if r[2])
        okk = sum(1 for r in rs if r[4])
        print(f"   {k:<16} ผ่านด่าน1 {gp:>3}/{len(rs):<4}  จำได้ {okk:>3}/{len(rs):<4}"
              f" ({okk/len(rs)*100:>3.0f}%)")

    # หมวดที่โมเดลเลือกใช้จริง
    cats = collections.Counter(c for r in all_rows for c in r[5] if c)
    none_n = sum(1 for r in all_rows for c in r[5] if c is None)
    print(f"\n หมวดที่โมเดลเลือกใช้ (จาก 7 หมวดที่มี):")
    for c, v in cats.most_common():
        print(f"   {v:>4}x {c}")
    if none_n:
        print(f"   {none_n:>4}x (ไม่มีหมวด — หลุด closed set)")

    print(f"\n เวลารวม {secs:.0f}s")

    if args.save:
        json.dump([{"group": r[0], "text": r[1], "gate": r[2], "extracted": r[3],
                    "ok": r[4], "cats": r[5], "must": r[6], "note": r[7]}
                   for r in all_rows],
                  open(args.save, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f" เซฟผลดิบไว้ที่ {args.save}")


if __name__ == "__main__":
    asyncio.run(main())
