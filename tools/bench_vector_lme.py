"""วัด keyword vs vector บน LongMemEval — เงื่อนไขเดียวกับที่เปเปอร์ทดสอบ

ที่มา: ทดสอบ 3 optimization ของเปเปอร์แล้วไม่ช่วยเลยสักข้อ (340 -> 316/341/341)
วินิจฉัยว่าเป็นเพราะเปเปอร์วัดกับ **embedding** ส่วนเราใช้ **keyword count**
ไฟล์นี้พิสูจน์ข้อวินิจฉัยนั้น — ถ้าถูก vector ควรดีกว่า keyword ชัดเจน

⚠️ ใช้ /api/embed แบบ **batch** ไม่ใช่ /api/embeddings ทีละอัน
   วัดแล้ว: ทีละอัน 1.16s/session -> ครบชุด 8.6 ชั่วโมง (ทำไม่ไหว)
            batch 20 อัน 0.061s/session -> ครบชุด ~0.4 ชั่วโมง (เร็วขึ้น 19 เท่า)

⚠️ วัด **retrieval ล้วน** ไม่เรียก LLM rerank — เพราะ rerank ต้องยิง LLM ต่อคำถาม
   ซึ่งจะกลายเป็นหลายชั่วโมงอีก และเราต้องการเทียบ *วิธีให้คะแนน* ตรงๆ
"""
import argparse
import asyncio
import io
import json
import logging
import math
import os
import pathlib
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

import memory  # noqa: E402
from bench_paper_opts import build, wilson  # noqa: E402

logging.disable(logging.CRITICAL)

DATA = "tools/data/longmemeval_s.json"
EMBED_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3"
BATCH = 32


async def embed_many(texts: list) -> list:
    """embed หลายข้อความในครั้งเดียว — คืน list ของเวกเตอร์ (None ถ้าพลาด)"""
    out = []
    async with aiohttp.ClientSession() as sess:
        for i in range(0, len(texts), BATCH):
            chunk = texts[i:i + BATCH]
            try:
                async with sess.post(EMBED_URL,
                                     json={"model": EMBED_MODEL, "input": chunk},
                                     timeout=600) as r:
                    j = await r.json()
                out += j.get("embeddings") or [None] * len(chunk)
            except Exception:
                out += [None] * len(chunk)
    return out


def cosine(a, b) -> float:
    if not a or not b:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else -1.0


def keyword_rank(S: list, question: str) -> list:
    """จัดอันดับด้วย keyword count — วิธีที่ระบบเราใช้จริง"""
    words = memory._keywords(question)
    scored = [(sum(1 for w in words if w in s["text"]), i) for i, s in enumerate(S)]
    scored.sort(key=lambda x: -x[0])
    return [i for _, i in scored]


async def run_case(case: dict, mode: str) -> bool:
    S = build(case, False, False)
    if not S:
        return False
    gold = set(case.get("answer_session_ids") or [])

    if mode == "keyword":
        order = keyword_rank(S, case["question"])
    else:
        vecs = await embed_many([s["text"] for s in S])
        qv = (await embed_many([case["question"]]))[0]
        scored = [(cosine(qv, v), i) for i, v in enumerate(vecs)]
        scored.sort(key=lambda x: -x[0])
        order = [i for _, i in scored]
        if mode == "hybrid":
            # รวมอันดับสองวิธี (reciprocal rank fusion แบบง่าย)
            kw = keyword_rank(S, case["question"])
            rr = {}
            for rank, i in enumerate(order):
                rr[i] = rr.get(i, 0) + 1.0 / (60 + rank)
            for rank, i in enumerate(kw):
                rr[i] = rr.get(i, 0) + 1.0 / (60 + rank)
            order = [i for i, _ in sorted(rr.items(), key=lambda x: -x[1])]

    return S[order[0]]["_sid"] in gold if order else False


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="สุ่มกี่ข้อต่อชนิด (0 = ทั้งหมด)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--modes", default="keyword,vector,hybrid")
    args = ap.parse_args()

    if not os.path.exists(DATA):
        print(f"ไม่พบ {DATA} — รัน tools/fetch_longmemeval.py ก่อน")
        return
    data = json.load(open(DATA, encoding="utf-8"))
    types = ["single-session-preference", "single-session-user",
             "single-session-assistant", "knowledge-update",
             "multi-session", "temporal-reasoning"]

    rng = random.Random(args.seed)
    sel = {}
    for t in types:
        cs = [x for x in data if x["question_type"] == t]
        sel[t] = rng.sample(cs, min(args.limit, len(cs))) if args.limit else cs

    n_total = sum(len(v) for v in sel.values())
    print("=" * 100)
    print(" keyword vs vector บน LongMemEval — เงื่อนไขเดียวกับที่เปเปอร์ทดสอบ")
    print(f" {n_total} ข้อ" + (f" (สุ่ม {args.limit}/ชนิด seed={args.seed})" if args.limit else ""))
    print("=" * 100)

    modes = [m.strip() for m in args.modes.split(",")]
    results = {}
    for mode in modes:
        t0 = time.perf_counter()
        print(f"\n กำลังรัน {mode} ...")
        per = {}
        for t in types:
            ok = 0
            for c in sel[t]:
                ok += await run_case(c, mode)
            per[t] = (ok, len(sel[t]))
        results[mode] = per
        print(f"   เสร็จใน {time.perf_counter() - t0:.0f}s")

    print("\n" + "=" * 100)
    head = f" {'ชนิดคำถาม':<30}"
    for m in modes:
        head += f" {m:>14}"
    print(head)
    print("-" * 100)
    for t in types:
        row = f" {t:<30}"
        for m in modes:
            ok, n = results[m][t]
            row += f" {ok:>6}/{n:<7}"
        print(row)
    print("-" * 100)
    row = f" {'รวม':<30}"
    for m in modes:
        ok = sum(results[m][t][0] for t in types)
        n = sum(results[m][t][1] for t in types)
        lo, hi = wilson(ok, n)
        row += f" {ok:>6}/{n:<7}"
    print(row)
    for m in modes:
        ok = sum(results[m][t][0] for t in types)
        n = sum(results[m][t][1] for t in types)
        lo, hi = wilson(ok, n)
        print(f"   {m:<12} {ok}/{n} = {ok/n*100:.0f}%  ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
