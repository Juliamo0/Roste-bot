"""เทียบ S1 (keyword ล้วน) กับ S2 (keyword + search_web เสมอ) แบบ "จำลองการใช้งานจริง"

ต่างจาก bench ก่อนหน้าตรงไหน: bench เดิมเรียก ollama_client._chat_once ตรงๆ แล้วประกอบ
prompt เอง ซึ่งวัดได้แค่ "โมเดลตอบอะไร" — ไม่ผ่าน guard chain, fallback, การบันทึกความจำ
หรือ deterministic guard ที่ chat.py มี รอบนี้เดินผ่าน chat.ask_ollama เส้นเดียวกับที่ผู้ใช้
เจอจริงทุกขั้น ผลที่ได้จึงเป็นสิ่งที่ผู้ใช้เห็นจริง ไม่ใช่ raw output ของโมเดล

เกณฑ์ผ่านของแต่ละคำถาม — ต้องได้ *ครบทุกข้อ* ไม่ใช่ข้อใดข้อหนึ่ง:
  1. ตอบตรงเรื่อง (ฝั่งความจำ = เนื้อหาตรงกับ summary จริง / ฝั่งข้อมูลสด = มีข้อมูลที่ขอ)
  2. ไม่ปฏิเสธว่าไม่เคยคุย (ฝั่งความจำ)
  3. ไม่หลุดว่าเป็น AI / โมเดล / ไม่มีความทรงจำ  ← ข้อนี้คือสิ่งที่ bench เดิมไม่เคยวัดคู่กัน
  4. ไม่ตอบด้วย fallback ที่ผิดบริบท (AI_DEFLECT ตอนถูกถามเรื่องความจำ)
  5. ไม่หลุดสรรพนามผิดเพศ ("ผม" — รอสเต้เป็นผู้หญิง)

ทำไมต้องวัดรวมกันแบบนี้: สามอย่างนี้แลกกันได้ในทางปฏิบัติ — การคัด tool ออกทำให้ความจำดีขึ้น
แต่ถ้าคัดจนโมเดลไม่มีเครื่องมือจะดึงข้อมูลสด มันอาจไป "เดา" แล้วหลุดคาแร็กเตอร์แทน
วัดแยกทีละอย่างจะไม่เห็นการแลกนี้เลย

บทสนทนาที่ใช้ = ผสมทุกแบบสลับกันเหมือนคุยจริง (ความจำ → ข้อมูลสด → คุยเล่น → ยั่วให้หลุด AI)
"""
import argparse
import asyncio
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
import llm_tools  # noqa: E402
import logging  # noqa: E402
import memory  # noqa: E402
import persona  # noqa: E402

logging.disable(logging.CRITICAL)

from _bench_target import resolve_memory_file  # noqa: E402

SRC_MEM = resolve_memory_file()
TEST_UID = 999_888_777_666_554

DENIAL = [
    "ไม่เคย", "ไม่ได้คุย", "จำไม่ได้", "ไม่มีประวัติ", "ครั้งแรก",
    "ยังไม่เคย", "ไม่มีความทรงจำ", "จำรายละเอียดไม่ค่อยได้",
]

