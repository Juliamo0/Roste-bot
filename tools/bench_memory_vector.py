"""วัด vector search (semantic recall) บน fixture เดียวกับ bench_memory_read

ทำไมต้องวัดแยก: vector search ต่างจาก keyword 2 อย่าง
  1. ไม่มี PAST_HINTS gate — ทำงานทุกครั้ง (chat.py:601) จึงอาจช่วยเคสที่ keyword ถูกตัดทิ้ง
  2. ค้นด้วยความหมาย ไม่ใช่คำตรง — ควรครอบคำพ้อง ("การอ่าน" vs "นิยาย") ได้ดีกว่า
แต่มันไม่รู้จัก tag แยกเจ้าของเลย — คืน summary ทั้งบรรทัดเสมอ จึงมีปัญหาเดียวกับ P1

⚠️ ต้องเรียก Ollama จริง (embedding + LLM rerank) ผลจึงแกว่งได้ ต่างจาก bench_memory_read
   ที่เป็น rule ล้วน — รันซ้ำหลายรอบถึงเชื่อได้

⚠️ ใช้ user id ทดสอบแยก ไม่แตะความจำจริงของใคร
"""
import argparse
import asyncio
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging  # noqa: E402

import vectormemory as V  # noqa: E402
from memory_fixture import CASES, HARD_CASES, SUMMARIES  # noqa: E402
from memory_tool_proto import (  # noqa: E402
    build_memory_block, build_memory_block_hybrid, filter_by_owner,
)

logging.disable(logging.CRITICAL)

TEST_UID = 999_888_777_666_553


async def setup():
    """โหลด fixture เข้า vector store (ล้างของเก่าก่อน)"""
    try:
        V._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    for s in SUMMARIES:
        await V.add_conversation_memory(TEST_UID, s)


def teardown():
    try:
        V._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass


def judge(block: str, whose: str, must: list, forbid: list) -> tuple:
    bad = []
    if whose == "none":
        if block.strip():
            bad.append("ดึงของไม่เกี่ยวมา")
        return (not bad), bad
    if must and not any(w in block for w in must):
        bad.append(f"ไม่เจอ {must}")
    if forbid and any(w in block for w in forbid):
        bad.append(f"มีของอีกฝั่งปน {[w for w in forbid if w in block]}")
    return (not bad), bad


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=1)
    args = ap.parse_args()

    print("=" * 100)
    print(f" วัด vector search บน fixture — {len(SUMMARIES)} summary, "
          f"{len(CASES) + len(HARD_CASES)} เคส × {args.reps} รอบ")
    print(" (เรียก Ollama จริง: embedding + LLM rerank — ผลแกว่งได้)")
    print("=" * 100)

    await setup()
    try:
        allc = [(q, w, m, f, "ปกติ") for q, w, m, f in CASES] + \
               [(q, w, m, f, "หิน") for q, w, m, f in HARD_CASES]

        vec_ok = vecf_ok = p3_ok = hyb_ok = 0
        n = 0
        rows = []
        srcs = {}
        for q, whose, must, forbid, tag in allc:
            for _ in range(args.reps):
                vec = await V.query_conversation_memory(TEST_UID, q)
                v_ok, _ = judge("\n".join(vec), whose, must, forbid)
                # vector + กรองฝั่ง (แยกดูว่าที่ vector แพ้เพราะค้นผิดหรือเพราะไม่กรอง)
                vf_ok, _ = judge("\n".join(filter_by_owner(vec, whose)),
                                 whose, must, forbid)

                pblock, _ = build_memory_block(SUMMARIES, q)
                p_ok, _ = judge(pblock, whose, must, forbid)

                hblock, _, src = await build_memory_block_hybrid(
                    SUMMARIES, q, user_id=TEST_UID)
                h_ok, h_bad = judge(hblock, whose, must, forbid)
                srcs[src] = srcs.get(src, 0) + 1

                n += 1
                vec_ok += v_ok
                vecf_ok += vf_ok
                p3_ok += p_ok
                hyb_ok += h_ok
                rows.append((tag, q, whose, v_ok, vf_ok, p_ok, h_ok, src, h_bad))

        print(f"\n{'ชุด':<5} {'คำถาม':<36} {'ฝั่ง':<5} {'vec':>4} {'vec+f':>6} "
              f"{'P3':>4} {'hybrid':>7}  ที่มา")
        print("-" * 100)
        for tag, q, whose, v_ok, vf_ok, p_ok, h_ok, src, h_bad in rows:
            m = lambda x: "✅" if x else "❌"  # noqa: E731
            print(f"{tag:<5} {q[:34]:<36} {whose:<5} {m(v_ok):>4} {m(vf_ok):>6} "
                  f"{m(p_ok):>4} {m(h_ok):>7}  {src}")
            if not h_ok:
                print(f"      → hybrid: {', '.join(h_bad)[:80]}")

        print("\n" + "=" * 100)
        print(f" {'วิธี':<38} {'ผ่าน':>10}")
        print("-" * 100)
        print(f" {'vector ดิบ (ไม่กรองฝั่ง)':<38} {vec_ok:>4}/{n}")
        print(f" {'vector + กรองฝั่ง':<38} {vecf_ok:>4}/{n}")
        print(f" {'P3 (keyword + กรองฝั่ง)':<38} {p3_ok:>4}/{n}")
        print(f" {'hybrid (P3 + vector เมื่อควรเรียก)':<38} {hyb_ok:>4}/{n}")
        print("=" * 100)
        print(f"\n ที่มาของคำตอบใน hybrid: {srcs}")
        print(" 'vector' = เคสที่ keyword พลาดแล้ว vector ช่วยได้จริง")
        print(" 'ไม่มีฝั่งนี้' = คืนว่างอย่างถูกต้อง (ไม่เรียก vector = ไม่เสี่ยงดึงของผิดฝั่ง)")
    finally:
        teardown()


if __name__ == "__main__":
    asyncio.run(main())
