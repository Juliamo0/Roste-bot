"""ยืนยันว่าตัด LLM rerank ออกจาก conversation memory ได้จริงไหม — วัดที่ n สูงพอ

ทำไมต้องวัดซ้ำ: profile พบว่า rerank กิน 668ms จาก 1,070ms (62%) และทดสอบ 10 เคสแล้ว
ได้ 10/10 เท่ากันทั้งมีและไม่มี rerank — แต่ 10 เคสน้อยเกินกว่าจะสรุป (บทเรียนซ้ำๆ
จากทั้ง pass^8 และ n=17 ที่หลอกมาแล้วสองครั้ง)

สมมติฐานที่กำลังทดสอบ: rerank กลายเป็นงานซ้ำซ้อนหลังมี filter_by_owner
  - rerank ออกแบบมาตอนยังไม่มีการกรองฝั่ง หน้าที่คือ "กรองของไม่เกี่ยวออก"
  - ตอนนี้ filter_by_owner ทำงานนั้นด้วย rule ซึ่งเร็วกว่า ~300 เท่าและ deterministic
  - ถ้าจริง ตัด rerank ได้โดยความแม่นไม่ตก

⚠️ rerank_with_llm ใช้ร่วมกับ query_pdf ด้วย — ไฟล์นี้วัดเฉพาะฝั่ง conversation memory
   ถ้าจะตัดจริงต้องทำเป็น flag ไม่ใช่ลบฟังก์ชันทิ้ง (PDF RAG อาจยังต้องใช้)
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
from memory_tool_proto import filter_by_owner, guess_owner  # noqa: E402

UID = 999_888_777_666_549


def wilson(ok, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def judge(block, whose, must, forbid):
    if whose == "none":
        return not block.strip()
    if must and not any(w in block for w in must):
        return False
    if forbid and any(w in block for w in forbid):
        return False
    return True


async def search(question: str, use_rerank: bool, top_k: int = 3):
    """ค้น conversation memory — สลับเปิด/ปิด rerank ได้"""
    coll = V._convmem_collection(UID)
    if coll.count() == 0:
        return "", 0.0
    t0 = time.perf_counter()
    emb = await V.get_embedding(question)
    if emb is None:
        return "", time.perf_counter() - t0
    res = coll.query(query_embeddings=[emb],
                     n_results=min(V.RETRIEVE_K, coll.count()))
    cands = (res.get("documents") or [[]])[0]
    if use_rerank:
        cands = await V.rerank_with_llm(question, cands, top_n=top_k)
    else:
        cands = cands[:top_k]
    dt = time.perf_counter() - t0
    whose = guess_owner(question)
    return "\n".join(f"- {t}" for t in filter_by_owner(cands, whose)), dt


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    sets = [("ปกติ", CASES), ("หิน", HARD_CASES), ("คำพ้อง", SYNONYM_CASES)]
    total = sum(len(c) for _, c in sets)
    print("=" * 96)
    print(f" ตัด LLM rerank ได้ไหม — {total} เคส × {args.reps} รอบ = {total*args.reps} ตัวอย่าง/แบบ")
    print("=" * 96)

    try:
        V._client.delete_collection(f"convmem_{UID}")
    except Exception:
        pass
    for s in SUMMARIES:
        await V.add_conversation_memory(UID, s)

    rows = []
    try:
        for label, use_rr in (("มี rerank (เดิม)", True), ("ไม่มี rerank", False)):
            ok = n = 0
            per = {name: [0, 0] for name, _ in sets}
            lat = []
            diffs = []
            for sname, cases in sets:
                for q, whose, must, forbid in cases:
                    for _ in range(args.reps):
                        block, dt = await search(q, use_rr)
                        good = judge(block, whose, must, forbid)
                        ok += good
                        n += 1
                        per[sname][0] += good
                        per[sname][1] += 1
                        lat.append(dt)
                        if not good:
                            diffs.append((sname, q, whose))
            lo, hi = wilson(ok, n)
            rows.append(dict(label=label, ok=ok, n=n, lo=lo, hi=hi,
                             per={k: tuple(v) for k, v in per.items()},
                             lat=statistics.mean(lat), diffs=diffs))
            print(f"\n  【{label}】 {ok}/{n} ({ok/n*100:.0f}%)  ช่วง 95% [{lo*100:.0f}-{hi*100:.0f}%]")
            for sname, (a, b) in per.items():
                print(f"       {sname:<8} {a:>3}/{b:<4} ({a/max(b,1)*100:>3.0f}%)")
            print(f"       latency เฉลี่ย {statistics.mean(lat)*1000:.0f} ms")
            if diffs:
                seen = set()
                for s_, q_, w_ in diffs:
                    if q_ in seen:
                        continue
                    seen.add(q_)
                    print(f"       ❌ [{s_}] {q_[:52]}")
    finally:
        try:
            V._client.delete_collection(f"convmem_{UID}")
        except Exception:
            pass

    a, b = rows
    print("\n" + "=" * 96)
    print(f" {'แบบ':<22} {'ผ่าน':>10} {'ช่วง 95%':>14} {'latency':>12}")
    print("-" * 96)
    for r in rows:
        print(f" {r['label']:<22} {r['ok']:>4}/{r['n']:<5} "
              f"[{r['lo']*100:>3.0f}-{r['hi']*100:>3.0f}%] {r['lat']*1000:>10.0f} ms")
    print("=" * 96)

    sep = "ต่างจริง" if a["lo"] > b["hi"] or b["lo"] > a["hi"] else "แยกไม่ออก"
    print(f"\n เทียบ: {sep}")
    if sep == "แยกไม่ออก":
        print(f" → ความแม่นไม่ต่างกัน แต่เร็วขึ้น {a['lat']/max(b['lat'],1e-9):.1f}x "
              f"({a['lat']*1000:.0f} → {b['lat']*1000:.0f} ms)")
        print(" → ตัด rerank ได้ (สำหรับ conversation memory — PDF RAG ต้องวัดแยก)")
    else:
        print(" → ต่างจริง ต้องดูว่าใครสูงกว่าก่อนตัดสิน")


if __name__ == "__main__":
    asyncio.run(main())
