"""C2: ทดสอบว่า **โมเดลเล็ก** ขยายคำถาม (query rewriting) ได้ดีพอไหม

ไอเดียจากผู้ใช้: LLM rewrite ไม่จำเป็นต้องใช้โมเดลใหญ่ — ใช้ตัวเล็กรัน background ก็ได้

ทำไมน่าจะเวิร์ค: งานนี้ไม่ต้องใช้เหตุผลซับซ้อน แค่ "แบก → ภาระ/งาน" ซึ่งเป็นความรู้ภาษา
ล้วนๆ ต่างจากงาน conflict resolution ที่วัดแล้วว่าโมเดลเล็กทำไม่ได้ (P2 ได้ 34/100)

⚠️ แต่ MEMORY_EXPERIMENTS §3 เตือนว่าโมเดลเล็กมีข้อจำกัดจริง — จึงต้องวัด ไม่ใช่เดา
เทียบ 3 แบบ:
    baseline        ไม่ขยายคำถาม (= ปัจจุบัน)
    1.7b rewrite    โมเดลเล็ก
    8b rewrite      โมเดลหลัก (เพดานว่าถ้าใช้ตัวใหญ่จะได้แค่ไหน)

วัดด้วยชุดเดียวกับ bench_vocab_gap.py (คำถามสร้างจาก summary จริงอย่างเป็นระบบ)
"""
import argparse
import asyncio
import io
import json
import logging
import math
import os
import pathlib
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

import memory  # noqa: E402
import vectormemory  # noqa: E402
from bench_vocab_gap import VOCAB_CASES, check_no_overlap, wilson  # noqa: E402
from ollama_client import OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)

REAL_UID = 434893254576701450
TEST_UID = 999900000000000005

SMALL_MODEL = "qwen3:1.7b"
BIG_MODEL = "qwen3:8b"


def build_rewrite_prompt(question: str) -> str:
    """ขอคำที่ 'ความหมายใกล้เคียง' เพื่อเอาไปค้นความจำ

    ออกแบบให้สั้นและเจาะจงที่สุด เพราะโมเดลเล็กหลุดง่ายเมื่อ prompt ซับซ้อน
    ขอ JSON array เพื่อ parse ได้แน่นอน (รูปแบบเดียวกับที่โปรเจกต์ใช้ทุกที่)
    """
    return (
        "แปลงคำถามเป็น \"คำค้น\" สำหรับค้นบันทึกการสนทนาเก่า\n"
        "ตอบเป็นคำหรือวลีสั้นๆ ที่มีความหมายใกล้เคียงกับคำถาม 3-5 คำ\n"
        "กฎ:\n"
        "- ใช้คำที่คนทั่วไปใช้เขียนบันทึก ไม่ใช่คำในคำถาม\n"
        "- ถ้าคำถามใช้สำนวน ให้แปลงเป็นคำตรงๆ (เช่น \"แบกภาระ\" → \"งานหนัก\")\n"
        "- ภาษาไทยเท่านั้น ห้ามอธิบาย\n"
        "ตอบเป็น JSON array เท่านั้น เช่น [\"งานหนัก\",\"เหนื่อย\",\"ภาระ\"]\n\n"
        f"คำถาม: {question}"
    )


def parse_terms(raw: str) -> list:
    """fail-safe: parse ไม่ได้ = คืน [] (ไม่ขยายคำถาม ใช้ของเดิม)"""
    import re as _re
    txt = (raw or "").strip()
    if "</think>" in txt:
        txt = txt.rsplit("</think>", 1)[-1]
    m = _re.search(r"\[.*?\]", txt, _re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    return [t.strip() for t in arr
            if isinstance(t, str) and 1 < len(t.strip()) <= 30][:5]


async def rewrite(question: str, model: str) -> tuple:
    """คืน (คำค้นที่ขยายแล้ว, วินาทีที่ใช้)"""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_rewrite_prompt(question)}],
        "stream": False, "think": False,
        "options": {"temperature": 0},
    }
    t0 = time.perf_counter()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
                data = await r.json()
        raw = data.get("message", {}).get("content", "") or ""
    except Exception:
        return [], time.perf_counter() - t0
    return parse_terms(raw), time.perf_counter() - t0


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    args = ap.parse_args()

    summaries = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))["summaries"]
    cases, _ = check_no_overlap(summaries)

    print("=" * 96)
    print(" C2 — โมเดลเล็กขยายคำถามได้ดีพอไหม (ความจำจริง)")
    print(f" เคส {len(cases)} × {args.rounds} รอบ = n {len(cases) * args.rounds}")
    print("=" * 96)

    try:
        vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    print("\n เขียน summary ลง vector store ทดสอบ...")
    for e in summaries:
        await vectormemory.add_conversation_memory(TEST_UID, e["text"])

    variants = [("baseline (K=5)", None), ("RETRIEVE_K=20", "K20"),
                (f"rewrite {SMALL_MODEL}", SMALL_MODEL),
                ("K=20 + rewrite 1.7b", "K20+SMALL")]
    tally = {v: 0 for v, _ in variants}
    secs = {v: 0.0 for v, _ in variants}
    examples = []

    try:
        for rnd in range(args.rounds):
            print(f" รอบ {rnd + 1}/{args.rounds}...")
            for q, must in cases:
                whose = memory.guess_owner(q)
                for label, model in variants:
                    query = q
                    terms = []
                    old_k = vectormemory.RETRIEVE_K
                    if model in ("K20", "K20+SMALL"):
                        vectormemory.RETRIEVE_K = 20
                    if model in (SMALL_MODEL, "K20+SMALL"):
                        terms, dt = await rewrite(q, SMALL_MODEL)
                        secs[label] += dt
                        if terms:
                            query = q + " " + " ".join(terms)
                    kw = memory.recall_summaries({"summaries": summaries}, query)
                    vec = await vectormemory.query_conversation_memory(TEST_UID, query)
                    vectormemory.RETRIEVE_K = old_k
                    vec = memory.filter_by_owner(vec, whose)
                    blob = "\n".join(kw + vec)
                    tally[label] += any(m in blob for m in must)
                    if rnd == 0 and model == SMALL_MODEL:
                        examples.append((q, terms))
    finally:
        try:
            vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
        except Exception:
            pass

    n = len(cases) * args.rounds
    print("\n" + "=" * 96)
    print(f" {'วิธี':<24} {'ผ่าน':>10} {'ช่วง 95%':>14} {'เวลา rewrite':>16}")
    print("-" * 96)
    for label, model in variants:
        lo, hi = wilson(tally[label], n)
        avg = f"{secs[label] / n * 1000:.0f} ms/เคส" if secs[label] else "-"
        print(f" {label:<24} {tally[label]:>4}/{n:<5} {lo*100:>7.0f}-{hi*100:<4.0f}% {avg:>16}")
    print("=" * 96)

    print(f"\n ตัวอย่างคำที่ {SMALL_MODEL} ขยายให้:")
    for q, terms in examples[:10]:
        print(f"   {q[:34]:<36} → {terms}")


if __name__ == "__main__":
    asyncio.run(main())
