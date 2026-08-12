"""ตาราง 3×3 ตามเปเปอร์ 2603.02473 — วิธี**เขียน** × วิธี**ค้น** อันไหนสำคัญกว่ากัน

เปเปอร์ "Diagnosing Retrieval vs. Utilization Bottlenecks in LLM Agent Memory" วัดได้ว่า
    วิธีเขียนต่างกันแค่ 3-8 จุด · วิธีค้นต่างกัน 14-23 จุด
    เก็บดิบ (77.9/81.1) > สกัด fact (72.2/77.3) > **สรุปย่อหน้า (70.1/73.3) = วิธีที่เราใช้**
    BM25 57.1 · cosine 73.4 · hybrid+rerank 77.2

⚠️ ทำไมต้องวัดเอง ไม่เชื่อตัวเลขเขาตรงๆ:
  1. เขาวัดภาษาอังกฤษ — ไทยไม่มีช่องว่างระหว่างคำ keyword เปราะกว่าโดยโครงสร้าง
  2. เขาใช้ GPT-5.2 เป็น reranker — เราใช้ qwen3:8b บนเครื่องตัวเอง คนละชั้น
  3. เขาวัด QA จากบทสนทนา — เราเป็นบอทคู่หูที่ต้องคงบุคลิก คนละงาน

⚠️ ที่สำคัญที่สุด — **bench เดิมของเราปิด rerank ไว้ทั้งหมด**
   (เลี่ยงผลแกว่ง + rerank ยิง LLM ต่อคำถามทำให้รันเป็นชั่วโมง)
   แต่ production **มี** rerank อยู่จริง -> ตัวเลขที่เราตัดสินใจกันมาทั้งหมดวัดระบบที่อ่อนกว่าของจริง
   ไฟล์นี้เปิด rerank เป็นครั้งแรก

วิธีเขียน 3 แบบ (จำลองจาก session เดียวกัน ให้เทียบกันได้):
    raw       — เก็บบทสนทนาดิบ ไม่สรุป (แบบที่เปเปอร์บอกว่าชนะ)
    facts     — สกัดเป็นประโยคสั้น (แบบ mem0)
    summary   — สรุปเป็นย่อหน้า + tag วิธี F (**แบบที่เราใช้จริง**)

วิธีค้น 3 แบบ:
    bm25      — keyword count (แบบที่ production ใช้เป็นชั้นแรก)
    cosine    — vector ล้วน (bge-m3)
    hybrid    — รวมสองชั้น + rerank ด้วย LLM ตัวจริงของเรา
"""
import argparse
import asyncio
import json
import logging
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

import memory  # noqa: E402
import vectormemory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from bench_vector_lme import cosine, embed_many, keyword_rank  # noqa: E402
from bench_weighted_hybrid import fuse  # noqa: E402

logging.disable(logging.CRITICAL)

LME = "tools/data/longmemeval_s.json"
WRITES = ["raw", "facts", "summary"]
READS = ["bm25", "cosine", "hybrid"]
# เพดานตัวอักษรที่ส่งให้ rerank อ่านต่อครั้ง — ตั้งตาม attention cliff ~3,700c ที่วัดไว้ใน §1
RERANK_BUDGET_C = 3500


# ── วิธีเขียน 3 แบบ — จาก session เดียวกัน ─────────────────────────────────

def write_raw(sess: list) -> str:
    """เก็บดิบ — ต่อทุกเทิร์นเข้าด้วยกัน ไม่ตัดอะไร"""
    return "\n".join(f"{t.get('role')}: {t.get('content','')}" for t in sess)[:2000]


def write_facts(sess: list) -> str:
    """สกัดประโยคสั้น — เอาเฉพาะประโยคที่ผู้ใช้พูดถึงตัวเอง (heuristic ไม่ยิง LLM
    เพื่อให้เทียบได้นิ่ง และเปเปอร์เองก็สนใจ *รูปแบบข้อมูล* ไม่ใช่คุณภาพตัวสกัด)"""
    out = []
    for t in sess:
        if t.get("role") != "user":
            continue
        for s in t.get("content", "").split("."):
            s = s.strip()
            if 20 < len(s) < 160 and (" I " in f" {s} " or s.startswith("I ") or " my " in s.lower()):
                out.append(s)
    return " | ".join(out[:8])[:600]


def write_summary(sess: list) -> str:
    """สรุปย่อหน้า + tag — **แบบที่เราใช้จริง** จำลองความยาวและรูปแบบวิธี F
    (บีบให้สั้นแบบเดียวกับที่ production ได้ ~120-250c + tag ท้ายบรรทัด)"""
    user_txt = " ".join(t.get("content", "") for t in sess if t.get("role") == "user")
    head = user_txt[:220]
    words = [w for w in user_txt.split() if len(w) > 5][:4]
    tags = " | ".join(f"user_fact:{w}" for w in words)
    return f"{head} | {tags}"


WRITE_FN = {"raw": write_raw, "facts": write_facts, "summary": write_summary}


# ── วิธีค้น 3 แบบ ─────────────────────────────────────────────────────────

async def read_bm25(S: list, q: str, _v=None, _qv=None) -> list:
    return keyword_rank(S, q)


async def read_cosine(S: list, q: str, vecs=None, qv=None) -> list:
    return [i for _, i in sorted(((cosine(qv, v), i) for i, v in enumerate(vecs)),
                                 key=lambda x: -x[0])]


