"""วัด conflict resolution ด้วย **ชุดข้อมูลมาตรฐาน** LongMemEval แทน fixture ที่เราแต่งเอง

ที่มา: ผู้ใช้ทักว่า "ระบบมันต้องทดสอบได้สิ ไม่ก็มี data ที่ทำไว้ทดสอบระบบ ไม่งั้นเราจะรู้ได้ไง
ว่ามันทำงานถูกต้อง" — ถูกต้อง และมีจริง

LongMemEval (ICLR 2025) มีชนิดคำถาม **knowledge-update** 78 ข้อ = ผู้ใช้บอกข้อมูลอย่างหนึ่ง
แล้วต่อมาเปลี่ยนใจ/อัปเดต ระบบต้องตอบด้วยค่า *ใหม่* — ตรงกับ conflict resolution ของเราเป๊ะ
แต่ละข้อมี 2 session พร้อมวันที่ และ `answer_session_ids` บอกว่า session ไหนคือคำตอบที่ถูก
= **ground truth ที่คนอื่นทำไว้ ไม่ใช่ที่เราแต่งเอง**

⚠️ ทำไมถึงสำคัญ: Phase 1 เราวัด conflict ด้วย fixture ที่ผมแต่งเอง ได้ตัวเลขสวย
แล้วสรุปว่า "KV แย่กว่า vector ล้วน" — พอเอาข้อมูลจริงมาวัด **ผลกลับด้าน**
เพราะ fixture ผมออกแบบให้มีคู่ขัดแย้งเยอะเป็นพิเศษ ซึ่งความจำจริงไม่ได้เป็นแบบนั้น
ชุดมาตรฐานช่วยตัด bias ตรงนี้ออก

⚠️ ข้อจำกัดที่ต้องบอกตรงๆ:
  - ข้อมูลเป็น **ภาษาอังกฤษ** ส่วน pipeline ของเรา tune มาสำหรับไทย
    -> ตัวเลขที่ได้สะท้อน "อัลกอริทึมเลือกของใหม่ถูกไหม" ไม่ใช่ "ระบบไทยทั้งระบบดีแค่ไหน"
  - เราวัดเฉพาะชั้น *เลือก summary ที่ถูก* ไม่ได้วัดคุณภาพคำตอบสุดท้ายของ LLM
"""
import argparse
import collections
import io
import json
import logging
import math
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import conflict_proto as proto  # noqa: E402
import memory  # noqa: E402

logging.disable(logging.CRITICAL)

# ⚠️ ต้องใช้ไฟล์ _s (มี distractor 40 session/ข้อ) ไม่ใช่ oracle
# oracle มีแต่ evidence session และ answer_session_ids = ทั้งสอง session
# -> ทุกวิธีได้ 78/78 เพราะตอบอะไรก็ถูก = เบนช์วัดอะไรไม่ได้เลย (เจอจริงตอนรันรอบแรก)
DATA = "tools/data/longmemeval_s.json"


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def to_summaries(case: dict) -> list:
    """แปลง session ของ LongMemEval เป็นรูปแบบ summary ของเรา

    ใช้ข้อความ *ของผู้ใช้* เท่านั้น (ฝั่ง assistant เป็นคำตอบของบอท ไม่ใช่ข้อเท็จจริงผู้ใช้)
    ติด tag user_fact ให้เพื่อให้ split_owner_tags/filter_by_owner ทำงานได้เหมือนของจริง
    """
    out = []
    for sid, sess, date in zip(case["haystack_session_ids"],
                               case["haystack_sessions"],
                               case.get("haystack_dates", [])):
        user_turns = [t["content"].strip() for t in sess if t.get("role") == "user"]
        if not user_turns:
            continue
        body = " ".join(user_turns)[:400]
        iso = date.split()[0].replace("/", "-") if date else None
        out.append({"date": iso, "text": f"{iso}: สรุปบท | user_fact:{body}",
                    "_sid": sid})
    return out


def evaluate(case: dict, method) -> bool:
    """วิธีนี้เลือก session ที่ถูก (ตาม answer_session_ids) เป็นอันดับ 1 ไหม"""
    summaries = to_summaries(case)
    if len(summaries) < 2:
        return False
    gold = set(case.get("answer_session_ids") or [])
    got = method(summaries, case["question"])
    if not got:
        return False
    # จับคู่บรรทัดที่คืนมากลับไปหา session ต้นทาง
    top = got[0]
    for s in summaries:
        body = s["text"].split("user_fact:", 1)[-1][:60]
        if body and body[:40] in top:
            return s["_sid"] in gold
    return False


