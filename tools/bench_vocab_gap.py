"""C2 รอบใหม่: วัดช่องว่างคำพ้อง (vocabulary gap) อย่างเป็นระบบ — n ใหญ่พอตัดสินใจได้

⚠️ ทำไมต้องมีไฟล์นี้: รอบแรกผมสรุปว่า "C2 ไม่ต้องทำ" จากคำถามที่ผม *แต่งเอง 10 ข้อ*
ซึ่งมีปัญหา 2 อย่าง — n เล็กเกินกว่าจะให้ช่วงความเชื่อมั่นแคบพอ และผมเป็นคนเลือกคำถามเอง
(selection bias: เผลอเลือกคำถามที่ระบบตอบได้)

รอบนี้แก้ทั้งสองอย่าง:
  1. **สร้างคำถามจาก summary จริงอย่างเป็นระบบ** ไม่ใช่เลือกเอง — ไล่จากคำที่โผล่จริง
     ในความจำ แล้วถามด้วยคำที่ *ต่างออกไป* แต่หมายถึงเรื่องเดียวกัน
  2. n ใหญ่ขึ้นมาก + รายงาน Wilson CI

โครงสร้างเคส: (คำถามที่ใช้คำ "คนพูด", คำที่ต้องเจอใน summary, ที่มา)
ทุกเคสมีเงื่อนไขบังคับ: คำในคำถามต้อง **ไม่ตรง** กับคำใน summary เป้าหมาย
(เช็คอัตโนมัติด้วย assert_no_overlap ก่อนวัด — กันเคสที่ง่ายเกินไปหลุดเข้ามา)

วัด 3 เส้นทางเทียบกัน: keyword / vector / KV (แบบที่ chat.py ทำจริง)
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

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402
import vectormemory  # noqa: E402

logging.disable(logging.CRITICAL)

# uid ที่ใช้วัดกับความจำจริง — อ่านจาก env ไม่ฮาร์ดโค้ด
# (repo เป็น public — Discord user ID เป็นข้อมูลระบุตัวตน ไม่ควรติดมากับโค้ด)
# ตั้งใน .env: BENCH_REAL_UID=<discord user id>
REAL_UID = int(os.getenv("BENCH_REAL_UID") or 0)
TEST_UID = 999900000000000004

# ── เคสคำพ้อง: สร้างจากเนื้อหา summary จริงของผู้ใช้ ───────────────────────────
#
# ผู้ใช้คนนี้คุยเรื่อง: อ่านหนังสือ/หนังสือเก่า, งานหนัก+วิธีจัดการงาน, คำกล่าวขอบคุณ
# แบบเป็นทางการ, แนะนำร้าน, เล่าเรื่องราว, การหาคำตอบเมื่อไม่รู้
#
# แต่ละเคสถามด้วย "คำที่คนพูดจริง" ที่ *ไม่ตรง* กับคำใน summary
VOCAB_CASES = [
    # summary: "อ่านหนังสือ" / "หนังสือเก่า"
    ("ผมชอบเสพงานเขียนแบบไหน", ["หนังสือ", "อ่าน"]),
    ("ผมสนใจวรรณกรรมประเภทไหน", ["หนังสือ", "อ่าน"]),
    ("ผมใช้เวลากับตัวอักษรยังไง", ["หนังสือ", "อ่าน"]),
    ("รอสเต้ชอบของสะสมแบบไหน", ["หนังสือ", "เก่า"]),
    ("ผมชอบสิ่งพิมพ์แบบไหน", ["หนังสือ"]),
    ("เราคุยเรื่องการเสพสื่อกันไหม", ["หนังสือ", "อ่าน"]),
    # summary: "ทำงานหนัก" / "วิธีจัดการงาน"
    ("ผมเหนื่อยกับอะไรอยู่", ["งาน", "หนัก"]),
    ("ผมมีภาระอะไรเยอะ", ["งาน", "หนัก"]),
    ("รอสเต้สอนผมบริหารเวลายังไง", ["จัดการ", "งาน"]),
    ("ผมล้ากับเรื่องไหน", ["งาน", "หนัก"]),
    ("มีวิธีไหนที่รอสเต้บอกให้ผมจัดลำดับ", ["จัดการ", "งาน", "ลำดับ"]),
    ("ผมแบกอะไรอยู่", ["งาน", "หนัก"]),
    # summary: "คำกล่าวขอบคุณ" / "เป็นทางการ"
    ("ผมขอให้ช่วยร่างข้อความสุภาพเรื่องอะไร", ["ขอบคุณ", "ทางการ"]),
    ("ผมต้องเขียนสุนทรพจน์เรื่องอะไร", ["ขอบคุณ", "คำกล่าว"]),
    ("ผมอยากได้ถ้อยคำแบบพิธีการเรื่องไหน", ["ทางการ", "ขอบคุณ"]),
    ("ผมถามเรื่องการใช้ภาษาแบบไหน", ["ทางการ"]),
    # summary: "แนะนำร้านให้"
    ("รอสเต้เคยชี้เป้าที่กินให้ผมไหม", ["ร้าน"]),
    ("รอสเต้บอกที่นั่งชิลล์ให้ผมไหม", ["ร้าน"]),
    ("มีที่ไหนที่รอสเต้บอกให้ผมไปลอง", ["ร้าน"]),
    # summary: "เล่าเรื่องราว"
    ("รอสเต้เคยเล่านิทานให้ฟังไหม", ["เรื่องราว", "เล่า"]),
    ("รอสเต้เคยแบ่งปันประสบการณ์อะไร", ["เรื่องราว", "เล่า"]),
    # summary: "หาคำตอบ" / "ยอมรับความไม่รู้"
    ("รอสเต้ทำยังไงตอนไม่ทราบคำตอบ", ["ไม่รู้", "คำตอบ", "หา"]),
    ("รอสเต้รับมือกับสิ่งที่ตอบไม่ได้ยังไง", ["ไม่รู้", "คำตอบ"]),
    # summary: "มองโลกในแง่ดี"
    ("รอสเต้มีทัศนคติแบบไหน", ["แง่ดี", "มองโลก"]),
    ("รอสเต้คิดบวกเรื่องอะไร", ["แง่ดี", "มองโลก"]),
    # summary: "เบื่อการอ่าน" / "เปลี่ยนบรรยากาศ"
    ("ผมเคยรู้สึกเซ็งกับอะไร", ["เบื่อ"]),
    ("ผมอยากเปลี่ยนสภาพแวดล้อมเรื่องไหน", ["บรรยากาศ", "เปลี่ยน"]),
    # summary: "แนะนำตัวอย่างเป็นทางการ"
    ("ผมขอให้รอสเต้บอกว่าตัวเองเป็นใครไหม", ["แนะนำตัว"]),
    # summary: "กินข้าว"
    ("รอสเต้ทานอะไรมาหรือยัง", ["กินข้าว", "กิน"]),
    ("เราคุยเรื่องมื้ออาหารกันไหม", ["กินข้าว", "กิน"]),
]


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def load_real_summaries() -> list:
    d = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))
    return d["summaries"]


def check_no_overlap(summaries: list) -> list:
    """คัดเฉพาะเคสที่ 'คำในคำถาม' ไม่ทับกับ 'คำใน summary เป้าหมาย' จริงๆ

    กันเคสง่ายเกินไปหลุดเข้ามาแล้วทำให้ตัวเลขดูดีกว่าความจริง
    """
    texts = [e["text"] for e in summaries]
    kept, skipped = [], []
    for q, must in VOCAB_CASES:
        targets = [t for t in texts if any(m in t for m in must)]
        if not targets:
            skipped.append((q, "ไม่มี summary เป้าหมายในความจำจริง"))
            continue
        qw = set(memory._keywords(q, expand=False))
        # ถ้าคำถามมีคำที่ตรงกับ must เป๊ะ = ไม่ใช่เคสคำพ้อง
        if qw & set(must):
            skipped.append((q, f"คำถามมีคำเป้าหมายอยู่แล้ว {sorted(qw & set(must))}"))
            continue
        kept.append((q, must))
    return kept, skipped


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--show-skipped", action="store_true")
    args = ap.parse_args()

    summaries = load_real_summaries()
    cases, skipped = check_no_overlap(summaries)

    print("=" * 96)
    print(" C2 รอบใหม่ — วัดช่องว่างคำพ้องอย่างเป็นระบบ (ความจำจริง)")
    print(f" summary จริง: {len(summaries)} อัน")
    print(f" เคสตั้งต้น {len(VOCAB_CASES)} → ผ่านเกณฑ์ 'ไม่มีคำทับ' {len(cases)} เคส "
          f"(ตัดออก {len(skipped)})")
    print(f" รอบ: {args.rounds}  →  n รวม = {len(cases) * args.rounds}")
    print("=" * 96)
    if args.show_skipped:
        for q, why in skipped:
            print(f"   ตัดออก: {q[:40]:<42} {why}")

    # เขียน summary จริงลง collection ทดสอบ (ไม่แตะ collection ของผู้ใช้)
    try:
        vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    print("\n กำลังเขียน summary ลง vector store ทดสอบ...")
    for e in summaries:
        await vectormemory.add_conversation_memory(TEST_UID, e["text"])

    tally = {"K": 0, "V": 0, "KV": 0}
    rows = []
    try:
        for rnd in range(args.rounds):
            print(f" รอบ {rnd + 1}/{args.rounds}...")
            for q, must in cases:
                whose = memory.guess_owner(q)
                kw = memory.recall_summaries({"summaries": summaries}, q)
                vec = await vectormemory.query_conversation_memory(TEST_UID, q)
                vec = memory.filter_by_owner(vec, whose)
                kv = kw + [v for v in vec if v not in kw]

                hit = {"K": any(m in "\n".join(kw) for m in must),
                       "V": any(m in "\n".join(vec) for m in must),
                       "KV": any(m in "\n".join(kv) for m in must)}
                for k in tally:
                    tally[k] += hit[k]
                if rnd == 0:
                    rows.append((q, must, hit, len(kw), len(vec)))
    finally:
        try:
            vectormemory._client.delete_collection(f"convmem_{TEST_UID}")
        except Exception:
            pass

    n = len(cases) * args.rounds
    print("\n" + "=" * 96)
    print(f" {'เส้นทาง':<26} {'ผ่าน':>10}   {'ช่วง 95%':>14}")
    print("-" * 96)
    names = {"K": "keyword ล้วน", "V": "vector ล้วน", "KV": "keyword ∪ vector (chat.py)"}
    for k in ("K", "V", "KV"):
        lo, hi = wilson(tally[k], n)
        print(f" {names[k]:<26} {tally[k]:>4}/{n:<5} {lo*100:>8.0f}-{hi*100:<.0f}%")
    print("=" * 96)

    print("\n เคสที่ **ทั้ง keyword และ vector พลาดพร้อมกัน** (= เหตุผลเดียวที่ต้องทำ C2):")
    both_miss = [(q, must) for q, must, hit, _, _ in rows if not hit["K"] and not hit["V"]]
    if both_miss:
        for q, must in both_miss:
            print(f"   ❌ {q[:44]:<46} ต้องการ {must}")
    else:
        print("   (ไม่มี — vector ครอบทุกเคสที่ keyword พลาด)")
    print(f"\n   สรุป: {len(both_miss)}/{len(cases)} เคส")

    kmiss = [(q, must) for q, must, hit, _, _ in rows if not hit["K"]]
    print(f"\n เคสที่ keyword พลาด: {len(kmiss)}/{len(cases)} "
          f"— vector กู้คืนได้ {len(kmiss) - len(both_miss)}")


if __name__ == "__main__":
    asyncio.run(main())
