"""ทดสอบส่วนที่ 2 ของ pipeline ความจำ: **อ่าน/ค้น** — ส่วนที่ยังไม่เคยวัดเลย

pipeline ความจำมี 3 ส่วน:
    1. บันทึก  → build_summary_prompt        (วัดแล้ว: วิธี F ชนะ 87%)
    2. อ่าน/ค้น → recall_summaries / vector   ← ไฟล์นี้
    3. ส่ง     → ยัดเข้า system prompt        (วัดแล้ว: P3 ชนะ 88%)

ทำไมส่วนนี้สำคัญ: bench ก่อนหน้า *ข้าม* ส่วนนี้ไปเลย — ป้อน SUMMARIES ที่เขียนไว้ตายตัว
ให้ P1/P2/P3 หยิบจากกองนั้นตรงๆ ตัวเลข 88% ของ P3 จึงสมมติว่าส่วนที่ 2 ทำงานสมบูรณ์แบบ
ของจริงมีด่านก่อนหน้าอีก 2 ชั้นที่อาจคืน [] ตั้งแต่แรก:
    - memory.recall_summaries ต้องเจอคำใน PAST_HINTS ก่อน ไม่งั้นคืน [] ทันที
      ("ผมชอบอ่านอะไร" ไม่มีคำใบ้อดีตเลย → ไม่ค้นอะไรเลย)
    - ให้คะแนนด้วยการนับคำตรง — ถ้า summary ใช้คำอื่น (นิยาย vs การอ่าน) ก็ไม่เจอ

⚠️ ไม่แตะ production — เรียก memory.recall_summaries ตัวจริงมาวัด แล้วเทียบกับ
   build_memory_block (P3 prototype) ว่าตัวไหนหยิบของถูกกว่ากัน
⚠️ ไม่ใช้บทสนทนาจริงของผู้ใช้ — ใช้ memory_fixture ที่แต่งขึ้นเอง (ดูเหตุผลในไฟล์นั้น)

วัดที่ระดับ "หยิบถูกไหม" ล้วนๆ ไม่เรียกโมเดลเลย → เร็ว รันซ้ำได้ ผลไม่แกว่ง
"""
import argparse
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging  # noqa: E402

import memory  # noqa: E402
from memory_fixture import CASES, HARD_CASES, SUMMARIES  # noqa: E402
from memory_tool_proto import build_memory_block, guess_owner  # noqa: E402

logging.disable(logging.CRITICAL)

MEM = {"summaries": [{"date": "2026-08-01", "text": s} for s in SUMMARIES],
       "facts": [], "history": []}


def eval_current(question: str):
    """ระบบปัจจุบัน: memory.recall_summaries (keyword + PAST_HINTS gate)"""
    got = memory.recall_summaries(MEM, question)
    return "\n".join(got), len(got)


def eval_p3(question: str):
    """P3: กรองฝั่งเจ้าของก่อน (ยังใช้ keyword หาแต่ไม่มี PAST_HINTS gate)"""
    block, _ = build_memory_block(SUMMARIES, question)
    return block, len([ln for ln in block.splitlines() if ln.strip()])


def judge(block: str, whose: str, must: list, forbid: list) -> tuple:
    """ตรวจว่าบล็อกที่จะส่งให้โมเดล มีของถูกและไม่มีของผิด"""
    bad = []
    if whose == "none":
        # หัวข้อที่ไม่มีในความทรงจำ — ควรได้บล็อกว่าง (ไม่มีอะไรให้ส่ง)
        if block.strip():
            bad.append("ดึงของไม่เกี่ยวมา")
        return (not bad), bad
    if must and not any(w in block for w in must):
        bad.append(f"ไม่เจอ {must}")
    if forbid and any(w in block for w in forbid):
        bad.append(f"มีของอีกฝั่งปน {[w for w in forbid if w in block]}")
    return (not bad), bad


def run_set(name: str, cases: list, methods: list) -> dict:
    print(f"\n{'#' * 100}\n# {name} — {len(cases)} เคส\n{'#' * 100}")
    out = {}
    for label, fn in methods:
        ok_n = 0
        rows = []
        for q, whose, must, forbid in cases:
            block, cnt = fn(q)
            ok, bad = judge(block, whose, must, forbid)
            ok_n += ok
            rows.append((q, whose, ok, bad, cnt, block))
        out[label] = ok_n

        print(f"\n{'=' * 100}\n  {label}: {ok_n}/{len(cases)}\n{'=' * 100}")
        for q, whose, ok, bad, cnt, block in rows:
            mark = "✅" if ok else "❌"
            print(f"  {mark} [{whose:<4}] {q[:44]:<46} คืน {cnt} อัน")
            if not ok:
                print(f"        → {', '.join(bad)}")
                first = block.splitlines()[0] if block.strip() else "(ว่าง)"
                print(f"        → {first[:88]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()

    print("=" * 100)
    print(f" ทดสอบส่วน 'อ่าน/ค้น' (ไม่เรียกโมเดล ผลไม่แกว่ง)")
    print(f" ความทรงจำ: {len(SUMMARIES)} summary (fixture แต่งขึ้นเอง ไม่ใช่บทสนทนาจริง)")
    print("=" * 100)

    methods = [("ปัจจุบัน (recall_summaries)", eval_current),
               ("P3 (กรองฝั่งเจ้าของ)", eval_p3)]

    r_easy = run_set("ชุดปกติ", CASES, methods)
    r_hard = run_set("ชุดหิน (เขียนเพื่อหาจุดพัง)", HARD_CASES, methods)

    print("\n" + "=" * 100)
    print(f" {'วิธี':<32} {'ชุดปกติ':>10} {'ชุดหิน':>10} {'รวม':>10}")
    print("-" * 100)
    for label, _ in methods:
        e, h = r_easy[label], r_hard[label]
        print(f" {label:<32} {e:>5}/{len(CASES):<4} {h:>5}/{len(HARD_CASES):<4} "
              f"{e+h:>5}/{len(CASES)+len(HARD_CASES)}")
    print("=" * 100)

    # แยกดูเคสที่ไม่มีคำใบ้อดีต — จุดที่ PAST_HINTS gate ตัดทิ้ง
    print("\n เคสที่ไม่มีคำใบ้อดีต (PAST_HINTS ไม่ครอบ):")
    for q, whose, must, forbid in CASES:
        has_hint = any(h in q for h in memory.PAST_HINTS)
        if has_hint:
            continue
        cur, _ = eval_current(q)
        p3, _ = eval_p3(q)
        print(f"   {q[:44]:<46} ปัจจุบัน={'มีของ' if cur.strip() else 'ว่าง'}  "
              f"P3={'มีของ' if p3.strip() else 'ว่าง'}")

    print("\n หมายเหตุ: guess_owner ใช้เดาฝั่ง — ตรวจว่าเดาถูกด้วย")
    for q, whose, _, _ in CASES:
        if whose == "none":
            continue
        got = guess_owner(q)
        mark = "✅" if got == whose else "❌"
        print(f"   {mark} {q[:46]:<48} เดา={got} คาด={whose}")


if __name__ == "__main__":
    main()