async def read_hybrid(S: list, q: str, vecs=None, qv=None) -> list:
    """รวมสองชั้น (RRF ถ่วงเท่ากันแบบเปเปอร์) แล้ว **rerank ด้วย LLM ตัวจริงของเรา**"""
    vec_order = await read_cosine(S, q, vecs, qv)
    kw_order = keyword_rank(S, q)
    order = fuse(vec_order, kw_order, 0.5)
    # ⚠️ คุม pool ด้วย **จำนวนตัวอักษร** ไม่ใช่จำนวนรายการ
    # วัดแล้ว: top-10 ของ raw = 19,573c = 5 เท่าของ attention cliff 3,700c (§1)
    # -> rerank อ่านไม่ไหว คืนน้อยลง ทำให้ hybrid ดูแย่กว่า cosine ทั้งที่เป็นข้อจำกัดของ pool
    # เปเปอร์ใช้ GPT-5.2 ที่ context ใหญ่กว่ามาก จึงไม่เจอเพดานนี้ — เราเจอ
    pool, used = [], 0
    for i in order:
        ln = len(S[i]["text"])
        if pool and used + ln > RERANK_BUDGET_C:
            break
        pool.append(i)
        used += ln
        if len(pool) >= 10:
            break
    cands = [S[i]["text"] for i in pool]
    kept = await vectormemory.rerank_with_llm(q, cands, top_n=3)
    if not kept:
        return order                        # rerank fail-closed -> ใช้ลำดับเดิม
    by_text = {S[i]["text"]: i for i in pool}
    front = [by_text[t] for t in kept if t in by_text]
    return front + [i for i in order if i not in front]


READ_FN = {"bm25": read_bm25, "cosine": read_cosine, "hybrid": read_hybrid}


async def run_cell(cases: list, write: str, read: str) -> int:
    ok = 0
    for c in cases:
        S = [{"text": WRITE_FN[write](s), "_sid": sid}
             for sid, s in zip(c["haystack_session_ids"], c["haystack_sessions"])]
        S = [s for s in S if s["text"].strip()]
        if not S:
            continue
        gold = set(c.get("answer_session_ids") or [])
        vecs = qv = None
        if read != "bm25":
            vecs = await embed_many([s["text"] for s in S])
            qv = (await embed_many([c["question"]]))[0]
        order = await READ_FN[read](S, c["question"], vecs, qv)
        if order and S[order[0]]["_sid"] in gold:
            ok += 1
    return ok


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=8, help="ข้อ/ชนิดคำถาม")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--reads", default="bm25,cosine,hybrid")
    args = ap.parse_args()

    data = json.load(open(LME, encoding="utf-8"))
    types = ["single-session-preference", "single-session-user",
             "single-session-assistant", "knowledge-update",
             "multi-session", "temporal-reasoning"]
    rng = random.Random(args.seed)
    cases = []
    for t in types:
        cs = [x for x in data if x["question_type"] == t]
        cases += rng.sample(cs, min(args.limit, len(cs)))

    reads = [r.strip() for r in args.reads.split(",")]
    n = len(cases)
    print("=" * 94)
    print(" ตาราง 3×3 ตามเปเปอร์ 2603.02473 — วิธีเขียน × วิธีค้น อันไหนสำคัญกว่า")
    print(f" {n} คำถาม (สุ่ม {args.limit}/ชนิด seed={args.seed}) · rerank = qwen3:8b ตัวจริงของเรา")
    print("=" * 94)

    res = {}
    for w in WRITES:
        for r in reads:
            t0 = time.perf_counter()
            res[(w, r)] = await run_cell(cases, w, r)
            print(f"   {w:<8} × {r:<8} {res[(w,r)]:>3}/{n}   ({time.perf_counter()-t0:.0f}s)")

    print("\n" + "=" * 94)
    print(f" {'วิธีเขียน':<24}" + "".join(f"{r:>16}" for r in reads) + f"{'เฉลี่ย':>12}")
    print("-" * 94)
    for w in WRITES:
        row = f" {w:<24}"
        for r in reads:
            row += f"{res[(w,r)]:>8}/{n:<7}"
        avg = sum(res[(w, r)] for r in reads) / len(reads) / n * 100
        row += f"{avg:>10.0f}%"
        print(row)
    print("-" * 94)
    row = f" {'เฉลี่ยตามวิธีค้น':<24}"
    for r in reads:
        avg = sum(res[(w, r)] for w in WRITES) / len(WRITES) / n * 100
        row += f"{avg:>14.0f}% "
    print(row)
    print("=" * 94)

    spread_w = max(sum(res[(w, r)] for r in reads) for w in WRITES) - \
        min(sum(res[(w, r)] for r in reads) for w in WRITES)
    spread_r = max(sum(res[(w, r)] for w in WRITES) for r in reads) - \
        min(sum(res[(w, r)] for w in WRITES) for r in reads)
    print(f"\n ช่วงห่างจาก **วิธีเขียน**: {spread_w/len(reads)/n*100:.0f} จุด"
          f"   (เปเปอร์ได้ 3-8 จุด)")
    print(f" ช่วงห่างจาก **วิธีค้น**  : {spread_r/len(WRITES)/n*100:.0f} จุด"
          f"   (เปเปอร์ได้ 14-23 จุด)")
    print(f" -> {'วิธีค้นสำคัญกว่า (ตรงกับเปเปอร์)' if spread_r > spread_w else 'วิธีเขียนสำคัญกว่า (ขัดกับเปเปอร์)'}")

    print(f"\n {'ช่อง':<22}{'ช่วง 95%':>18}")
    for w in WRITES:
        for r in reads:
            lo, hi = wilson(res[(w, r)], n)
            print(f" {w+' × '+r:<22}{lo*100:>8.0f}-{hi*100:<8.0f}%")


if __name__ == "__main__":
    asyncio.run(main())
