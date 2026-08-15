"""วัด **utilization** — ข้อมูลอยู่ใน context ครบ แต่โมเดลไม่ใช้

ที่มา: เจอ 3 ครั้งติดกันจากการคุยจริง/จำลอง ทั้งที่ retrieval ทำงานถูก
    "ตอนนี้ผมออกกำลังกายยังไง"  ctx มี "เปลี่ยนมาว่ายน้ำ" -> ตอบ "เล่นแบดมินตัน" (ค่าเก่า)
    "ผมอยู่จังหวัดอะไร"         ctx มี "กรุงเทพ"          -> ตอบ "อยู่ที่ไหนกันแน่คะ" (เลี่ยง)
    sim_staleness current       2/3

ตรงกับเปเปอร์ 2603.02473 ที่แยก retrieval failure (11-46%) ออกจาก
utilization failure (4-8% คงที่) — ของเราน่าจะสูงกว่านั้นมาก ต้องวัดให้รู้

⚠️ ตัดตัวแปร retrieval ออกทั้งหมด — **ป้อน context ที่ถูกต้องให้ตรงๆ**
   ถ้ายังตอบผิด = utilization ล้วน ไม่ใช่ retrieval

วัด 4 รูปแบบที่สงสัยว่าทำให้โมเดลไม่ใช้ข้อมูล:
    plain      ข้อมูลเดียว ไม่มีอะไรกวน            <- ขอบบน ถ้าพลาดตรงนี้คือหนัก
    noise      ข้อมูลถูก + บรรทัดไม่เกี่ยว 4 อัน    <- วัดผลของ noise 27% ที่เราวัดได้
    conflict   ข้อมูลเก่า + ใหม่ (ต้องเลือกใหม่)   <- เคสที่เจอจริง
    tagged     ข้อมูลถูก + ป้าย provenance         <- ป้ายที่เราเพิ่มไปทำให้สับสนไหม
"""
import argparse
import asyncio
import logging
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

import persona  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from config import OLLAMA_MODEL, OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)

# ⚠️ ใช้รูปประโยคเดียวกับที่ filter_by_owner สร้างจริง ("— ผู้ใช้บอกว่า...")
# รอบแรกเขียนรูปเก่า ("— ผู้ใช้: ...") ทำให้วัด context ที่ production ไม่ได้ส่งจริง
NOISE = [
    "6 ส.ค.: คุยเรื่องหนังสือ — ผู้ใช้บอกว่าชอบอ่านนิยาย",
    "7 ส.ค.: คุยเรื่องอาหาร — ผู้ใช้บอกว่าชอบของเผ็ด",
    "8 ส.ค.: คุยเรื่องเพลง — ผู้ใช้บอกว่าฟังเพลงร็อค",
    "9 ส.ค.: คุยเรื่องหนัง — รอสเต้บอกว่าชอบหนังไซไฟ",
]

# (คำถาม, บรรทัดที่มีคำตอบ, คำที่ต้องมีในคำตอบ, บรรทัดค่าเก่าสำหรับโหมด conflict)
CASES = [
    ("ผมอยู่จังหวัดอะไร",
     "10 ส.ค.: คุยเรื่องที่อยู่ — ผู้ใช้บอกว่าอยู่กรุงเทพ",
     "กรุงเทพ",
     "1 ส.ค.: คุยเรื่องที่อยู่ — ผู้ใช้บอกว่าอยู่เชียงใหม่"),
    ("ผมทำงานอะไร",
     "10 ส.ค.: คุยเรื่องงาน — ผู้ใช้บอกว่าเป็นวิศวกรซอฟต์แวร์",
     "วิศวกร",
     "1 ส.ค.: คุยเรื่องงาน — ผู้ใช้บอกว่าเป็นครู"),
    ("ผมแพ้อะไร",
     "10 ส.ค.: คุยเรื่องอาหาร — ผู้ใช้บอกว่าแพ้อาหารทะเล",
     "ทะเล",
     "1 ส.ค.: คุยเรื่องอาหาร — ผู้ใช้บอกว่าแพ้ถั่ว"),
    ("ผมเลี้ยงสัตว์อะไร",
     "10 ส.ค.: คุยเรื่องสัตว์เลี้ยง — ผู้ใช้บอกว่าเลี้ยงแมวชื่อโมจิ",
     "แมว",
     "1 ส.ค.: คุยเรื่องสัตว์เลี้ยง — ผู้ใช้บอกว่าเลี้ยงหมาชื่อบุญมี"),
    ("ผมชอบเล่นดนตรีอะไร",
     "10 ส.ค.: คุยเรื่องงานอดิเรก — ผู้ใช้บอกว่าชอบเล่นกีตาร์",
     "กีตาร์",
     "1 ส.ค.: คุยเรื่องงานอดิเรก — ผู้ใช้บอกว่าชอบเล่นเปียโน"),
]

