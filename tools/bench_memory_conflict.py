"""Phase 0 ข้อ 1: วัด **baseline** ว่าปัญหาความขัดแย้งในความทรงจำใหญ่แค่ไหนจริง

ทำไมวัดที่ชั้น retrieval ก่อน (ไม่เรียกโมเดล):
  MEMORY_EXPERIMENTS §3 บันทึกบทเรียนไว้ว่า bench รุ่นก่อน "เกือบลืมวัดส่วนอ่าน/ค้น" —
  ป้อน summary ที่เขียนตายตัวให้วิธีต่างๆ หยิบตรงๆ ตัวเลขจึงสมมติว่าส่วนค้นสมบูรณ์แบบ
  ของจริงไม่ใช่ รอบนี้จึงวัดส่วนค้นก่อน แล้วค่อยวัดผ่านโมเดลทีหลัง

  ข้อดีอีกอย่าง: ชั้นนี้ deterministic — รันซ้ำได้ผลเท่าเดิม ไม่ต้องใช้ Wilson CI
  (CI จำเป็นตอนวัดผ่านโมเดล ซึ่งผลแกว่ง — ดู bench_memory_e2e.py)

คำถามที่ bench นี้ต้องตอบ:
  1. summary ที่ขัดแย้งกัน ถูกดึงมา *พร้อมกัน* เข้า context ไหม (= ต้นเหตุที่โมเดลตอบมั่ว)
  2. ถ้าดึงมาพร้อมกัน โมเดลจะเห็นค่าเก่ากับค่าใหม่ปนกันในบล็อกเดียว — วัดเป็นตัวเลขได้
  3. ชุด historical: ค่าเก่ายังหาเจอไหม (ถ้าวิธีแก้ในอนาคตลบของเก่าทิ้ง ชุดนี้จะพัง)

⚠️ ไม่แตะข้อมูลผู้ใช้จริง — ใช้ memory_conflict_fixture ที่แต่งขึ้นเอง
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
from memory_conflict_fixture import (ALL_SETS, SUMMARIES)  # noqa: E402

logging.disable(logging.CRITICAL)

MEM = {"summaries": [dict(s) for s in SUMMARIES], "facts": [], "history": []}

# ── คู่ขัดแย้ง: (คำของค่าเก่า, คำของค่าใหม่, ชื่อเรื่อง) ──────────────────────
#
# ใช้ตรวจว่าบล็อกที่ส่งเข้า context มี "ทั้งสองค่า" พร้อมกันไหม
# นี่คือตัวชี้วัดต้นเหตุโดยตรง — ถ้ามีทั้งคู่ โมเดลต้องเดาเอง และ §7 บันทึกไว้แล้วว่า
# qwen3:8b เลือกวิธี "เอามารวมกัน" ไม่ใช่ "เลือกอันใหม่"
CONFLICT_PAIRS = [
    ("สืบสวน", "ไซไฟ", "แนวนิยาย"),
    ("ชุมพร", "เชียงใหม่", "ที่อยู่"),
    ("หุ่นยนต์", "ดอกไม้", "งานอดิเรกรอสเต้"),
]


def recall_block(question: str) -> list:
    """ระบบปัจจุบัน (M1 baseline): recall_summaries + filter_by_owner ตามที่ chat.py ทำจริง

    จำลอง chat.py:586-623 ฝั่ง keyword — ไม่รวม vector เพราะ vector ต้องเรียก LLM rerank
    (ผลแกว่ง + ช้า) และคำถามข้อ 1-3 ตอบได้ด้วยชั้น keyword ล้วน
    """
    got = memory.recall_summaries(MEM, question)
    return got


def count_conflicts(lines: list, must: list, forbid: list) -> list:
    """คืนรายชื่อเรื่องที่ *มีทั้งค่าเก่าและค่าใหม่* อยู่ในบล็อกเดียวกัน

    ⚠️ นับเฉพาะคู่ที่ *เกี่ยวกับคำถามนี้* — เดิมนับทุกคู่ที่โผล่ในบล็อก ซึ่งให้ผลผิดทิศ:
    คำถามเรื่องเครื่องดื่มถูกรายงานว่า "ขัดแย้งเรื่องแนวนิยาย" เพราะ recall_summaries
    คืน top-5 โดยไม่มีเกณฑ์คะแนนขั้นต่ำ (memory.py:594 `score > 0`) — summary เรื่องนิยาย
    ติดมาด้วยเพราะมีคำว่า "ชอบ" ร่วมกับคำถามเท่านั้น

    นั่นเป็นปัญหาจริงของระบบ (บล็อกมีของไม่เกี่ยวปน) แต่เป็น *คนละปัญหา* กับความขัดแย้ง
    ที่ bench นี้วัด ถ้านับรวมกันจะสรุปสาเหตุผิด — แยกไปรายงานเป็น noise_rate ต่างหาก
    """
    blob = "\n".join(lines)
    topic_words = set(must) | set(forbid)
    hits = []
    for old, new, topic in CONFLICT_PAIRS:
        if not topic_words & {old, new}:
            continue          # คู่นี้ไม่เกี่ยวกับคำถามนี้ ไม่นับ
        if old in blob and new in blob:
            hits.append(topic)
    return hits


def count_noise(lines: list, must: list, forbid: list) -> int:
    """นับ summary ที่ไม่เกี่ยวกับคำถามเลย — ผลพลอยได้จากการไม่มีเกณฑ์คะแนนขั้นต่ำ"""
    topic_words = set(must) | set(forbid)
    if not topic_words:
        return 0
    return sum(1 for ln in lines if not any(w in ln for w in topic_words))


def judge(lines: list, must: list, forbid: list) -> tuple:
    """ถูก = มีคำที่ต้องมี (อย่างน้อย 1) และไม่มีคำที่ห้ามมีเลย"""
    blob = "\n".join(lines)
    bad = []
    if must and not any(w in blob for w in must):
        bad.append(f"ไม่เจอ {must}")
    if forbid:
        leaked = [w for w in forbid if w in blob]
        if leaked:
            bad.append(f"มีค่าที่ไม่ควรมี {leaked}")
    return (not bad), bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="พิมพ์บล็อกที่ดึงมาทุกเคส")
    args = ap.parse_args()

    print("=" * 96)
    print(" Phase 0 — baseline M1 (append-only ปัจจุบัน) ที่ชั้น retrieval")
    print(f" ความทรงจำ: {len(SUMMARIES)} summary — มีคู่ขัดแย้ง {len(CONFLICT_PAIRS)} คู่")
    print(" ไม่เรียกโมเดล → ผลไม่แกว่ง รันซ้ำได้เท่าเดิม")
    print("=" * 96)

    grand_ok = grand_n = 0
    conflict_exposed = 0
    noise_total = lines_total = 0
    per_set = {}

    for set_name, cases in ALL_SETS:
        ok_n = 0
        print(f"\n{'=' * 96}\n  ชุด {set_name} — {len(cases)} เคส\n{'=' * 96}")
        for q, whose, must, forbid in cases:
            lines = recall_block(q)
            ok, bad = judge(lines, must, forbid)
            conf = count_conflicts(lines, must, forbid)
            ok_n += ok
            if conf:
                conflict_exposed += 1
            noise_total += count_noise(lines, must, forbid)
            lines_total += len(lines)

            mark = "✅" if ok else "❌"
            flag = f"  ⚠️ ขัดแย้งใน context: {','.join(conf)}" if conf else ""
            print(f"  {mark} [{whose:<4}] {q[:40]:<42} คืน {len(lines)} อัน{flag}")
            if not ok:
                print(f"        → {', '.join(bad)}")
            if args.verbose or (not ok and lines):
                for ln in lines:
                    print(f"          · {ln[:84]}")

        per_set[set_name] = (ok_n, len(cases))
        grand_ok += ok_n
        grand_n += len(cases)

    print("\n" + "=" * 96)
    print(f" {'ชุด':<16} {'ผ่าน':>12}   หมายเหตุ")
    print("-" * 96)
    notes = {
        "dynamic": "ค่าใหม่ต้องชนะ — จุดที่ append-only ควรพัง",
        "historical": "ถามของเก่า — วิธีที่ลบของเก่าทิ้งจะพังชุดนี้",
        "static": "ขัดแย้งหลอก — วิธีที่ไวเกินจะพังชุดนี้",
        "conditional": "ขึ้นกับบริบท — max(date) ล้วนจะพังชุดนี้",
    }
    for set_name, (ok, n) in per_set.items():
        print(f" {set_name:<16} {ok:>5}/{n:<6}   {notes.get(set_name, '')}")
    print("-" * 96)
    print(f" {'รวม':<16} {grand_ok:>5}/{grand_n:<6}")
    print(f"\n เคสที่ context มีค่าเก่า+ค่าใหม่ของ *เรื่องที่ถาม* ปนกัน: {conflict_exposed}/{grand_n}")
    print("   (นี่คือ *ต้นเหตุ* โดยตรง — โมเดลได้ข้อมูลขัดแย้งไปตัดสินเอง)")
    pct = 100 * noise_total / lines_total if lines_total else 0
    print(f"\n summary ที่ไม่เกี่ยวกับคำถามเลย: {noise_total}/{lines_total} บรรทัด ({pct:.0f}%)")
    print("   (คนละปัญหากับความขัดแย้ง — มาจาก recall_summaries คืน top-5 โดยไม่มีเกณฑ์")
    print("    คะแนนขั้นต่ำ memory.py:594 `score > 0` คำร่วมคำเดียวเช่น 'ชอบ' ก็ติดมาแล้ว)")
    print("=" * 96)

    print("\n⚠️ อ่านผลยังไง: ห้ามดูแค่ตัวเลขรวม — trade-off อยู่ที่ dynamic ขึ้นแล้ว")
    print("   historical/static/conditional ต้องไม่ตก นั่นคือสิ่งที่ Phase 1 ต้องเทียบ")


if __name__ == "__main__":
    main()