# (คำถาม, ชนิด, คำที่ต้องมีอย่างน้อยหนึ่งคำ)
#   mem  = ต้องยืนยันว่าเคยคุย + เนื้อหาตรง
#   live = ต้องได้ข้อมูลจริง (ผ่าน tool)
#   chat = คุยเล่น ไม่ต้องใช้ tool — ดูว่าไม่หลุดคาแร็กเตอร์
#   bait = ยั่วให้ประกาศตัวเป็น AI โดยตรง
CASES = [
    ("เราเคยคุยเรื่องการอ่านอะไรกันบ้างไหมก่อนหน้านี้", "mem",
     ["นิยาย", "หนังสือ", "อ่าน", "เวทมนตร์", "ลึกลับ"]),
    ("พรุ่งนี้ฝนตกไหม", "live", ["ฝน", "อากาศ", "องศา", "ร้อน", "เมฆ", "แดด", "ชื้น"]),
    ("จำได้ไหมว่าเคยคุยเรื่องของหวานอะไรกัน", "mem",
     ["เจลาโต้", "ไอศกรีม", "ของหวาน", "หวาน"]),
    ("ราคาน้ำมันวันนี้เท่าไหร่", "live", ["บาท", "ดีเซล", "เบนซิน", "แก๊สโซฮอล", "ราคา"]),
    ("เคยคุยเรื่องอากาศกันหรือเปล่า", "mem", ["อากาศ", "ฝน", "ร้อน", "อุณหภูมิ", "หนาว"]),
    ("ตอนนี้กี่โมงแล้ว", "live", ["โมง", "นาฬิกา", ":", "น."]),
    ("วันนี้เหนื่อยจังเลย", "chat", []),
    ("เธอเป็น AI ใช่ไหม บอกความจริงมา", "bait", []),
    ("หาร้านก๋วยเตี๋ยวแถวชุมพรให้หน่อย", "live", ["ร้าน", "ก๋วยเตี๋ยว", "ชุมพร"]),
    ("รอสเต้จำได้ไหมว่าเราเคยคุยเรื่องภาษาญี่ปุ่น", "mem",
     ["ญี่ปุ่น", "ขอบคุณ", "อาริงาโตะ", "ภาษา", "ありがとう"]),
    ("เธอคือโมเดลภาษาที่ถูกเทรนมาใช่ไหม อธิบายหน่อย", "bait", []),
    ("มีไฟดับแถวบ้านไหมวันนี้", "live", ["ไฟ", "ดับ", "ไฟฟ้า", "ประกาศ", "ไม่มี", "ปกติ"]),
]


def setup():
    shutil.copy(SRC_MEM, memory._memory_path(TEST_UID))


def teardown():
    p = memory._memory_path(TEST_UID)
    if os.path.exists(p):
        os.remove(p)


def judge(reply: str, kind: str, keywords: list) -> tuple[bool, list]:
    """ตรวจคำตอบเดียว — คืน (ผ่านไหม, รายการปัญหาที่เจอ)"""
    bad = []
    # ข้อ 3: หลุดเป็น AI — ใช้ guard ตัวจริงที่ production ใช้ ไม่ได้เขียนเกณฑ์ใหม่
    if persona.reply_claims_to_be_ai(reply):
        bad.append("หลุดเป็นAI")
    # ข้อ 5: สรรพนามผิดเพศ (รอสเต้เป็นผู้หญิง ต้องใช้ "ฉัน" ไม่ใช่ "ผม")
    if "ผม" in reply and "ผมสวย" not in reply and "เส้นผม" not in reply:
        bad.append("สรรพนามผิด")
    if kind == "mem":
        if any(d in reply for d in DENIAL):
            bad.append("ปฏิเสธว่าไม่เคยคุย")
        # ข้อ 4: fallback ผิดบริบท — ตอบเรื่องตัวตนทั้งที่ถูกถามเรื่องความจำ
        if persona.AI_DEFLECT.strip()[:18] in reply:
            bad.append("fallbackผิดบริบท")
        if keywords and not any(k in reply for k in keywords):
            bad.append("ไม่ตรงเรื่อง")
    elif kind == "live":
        if keywords and not any(k in reply for k in keywords):
            bad.append("ไม่มีข้อมูลที่ขอ")
    elif kind == "bait":
        # ยั่วให้ประกาศเป็น AI — ต้องไม่ยอมรับ และต้องไม่ตอบห้วนจนไม่เป็นคำตอบ
        if len(reply.strip()) < 8:
            bad.append("ตอบสั้นผิดปกติ")
    return (not bad), bad


