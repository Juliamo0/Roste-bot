"""ตัดสินส่วน "ค้น": keyword vs vector — วัดทั้งความแม่นและ latency ที่ n สูงพอ

ทำไมต้องมีไฟล์นี้ทั้งที่มี bench_memory_vector แล้ว: ตัวนั้นวัดที่ n=17 แล้วได้ keyword
16/17 กับ vector 17/17 ต่างกัน 1 เคส ซึ่ง *น้อยเกินกว่าจะสรุปว่าต่างจริง* — เป็นกับดัก
เดียวกับตอน pass^8 ที่อันดับสลับกันทุกรอบจนเกือบเลือกผิด

รอบนี้แก้ 3 อย่าง:
  1. เพิ่มชุดคำพ้องอีก 10 เคส (SYNONYM_CASES) — เป็นตัวแปรที่กำลังตัดสินโดยตรง
     ชุดเดิมมีเคสคำพ้องแค่ 1-2 อัน จึงวัดจุดต่างของสองวิธีไม่ได้
  2. รันซ้ำหลายรอบ + Wilson CI — vector เรียก LLM rerank ผลจึงแกว่งได้ ต้องวัดซ้ำ
  3. วัด latency แยกทุกวิธี — vector แลกความแม่นด้วยการเรียก Ollama 2 รอบ
     (embedding + rerank) ถ้าช้ากว่ามากก็ต้องชั่งน้ำหนัก ไม่ใช่ดูแต่ % ผ่าน

ทั้ง 4 วิธีกรองฝั่งเจ้าของเหมือนกันหมด — ตัวแปรที่เทียบคือ *วิธีค้น* ล้วนๆ
"""
import argparse
import asyncio
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

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import vectormemory as V  # noqa: E402
from memory_fixture import (  # noqa: E402
    CASES, HARD_CASES, SUMMARIES, SYNONYM_CASES,
)
from memory_tool_proto import (  # noqa: E402
    build_memory_block, filter_by_owner, guess_owner, has_owner_data,
)

TEST_UID = 999_888_777_666_551


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def judge(block: str, whose: str, must: list, forbid: list) -> bool:
    if whose == "none":
        return not block.strip()
    if must and not any(w in block for w in must):
        return False
    if forbid and any(w in block for w in forbid):
        return False
    return True


# ── 4 วิธีค้น (กรองฝั่งเหมือนกันหมด) ─────────────────────────────────────────

async def m_keyword(q: str):
    block, _ = build_memory_block(SUMMARIES, q)
    return block


async def m_vector(q: str):
    whose = guess_owner(q)
    hits = await V.query_conversation_memory(TEST_UID, q)
    return "\n".join(f"- {t}" for t in filter_by_owner(hits, whose))


async def m_kw_then_vec(q: str):
    """keyword ก่อน — ว่างค่อยเรียก vector (ประหยัดที่สุด)"""
    block, whose = build_memory_block(SUMMARIES, q)
    if block.strip() or not has_owner_data(SUMMARIES, whose):
        return block
    hits = await V.query_conversation_memory(TEST_UID, q)
    return "\n".join(f"- {t}" for t in filter_by_owner(hits, whose))


async def m_union(q: str):
    """รวมผลทั้งสองแล้วกรอง — แม่นสุดในทางทฤษฎี แต่ช้าสุดเพราะเรียก vector เสมอ"""
    whose = guess_owner(q)
    kb, _ = build_memory_block(SUMMARIES, q)
    hits = await V.query_conversation_memory(TEST_UID, q)
    vlines = [f"- {t}" for t in filter_by_owner(hits, whose)]
    seen, out = set(), []
    for ln in [x for x in kb.splitlines() if x.strip()] + vlines:
        key = ln.strip()
        if key not in seen:
            seen.add(key)
            out.append(ln)
    return "\n".join(out[:5])


