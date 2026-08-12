"""หา attention cliff ของ **qwen3:4b** (ตัวสกัด) — เรารู้แค่ของ 8B ว่าอยู่ที่ ~3,700c

ที่มา (ผู้ใช้ตั้งสมมติฐาน): "ที่ 4B ทิ้งสาเหตุอาจมาจาก 3700c แบบ 8B
แต่เราไม่รู้ไงว่า 4B เป็นไง"

ถูกต้อง — §1 วัด cliff กับ **qwen3:8b ตอนตอบแชต** เท่านั้น
ไม่เคยวัดกับ 4B และไม่เคยวัดกับ *งานสกัด* ซึ่งเป็นคนละงาน

อาการที่ต้องอธิบาย: 4B ทิ้ง user_fact:เลี้ยงแมวชื่อโมจิ เมื่อบทมีคำแนะนำยาวๆ
    สมมติฐาน A: บทยาวเกิน cliff ของ 4B -> ทิ้งของที่อยู่ต้นบท
    สมมติฐาน B: ไม่เกี่ยวกับความยาว แต่เป็นเรื่อง "คำแนะนำกลบข้อเท็จจริง"

วิธีแยก: ใส่ข้อเท็จจริงไว้ **ต้นบท** แล้วขยายความยาวบทขึ้นเรื่อยๆ ด้วยเนื้อหาที่ไม่เกี่ยว
    ถ้าเป็น A -> ยิ่งยาวยิ่งทิ้ง มีจุดหักชัดเจน
    ถ้าเป็น B -> ทิ้งตั้งแต่บทสั้นถ้ามีคำแนะนำ และไม่ทิ้งถ้าไม่มีคำแนะนำ (ไม่ว่าจะยาวแค่ไหน)

วัด: fact ที่ปักไว้ ("แมวชื่อโมจิ") รอดมาอยู่ใน summary ไหม × N รอบ (temperature 0)
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

import memory  # noqa: E402
from bench_paper_opts import wilson  # noqa: E402
from bench_write_schema import post  # noqa: E402
from config import OLLAMA_EXTRACT_MODEL  # noqa: E402

logging.disable(logging.CRITICAL)

# ข้อเท็จจริงที่ปักไว้ต้นบทเสมอ — ต้องรอดทุกกรณี
ANCHOR_U = "ผมเลี้ยงแมวไว้ตัวนึงชื่อโมจิ สีส้มทั้งตัว"
ANCHOR_A = "น่ารักจังค่ะ"

# เนื้อหาถ่วงความยาว 2 แบบ — แยกตัวแปร "ความยาว" ออกจาก "เป็นคำแนะนำ"
FILLER_ADVICE = [
    ("ขอคำแนะนำเรื่องเลี้ยงแมวหน่อยสิ",
     "ให้อาหารแมวเฉพาะทางที่มีโปรตีนสูงนะคะ หลีกเลี่ยงของหวานและอาหารคน "
     "พาไปตรวจสุขภาพปีละครั้ง ฉีดวัคซีนตามกำหนด เล่นกับแมววันละ 15 นาที "
     "เพื่อไม่ให้อ้วนและเครียด ทำความสะอาดกระบะทรายทุกวันค่ะ"),
    ("แล้วเรื่องอาบน้ำล่ะ",
     "แมวอาบน้ำเดือนละครั้งพอค่ะ ใช้แชมพูสำหรับแมวโดยเฉพาะ "
     "เช็ดตัวให้แห้งสนิทกันหวัด ตัดเล็บทุก 2 สัปดาห์ แปรงขนทุกวันลดขนร่วงค่ะ"),
    ("อาหารเสริมจำเป็นไหม",
     "ถ้าให้อาหารสำเร็จรูปคุณภาพดีอยู่แล้วก็ไม่จำเป็นค่ะ "
     "แต่ถ้าแมวขนร่วงเยอะอาจเสริมน้ำมันปลาได้ ปรึกษาสัตวแพทย์ก่อนนะคะ"),
]
FILLER_CHITCHAT = [
    ("วันนี้อากาศดีนะ", "ใช่ค่ะ ท้องฟ้าใสมากเลย"),
    ("เมื่อคืนนอนดึกไปหน่อย", "พักผ่อนเยอะๆ นะคะ"),
    ("พรุ่งนี้ว่างทั้งวันเลย", "ดีจังค่ะ ได้พักผ่อนเต็มที่"),
]


def build(n_filler: int, kind: str) -> list:
    pairs = [{"role": "user", "content": ANCHOR_U},
             {"role": "assistant", "content": ANCHOR_A}]
    src = FILLER_ADVICE if kind == "advice" else FILLER_CHITCHAT
    for i in range(n_filler):
        u, a = src[i % len(src)]
        pairs.append({"role": "user", "content": u})
        pairs.append({"role": "assistant", "content": a})
    return pairs


async def probe(pairs: list, rounds: int) -> tuple:
    """คืน (fact รอดกี่ครั้ง, ขนาด prompt)"""
    prompt = memory.build_summary_prompt(pairs)
    ok = 0
    for _ in range(rounds):
        line = memory.parse_summary_json(await post(OLLAMA_EXTRACT_MODEL, prompt, True))
        if "โมจิ" in line or "แมว" in line:
            ok += 1
    return ok, len(prompt)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--max-filler", type=int, default=6)
    args = ap.parse_args()

    print("=" * 92)
    print(f" หา attention cliff ของ {OLLAMA_EXTRACT_MODEL} (ตัวสกัด)")
    print(" ปัก fact 'แมวชื่อโมจิ' ไว้ **ต้นบท** แล้วขยายความยาวด้วยเนื้อหา 2 แบบ")
    print("   advice   = คำแนะนำยาวๆ (มีทั้งความยาว + ความเป็นคำแนะนำ)")
    print("   chitchat = คุยเล่นสั้นๆ (มีแต่ความยาว ไม่มีคำแนะนำ)")
    print(f" cliff ของ qwen3:8b ตอนตอบแชต = 3,700c (§1) — 4B ยังไม่เคยวัด")
    print("=" * 92)
    print(f"\n {'เนื้อหา':<12}{'คู่ถ่วง':>8}{'ขนาด prompt':>14}{'fact รอด':>12}{'ช่วง 95%':>16}")
    print("-" * 92)

    for kind in ("chitchat", "advice"):
        for n in range(0, args.max_filler + 1, 2):
            ok, size = await probe(build(n, kind), args.rounds)
            lo, hi = wilson(ok, args.rounds)
            flag = "  <-- ทิ้ง!" if ok < args.rounds else ""
            print(f" {kind:<12}{n:>8}{size:>13}c{ok:>8}/{args.rounds}"
                  f"{lo*100:>10.0f}-{hi*100:<5.0f}%{flag}")
        print()

    print("=" * 92)
    print(" อ่านผล:")
    print("   ถ้า advice ทิ้งตั้งแต่บทสั้น แต่ chitchat ไม่ทิ้งแม้ยาวกว่า")
    print("     -> ไม่ใช่เรื่องความยาว แต่เป็น 'คำแนะนำกลบข้อเท็จจริง'")
    print("   ถ้าทั้งคู่ทิ้งที่ขนาดใกล้กัน -> เป็น cliff ของ 4B จริง")


if __name__ == "__main__":
    asyncio.run(main())
