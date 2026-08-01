"""ข้อ 4: วัดระบบความจำใหม่ผ่าน chat.ask_ollama จริง + วัด latency ทุกขั้น

ต่างจาก bench ก่อนหน้าทั้งหมด: ตัวอื่นเรียก _chat_once หรือ recall_summaries ตรงๆ
ตัวนี้เดินผ่าน ask_ollama เส้นเดียวกับที่ผู้ใช้เจอ — ผ่าน guard chain, fallback,
tool selection, การบันทึกจริง ครบทุกขั้น ตัวเลขที่ได้จึงเป็นสิ่งที่ผู้ใช้เห็นจริง

วัด 3 อย่าง:
  1. ความจำ    — ตอบถูกฝั่งไหม (ของผู้ใช้ vs ของรอสเต้) ไม่สลับเจ้าของ
  2. ข้อมูลสด  — ยังเรียก tool ได้ถูก (กันแก้ความจำแล้วพังอีกทาง)
  3. latency   — แยกทีละขั้นจาก stats module ว่าเวลาไปไหน (ที่ไหนลดได้บ้าง)

⚠️ ใช้ fixture ที่แต่งเอง ไม่ใช่ความจำผู้ใช้จริง และเขียนลง user id ทดสอบแยก
"""
import argparse
import asyncio
import math
import os
import pathlib
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging  # noqa: E402
logging.disable(logging.CRITICAL)

import chat  # noqa: E402
import memory  # noqa: E402
import stats  # noqa: E402
import vectormemory as V  # noqa: E402
from memory_fixture import FACTS, SUMMARIES  # noqa: E402

TEST_UID = 999_888_777_666_548

# (คำถาม, ชนิด, คำที่ต้องมี, คำที่ห้ามมี)
CASES = [
    ("จำได้ไหมว่าผมชอบอ่านนิยายแนวไหน", "mem", ["สืบสวน"], ["แฟนตาซี"]),
    ("รอสเต้ชอบอ่านแนวไหนเหรอ จำได้ไหม", "mem", ["แฟนตาซี"], ["สืบสวน"]),
    ("ผมกินเผ็ดได้ไหมนะ จำได้ไหม", "mem", ["เผ็ด"], []),
    ("รอสเต้ไม่ชอบกินอะไร จำได้ไหม", "mem", ["หวาน"], ["เผ็ด"]),
    ("ผมชอบอ่านอะไร", "mem", ["สืบสวน"], ["แฟนตาซี"]),
    ("พรุ่งนี้ฝนตกไหม", "live", [], []),
    ("ราคาน้ำมันวันนี้เท่าไหร่", "live", [], []),
]

DENIAL = ["ไม่เคย", "ไม่ได้คุย", "จำไม่ได้", "ไม่มีข้อมูล", "ไม่แน่ใจ", "ไม่ค่อยจำ"]