MODES = ["plain", "noise", "conflict", "tagged"]


def build_ctx(mode: str, gold: str, old: str) -> str:
    if mode == "plain":
        lines = [gold]
    elif mode == "noise":
        lines = NOISE[:2] + [gold] + NOISE[2:]
    elif mode == "conflict":
        lines = [old, gold]          # เก่าก่อน ใหม่ทีหลัง (ตามลำดับเวลาจริง)
    else:                            # tagged
        lines = [gold + " (ยืนยันแล้ว)"]
    return "\n".join(f"- {x}" for x in lines)


async def ask(system: str, user: str) -> str:
    pl = {"model": OLLAMA_MODEL,
          "messages": [{"role": "system", "content": system},
                       {"role": "user", "content": user}],
          "stream": False, "think": False,
          "options": {"temperature": 0.8, "repeat_penalty": 1.12}}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=pl, timeout=300) as r:
                d = await r.json()
        raw = d.get("message", {}).get("content", "") or ""
        return raw.rsplit("</think>", 1)[-1].strip()
    except Exception as e:
        return f"(error {type(e).__name__})"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--real-persona", action="store_true",
                    help="ใช้ SYSTEM_PROMPT ตัวจริง (ยาว ~2,000c) แทนตัวสั้น")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",")]

    base = (persona.SYSTEM_PROMPT if args.real_persona else
            "คุณคือรอสเต้ ผู้ช่วยหญิงชาวไทย พูดไทย ลงท้าย ค่ะ/นะคะ ตอบสั้นๆ")

    print("=" * 96)
    print(" utilization — ข้อมูลอยู่ใน context ครบ โมเดลใช้ไหม")
    print(f" {len(CASES)} เคส × {args.rounds} รอบ · {OLLAMA_MODEL}"
          f" · persona {'จริง' if args.real_persona else 'สั้น'} ({len(base)}c)")
    print(" ⚠️ ป้อน context ที่ถูกต้องตรงๆ = ตัดตัวแปร retrieval ออกหมด")
    print("=" * 96)

    n = len(CASES) * args.rounds
    print(f"\n {'โหมด':<12}{'ใช้ข้อมูลถูก':>16}{'ช่วง 95%':>18}{'เลี่ยง/ถามกลับ':>16}")
    print("-" * 96)
    res = {}
    for mode in modes:
        ok = dodge = 0
        bad_ex = []
        for q, gold, want, old in CASES:
            ctx = build_ctx(mode, gold, old)
            sysmsg = base + "\n\nเรื่องที่เคยคุยกันก่อนหน้า:\n" + ctx
            for _ in range(args.rounds):
                a = await ask(sysmsg, q)
                if want in a:
                    ok += 1
                else:
                    if any(w in a for w in ("ไม่แน่ใจ", "ไม่ทราบ", "บอกหน่อย", "อะไรคะ",
                                            "ไหนคะ", "จำไม่ได้", "ยังไม่ได้บอก")):
                        dodge += 1
                    if len(bad_ex) < 2:
                        bad_ex.append((q, a[:70]))
        res[mode] = ok
        lo, hi = wilson(ok, n)
        print(f" {mode:<12}{ok:>8}/{n:<7}{lo*100:>9.0f}-{hi*100:<7.0f}%{dodge:>12}/{n}")
        for q, a in bad_ex:
            print(f"      ผิด: {q} -> {a}")

    print("=" * 96)
    if "plain" in res:
        print(f"\n ขอบบน (plain) = {res['plain']}/{n}"
              f" — ถ้าต่ำแปลว่าโมเดลไม่ใช้ข้อมูลแม้ไม่มีอะไรกวนเลย")
        for m in modes:
            if m != "plain":
                d = res[m] - res["plain"]
                print(f"   {m:<10} {res[m]}/{n}  ({d:+d} จาก plain)")


if __name__ == "__main__":
    asyncio.run(main())
