"""ชุดความจำ **จริง** ของ production แบบ **เปิด rerank** — ช่องสุดท้ายที่ยังไม่ได้วัด

ที่มา: ตาราง 3×3 (bench_write_x_read) ชี้ว่า summary × cosine ชนะ summary × bm25 ขาด
(68/90 vs 32/90 ช่วงไม่ซ้อนทับ) แต่ชุด **ความจำจริงของเรา** เป็นชุดเดียวที่ยังบอกกลับด้าน
(keyword 81% vs vector 78%) — และชุดนั้นวัดตอน **ปิด rerank**

production มี rerank อยู่จริง จึงต้องวัดชุดนี้แบบเปิด ก่อนจะเคาะน้ำหนัก vector:keyword

⚠️ ทำไมชุดนี้ rerank ได้รับการวัดอย่างเป็นธรรม (ต่างจากใน bench_write_x_read):
    summary จริงเฉลี่ย 141c -> pool 5 อัน = 995c ยังต่ำกว่า attention cliff 3,700c มาก
    ส่วนใน 3×3 ผมส่ง raw 10 อัน = 19,573c ซึ่งเกิน 5 เท่า (บั๊กที่แก้ไปแล้ว)
    -> ที่นี่ถ้า rerank ยังแพ้ แปลว่าแพ้เพราะตัวมันเอง ไม่ใช่เพราะ pool ใหญ่เกิน

เทียบ 4 เส้นทาง — ทุกเส้นใช้ pipeline production จริง (memory.filter_by_owner + guess_owner):
    bm25            keyword ล้วน (**ที่ใช้อยู่ตอนนี้**)
    cosine          vector ล้วน
    cosine+rerank   vector -> ให้ qwen3:8b คัด
    hybrid+rerank   รวมสองชั้น -> qwen3:8b คัด (ใกล้ production ที่สุดถ้าเปลี่ยนไป hybrid)
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
import vectormemory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from bench_vector_lme import cosine, embed_many, keyword_rank  # noqa: E402
from bench_weighted_hybrid import fuse  # noqa: E402
from thai_recall_cases import load as load_thai  # noqa: E402

logging.disable(logging.CRITICAL)

REAL_UID = 434893254576701450
TOP_K = 5           # production ใช้ 5 ในชั้น keyword
RERANK_N = 3        # production ใช้ top_n=3 ในชั้น rerank
MODES = ["bm25", "cosine", "cosine+rerank", "hybrid+rerank"]


async def order_for(mode: str, S: list, q: str, vecs, qv) -> list:
    """คืนลำดับ index — ยกเว้น 'production' ที่คืนรายการที่ inject จริงตรงๆ (ดู union_lines)"""
    if mode == "bm25":
        return keyword_rank(S, q)
    vec_order = [i for _, i in sorted(((cosine(qv, v), i) for i, v in enumerate(vecs)),
                                      key=lambda x: -x[0])]
    if mode == "cosine":
        return vec_order
    base = vec_order if mode.startswith("cosine") else fuse(vec_order, keyword_rank(S, q), 0.5)
    pool = base[:TOP_K]
    cands = [S[i]["text"] for i in pool]
    kept = await vectormemory.rerank_with_llm(q, cands, top_n=RERANK_N)
    if not kept:
        # fail-closed แบบ production: rerank ไม่เห็นอะไรเกี่ยว = ไม่ inject
        return []
    by_text = {S[i]["text"]: i for i in pool}
    front = [by_text[t] for t in kept if t in by_text]
    return front + [i for i in base if i not in front]


async def production_lines(S: list, q: str, vecs, qv) -> list:
    """**เส้นที่ production รันจริง** — chat.py:640-658

    keyword(top-5) ∪ rerank(vector)(top-3) แล้วตัดซ้ำ
    ⚠️ ไม่มีการให้คะแนนร่วมระหว่างสองฝั่งเลย (ต่างจาก mem0 ที่ fuse ด้วยคะแนน)
    ⚠️ กรองเจ้าของ **คนละจังหวะ**: ฝั่ง vector กรองก่อนตัดซ้ำ ฝั่ง keyword กรองทีหลัง
       -> ทำตามลำดับเดิมของ chat.py เป๊ะ เพื่อให้ตัวเลขเป็นของจริง ไม่ใช่ของที่ผมคิดว่าควรเป็น
    """
    whose = memory.guess_owner(q)
    # ชั้น vector: rerank -> กรองเจ้าของ (chat.py:651-654)
    vec_order = [i for _, i in sorted(((cosine(qv, v), i) for i, v in enumerate(vecs)),
                                      key=lambda x: -x[0])]
    cands = [S[i]["text"] for i in vec_order[:TOP_K]]
    vec_lines = await vectormemory.rerank_with_llm(q, cands, top_n=RERANK_N)
    vec_lines = memory.filter_by_owner(vec_lines, whose)
    # ชั้น keyword: เรียก recall_summaries **ตัวจริง** ไม่ใช่ keyword_rank ที่ผมประมาณไว้
    # (ตัวจริงมี decay/เกณฑ์คะแนน/broad-recall ที่ keyword_rank ไม่มี — ต้องใช้ของจริง
    #  ไม่งั้นจะวัด "เส้น production" ที่ไม่ใช่ production)
    kw_lines = memory.recall_summaries({"summaries": S}, q, top_k=TOP_K)
    kw_lines = memory.filter_by_owner(kw_lines, whose)
    # union + ตัดซ้ำ (chat.py:658)
    return kw_lines + [s for s in vec_lines if s not in kw_lines]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default=",".join(MODES))
    args = ap.parse_args()

    summaries = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))["summaries"]
    cases = load_thai(summaries)
    S = [{"text": e["text"], "date": e.get("date")} for e in summaries]
    doc_vecs = await embed_many([s["text"] for s in S])
    modes = [m.strip() for m in args.modes.split(",")]

    lens = [len(s["text"]) for s in S]
    print("=" * 92)
    print(" ความจำ **จริง** ของ production แบบเปิด rerank")
    print(f" summary {len(S)} อัน (เฉลี่ย {sum(lens)//len(lens)}c) · {len(cases)} คำถามไทย")
    print(f" pool ที่ส่ง rerank = {TOP_K} อัน ~{sum(sorted(lens)[-TOP_K:])}c < cliff 3,700c ✅")
    print("=" * 92)

    tally = {m: 0 for m in modes}
    empty = {m: 0 for m in modes}
    for m in modes:
        t0 = time.perf_counter()
        for q, must in cases:
            qv = (await embed_many([q]))[0]
            order = await order_for(m, S, q, doc_vecs, qv)
            if not order:
                empty[m] += 1
                continue
            whose = memory.guess_owner(q)
            lines = memory.filter_by_owner([S[i]["text"] for i in order[:TOP_K]], whose)
            if any(x in "\n".join(lines) for x in must):
                tally[m] += 1
        print(f"   {m:<16} {tally[m]:>3}/{len(cases)}  (ไม่ inject {empty[m]} ครั้ง, {time.perf_counter()-t0:.0f}s)")

    n = len(cases)
    print("\n" + "=" * 92)
    print(f" {'วิธี':<20}{'ตอบถูก':>12}{'ช่วง 95%':>18}{'ไม่ inject':>14}")
    print("-" * 92)
    for m in modes:
        lo, hi = wilson(tally[m], n)
        tag = "  <- ปัจจุบัน" if m == "bm25" else ""
        print(f" {m:<20}{tally[m]:>6}/{n:<5}{lo*100:>9.0f}-{hi*100:<8.0f}%{empty[m]:>10}{tag}")
    print("=" * 92)

    base = tally.get("bm25", 0)
    lb, hb = wilson(base, n)
    for m in modes:
        if m == "bm25":
            continue
        lo, hi = wilson(tally[m], n)
        ov = not (lo > hb or lb > hi)
        print(f" {m:<16} vs keyword: {'ซ้อนทับ = แยกไม่ออก' if ov else 'ต่างจริง ✅'}"
              f"  ({tally[m]} vs {base})")


if __name__ == "__main__":
    asyncio.run(main())