def wilson(ok, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


async def setup():
    mem = {
        "name": "ผู้ทดสอบ", "preferred_name": "",
        "facts": [dict(f, created="2026-07-26T00:00:00+07:00", superseded=False,
                       superseded_at=None, superseded_by=None) for f in FACTS],
        "history": [],
        "summaries": [{"date": "2026-08-01", "text": s} for s in SUMMARIES],
    }
    memory.save_memory(TEST_UID, mem)
    try:
        V._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass
    for s in SUMMARIES:
        await V.add_conversation_memory(TEST_UID, s)


def teardown():
    p = memory._memory_path(TEST_UID)
    if os.path.exists(p):
        os.remove(p)
    try:
        V._client.delete_collection(f"convmem_{TEST_UID}")
    except Exception:
        pass


def judge(reply, kind, must, forbid):
    """คืน (ผ่านไหม, รายการปัญหา) — แยกชนิดความผิดให้ชัด เพราะแก้คนละวิธี

    ⚠️ ต้องแยก "ถามกลับ" ออกจาก "จำสลับ": เจอเคสที่รอสเต้ตอบว่า "ชอบแนวไหนบ้างคะ?
    นิยายสืบสวนหรือแฟนตาซี" ซึ่งเอ่ยทั้งสองฝั่งเลยถูกนับเป็นสลับเจ้าของ ทั้งที่จริงคือ
    *ไม่ยอมตอบ* (ถามกลับ) ไม่ใช่จำผิด — สองอาการนี้แก้คนละทาง จึงต้องนับแยก
    """
    bad = []
    if kind == "mem":
        asked_back = reply.rstrip().endswith(("?", "？")) or "หรือว่า" in reply
        if any(d in reply for d in DENIAL):
            bad.append("ปฏิเสธว่าจำไม่ได้")
        if must and not any(w in reply for w in must):
            bad.append(f"ขาด {must}")
        if forbid and any(w in reply for w in forbid):
            bad.append("ถามกลับ(เอ่ยสองฝั่ง)" if asked_back
                       else f"สลับเจ้าของ {[w for w in forbid if w in reply]}")
    else:
        # ข้อมูลสด: ต้องมีตัวเลข/หน่วยจริง ไม่ใช่ตอบลอยๆ
        if not any(c.isdigit() for c in reply):
            bad.append("ไม่มีข้อมูลจริง")
    return (not bad), bad


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    await setup()
    print("=" * 100)
    print(f" ข้อ 4: วัดผ่าน chat.ask_ollama จริง — {len(CASES)} เคส × {args.reps} รอบ")
    print(f" ความทรงจำ: {len(SUMMARIES)} summary รูปแบบ F (fixture ไม่ใช่ข้อมูลจริง)")
    print("=" * 100)

    mem_ok = mem_n = live_ok = live_n = swap = asked_back = 0
    lat_all = []
    stage_acc = {}
    fails = []
    try:
        for q, kind, must, forbid in CASES:
            for _ in range(args.reps):
                # ล้าง history ทุกรอบ ให้แต่ละเคสเป็นอิสระ
                m = memory.load_memory(TEST_UID)
                m["history"] = []
                memory.save_memory(TEST_UID, m)

                t0 = time.perf_counter()
                try:
                    reply = await chat.ask_ollama(TEST_UID, "ผู้ทดสอบ", q)
                except Exception as exc:
                    reply = f"[ERROR {exc}]"
                dt = time.perf_counter() - t0
                lat_all.append(dt)

                # ⚠️ get_recent() คืน "ใหม่สุดอยู่ท้ายลิสต์" — เดิมอ่าน [0] ซึ่งเป็นอันเก่าสุด
                # ทำให้เก็บค่าของรอบแรกซ้ำๆ ทุกรอบ แล้วคำนวณสัดส่วนออกมาเกิน 100%
                rec = stats.get_recent(1)
                if rec:
                    for k, v in rec[-1].items():
                        if isinstance(v, (int, float)) and k not in ("ts",):
                            stage_acc.setdefault(k, []).append(v)

                ok, bad = judge(reply, kind, must, forbid)
                if kind == "mem":
                    mem_n += 1
                    mem_ok += ok
                    if any(b.startswith("สลับเจ้าของ") for b in bad):
                        swap += 1
                    if any("ถามกลับ" in b for b in bad):
                        asked_back += 1
                else:
                    live_n += 1
                    live_ok += ok
                if not ok and len(fails) < 8:
                    fails.append((q, ", ".join(bad), reply[:70].replace("\n", " ")))
    finally:
        teardown()

    lo, hi = wilson(mem_ok, mem_n)
    print(f"\n ความจำ   {mem_ok}/{mem_n} ({mem_ok/max(mem_n,1)*100:.0f}%)  "
          f"ช่วง 95% [{lo*100:.0f}-{hi*100:.0f}%]")
    print(f"          สลับเจ้าของ {swap}   ถามกลับแทนตอบ {asked_back}")
    print(f" ข้อมูลสด {live_ok}/{live_n} ({live_ok/max(live_n,1)*100:.0f}%)")
    print(f" latency  เฉลี่ย {statistics.mean(lat_all):.2f}s  "
          f"p95 {sorted(lat_all)[int(len(lat_all)*0.95)-1]:.2f}s")

    if fails:
        print("\n เคสที่ไม่ผ่าน:")
        for q, why, r in fails:
            print(f"   ❌ {q[:32]:<34} {why}")
            print(f"      → {r}")

    print("\n" + "=" * 100)
    print(" latency แยกตามขั้น (จาก stats module) — หาที่ลดชดเชย vector 1.2s")
    print("-" * 100)
    # ใช้ 'total' ที่ stats จับเองเป็นฐาน (ไม่ใช่ perf_counter ข้างนอก) เพื่อให้สัดส่วน
    # เทียบกับสิ่งที่ stage วัดจริงในขอบเขตเดียวกัน
    base = statistics.mean(stage_acc.get("total", lat_all))
    rows = sorted(((k, statistics.mean(v), len(v)) for k, v in stage_acc.items()
                   if k != "total"), key=lambda x: -x[1])
    print(f"   {'total (stats จับเอง)':<24} {base*1000:>8.0f} ms")
    print(f"   {'total (จับข้างนอก)':<24} {statistics.mean(lat_all)*1000:>8.0f} ms")
    print("-" * 100)
    acc = 0.0
    for k, v, cnt in rows:
        if v < 0.001:
            continue
        acc += v
        print(f"   {k:<24} {v*1000:>8.0f} ms  ({v/base*100:>4.1f}%)  n={cnt}")
    print(f"   {'(ที่เหลือ/ไม่ได้จับ)':<24} {(base-acc)*1000:>8.0f} ms  "
          f"({(base-acc)/base*100:>4.1f}%)")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
