"""เทียบโมเดล **ฝั่งตอบแชต** — qwen3:8b (ปัจจุบัน) vs qwen3.5:9b (ใหม่กว่า 2 เจน)

⚠️ ไม่ใช่การวัด "โมเดลไหนฉลาดกว่า" แต่วัด **งานที่รอสเต้ทำจริง 3 อย่าง**
เพราะเราวัดมาแล้วว่าใหญ่กว่า/ใหม่กว่า != ดีกว่าสำหรับงานนี้
(qwen3:4b 88% > qwen3:8b 82% > gemma3:12b 71% ในงานสกัด)

วัด 3 ด้านที่โมเดลตอบแชตต้องทำ:

1. attention cliff — จุดตายของโปรเจกต์นี้
   ยัด filler เข้า system prompt เรื่อยๆ แล้วดูว่าจุดไหนเริ่มลืม summary
   ปัจจุบัน qwen3:8b พังที่ ~3,700c (วัดไว้ใน §1) ถ้า 3.5 ทนกว่า = ได้ headroom คืน

2. utilization — คอขวดจริงที่เจอจาก sim_staleness
   context มีทั้งค่าเก่าและใหม่ -> เลือกค่าใหม่ถูกไหม (ไม่ใช่เลี่ยงตอบ)

3. persona — ต้องพูดไทย ลงท้าย ค่ะ/นะคะ ไม่หลุด "ครับ"
   (sim_staleness เจอ qwen3:8b หลุด "ครับ" มาแล้ว)

⚠️ วัด pass^N ไม่ใช่รอบเดียว — §1 บันทึกว่าที่ n น้อยผลสลับกันได้
"""
import argparse
import asyncio
import logging
import os
import pathlib
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import aiohttp  # noqa: E402

from bench_paper_opts import wilson  # noqa: E402
from config import OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)

MODELS = ["qwen3:8b", "qwen3.5:9b"]

# summary ที่ต้องจำให้ได้ — ปักไว้ท้าย system prompt เหมือน production
ANCHOR = "6 ส.ค.: คุยเรื่องแนวนิยาย — ผู้ใช้: ชอบอ่านนิยายสืบสวน"
CLIFF_Q = "ผมชอบอ่านหนังสือแนวไหน"
CLIFF_WANT = "สืบสวน"

# utilization — context มีค่าเก่า+ใหม่พร้อมกัน ต้องเลือกค่าใหม่
STALE_CTX = ("- 21 พ.ค.: ผู้ใช้เล่นแบดมินตันทุกเย็น — ผู้ใช้: เล่นแบดมินตัน\n"
             "- 25 ก.ค.: เลิกเล่นแบดแล้ว เปลี่ยนมาว่ายน้ำ — ผู้ใช้: เปลี่ยนมาว่ายน้ำแทน")
STALE_Q = "ตอนนี้ผมออกกำลังกายยังไง"

BASE_PERSONA = ("คุณคือรอสเต้ ผู้ช่วยหญิงชาวไทย พูดไทยเสมอ ลงท้ายด้วย ค่ะ/นะคะ "
                "ห้ามใช้ ครับ เด็ดขาด ตอบสั้นๆ เป็นธรรมชาติ")


async def ask(model: str, system: str, user: str) -> str:
    pl = {"model": model,
          "messages": [{"role": "system", "content": system},
                       {"role": "user", "content": user}],
          "stream": False, "think": False, "options": {"temperature": 0}}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=pl, timeout=300) as r:
                d = await r.json()
        raw = d.get("message", {}).get("content", "") or ""
        return raw.rsplit("</think>", 1)[-1] if "</think>" in raw else raw
    except Exception as e:
        return f"(error {type(e).__name__})"


async def test_cliff(model: str, filler_c: int, rounds: int) -> int:
    """ยัด filler แล้วดูว่ายังจำ summary ท้าย system prompt ได้ไหม"""
    sysmsg = (BASE_PERSONA + "\n\n[ข้อมูลระบบ]\n" + ("x" * filler_c) +
              "\n\nเรื่องที่เคยคุยกันก่อนหน้า:\n- " + ANCHOR)
    ok = 0
    for _ in range(rounds):
        if CLIFF_WANT in await ask(model, sysmsg, CLIFF_Q):
            ok += 1
    return ok


