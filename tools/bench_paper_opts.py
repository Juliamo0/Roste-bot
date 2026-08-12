"""ทดสอบ **ทั้ง 3 ข้อ** ที่เปเปอร์ LongMemEval แนะนำ กับ retriever ของเรา

เปเปอร์ LongMemEval (ICLR 2025) §5 เสนอ 3 optimization พร้อมตัวเลขที่เขาวัดได้:
    1. session decomposition        เก็บเป็น "รอบ" แทน session ทั้งก้อน  (+11.3% recall)
    2. fact-augmented key expansion เอา fact ที่สกัดได้มาต่อหน้า index   (+9.4% recall)
    3. time-aware query expansion   ดึงช่วงเวลาจากคำถามมาจำกัดขอบเขตค้น  (+6.8-11.3%)

⚠️ ตัวเลขของเขาวัดกับ retriever แบบ **embedding** ส่วนของเราให้คะแนนด้วย **keyword count**
   จึงต้องวัดเองว่าถ่ายทอดมาได้ไหม — ข้อ 2 ลองแล้วได้ +1/500 (ไม่ช่วย) เพราะเหตุผลนี้

วัดบนชุดเดียวกัน 500 ข้อ · cap 1500 ตัวอักษร (ค่าที่วัดแล้วว่าไม่ตัดเนื้อหาทิ้งเกินไป)
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

import memory  # noqa: E402
import conflict_proto as proto  # noqa: E402

logging.disable(logging.CRITICAL)

DATA = "tools/data/longmemeval_s.json"
CAP = 1500

PREF_RE = re.compile(
    r"\b(i\s+(like|love|prefer|enjoy|hate|dislike|usually|always|never|am|have|need|want)"
    r"|my\s+favorite|i'd\s+rather|i'm\s+(a|an|really|quite))\b", re.I)

# ── ข้อ 3: ดึงช่วงเวลาจากคำถาม (rule-based แทน LLM เพื่อไม่ให้ช้า/แกว่ง) ──
_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_TIME_RE = re.compile(
    r"\b(last|this|next)\s+(week|month|year|summer|winter|spring|fall)"
    r"|\b(19|20)\d{2}\b|\b(" + "|".join(_MONTHS) + r")\b"
    r"|\b(yesterday|today|recently|ago)\b", re.I)


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def build(case: dict, decompose: bool, expand: bool) -> list:
    """แปลง session -> summary ตามตัวเลือกที่เปิด

    decompose=True  -> แตกเป็น "รอบ" (1 user turn = 1 หน่วยความจำ) ตามข้อ 1
    expand=True     -> ต่อประโยคที่บอกความชอบไว้หน้าเนื้อความ ตามข้อ 2
    """
    out = []
    for sid, sess, date in zip(case["haystack_session_ids"],
                               case["haystack_sessions"],
                               case.get("haystack_dates", [])):
        turns = [t["content"].strip() for t in sess if t.get("role") == "user"]
        if not turns:
            continue
        iso = date.split()[0].replace("/", "-") if date else None
        units = turns if decompose else [" ".join(turns)]
        for u in units:
            key = ""
            if expand:
                sents = re.split(r"(?<=[.!?])\s+", u)
                key = " ".join([s for s in sents if PREF_RE.search(s)][:4])
            body = (key + " " + u).strip()[:CAP]
            if not body:
                continue
            out.append({"date": iso, "text": f"{iso}: สรุปบท | user_fact:{body}",
                        "_sid": sid})
    return out


def query_years(question: str, dates: list) -> set:
    """ข้อ 3: ถ้าคำถามอ้างถึงเวลา ให้จำกัดขอบเขตเป็นช่วงที่เกี่ยวข้อง

    ⚠️ ใช้ rule-based ไม่ใช่ LLM — เปเปอร์ใช้ LLM แต่เราต้องรัน 500 ข้อ x หลายแบบ
    ถ้าเรียก LLM ทุกข้อจะช้ามากและผลแกว่ง (และเราสนใจว่า *แนวคิด* ช่วยไหม)

    ⚠️ รอบแรกกรองระดับ "ปี" ซึ่งเป็น no-op — ข้อมูลทั้งชุดอยู่ปี 2023 หมด
       (ตรวจแล้ว: เหลือ 49/49 session) จึงเปลี่ยนเป็นระดับ **เดือน**
       "recently/last month" -> เอา 2 เดือนล่าสุด · ระบุชื่อเดือน -> เอาเดือนนั้น
    """
    q = question.lower()
    if not _TIME_RE.search(q):
        return set()
    months = sorted({d[:7] for d in dates if d})
    if not months:
        return set()
    # ระบุชื่อเดือนตรงๆ -> เอาเฉพาะเดือนนั้น
    named = [i + 1 for i, m in enumerate(_MONTHS) if re.search(rf"\b{m}\b", q)]
    if named:
        want = {f"{mm:02d}" for mm in named}
        sel = {m for m in months if m[5:7] in want}
        if sel:
            return sel
    # "recently / last month / ago" -> เอาช่วงท้าย (2 เดือนล่าสุด)
    if re.search(r"\b(recently|last|ago|yesterday|this)\b", q):
        return set(months[-2:])
    return set()


def evaluate(case: dict, decompose: bool, expand: bool, time_filter: bool) -> bool:
    S = build(case, decompose, expand)
    if not S:
        return False
    if time_filter:
        keep = query_years(case["question"], [s["date"] or "" for s in S])
        if keep:
            filt = [s for s in S if (s["date"] or "")[:7] in keep]
            if filt:
                S = filt
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
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    if not os.path.exists(DATA):
        print(f"ไม่พบ {DATA} — รัน tools/fetch_longmemeval.py ก่อน")
        return
    data = json.load(open(DATA, encoding="utf-8"))
    types = ["single-session-preference", "single-session-user",
             "single-session-assistant", "knowledge-update",
             "multi-session", "temporal-reasoning"]

    variants = [
        ("baseline (ของเรา)", False, False, False),
        ("1. session decomposition", True, False, False),
        ("2. key expansion", False, True, False),
        ("3. time-aware filter", False, False, True),
        ("1+2+3 ทั้งหมด", True, True, True),
    ]

    print("=" * 104)
    print(" ทดสอบทั้ง 3 optimization ที่เปเปอร์ LongMemEval แนะนำ กับ retriever ของเรา")
    print(f" 500 ข้อ · cap {CAP} ตัวอักษร · ⚠️ เปเปอร์วัดกับ embedding เราใช้ keyword count")
    print("=" * 104)

    header = f" {'วิธี':<28}"
    for t in types:
        header += f" {t.replace('single-session-', 'ss-')[:11]:>12}"
    header += f" {'รวม':>10}"
    print(header)
    print("-" * 104)

    base_total = None
    for label, dec, exp, tf in variants:
        row = f" {label:<28}"
        tot = n = 0
        for t in types:
            cs = [x for x in data if x["question_type"] == t]
            if args.limit:
                cs = cs[:args.limit]
            ok = sum(1 for c in cs if evaluate(c, dec, exp, tf))
            tot += ok
            n += len(cs)
            row += f" {ok:>5}/{len(cs):<6}"
        lo, hi = wilson(tot, n)
        diff = "" if base_total is None else f" ({tot - base_total:+d})"
        row += f" {tot:>4}/{n}{diff}"
        print(row)
        print(f" {'':<28} {'':>12} ช่วง 95%: {lo*100:.0f}-{hi*100:.0f}%")
        if base_total is None:
            base_total = tot
    print("=" * 104)


if __name__ == "__main__":
    main()
