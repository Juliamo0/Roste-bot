"""หา "น้ำหนัก vector : keyword" ที่ดีที่สุด — วัดทั้ง 2 ชุดข้อมูล

ที่มา: วัดแล้วได้ผลขัดกัน จึงต้องหาว่าน้ำหนักไหนดีทั้งคู่ (ไม่ใช่เลือกข้างจากชุดเดียว)
    ข้อมูลไทยของเรา (n=84):  KV รวมสองชั้น 72/84 **ชนะ** vector ล้วน 57/84
    LongMemEval (n=150):     vector ล้วน 134/150 **ชนะ** hybrid ถ่วงเท่ากัน 112/150

สมมติฐาน: hybrid ที่ถ่วง *เท่ากัน* ไม่เหมาะเมื่อสองฝั่งคุณภาพต่างกันมาก
-> ถ่วงให้ vector มากกว่าน่าจะได้ทั้งสองโลก

วิธี: weighted reciprocal rank fusion
    score(doc) = w_vec/(k+rank_vec) + (1-w_vec)/(k+rank_kw)
    w_vec=1.0 -> vector ล้วน · w_vec=0.5 -> ถ่วงเท่ากัน (ที่ลองแล้ว) · w_vec=0.0 -> keyword ล้วน

⚠️ ต้องดีทั้ง 2 ชุดถึงจะ merge — ชุดเดียวเคยหลอกเรามาแล้ว (fixture Phase 1)
⚠️ ข้อมูลไทยมี 55 summary ที่ผ่าน pipeline สรุปแล้ว (ใกล้ production จริง)
   ส่วน LongMemEval เป็น session ดิบยาว — ต่างกันโดยธรรมชาติ
"""
import argparse
import asyncio
import io
import json
import logging
import os
import pathlib
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import memory  # noqa: E402
from bench_paper_opts import build, wilson  # noqa: E402
from bench_vector_lme import cosine, embed_many, keyword_rank  # noqa: E402

logging.disable(logging.CRITICAL)

LME = "tools/data/longmemeval_s.json"
REAL_UID = 434893254576701450
RRF_K = 60


def fuse(vec_order: list, kw_order: list, w_vec: float) -> list:
    """weighted RRF — คืนลำดับ index ที่รวมสองฝั่งแล้ว"""
    score = {}
    for rank, i in enumerate(vec_order):
        score[i] = score.get(i, 0.0) + w_vec / (RRF_K + rank)
    for rank, i in enumerate(kw_order):
        score[i] = score.get(i, 0.0) + (1.0 - w_vec) / (RRF_K + rank)
    return [i for i, _ in sorted(score.items(), key=lambda x: -x[1])]


# ── ชุดที่ 1: LongMemEval ─────────────────────────────────────────────────────

async def run_lme(weights: list, limit: int, seed: int) -> dict:
    data = json.load(open(LME, encoding="utf-8"))
    types = ["single-session-preference", "single-session-user",
             "single-session-assistant", "knowledge-update",
             "multi-session", "temporal-reasoning"]
    rng = random.Random(seed)
    cases = []
    for t in types:
        cs = [x for x in data if x["question_type"] == t]
        cases += rng.sample(cs, min(limit, len(cs))) if limit else cs

    tally = {w: 0 for w in weights}
    for c in cases:
        S = build(c, False, False)
        if not S:
            continue
        gold = set(c.get("answer_session_ids") or [])
        vecs = await embed_many([s["text"] for s in S])
        qv = (await embed_many([c["question"]]))[0]
        vec_order = [i for _, i in sorted(
            ((cosine(qv, v), i) for i, v in enumerate(vecs)), key=lambda x: -x[0])]
        kw_order = keyword_rank(S, c["question"])
        for w in weights:
            order = fuse(vec_order, kw_order, w)
            if order and S[order[0]]["_sid"] in gold:
                tally[w] += 1
    return {"tally": tally, "n": len(cases)}


