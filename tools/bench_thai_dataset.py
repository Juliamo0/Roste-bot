"""วัด retrieval ด้วย **บทสนทนาไทยจากชุดข้อมูลสาธารณะ** ไม่ใช่คำถามที่ผมแต่งเอง

ที่มา: ผู้ใช้เสนอให้หาข้อมูล open จากอินเทอร์เน็ตมาใช้ — ดีกว่าให้ผมจำลองเอง
เพราะยิ่งผมเขียนคำถามเองเยอะ ยิ่งเสี่ยง selection bias (เคยพลาดมาแล้วใน C2)

ชุดข้อมูล: WangchanThaiInstruct Multi-turn (ThaiSyntheticQA, cc-by-sa-4.0)
    5,014 บทสนทนาไทยหลายเทิร์น · Finance/Legal
    445 บท (9%) มีผู้ใช้พูดถึงตัวเอง เช่น "ฉันชื่อนิก" "เงินเดือน 60,000" "เป็นพนักงานออฟฟิศ"

⚠️ ข้อจำกัดที่ต้องบอก:
  - เป็นบทถาม-ตอบเรื่องการเงิน/กฎหมาย ไม่ใช่บทคุยเล่นแบบที่รอสเต้เจอ
  - ข้อมูลส่วนตัวมีน้อย (9%) และมักเป็นบริบทของคำถาม ไม่ใช่ fact ถาวร
  - จึงใช้วัด "retrieval หาบทที่เกี่ยวข้องเจอไหม" ได้ แต่ไม่ได้แทนความจำจริงของผู้ใช้

วิธีสร้างเคส (อัตโนมัติ ไม่ผ่านดุลพินิจผม):
  1. เอาบทที่มีประโยคผู้ใช้พูดถึงตัวเอง
  2. ประโยคนั้น = "ความจำ" · เทิร์นถัดไปของผู้ใช้ = "คำถาม"
  3. distractor = บทอื่นที่สุ่มมา (จำลองความจำที่มีหลายเรื่อง)
"""
import argparse
import asyncio
import io
import json
import logging
import os
import pathlib
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import memory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from bench_vector_lme import cosine, embed_many, keyword_rank  # noqa: E402
from bench_weighted_hybrid import fuse  # noqa: E402

logging.disable(logging.CRITICAL)

DATA = "tools/data/thai_multiturn.jsonl"
PERS = re.compile(r"(ผม|ฉัน|ดิฉัน|หนู)\s*(ชื่อ|อยู่|ทำงาน|ชอบ|มี|เป็น|แพ้|เรียน|สนใจ)")


def build_cases(rows: list, n_distract: int, seed: int) -> list:
    """สร้างเคส: (คำถาม, ข้อความความจำที่ถูก, [ความจำทั้งหมด])"""
    rng = random.Random(seed)
    pool = []
    for r in rows:
        turns = [t for t in (r.get("Multi-turn") or []) if t.get("role") == "user"]
        if len(turns) < 2:
            continue
        first = turns[0].get("content", "").strip()
        if not PERS.search(first) or len(first) < 40:
            continue
        follow = turns[1].get("content", "").strip()
        if len(follow) < 15:
            continue
        pool.append((r["ID"], first[:400], follow[:200]))

    cases = []
    for i, (rid, mem_text, question) in enumerate(pool):
        others = [p for j, p in enumerate(pool) if j != i]
        if len(others) < n_distract:
            continue
        distract = rng.sample(others, n_distract)
        mems = [{"id": rid, "text": f"user_fact:{mem_text}"}]
        mems += [{"id": d[0], "text": f"user_fact:{d[1]}"} for d in distract]
        rng.shuffle(mems)
        cases.append({"question": question, "gold": rid, "mems": mems})
    return cases


async def run(cases: list, weights: list) -> dict:
    tally = {w: 0 for w in weights}
    for c in cases:
        texts = [m["text"] for m in c["mems"]]
        vecs = await embed_many(texts)
        qv = (await embed_many([c["question"]]))[0]
        vec_order = [i for _, i in sorted(
            ((cosine(qv, v), i) for i, v in enumerate(vecs)), key=lambda x: -x[0])]
        S = [{"text": t} for t in texts]
        kw_order = keyword_rank(S, c["question"])
        for w in weights:
            order = fuse(vec_order, kw_order, w)
            if order and c["mems"][order[0]]["id"] == c["gold"]:
                tally[w] += 1
    return tally


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    ap.add_argument("--distract", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--weights", default="0.0,0.3,0.5,0.7,0.85,1.0")
    args = ap.parse_args()

    if not os.path.exists(DATA):
        print(f"ไม่พบ {DATA} — ดาวน์โหลดจาก HuggingFace")
        print("  ThaiSyntheticQA/WangchanThaiInstruct_Multi-turn_Conversation_Dataset")
        return

    rows = [json.loads(l) for l in open(DATA, encoding="utf-8")]
    cases = build_cases(rows, args.distract, args.seed)
    if args.limit:
        cases = cases[:args.limit]
    weights = [float(x) for x in args.weights.split(",")]

    print("=" * 92)
    print(" วัดด้วยบทสนทนาไทยจากชุดข้อมูลสาธารณะ (WangchanThaiInstruct Multi-turn)")
    print(f" {len(cases)} เคส · ความจำ {args.distract + 1} อัน/เคส (1 ถูก + {args.distract} distractor)")
    print(" ⚠️ เป็นบทถาม-ตอบการเงิน/กฎหมาย ไม่ใช่บทคุยเล่น — วัด retrieval ไม่ใช่ความจำส่วนตัว")
    print("=" * 92)

    tally = await run(cases, weights)
    n = len(cases)
    print(f"\n {'w_vec':<10} {'เลือกถูก':>12} {'ช่วง 95%':>16}")
    print("-" * 92)
    for w in weights:
        lo, hi = wilson(tally[w], n)
        tag = {0.0: "  keyword ล้วน (ปัจจุบัน)", 0.5: "  ถ่วงเท่ากัน",
               1.0: "  vector ล้วน"}.get(w, "")
        print(f" {w:<10} {tally[w]:>5}/{n:<6} {lo*100:>6.0f}-{hi*100:<6.0f}%{tag}")
    print("=" * 92)

    best = max(weights, key=lambda w: tally[w])
    l0, h0 = wilson(tally[0.0], n) if 0.0 in tally else (0, 0)
    lb, hb = wilson(tally[best], n)
    print(f"\n ดีสุด: w={best} ({tally[best]}/{n})")
    if 0.0 in tally:
        ov = not (lb > h0 or l0 > hb)
        print(f" เทียบ keyword ล้วน: {'ซ้อนทับ = แยกไม่ออก' if ov else 'ต่างจริง ✅'}")


if __name__ == "__main__":
    asyncio.run(main())
