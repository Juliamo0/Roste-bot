"""ทดสอบระบบความจำแบบครบวงจร — ผ่าน chat.ask_ollama จริง (ไม่ใช่ประกอบ prompt เอง)

ต่างจาก bench ก่อนหน้าที่เรียก _chat_once ตรงๆ: รอบนี้เดินผ่านเส้นทางเดียวกับที่ผู้ใช้เจอ
ทุกขั้น — recall → prompt → โมเดล → guard → fallback → บันทึกกลับ

วัด 4 อย่างต่อคำถาม (pass^k เพราะโมเดลไม่นิ่ง):
  1. ยืนยันว่าเคยคุย (ไม่ปฏิเสธ)
  2. เนื้อหาตรงกับ summary จริง (ไม่ใช่แค่ตอบว่า "เคย" ลอยๆ)
  3. ไม่หลุดคาแร็กเตอร์ (ไม่ประกาศเป็น AI)
  4. ไม่ได้ fallback ผิดบริบท (ไม่โดน AI_DEFLECT ตอนถามเรื่องความจำ)

ใช้ memory ของผู้ใช้จริงเป็นฐาน แต่ copy ไปยัง user id ทดสอบ เพื่อไม่แตะไฟล์จริง
"""
import asyncio
import json
import os
import pathlib
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import chat  # noqa: E402
import memory  # noqa: E402
import persona  # noqa: E402

from _bench_target import resolve_memory_file  # noqa: E402

SRC_MEM = resolve_memory_file()
TEST_UID = 999_888_777_666_555
N = 5

# (คำถาม, คำที่ต้องมีอย่างน้อยหนึ่งคำ = เนื้อหาตรงกับ summary จริง)
CASES = [
    ("เราเคยคุยเรื่องการอ่านอะไรกันบ้างไหมก่อนหน้านี้",
     ["นิยาย", "หนังสือ", "อ่าน", "เวทมนตร์", "ลึกลับ"]),
    ("จำได้ไหมว่าเคยคุยเรื่องของหวานอะไรกัน",
     ["เจลาโต้", "ไอศกรีม", "ของหวาน", "หวาน"]),
    ("เมื่อก่อนเราคุยเรื่องน้ำมันอะไรกันบ้าง",
     ["น้ำมัน", "ราคา", "ดีเซล", "เบนซิน"]),
    ("เคยคุยเรื่องอากาศกันหรือเปล่า",
     ["อากาศ", "ฝน", "ร้อน", "อุณหภูมิ", "หนาว"]),
    ("รอสเต้จำได้ไหมว่าเราเคยคุยเรื่องภาษาญี่ปุ่น",
     ["ญี่ปุ่น", "ขอบคุณ", "อาริงาโตะ", "ภาษา"]),
]

DENIAL = [
    "ไม่เคย", "ไม่ได้คุย", "จำไม่ได้", "ไม่มีประวัติ", "ครั้งแรก",
    "ยังไม่เคย", "ไม่มีความทรงจำ", "จำรายละเอียดไม่ค่อยได้",
]


def setup():
    shutil.copy(SRC_MEM, memory._memory_path(TEST_UID))


def teardown():
    p = memory._memory_path(TEST_UID)
    if os.path.exists(p):
        os.remove(p)


async def main():
    setup()
    print("=" * 80)
    print(f" ทดสอบระบบความจำ pass^{N} — ผ่าน chat.ask_ollama จริง (เส้นทางเดียวกับผู้ใช้)")
    print("=" * 80)

    mem0 = memory.load_memory(TEST_UID)
    print(f" ฐานข้อมูล: summaries {len(mem0.get('summaries', []))} | "
          f"facts {len([f for f in mem0.get('facts', []) if not memory._fact_superseded(f)])}")

    grand_pass = 0
    grand_total = 0
    results = []

    for q, keywords in CASES:
        # ตรวจก่อนว่า recall ส่งอะไรให้ — แยกความผิดของ recall ออกจากความผิดของโมเดล
        mem = memory.load_memory(TEST_UID)
        recalled = memory.recall_summaries(mem, q)

        ok = denied = leaked = wrong_fb = off_topic = 0
        samples = []
        for i in range(N):
            # ล้าง history ทุกรอบ ให้แต่ละรอบเป็นอิสระ (ไม่ให้คำตอบรอบก่อนชี้นำ)
            m = memory.load_memory(TEST_UID)
            m["history"] = []
            memory.save_memory(TEST_UID, m)

            reply = await chat.ask_ollama(TEST_UID, "ผู้ทดสอบ", q)

            is_denial = any(d in reply for d in DENIAL)
            is_leak = persona.reply_claims_to_be_ai(reply)
            is_wrong_fb = persona.AI_DEFLECT.strip()[:20] in reply
            on_topic = any(k in reply for k in keywords)

            passed = on_topic and not is_denial and not is_leak and not is_wrong_fb
            ok += passed
            denied += is_denial
            leaked += is_leak
            wrong_fb += is_wrong_fb
            off_topic += (not on_topic)
            if len(samples) < 2:
                samples.append(("PASS" if passed else "FAIL", reply[:88]))

        grand_pass += ok
        grand_total += N
        results.append((q, ok, recalled))

        status = "✅" if ok == N else ("⚠️" if ok >= N * 0.6 else "❌")
        print(f"\n {status} {q}")
        print(f"     recall ส่งให้ {len(recalled)} อัน | ผ่าน {ok}/{N}")
        if denied or leaked or wrong_fb or off_topic:
            print(f"     ปฏิเสธ {denied} | หลุดเป็น AI {leaked} | "
                  f"fallback ผิดบริบท {wrong_fb} | ไม่ตรงเรื่อง {off_topic}")
        for st, s in samples:
            print(f"        [{st}] {s}")

    teardown()

    print("\n" + "=" * 80)
    pct = grand_pass / grand_total * 100
    print(f" รวม: {grand_pass}/{grand_total}  ({pct:.0f}%)")
    print("-" * 80)
    for q, ok, rec in results:
        bar = "█" * ok + "░" * (N - ok)
        print(f"   {bar}  {ok}/{N}  recall={len(rec)}  {q[:44]}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
