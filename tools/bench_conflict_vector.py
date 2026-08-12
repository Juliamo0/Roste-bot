"""วัดว่า **vector retrieval** ปิดช่องว่าง 6 เคสที่ keyword หยิบไม่เจอได้จริงไหม

ที่มา: bench Phase 0/1 วัดเฉพาะชั้น keyword (`_score_and_filter`) เพราะตั้งใจเลี่ยง
LLM rerank ที่ผลแกว่ง แต่ผล oracle ชี้ว่า **คอขวดจริงคือ retrieval ไม่ใช่ conflict**:
  - แก้ความขัดแย้งสมบูรณ์แบบ (oracle) ได้เพดานแค่ 31/39
  - 6/39 เคส คำตอบอยู่ในความจำครบ แต่ recall_summaries หยิบไม่เจอ (ปัญหาคำพ้อง)
  - conditional ได้ 1/5 เท่ากันทุกวิธี รวมทั้ง oracle

MEMORY_EXPERIMENTS §3 วัดไว้แล้วว่า vector ชนะ keyword ในชุดคำพ้อง (30/30 vs 21/30)
ไฟล์นี้ตรวจว่าข้อสรุปนั้นยังจริงกับ fixture ความขัดแย้ง และครอบ 6 เคสนั้นได้แค่ไหน

เทียบ 4 เส้นทาง:
  K   keyword ล้วน           = recall_summaries (production ชั้นแรก)
  V   vector ล้วน            = query_conversation_memory (production ชั้นสอง)
  KV  keyword ∪ vector       = ที่ chat.py ทำจริง (รวมสองชั้น)
  KV+ KV + conflict (M3)     = รวมสองชั้น แล้วตัดของที่ถูก supersede

⚠️ V/KV/KV+ เรียก LLM rerank → ผลอาจแกว่ง ใช้ --rounds เพื่อวัดซ้ำ
⚠️ ใช้ user id ทดสอบ ลบ collection ทิ้งท้ายรอบเสมอ — ไม่แตะข้อมูลผู้ใช้จริง
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
import memory  # noqa: E402
import vectormemory  # noqa: E402
from memory_conflict_fixture import ALL_SETS, SUMMARIES  # noqa: E402

logging.disable(logging.CRITICAL)

TEST_UID = 999900000000000002

# เคสที่ keyword หยิบไม่เจอทั้งที่คำตอบอยู่ในความจำ (วัดไว้แล้วในรอบ oracle)
# ติดตามแยกเพื่อดูว่า vector ปิดช่องว่างตรงนี้ได้กี่เคส
KEYWORD_BLIND = {
    "รอสเต้ชอบทำอะไรยามว่าง", "ตอนนี้ผมออกกำลังกายยังไง",
    "เมื่อก่อนรอสเต้ทำงานอะไร", "ผมเลี้ยงสัตว์อะไรบ้าง",
    "หน้าร้อนผมชอบไปเที่ยวไหน", "หน้าหนาวผมชอบไปไหน",
}


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def judge(lines: list, must: list, forbid: list) -> bool:
    blob = "\n".join(lines)
    if must and not any(w in blob for w in must):
        return False
    if forbid and any(w in blob for w in forbid):
        return False
    return True


async def seed_vector(texts: list):
    """เขียน summary ลง Chroma — ล้างของเก่าก่อนเสมอ (บทเรียนจาก probe_vector_drift)"""
    try:
        vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    for t in texts:
        await vectormemory.add_conversation_memory(TEST_UID, t)


def cleanup():
    try:
        vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass


async def eval_paths(pool: list, question: str) -> dict:
    """คืนบรรทัดที่แต่ละเส้นทางหยิบได้ — จำลอง chat.py:586-623 ให้ตรงที่สุด"""
    whose = memory.guess_owner(question)

    kw = memory.recall_summaries({"summaries": pool}, question)

    vec = await vectormemory.query_conversation_memory(TEST_UID, question)
    vec = memory.filter_by_owner(vec, whose)
    # ตัดของที่ไม่ได้อยู่ใน pool ปัจจุบัน (เช่นถูก supersede ไปแล้ว)
    pool_texts = [e["text"] if isinstance(e, dict) else e for e in pool]

    def in_pool(line: str) -> bool:
        head = line.split("—")[0].strip()
        return any(head and head in t for t in pool_texts)

    vec_pool = [v for v in vec if in_pool(v)]
    kv = kw + [v for v in vec_pool if v not in kw]
    return {"K": kw, "V": vec_pool, "KV": kv}


async def run_round(consolidated: list) -> dict:
    """รันทุกเคส 1 รอบ คืนผลรายชุดของแต่ละเส้นทาง"""
    out = {p: {} for p in ("K", "V", "KV", "KV+")}
    blind = {p: 0 for p in out}
    for set_name, cases in ALL_SETS:
        acc = {p: 0 for p in out}
        for q, whose, must, forbid in cases:
            got = await eval_paths(SUMMARIES, q)

            # KV+ : ใช้กองที่ตัด superseded แล้ว (ยกเว้นคำถามอดีต)
            pool_plus = (consolidated if proto.wants_history(q)
                         else [e for e in consolidated if not e.get("superseded")])
            got_plus = await eval_paths(pool_plus, q)
            got["KV+"] = got_plus["KV"]

            for p in out:
                ok = judge(got[p], must, forbid)
                acc[p] += ok
                if ok and q in KEYWORD_BLIND:
                    blind[p] += 1
        for p in out:
            out[p][set_name] = (acc[p], len(cases))
    return out, blind


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    args = ap.parse_args()

    n_cases = sum(len(c) for _, c in ALL_SETS)
    print("=" * 104)
    print(" วัดว่า vector retrieval ปิดช่องว่างที่ keyword หยิบไม่เจอได้ไหม")
    print(f" fixture: {len(SUMMARIES)} summary, {n_cases} เคส  |  รอบ: {args.rounds}")
    print(f" เคสที่ keyword ตาบอด: {len(KEYWORD_BLIND)} เคส")
    print("=" * 104)

    cleanup()
    try:
        print("\n กำลังเขียน summary ลง vector store (bge-m3)...")
        await seed_vector([s["text"] for s in SUMMARIES])
        consolidated = proto.m3_consolidate(SUMMARIES)

        totals = {p: {} for p in ("K", "V", "KV", "KV+")}
        blind_tot = {p: 0 for p in totals}
        for r in range(args.rounds):
            print(f" รอบ {r + 1}/{args.rounds} — กำลังค้น (มี LLM rerank ต่อเคส)...")
            res, blind = await run_round(consolidated)
            for p in totals:
                for s, (ok, n) in res[p].items():
                    pok, pn = totals[p].get(s, (0, 0))
                    totals[p][s] = (pok + ok, pn + n)
                blind_tot[p] += blind[p]

        names = {"K": "K  keyword ล้วน (ปัจจุบัน)", "V": "V  vector ล้วน",
                 "KV": "KV keyword ∪ vector (chat.py)", "KV+": "KV+ รวม + conflict (M3)"}
        print("\n" + "=" * 104)
        set_names = [s for s, _ in ALL_SETS]
        head = f" {'เส้นทาง':<30}"
        for s in set_names:
            head += f" {s:>12}"
        head += f" {'รวม':>11} {'ตาบอด':>7}"
        print(head)
        print("-" * 104)
        for p in ("K", "V", "KV", "KV+"):
            row = f" {names[p]:<30}"
            tok = tn = 0
            for s in set_names:
                ok, n = totals[p][s]
                tok += ok
                tn += n
                row += f" {ok:>5}/{n:<6}"
            lo, hi = wilson(tok, tn)
            row += f" {tok:>4}/{tn:<6} {blind_tot[p]:>3}/{len(KEYWORD_BLIND) * args.rounds}"
            print(row)
            print(f" {'':<30} ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%")
        print("=" * 104)
        print("\n 'ตาบอด' = จำนวนเคสที่ keyword หยิบไม่เจอ แต่เส้นทางนี้หยิบเจอ")
    finally:
        cleanup()
        print("\n(ลบข้อมูลทดสอบเรียบร้อย)")


if __name__ == "__main__":
    asyncio.run(main())