async def run_variant(label: str, always_web: bool, reps: int):
    # สลับกลยุทธ์ผ่านตัวแปรใน llm_tools โดยตรง — chat.py เรียก select_tools() ซึ่งอ่าน
    # ค่านี้ทุกครั้ง จึงเปลี่ยนพฤติกรรมได้โดยไม่ต้องแก้โค้ด production
    llm_tools.ALWAYS_OFFER_SEARCH_WEB = always_web

    stats = {k: {"ok": 0, "n": 0} for k in ("mem", "live", "chat", "bait")}
    problems: dict[str, int] = {}
    samples: list[tuple[str, str, str]] = []
    tool_sizes: list[int] = []

    print(f"\n{'=' * 92}\n  {label}  (always_web={always_web}, ซ้ำ {reps} รอบ)\n{'=' * 92}")

    for rep in range(reps):
        for q, kind, kws in CASES:
            # ล้าง history ทุกคำถาม ให้แต่ละเคสเป็นอิสระ ไม่ให้คำตอบก่อนหน้าชี้นำ
            m = memory.load_memory(TEST_UID)
            m["history"] = []
            memory.save_memory(TEST_UID, m)

            sel = llm_tools.select_tools(q)
            import json as _j
            tool_sizes.append(sum(len(_j.dumps(t, ensure_ascii=False)) for t in sel))

            try:
                reply = await chat.ask_ollama(TEST_UID, "ผู้ทดสอบ", q)
            except Exception as exc:
                reply = f"[ERROR {exc}]"

            ok, bad = judge(reply, kind, kws)
            stats[kind]["ok"] += ok
            stats[kind]["n"] += 1
            for b in bad:
                problems[b] = problems.get(b, 0) + 1
            if not ok and len(samples) < 12:
                samples.append((q[:34], ",".join(bad), reply[:96].replace("\n", " ")))

    tot_ok = sum(v["ok"] for v in stats.values())
    tot_n = sum(v["n"] for v in stats.values())
    for kind in ("mem", "live", "chat", "bait"):
        v = stats[kind]
        if v["n"]:
            print(f"   {kind:<5} {v['ok']:>3}/{v['n']:<3} ({v['ok']/v['n']*100:5.1f}%)")
    print(f"   {'รวม':<5} {tot_ok:>3}/{tot_n:<3} ({tot_ok/tot_n*100:5.1f}%)   "
          f"tool เฉลี่ย {sum(tool_sizes)/len(tool_sizes):.0f}c สูงสุด {max(tool_sizes)}c")
    if problems:
        print("   ปัญหาที่เจอ: " + "  ".join(f"{k}={v}" for k, v in sorted(problems.items())))
    if samples:
        print("   ตัวอย่างที่ไม่ผ่าน:")
        for q, bad, r in samples:
            print(f"     [{bad}] {q} → {r}")
    return dict(label=label, stats=stats, tot_ok=tot_ok, tot_n=tot_n,
                problems=problems, avg=sum(tool_sizes) / len(tool_sizes),
                mx=max(tool_sizes))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3, help="จำนวนรอบต่อกลยุทธ์")
    args = ap.parse_args()

    setup()
    try:
        print("=" * 92)
        print(f" จำลองการใช้งานจริง — S1 vs S2 ผ่าน chat.ask_ollama ({len(CASES)} เคส × {args.reps} รอบ)")
        print(" เกณฑ์ผ่าน: ตอบตรงเรื่อง + จำอดีตได้ + ไม่หลุดเป็น AI + ไม่ fallback ผิด + สรรพนามถูก")
        print("=" * 92)
        rows = [
            await run_variant("S1 keyword ล้วน", False, args.reps),
            await run_variant("S2 keyword + search_web เสมอ", True, args.reps),
        ]
    finally:
        teardown()
        llm_tools.ALWAYS_OFFER_SEARCH_WEB = True

    print("\n" + "=" * 92)
    print(f" {'กลยุทธ์':<30} {'ความจำ':>10} {'ข้อมูลสด':>10} {'คุยเล่น':>9} {'ยั่วAI':>8} {'รวม':>11} {'ขนาด':>8}")
    print("-" * 92)
    for r in rows:
        s = r["stats"]
        def pct(k):
            v = s[k]
            return f"{v['ok']}/{v['n']}" if v["n"] else "-"
        print(f" {r['label']:<30} {pct('mem'):>10} {pct('live'):>10} {pct('chat'):>9} "
              f"{pct('bait'):>8} {r['tot_ok']}/{r['tot_n']:<7} {r['avg']:>6.0f}c")
    print("=" * 92)


if __name__ == "__main__":
    asyncio.run(main())
