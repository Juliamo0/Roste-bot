"""Phase 1: เทียบ 5 วิธีแก้ความขัดแย้งที่ชั้น retrieval

    M0  เกณฑ์คะแนนขั้นต่ำ (ไม่แก้ความขัดแย้ง แค่ตัด noise)
    M1  baseline ปัจจุบัน
    M2  recency-wins ตอน recall
    M3  deterministic supersede ตอนเขียน
    M4  LLM ตัดสินตอนเขียน (ADD/UPDATE/NOOP)   — ต้องมี Ollama, ใส่ --with-m4

M0-M3 ไม่เรียกโมเดล → deterministic รันซ้ำได้ผลเท่าเดิม ไม่ต้องใช้ Wilson CI
M4 เรียกโมเดล → ผลแกว่ง ต้องรันหลายรอบ (--rounds) แล้วรายงาน Wilson CI

⚠️ วิธีอ่านผล (สำคัญกว่าตัวเลข):
   ห้ามดูค่าเฉลี่ยรวมอย่างเดียว — trade-off อยู่ที่ dynamic ขึ้นแล้ว historical/static/
   conditional ต้องไม่ตก วิธีที่ได้ dynamic 6/6 แต่ historical 0/6 = ใช้ไม่ได้
   (MEMORY_EXPERIMENTS §4: "metric ที่วัดไม่ได้ผลแยกวิธี = ไร้ประโยชน์")
"""
import argparse
import asyncio
import math
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging  # noqa: E402

import conflict_proto as proto  # noqa: E402
from memory_conflict_fixture import ALL_SETS, SUMMARIES  # noqa: E402

logging.disable(logging.CRITICAL)


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    """ช่วงความเชื่อมั่น 95% แบบ Wilson — เหมือน bench_memory_pipeline.py:172

    MEMORY_EXPERIMENTS §1 บันทึกไว้ว่าเคยเกือบเลือกวิธีผิดเพราะอ่านตัวเลขที่ดูสูงกว่า
    โดยไม่ดูช่วง — ช่วงซ้อนทับ = แยกไม่ออก ไม่ใช่ "ดีกว่า"
    """
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def judge(lines: list, must: list, forbid: list) -> tuple:
    blob = "\n".join(lines)
    bad = []
    if must and not any(w in blob for w in must):
        bad.append(f"ไม่เจอ {must}")
    if forbid:
        leaked = [w for w in forbid if w in blob]
        if leaked:
            bad.append(f"มีค่าที่ไม่ควรมี {leaked}")
    return (not bad), bad