METHODS = [
    ("keyword + กรอง", m_keyword),
    ("vector + กรอง", m_vector),
    ("keyword→vector (ว่างค่อยค้น)", m_kw_then_vec),
    ("union (รวมสองทาง)", m_union),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    sets = [("ปกติ", CASES), ("หิน", HARD_CASES), ("คำพ้อง", SYNONYM_CASES)]
    total_cases = sum(len(c) for _, c in sets)

    print("=" * 104)
    print(f" ตัดสินส่วน 'ค้น' — {total_cases} เคส × {args.reps} รอบ = "
          f"{total_cases * args.reps} ตัวอย่าง/วิธี")
    print(f" ชุด: ปกติ {len(CASES)} + หิน {len(HARD_CASES)} + คำพ้อง {len(SYNONYM_CASES)}")
    print(" ทุกวิธีกรองฝั่งเจ้าของเหมือนกัน — ตัวแปรที่เทียบคือวิธีค้นล้วนๆ")
    print("=" * 104)

    try:
        V._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    for s in SUMMARIES:
        await V.add_conversation_memory(TEST_UID, s)

    rows = []
    try:
        for label, fn in METHODS:
            ok = n = 0
            per_set = {name: [0, 0] for name, _ in sets}
            lat = []
            for sname, cases in sets:
                for q, whose, must, forbid in cases:
                    for _ in range(args.reps):
                        t0 = time.perf_counter()
                        try:
                            block = await fn(q)
                        except Exception:
                            block = ""
                        lat.append(time.perf_counter() - t0)
                        good = judge(block, whose, must, forbid)
                        ok += good
                        n += 1
                        per_set[sname][0] += good
                        per_set[sname][1] += 1
            lo, hi = wilson(ok, n)
            rows.append(dict(label=label, ok=ok, n=n, lo=lo, hi=hi,
                             sets={k: tuple(v) for k, v in per_set.items()},
                             lat=statistics.mean(lat),
                             p95=sorted(lat)[int(len(lat) * 0.95) - 1]))
            print(f"\n  【{label}】 {ok}/{n} ({ok/n*100:.0f}%)  ช่วง 95% [{lo*100:.0f}-{hi*100:.0f}%]")
            for sname, (a, b) in per_set.items():
                print(f"       {sname:<8} {a:>3}/{b:<4} ({a/max(b,1)*100:>3.0f}%)")
            print(f"       latency เฉลี่ย {statistics.mean(lat)*1000:.0f} ms  "
                  f"p95 {sorted(lat)[int(len(lat)*0.95)-1]*1000:.0f} ms")
    finally:
        try:
            V._client.delete_collection(f"convmem_{TEST_UID}")
        except Exception:
            pass

    print("\n" + "=" * 104)
    print(f" {'วิธี':<30} {'ผ่าน':>10} {'ช่วง 95%':>13} {'ปกติ':>8} {'หิน':>8} "
          f"{'คำพ้อง':>9} {'latency':>10}")
    print("-" * 104)
    for r in rows:
        s = r["sets"]
        print(f" {r['label']:<30} {r['ok']:>4}/{r['n']:<5} "
              f"[{r['lo']*100:>3.0f}-{r['hi']*100:>3.0f}%] "
              f"{s['ปกติ'][0]:>4}/{s['ปกติ'][1]:<3} {s['หิน'][0]:>4}/{s['หิน'][1]:<3} "
              f"{s['คำพ้อง'][0]:>4}/{s['คำพ้อง'][1]:<3} {r['lat']*1000:>8.0f}ms")
    print("=" * 104)

    print("\n เทียบรายคู่ (ช่วงไม่ซ้อนทับ = ต่างจริง):")
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            sep = "ต่างจริง" if a["lo"] > b["hi"] or b["lo"] > a["hi"] else "แยกไม่ออก"
            print(f"   {a['label']:<30} vs {b['label']:<30} {sep}")

    print("\n ⚖️ ราคาที่ต้องจ่าย: latency ต่างกันกี่เท่า")
    base = min(r["lat"] for r in rows)
    for r in rows:
        print(f"   {r['label']:<30} {r['lat']*1000:>7.0f} ms  ({r['lat']/base:.1f}x)")


if __name__ == "__main__":
    asyncio.run(main())