# ── ชุดที่ 2: ความจำไทยจริง (ใกล้ production) ────────────────────────────────

async def run_thai(weights: list) -> dict:
    """ใช้ชุดคำถามคำพ้องที่สร้างจาก summary จริงอย่างเป็นระบบ (bench_vocab_gap)"""
    from thai_recall_cases import load as load_thai
    summaries = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))["summaries"]
    cases = load_thai(summaries)

    S = [{"text": e["text"], "date": e.get("date")} for e in summaries]
    doc_vecs = await embed_many([s["text"] for s in S])

    tally = {w: 0 for w in weights}
    for q, must in cases:
        qv = (await embed_many([q]))[0]
        vec_order = [i for _, i in sorted(
            ((cosine(qv, v), i) for i, v in enumerate(doc_vecs)), key=lambda x: -x[0])]
        kw_order = keyword_rank(S, q)
        whose = memory.guess_owner(q)
        for w in weights:
            order = fuse(vec_order, kw_order, w)[:5]
            lines = memory.filter_by_owner([S[i]["text"] for i in order], whose)
            blob = "\n".join(lines)
            if any(m in blob for m in must):
                tally[w] += 1
    return {"tally": tally, "n": len(cases)}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25, help="ข้อ/ชนิด สำหรับ LongMemEval")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--weights", default="0.0,0.3,0.5,0.7,0.85,1.0")
    args = ap.parse_args()

    weights = [float(x) for x in args.weights.split(",")]

    print("=" * 100)
    print(" หาน้ำหนัก vector:keyword ที่ดีที่สุด — ต้องดีทั้ง 2 ชุดถึงจะใช้ได้")
    print(" w=1.0 คือ vector ล้วน · w=0.5 คือถ่วงเท่ากัน · w=0.0 คือ keyword ล้วน")
    print("=" * 100)

    print("\n [1/2] ความจำไทยจริง (55 summary ผ่าน pipeline สรุปแล้ว — ใกล้ production)")
    thai = await run_thai(weights)
    print(f"       {thai['n']} คำถาม")

    print(f"\n [2/2] LongMemEval (session ดิบยาว — สุ่ม {args.limit}/ชนิด)")
    lme = await run_lme(weights, args.limit, args.seed)
    print(f"       {lme['n']} คำถาม")

    print("\n" + "=" * 100)
    print(f" {'w_vec':<8} {'ไทย (production-like)':>28} {'LongMemEval':>28}")
    print("-" * 100)
    for w in weights:
        a, na = thai["tally"][w], thai["n"]
        b, nb = lme["tally"][w], lme["n"]
        la, ha = wilson(a, na)
        lb, hb = wilson(b, nb)
        tag = ""
        if w == 1.0:
            tag = "  (vector ล้วน)"
        elif w == 0.5:
            tag = "  (ถ่วงเท่ากัน)"
        elif w == 0.0:
            tag = "  (keyword ล้วน)"
        print(f" {w:<8} {a:>6}/{na:<4} {la*100:>4.0f}-{ha*100:<4.0f}%"
              f" {b:>10}/{nb:<4} {lb*100:>4.0f}-{hb*100:<4.0f}%{tag}")
    print("=" * 100)

    best_thai = max(weights, key=lambda w: thai["tally"][w])
    best_lme = max(weights, key=lambda w: lme["tally"][w])
    print(f"\n ดีสุดฝั่งไทย: w={best_thai}  ·  ดีสุดฝั่ง LongMemEval: w={best_lme}")
    # หาน้ำหนักที่ดีทั้งคู่ (rank รวมต่ำสุด)
    rank_t = sorted(weights, key=lambda w: -thai["tally"][w])
    rank_l = sorted(weights, key=lambda w: -lme["tally"][w])
    combo = min(weights, key=lambda w: rank_t.index(w) + rank_l.index(w))
    print(f" สมดุลที่สุดเมื่อดูทั้งสองชุด: w={combo}")


if __name__ == "__main__":
    asyncio.run(main())