def run_all_types(data: list, args) -> None:
    """วัดทุกชนิดคำถาม — บอกว่าระบบพังตรงชนิดไหน (แผนที่จุดอ่อน)

    ใช้ M1 (baseline = ระบบปัจจุบัน) เพราะวัดแล้วว่า M2/M3 ไม่ช่วย
    """
    by_type = collections.defaultdict(list)
    for c in data:
        by_type[c["question_type"]].append(c)

    print("=" * 96)
    print(" แผนที่จุดอ่อน — recall ปัจจุบันทำได้แค่ไหนในแต่ละชนิดคำถาม")
    print(f" LongMemEval-S · {len(data)} ข้อ · 40 session/ข้อ")
    print("=" * 96)
    print(f" {'ชนิดคำถาม':<30} {'ผ่าน':>12} {'ช่วง 95%':>14}")
    print("-" * 96)

    fails = []
    for t in sorted(by_type, key=lambda x: -len(by_type[x])):
        cases = by_type[t][:args.limit] if args.limit else by_type[t]
        ok = 0
        for c in cases:
            r = evaluate(c, lambda s, q: proto.m1_baseline(s, q))
            ok += r
            if not r:
                fails.append((t, c))
        lo, hi = wilson(ok, len(cases))
        flag = "  <-- อ่อนสุด" if ok / len(cases) < 0.5 else ""
        print(f" {t:<30} {ok:>5}/{len(cases):<6} {lo*100:>6.0f}-{hi*100:<6.0f}%{flag}")
    print("=" * 96)

    if args.show_fail:
        print("\n ตัวอย่างเคสที่พลาด:")
        for t, c in fails[:args.show_fail]:
            print(f"\n [{t}] {c['question'][:80]}")
            print(f"    เฉลย: {str(c['answer'])[:80]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="จำกัดจำนวนข้อ (0 = ทั้งหมด)")
    ap.add_argument("--all-types", action="store_true",
                    help="วัดทุกชนิดคำถาม ไม่ใช่แค่ knowledge-update")
    ap.add_argument("--show-fail", type=int, default=0, help="โชว์เคสที่พลาด N ข้อ")
    args = ap.parse_args()

    if not os.path.exists(DATA):
        print(f"ไม่พบ {DATA} — ดาวน์โหลดจาก HuggingFace xiaowu0162/longmemeval-cleaned ก่อน")
        return

    data = json.load(open(DATA, encoding="utf-8"))
    if args.all_types:
        run_all_types(data, args)
        return
    ku = [x for x in data if x["question_type"] == "knowledge-update"]
    if args.limit:
        ku = ku[:args.limit]

    print("=" * 96)
    print(" conflict resolution วัดด้วยชุดมาตรฐาน LongMemEval (knowledge-update)")
    n_sess = len(ku[0]["haystack_sessions"]) if ku else 0
    print(f" {len(ku)} ข้อ · {n_sess} session/ข้อ (gold 2) · ground truth จากชุดข้อมูล")
    print(" ⚠️ ข้อมูลภาษาอังกฤษ — วัด *อัลกอริทึม* ไม่ใช่ pipeline ไทยทั้งระบบ")
    print("=" * 96)

    methods = [
        ("M1 baseline (ไม่แก้ขัดแย้ง)", lambda s, q: proto.m1_baseline(s, q)),
        ("M2 recency-wins", lambda s, q: proto.m2_recency_wins(s, q)),
        ("M3 deterministic supersede", lambda s, q: proto.m3_deterministic(s, q)),
    ]

    print(f"\n {'วิธี':<32} {'เลือกถูก':>12} {'ช่วง 95%':>14}")
    print("-" * 96)
    results = {}
    for label, fn in methods:
        ok = sum(1 for c in ku if evaluate(c, fn))
        lo, hi = wilson(ok, len(ku))
        results[label] = ok
        print(f" {label:<32} {ok:>5}/{len(ku):<6} {lo*100:>6.0f}-{hi*100:<6.0f}%")
    print("=" * 96)

    best = max(results, key=results.get)
    b_lo, b_hi = wilson(results[best], len(ku))
    base_lo, base_hi = wilson(results["M1 baseline (ไม่แก้ขัดแย้ง)"], len(ku))
    overlap = not (b_lo > base_hi or base_lo > b_hi)
    print(f"\n ดีสุด: {best}")
    print(f" เทียบกับ baseline: {'ช่วงซ้อนทับ = แยกไม่ออกทางสถิติ' if overlap else 'ต่างจริง ✅'}")


if __name__ == "__main__":
    main()
