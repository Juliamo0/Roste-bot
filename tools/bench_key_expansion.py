"""ทดสอบ "fact-augmented key expansion" ที่เปเปอร์ LongMemEval แนะนำ

ที่มา: ผู้ใช้ทักว่าชุดทดสอบมาตรฐานน่าจะมีคำแนะนำแนบมาว่าควรแก้ยังไง — ถูกต้อง
เปเปอร์ LongMemEval (ICLR 2025) §5 เสนอ 3 อย่าง:

  1. session decomposition       เก็บเป็น "รอบ" แทน "session" ทั้งก้อน  (+11.3% recall)
  2. fact-augmented key expansion เอา fact ที่สกัดได้มาต่อหน้า index    (+9.4% recall / +5.4% acc)
  3. time-aware query expansion   ดึงช่วงเวลาจากคำถามมาจำกัดขอบเขตค้น   (+6.8-11.3% temporal)

ไฟล์นี้ทดสอบข้อ 2 เพราะตรงกับจุดอ่อนที่วัดได้ (single-session-preference 7/30)
และเรามีกลไกสกัด fact อยู่แล้ว (auto_remember) จึงต่อยอดได้เลย

วิธี: ดึงประโยคที่ "บอกความชอบ" ออกมาต่อไว้*หน้า*เนื้อความ → คำที่บอกความชอบจึงมีน้ำหนัก
มากขึ้นตอนให้คะแนน keyword โดยไม่ต้องแก้อัลกอริทึมจัดอันดับ

⚠️ วินิจฉัยก่อนหน้า: เฉลยติด top-5 13/30 แต่เป็นอันดับ 1 แค่ 4/30
   = ปัญหาการ *จัดอันดับ* — key expansion แก้ตรงจุดนี้พอดี
"""
import argparse
import io
import json
import logging
import math
import os
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import conflict_proto as proto  # noqa: E402

logging.disable(logging.CRITICAL)

DATA = "tools/data/longmemeval_s.json"

# ประโยคที่บ่งบอก "ความชอบ/นิสัย/ข้อเท็จจริงของผู้ใช้" — ใช้เป็น key ขยาย
# (ข้อมูลชุดนี้เป็นภาษาอังกฤษ จึงเขียน pattern อังกฤษ)
PREF_RE = re.compile(
    r"\b(i\s+(like|love|prefer|enjoy|hate|dislike|usually|always|never|am|have|need|want)"
    r"|my\s+favorite|i'd\s+rather|i'm\s+(a|an|really|quite))\b", re.I)


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def to_summaries(case: dict, cap: int, expand: bool) -> list:
    out = []
    for sid, sess, date in zip(case["haystack_session_ids"],
                               case["haystack_sessions"],
                               case.get("haystack_dates", [])):
        turns = [t["content"].strip() for t in sess if t.get("role") == "user"]
        if not turns:
            continue
        body = " ".join(turns)
        key = ""
        if expand:
            sents = re.split(r"(?<=[.!?])\s+", body)
            key = " ".join([s for s in sents if PREF_RE.search(s)][:4])
        iso = date.split()[0].replace("/", "-") if date else None
        text = f"{iso}: สรุปบท | user_fact:{(key + ' ' + body).strip()[:cap]}"
        out.append({"date": iso, "text": text, "_sid": sid})
    return out


def evaluate(case: dict, cap: int, expand: bool) -> bool:
    S = to_summaries(case, cap, expand)
    gold = set(case.get("answer_session_ids") or [])
    got = proto.m1_baseline(S, case["question"])
    if not got:
        return False
    top = got[0]
    for s in S:
        b = s["text"].split("user_fact:", 1)[-1][:40]
        if b and b in top:
            return s["_sid"] in gold
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=1500)
    args = ap.parse_args()

    if not os.path.exists(DATA):
        print(f"ไม่พบ {DATA} — รัน tools/fetch_longmemeval.py ก่อน")
        return
    data = json.load(open(DATA, encoding="utf-8"))

    print("=" * 92)
    print(" fact-augmented key expansion (LongMemEval §5.3 — เปเปอร์รายงาน +9.4% recall)")
    print(f" cap={args.cap} ตัวอักษร/session")
    print("=" * 92)
    print(f" {'ชนิดคำถาม':<30} {'เดิม':>10} {'+key expansion':>17} {'ต่าง':>7}")
    print("-" * 92)

    tot_a = tot_b = tot_n = 0
    for t in ("single-session-preference", "single-session-user",
              "single-session-assistant", "knowledge-update",
              "multi-session", "temporal-reasoning"):
        cs = [x for x in data if x["question_type"] == t]
        if not cs:
            continue
        a = sum(1 for c in cs if evaluate(c, args.cap, False))
        b = sum(1 for c in cs if evaluate(c, args.cap, True))
        tot_a += a
        tot_b += b
        tot_n += len(cs)
        mark = "  ✅" if b > a else ("  ❌" if b < a else "")
        print(f" {t:<30} {a:>4}/{len(cs):<5} {b:>10}/{len(cs):<5} {b - a:>+5}{mark}")

    print("-" * 92)
    la, ha = wilson(tot_a, tot_n)
    lb, hb = wilson(tot_b, tot_n)
    print(f" {'รวม':<30} {tot_a:>4}/{tot_n:<5} {tot_b:>10}/{tot_n:<5} {tot_b - tot_a:>+5}")
    print(f" ช่วง 95%: เดิม {la*100:.0f}-{ha*100:.0f}%  ·  +expansion {lb*100:.0f}-{hb*100:.0f}%")
    print(f" {'ซ้อนทับ = แยกไม่ออก' if not (lb > ha or la > hb) else 'ไม่ซ้อนทับ = ต่างจริง ✅'}")
    print("=" * 92)


if __name__ == "__main__":
    main()