async def m4_consolidate(summaries: list) -> list:
    """M4: ให้โมเดลตัดสินทีละ summary ว่าทับของเก่าอันไหน (จำลอง write path)"""
    import aiohttp
    from ollama_client import MODEL, OLLAMA_URL

    out = [dict(e) for e in summaries]
    for i, new in enumerate(out):
        prior = [(j, e) for j, e in enumerate(out[:i]) if not e.get("superseded")]
        if not prior:
            continue
        cands = [e["text"] for _, e in prior]
        payload = {
            "model": MODEL,
            "messages": [{"role": "user",
                          "content": proto.build_conflict_prompt(new["text"], cands)}],
            "stream": False, "think": False,
            "options": {"temperature": 0},
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
                    data = await r.json()
            raw = data.get("message", {}).get("content", "") or ""
        except Exception:
            continue                                    # เรียกไม่ได้ = NOOP (fail-safe)
        d = proto.parse_conflict_json(raw)
        if d["action"] != "UPDATE":
            continue
        for idx in d["replaces"]:
            if 0 <= idx < len(prior):
                out[prior[idx][0]]["superseded"] = True
    return out


async def m5_consolidate(summaries: list) -> list:
    """M5 = M3 ก่อน แล้วถาม LLM เฉพาะคู่ที่ M3 ตัดสินไม่ได้ (hybrid)

    ต่างจาก M4 ตรงที่ LLM เห็น candidate น้อยกว่ามาก และเห็นเฉพาะคู่ที่มีสัญญาณ
    การเปลี่ยนแปลงจริง — ลดโอกาสที่โมเดลจะเผลอ supersede กับดัก static
    (M4 เอา "ทำงานสายไอที" ไปทับด้วย "เป็นโปรแกรมเมอร์" เพราะเห็นทุกคู่พร้อมกัน)
    """
    import aiohttp
    from ollama_client import MODEL, OLLAMA_URL

    out = proto.m3_consolidate(summaries)        # ด่าน 1: deterministic
    pairs = proto.m3_undecided_pairs(summaries)  # คู่ที่ยังตัดสินไม่ได้

    by_new = {}
    for old_i, new_i in pairs:
        by_new.setdefault(new_i, []).append(old_i)

    n_llm = 0
    for new_i, old_idxs in by_new.items():
        cands = [out[i]["text"] for i in old_idxs]
        payload = {
            "model": MODEL,
            "messages": [{"role": "user",
                          "content": proto.build_conflict_prompt(out[new_i]["text"], cands)}],
            "stream": False, "think": False,
            "options": {"temperature": 0},
        }
        n_llm += 1
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
                    data = await r.json()
            raw = data.get("message", {}).get("content", "") or ""
        except Exception:
            continue
        d = proto.parse_conflict_json(raw)
        if d["action"] != "UPDATE":
            continue
        for k in d["replaces"]:
            if 0 <= k < len(old_idxs):
                out[old_idxs[k]]["superseded"] = True
    return out, n_llm


def run_static_methods(methods: list) -> dict:
    """รันวิธีที่ไม่เรียกโมเดล — ผลนิ่ง รันรอบเดียวพอ"""
    results = {}
    for label, fn in methods:
        per_set = {}
        for set_name, cases in ALL_SETS:
            ok_n = 0
            for q, whose, must, forbid in cases:
                lines = fn(q)
                ok, _ = judge(lines, must, forbid)
                ok_n += ok
            per_set[set_name] = (ok_n, len(cases))
        results[label] = per_set
    return results


def print_table(results: dict, title: str):
    print(f"\n{'=' * 104}\n {title}\n{'=' * 104}")
    set_names = [s for s, _ in ALL_SETS]
    head = f" {'วิธี':<30}"
    for s in set_names:
        head += f" {s:>13}"
    head += f" {'รวม':>13}"
    print(head)
    print("-" * 104)
    for label, per_set in results.items():
        row = f" {label:<30}"
        tot_ok = tot_n = 0
        for s in set_names:
            ok, n = per_set[s]
            tot_ok += ok
            tot_n += n
            row += f" {ok:>6}/{n:<6}"
        lo, hi = wilson(tot_ok, tot_n)
        row += f" {tot_ok:>4}/{tot_n:<3}"
        print(row)
        print(f" {'':<30} {'':>13} {'':>13} {'':>13} ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%")
    print("=" * 104)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-m4", action="store_true", help="รวม M4/M5 (ต้องมี Ollama รันอยู่)")
    ap.add_argument("--min-score", type=int, default=2, help="เกณฑ์คะแนนขั้นต่ำของ M0")
    ap.add_argument("--rounds", type=int, default=1,
                    help="จำนวนรอบสำหรับวิธีที่เรียก LLM (M4/M5) — เพิ่ม n ให้ช่วงแคบลง")
    args = ap.parse_args()

    n_cases = sum(len(c) for _, c in ALL_SETS)
    print("=" * 104)
    print(" Phase 1 — เทียบวิธีแก้ความขัดแย้ง ที่ชั้น retrieval")
    print(f" fixture: {len(SUMMARIES)} summary, {n_cases} เคส ใน {len(ALL_SETS)} ชุด")
    print("=" * 104)

    methods = [
        ("M1 baseline (ปัจจุบัน)", lambda q: proto.m1_baseline(SUMMARIES, q)),
        (f"M0 เกณฑ์คะแนน >= {args.min_score}", lambda q: proto.m0_min_score(SUMMARIES, q, args.min_score)),
        ("M2 recency-wins", lambda q: proto.m2_recency_wins(SUMMARIES, q)),
        ("M3 deterministic supersede", lambda q: proto.m3_deterministic(SUMMARIES, q)),
    ]
    results = run_static_methods(methods)

    if args.with_m4:
        # วิธีที่เรียก LLM ต้องรันหลายรอบ — สะสมผลทุกรอบเข้าด้วยกันก่อนคิด CI
        # (ที่ temperature 0 ผลควรนิ่ง แต่ "ควร" ไม่ใช่ "แน่นอน" — วัดดีกว่าเชื่อ)
        acc = {}
        for rnd in range(args.rounds):
            tag = f" (รอบ {rnd + 1}/{args.rounds})" if args.rounds > 1 else ""
            print(f"\n กำลังให้โมเดลตัดสินความขัดแย้ง (M4){tag}...")
            c4 = await m4_consolidate(SUMMARIES)
            n4 = sum(1 for e in c4 if e.get("superseded"))

            print(f" กำลังรัน M5 (M3 ก่อน แล้วถาม LLM เฉพาะคู่ที่คัดแล้ว){tag}...")
            c5, n_llm = await m5_consolidate(SUMMARIES)
            n5 = sum(1 for e in c5 if e.get("superseded"))
            print(f"   M4 supersede {n4} อัน (เรียก LLM {len(SUMMARIES) - 1} ครั้ง)  |  "
                  f"M5 supersede {n5} อัน (เรียก LLM {n_llm} ครั้ง)")

            def mk(pool_src):
                def f(q):
                    pool = (pool_src if proto.wants_history(q)
                            else [e for e in pool_src if not e.get("superseded")])
                    return proto._score_and_filter(pool, q)
                return f

            for label, src in (("M4 LLM ตัดสินตอนเขียน", c4), ("M5 hybrid (M3→LLM)", c5)):
                r = run_static_methods([(label, mk(src))])[label]
                bucket = acc.setdefault(label, {})
                for s, (ok, n) in r.items():
                    pok, pn = bucket.get(s, (0, 0))
                    bucket[s] = (pok + ok, pn + n)
        results.update(acc)

        # วิธี deterministic ไม่แกว่ง — คูณ n ให้เท่ากันเพื่อเทียบ CI อย่างเป็นธรรม
        if args.rounds > 1:
            for label in list(results):
                if label.startswith(("M4", "M5")):
                    continue
                results[label] = {s: (ok * args.rounds, n * args.rounds)
                                  for s, (ok, n) in results[label].items()}

    print_table(results, "ผลรวม — แยกตามชนิดความขัดแย้ง")

    print("\n⚠️ อ่านผล: ดูรายชุด ไม่ใช่แค่ค่ารวม")
    print("   dynamic ต้องขึ้น  |  historical/static/conditional ต้องไม่ตก")
    print("   ช่วง 95% ซ้อนทับ = แยกไม่ออกทางสถิติ ไม่ใช่ 'ดีกว่า'")


if __name__ == "__main__":
    asyncio.run(main())
