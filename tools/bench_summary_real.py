"""ทดสอบ summary v2 กับ *บทสนทนาจริง* จาก memory/ — ไม่ใช่บทที่แต่งขึ้นเอง

ทำไมต้องมีแยกจาก bench_summary_detail.py: bench ตัวนั้นใช้บทที่เขียนขึ้นเอง สั้น (4 ข้อความ)
และมีรายละเอียดชัดเจนผิดปกติ ซึ่งเอื้อกับ v2 เกินจริง — บทจริงยาวกว่า (MAX_HISTORY_PAIRS=8 คู่)
มี tool output ยาวๆ ปนอยู่ (ราคาน้ำมันทุกยี่ห้อ, พยากรณ์อากาศเต็มรูปแบบ) และบางทีก็คุยเรื่อง
ไม่มีสาระให้สรุปเลย ผลจากบทแต่งเองจึงยังไม่พอสรุปว่าใช้ได้จริง

⚠️ ไม่แตะ production — เรียก memory.build_summary_prompt เป็น baseline เทียบเท่านั้น

วัด 3 อย่าง:
  1. ขนาดจริงบนบทจริง       — v2 ยาวขึ้นเท่าไหร่เมื่อเจอบทที่มี tool output ปน
  2. grounding trigger จริงไหม — บทจริงซับซ้อนกว่า โมเดลมีโอกาสแต่งมากกว่า
  3. เนื้อหาที่เพิ่มมามีค่าไหม  — ให้คนอ่านเทียบเอง (พิมพ์คู่กัน)
"""
import argparse
import asyncio
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import logging  # noqa: E402

import memory  # noqa: E402
import ollama_client  # noqa: E402
from _bench_target import resolve_memory_file  # noqa: E402
from summary_v2 import (  # noqa: E402
    build_summary_prompt_v2, clip_summary, find_self_description, find_ungrounded,
)

logging.disable(logging.CRITICAL)


def load_real_chunks(path: str, pairs_per_chunk: int = 4) -> list:
    """แบ่ง history จริงเป็นก้อนๆ ก้อนละหลายคู่ — เลียนแบบที่ summarize_and_verify เจอจริง"""
    d = json.load(open(path, encoding="utf-8"))
    hist = d.get("history", [])
    chunks, cur = [], []
    for m in hist:
        cur.append(m)
        if len(cur) >= pairs_per_chunk * 2:
            chunks.append(cur)
            cur = []
    if len(cur) >= 4:
        chunks.append(cur)
    return chunks


async def _gen(prompt: str) -> str:
    msg = await ollama_client._chat_once(
        [{"role": "user", "content": prompt}], temperature=0.1)
    raw = ollama_client._strip_think(msg.get("content", "") or "")
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    return lines[0] if lines else ""


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    path = resolve_memory_file()
    chunks = load_real_chunks(path)
    if not chunks:
        raise SystemExit("history ในไฟล์ความจำสั้นเกินไป — คุยกับบอทเพิ่มก่อน")

    print("=" * 96)
    print(f" ทดสอบ summary v2 กับบทสนทนาจริง — {len(chunks)} ก้อน × {args.reps} รอบ")
    print(f" ไฟล์: {path}")
    print("=" * 96)

    stat = {"a_size": [], "b_size": [], "trigger": 0, "clipped": 0,
            "selfdesc": 0, "selfdesc_fixed": 0}

    for i, pairs in enumerate(chunks, 1):
        convo_len = sum(len(m.get("content") or "") for m in pairs)
        preview = (pairs[0].get("content") or "")[:52].replace("\n", " ")
        print(f"\n{'─' * 96}")
        print(f" ก้อนที่ {i}: {len(pairs)} ข้อความ, {convo_len}c   เริ่มด้วย: {preview!r}")
        print("─" * 96)

        for r in range(args.reps):
            a = await _gen(memory.build_summary_prompt(pairs))
            b_raw = await _gen(build_summary_prompt_v2(pairs))

            # ── ตรวจ 2 ชั้นแล้วขอใหม่ถ้าไม่ผ่าน (ไม่ซ่อมสตริงที่โมเดลเขียน) ──
            ung = find_ungrounded(b_raw, pairs)
            self_d = find_self_description(b_raw)
            if ung:
                stat["trigger"] += 1
            if self_d:
                stat["selfdesc"] += 1
            if ung or self_d:
                retry = await _gen(build_summary_prompt_v2(pairs))
                if (retry and not find_ungrounded(retry, pairs)
                        and not find_self_description(retry)):
                    b_raw = retry
                    if self_d:
                        stat["selfdesc_fixed"] += 1

            b = clip_summary(b_raw)
            if len(b) < len(b_raw.strip()):
                stat["clipped"] += 1
            stat["a_size"].append(len(a))
            stat["b_size"].append(len(b))

            if r == 0:      # พิมพ์รอบแรกให้ดูเนื้อหาเทียบกัน
                print(f"   เดิม ({len(a):>3}c): {a}")
                print(f"   v2   ({len(b):>3}c): {b}")
                if ung:
                    print(f"   ⚠️ grounding จับได้: {ung}")
                if self_d:
                    print(f"   ⚠️ บรรยายตัวเอง: {self_d[:2]}")
                if len(b) < len(b_raw.strip()):
                    print(f"   ✂️ ถูกตัดจาก {len(b_raw.strip())}c")

    a_avg = sum(stat["a_size"]) / max(len(stat["a_size"]), 1)
    b_avg = sum(stat["b_size"]) / max(len(stat["b_size"]), 1)
    n = len(stat["a_size"])

    print("\n" + "=" * 96)
    print(f" สรุป ({n} ตัวอย่าง)")
    print("-" * 96)
    print(f"   ขนาดเฉลี่ย   เดิม {a_avg:>5.0f}c   v2 {b_avg:>5.0f}c   "
          f"(+{(b_avg/max(a_avg,1)-1)*100:.0f}%)")
    print(f"   ยาวสุด       เดิม {max(stat['a_size']):>5}c   v2 {max(stat['b_size']):>5}c")
    print(f"   grounding จับได้ {stat['trigger']}/{n} ครั้ง")
    print(f"   บรรยายตัวเอง จับได้ {stat['selfdesc']}/{n} ครั้ง "
          f"(ขอใหม่แล้วหาย {stat['selfdesc_fixed']}/{stat['selfdesc']})")
    print(f"   ถูกตัดเพราะยาวเกิน {stat['clipped']}/{n} ครั้ง")
    print()
    print(f"   ผลต่อ context (recall คืนสูงสุด 5 อัน):")
    print(f"     เดิม 5 x {a_avg:.0f}c = {5*a_avg:.0f}c   |   v2 5 x {b_avg:.0f}c = {5*b_avg:.0f}c")
    print(f"     รวม tool สูงสุด 1,520c → เดิม {1520+5*a_avg:.0f}c | v2 {1520+5*b_avg:.0f}c "
          f"(เกณฑ์พัง ~3,700c)")
    print("=" * 96)


if __name__ == "__main__":
    asyncio.run(main())