async def test_stale(model: str, rounds: int) -> tuple:
    sysmsg = BASE_PERSONA + "\n\nเรื่องที่เคยคุยกันก่อนหน้า:\n" + STALE_CTX
    new = old = 0
    for _ in range(rounds):
        a = await ask(model, sysmsg, STALE_Q)
        if "ว่ายน้ำ" in a:
            new += 1
        elif "แบด" in a:
            old += 1
    return new, old


async def test_persona(model: str, rounds: int) -> int:
    """ต้องไม่หลุด ครับ — sim_staleness เจอ qwen3:8b หลุดมาแล้ว"""
    qs = ["วันนี้เหนื่อยจัง", "เล่าเรื่องสนุกๆ หน่อย", "ช่วยคิดหัวข้อประชุมหน่อย"]
    ok = 0
    for q in qs:
        for _ in range(rounds):
            a = await ask(model, BASE_PERSONA, q)
            if "ครับ" not in a:
                ok += 1
    return ok


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--models", default=",".join(MODELS))
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",")]
    R = args.rounds

    print("=" * 92)
    print(" เทียบโมเดลฝั่งตอบแชต — วัดงานที่รอสเต้ทำจริง ไม่ใช่ benchmark ทั่วไป")
    print("=" * 92)

    # ── 1. attention cliff ──
    print(f"\n [1/3] attention cliff — จำ summary ท้าย system prompt ได้ถึง filler เท่าไหร่"
          f" ({R} รอบ/จุด)")
    steps = [0, 2000, 3500, 5000, 8000]
    print(f"\n {'filler':<10}" + "".join(f"{m:>16}" for m in models))
    print("-" * 92)
    cliff = {m: [] for m in models}
    for f in steps:
        row = f" {f:<10}"
        for m in models:
            ok = await test_cliff(m, f, R)
            cliff[m].append(ok)
            row += f"{f'{ok}/{R}':>16}"
        print(row)

    # ── 2. utilization ──
    print(f"\n [2/3] utilization — context มีค่าเก่า+ใหม่ ต้องตอบ 'ว่ายน้ำ' ({R} รอบ)")
    print(f"\n {'โมเดล':<16}{'ตอบค่าใหม่':>14}{'ตอบค่าเก่า':>14}{'เลี่ยง/อื่นๆ':>14}")
    print("-" * 92)
    stale = {}
    for m in models:
        new, old = await test_stale(m, R)
        stale[m] = new
        print(f" {m:<16}{f'{new}/{R}':>14}{f'{old}/{R}':>14}{f'{R-new-old}/{R}':>14}")

    # ── 3. persona ──
    print(f"\n [3/3] persona — ห้ามหลุด 'ครับ' (3 คำถาม × {R} รอบ)")
    print(f"\n {'โมเดล':<16}{'ไม่หลุด':>14}{'ช่วง 95%':>18}")
    print("-" * 92)
    persona_r = {}
    n_p = 3 * R
    for m in models:
        ok = await test_persona(m, R)
        persona_r[m] = ok
        lo, hi = wilson(ok, n_p)
        print(f" {m:<16}{f'{ok}/{n_p}':>14}{lo*100:>9.0f}-{hi*100:<7.0f}%")

    # ── สรุป ──
    print("\n" + "=" * 92)
    print(" สรุป")
    print("-" * 92)
    for m in models:
        # จุดที่เริ่มพัง = filler แรกที่ได้ < ครึ่ง
        broke = next((steps[i] for i, v in enumerate(cliff[m]) if v < R / 2), None)
        print(f" {m:<16} cliff: {'ทน >8000c' if broke is None else f'พังที่ ~{broke}c'}"
              f"  · utilization {stale[m]}/{R}"
              f"  · persona {persona_r[m]}/{n_p}")
    print("\n ⚠️ เปลี่ยนโมเดลก็ต่อเมื่อ **ดีขึ้นทุกด้าน** หรืออย่างน้อยไม่แย่ลงเลย")
    print("    (qwen3:8b ผูกกับ tool calling/rerank/summarize ด้วย — เปลี่ยนแล้วกระทบหลายจุด)")


if __name__ == "__main__":
    asyncio.run(main())
