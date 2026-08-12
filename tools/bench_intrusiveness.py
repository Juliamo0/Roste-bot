"""วัด **intrusiveness** ของ 4 เส้นทาง — ของไม่เกี่ยวที่ยัดเข้า context

ที่มา: คะแนน "ตอบถูก" ตัดสินไม่ได้ที่ n=37 (ทั้ง 4 เส้นช่วงซ้อนทับหมด)
แต่ intrusiveness วัด **ต่อบรรทัด** ไม่ใช่ต่อคำถาม -> n ใหญ่กว่าราว 5 เท่า จึงอาจแยกได้

ทำไมสำคัญกว่าคะแนนตอบถูก ณ จุดนี้:
  - เราชนกับ attention cliff 3,700c อยู่ (§1: qwen3:8b ตก 6/6 -> 0-1/6 เมื่อเกิน)
  - บรรทัดที่ไม่เกี่ยว = เปลืองโควตานั้นไปเปล่าๆ และดัน summary ที่เกี่ยวออกจากช่วงที่โมเดลสนใจ
  - Phase 0 วัดไว้ว่า noise 46% แต่วัดด้วย probe question ที่ **ไม่มีเฉลย** จึงบอกได้แค่ "ดึงมากี่อัน"

ต่างจากของเดิม: ชุด 37 คำถามมี **เฉลย** (must-appear) จึงแยก "เกี่ยว/ไม่เกี่ยว" ได้จริง

metric (ต่อบรรทัดที่ inject จริง หลังผ่าน filter_by_owner แบบ production):
    precision   บรรทัดที่เกี่ยว / บรรทัดที่ inject ทั้งหมด   <- ตัวหลัก
    noise       1 - precision
    ctx_chars   ตัวอักษรที่ยัดเข้า context เฉลี่ยต่อคำถาม
    silent      จำนวนคำถามที่ไม่ inject อะไรเลย (บอทเงียบใส่ผู้ใช้ = แย่กว่าตอบไม่ตรง)

⚠️ "เกี่ยว" นิยามตามเฉลยของเคส (must-appear) ซึ่งเป็นนิยามที่แคบ —
   บรรทัดอาจเกี่ยวกับคำถามจริงแต่ไม่มีคำในเฉลย จะถูกนับเป็น noise
   ตัวเลข precision จึงเป็น **ขอบล่าง** ใช้เทียบระหว่างเส้นทางได้ แต่ไม่ใช่ค่าสัมบูรณ์
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
from bench_paper_opts import wilson  # noqa: E402
from bench_real_rerank import (REAL_UID, RERANK_N, TOP_K,  # noqa: E402
                               order_for, production_lines)
from bench_vector_lme import embed_many  # noqa: E402
from thai_recall_cases import load as load_thai  # noqa: E402

logging.disable(logging.CRITICAL)

# ⚠️ "production" = เส้นที่ chat.py รันจริง (keyword ∪ rerank(vector))
#    รอบก่อนผมลืมใส่ baseline ตัวนี้ -> เทียบทางเลือกกันเองโดยไม่มีของจริงในตาราง
MODES = ["production", "bm25", "cosine", "cosine+rerank", "hybrid+rerank"]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default=",".join(MODES))
    args = ap.parse_args()

    summaries = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))["summaries"]
    cases = load_thai(summaries)
    S = [{"text": e["text"], "date": e.get("date")} for e in summaries]
    doc_vecs = await embed_many([s["text"] for s in S])
    modes = [m.strip() for m in args.modes.split(",")]

    print("=" * 96)
    print(" intrusiveness — ของไม่เกี่ยวที่ยัดเข้า context (ความจำจริง 55 อัน)")
    print(f" {len(cases)} คำถาม · วัดต่อ **บรรทัด** จึงมี n ใหญ่กว่าการวัดต่อคำถาม")
    print("=" * 96)

    res = {}
    for m in modes:
        t0 = time.perf_counter()
        rel = tot = silent = 0
        chars = []
        for q, must in cases:
            qv = (await embed_many([q]))[0]
            if m == "production":
                lines = await production_lines(S, q, doc_vecs, qv)
                if not lines:
                    silent += 1
                chars.append(sum(len(x) + 2 for x in lines))
                for ln in lines:
                    tot += 1
                    if any(x in ln for x in must):
                        rel += 1
                continue
            order = await order_for(m, S, q, doc_vecs, qv)
            whose = memory.guess_owner(q)
            # ⚠️ เส้นที่มี rerank ต้องตัดที่ **top_n=3 ที่ rerank คัดมา** ไม่ใช่ TOP_K=5
            # production ใช้ผลของ rerank ตรงๆ (vectormemory.py:321 คืน top_n=3)
            # ถ้าตัดที่ 5 เหมือนกันหมด = การจัดลำดับใหม่ของ rerank ถูกกลบ
            # (วัดแล้ว: rerank สลับอันดับจริง 6/12 ครั้ง แต่ยังอยู่ใน 5 อันเดิม จึงไม่เห็นผล)
            cut = RERANK_N if "rerank" in m else TOP_K
            lines = memory.filter_by_owner([S[i]["text"] for i in order[:cut]], whose) if order else []
            if not lines:
                silent += 1
            chars.append(sum(len(x) + 2 for x in lines))
            for ln in lines:
                tot += 1
                if any(x in ln for x in must):
                    rel += 1
        res[m] = {"rel": rel, "tot": tot, "silent": silent,
                  "ctx": sum(chars) / len(chars), "t": time.perf_counter() - t0}
        print(f"   {m:<16} {rel}/{tot} บรรทัดเกี่ยว  ({res[m]['t']:.0f}s)")

    print("\n" + "=" * 96)
    print(f" {'วิธี':<18}{'precision':>22}{'ช่วง 95%':>16}{'noise':>9}{'ctx เฉลี่ย':>12}{'เงียบ':>8}")
    print("-" * 96)
    for m in modes:
        r = res[m]
        p = r["rel"] / r["tot"] if r["tot"] else 0
        lo, hi = wilson(r["rel"], r["tot"]) if r["tot"] else (0, 0)
        tag = "  <- ที่รันจริง" if m == "production" else ""
        print(f" {m:<18}{r['rel']:>7}/{r['tot']:<5}{p*100:>7.0f}%{lo*100:>8.0f}-{hi*100:<7.0f}%"
              f"{(1-p)*100:>7.0f}%{r['ctx']:>10.0f}c{r['silent']:>8}{tag}")
    print("=" * 96)

    if "production" in res:
        b = res["production"]
        lb, hb = wilson(b["rel"], b["tot"])
        print(f"\n เทียบกับเส้นที่รันจริง (precision {b['rel']/b['tot']*100:.0f}%):")
        for m in modes:
            if m == "production":
                continue
            r = res[m]
            lo, hi = wilson(r["rel"], r["tot"])
            ov = not (lo > hb or lb > hi)
            print(f"   {m:<16} {'ซ้อนทับ = แยกไม่ออก' if ov else 'ต่างจริง ✅'}"
                  f"   ({r['rel']/r['tot']*100:.0f}% vs {b['rel']/b['tot']*100:.0f}%)"
                  f"   ctx {r['ctx']:.0f}c vs {b['ctx']:.0f}c")


if __name__ == "__main__":
    asyncio.run(main())
