"""เทียบวิธีแก้ write path บนชุดเดียวกับ baseline (80 เคส 10 กลุ่ม)

baseline วัดได้: จำได้ 11/80 = 14%  ·  มีหมวดรองรับ 62% vs ไม่มีหมวด 8%
ต้นเหตุ: โซ่ whitelist — คำใบ้ 20 คำ (ด่าน1) + หมวดปิด 7 หมวด (ด่าน2)

เทียบ 4 แบบ:
    baseline    ปัจจุบัน
    B           ตัดด่าน 1 ทิ้ง (ให้โมเดลตัดสินเอง)
                → งานวิจัย mem0: "LLM เป็น filter ที่ดีกว่า pre-computed structure"
    A           open schema — โมเดลตั้งชื่อหมวดเองอิสระ
                → arXiv 2604.11610: self-evolving schema ชนะ fixed taxonomy
    A+B         ทั้งสองอย่าง

⚠️ แนว A ต้องเขียน prompt ใหม่ (ไม่ใช้ closed set) — เขียนไว้ในไฟล์นี้เพื่อทดลอง
   ยังไม่แตะ production จนกว่าตัวเลขจะบอกว่าคุ้ม
"""
import argparse
import asyncio
import collections
import io
import json
import logging
import math
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

import memory  # noqa: E402
from memory_coverage_fixture import CASES, SUPPORTED_GROUPS  # noqa: E402
from ollama_client import MODEL, OLLAMA_URL  # noqa: E402

logging.disable(logging.CRITICAL)


def wilson(ok: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


# ── แนว A: prompt แบบ open schema ────────────────────────────────────────────
#
# ต่างจาก build_extract_prompt เดิม 3 อย่าง:
#   1. ไม่มีลิสต์หมวดปิด — ให้โมเดลตั้งชื่อหมวดเองเป็นคำไทยสั้นๆ
#   2. บอกชัดว่าเก็บ "อะไรก็ได้ที่จะยังมีค่าในอีก 3 เดือน" (salience ไม่ใช่หมวด)
#   3. สั่งเรื่อง negation ตรงๆ เพราะ baseline วัดได้ 0/12
def build_open_extract_prompt(user_message: str) -> str:
    return (
        "ดึง \"ข้อเท็จจริงถาวรเกี่ยวกับตัวผู้ใช้\" จากข้อความด้านล่าง\n"
        "เกณฑ์: เก็บสิ่งที่ยังจะมีค่าในอีก 3 เดือน (เช่น โรคประจำตัว ครอบครัว ทักษะ "
        "ความเชื่อ เป้าหมาย กิจวัตร ของที่มี ข้อจำกัด วันสำคัญ ประสบการณ์)\n"
        "กฎ:\n"
        "- เอาเฉพาะเรื่องของ *ตัวผู้ใช้เอง* ถ้าพูดถึงคนอื่น (ภรรยา/แม่/ลูก) "
        "ให้เขียนระบุว่าเป็นของใคร เช่น \"ภรรยาเป็นพยาบาล\"\n"
        "- **ประโยคปฏิเสธก็เป็นข้อเท็จจริง** — \"กินเผ็ดไม่ได้\" \"ขับรถไม่เป็น\" "
        "\"ไม่กินเนื้อวัว\" ต้องเก็บ เขียนให้คงความหมายปฏิเสธไว้\n"
        "- ห้ามเอา: คำถาม, ความรู้สึกชั่วคราว, เรื่องทั่วไปที่ไม่เกี่ยวกับผู้ใช้\n"
        "- \"category\" ให้ตั้งชื่อเองเป็นคำไทยสั้นๆ 1-2 คำ ที่อธิบายชนิดข้อมูลนั้น\n"
        "- ถ้าไม่มีข้อมูลที่เข้าเกณฑ์เลย ตอบ []\n"
        "ตอบเป็น JSON array ของ object ที่มี \"category\" กับ \"text\" เท่านั้น เช่น\n"
        "[{\"category\": \"สุขภาพ\", \"text\": \"แพ้กุ้ง\"}, "
        "{\"category\": \"ครอบครัว\", \"text\": \"มีลูกสาว 2 คน\"}]\n\n"
        f"ข้อความ: {user_message}"
    )


async def call_extract(prompt: str) -> list:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False, "think": False,
        "options": {"temperature": 0.2},
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
                data = await r.json()
        return data.get("message", {}).get("content", "") or ""
    except Exception:
        return ""


def parse_open(raw: str) -> list:
    """parse แบบ open — รับ category เป็นข้อความอิสระ (ไม่บังคับ closed set)

    ใช้ตรรกะเดียวกับ memory.parse_extracted_facts ทุกอย่าง ยกเว้นไม่ตี category เป็น None
    """
    import json as _json
    import re as _re
    if not raw:
        return []
    if "</think>" in raw:
        raw = raw.rsplit("</think>", 1)[-1]
    m = _re.search(r"\[.*?\]", raw, _re.DOTALL)
    if not m:
        return []
    try:
        items = _json.loads(m.group(0))
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict):
            text, cat = it.get("text"), it.get("category")
        elif isinstance(it, str):
            text, cat = it, None
        else:
            continue
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not (2 <= len(text) <= 60):
            continue
        out.append({"category": (cat or "").strip() or None, "text": text})
    return out


def remembered(must: list, facts: list) -> bool:
    blob = " ".join(f["text"] for f in facts)
    return any(m in blob for m in must)


async def run_variant(name: str, skip_gate: bool, open_schema: bool) -> list:
    rows = []
    for text, must, group, note in CASES:
        if not skip_gate and not memory.should_try_extract(text):
            rows.append((group, text, False, [], must, note))
            continue
        prompt = (build_open_extract_prompt(text) if open_schema
                  else memory.build_extract_prompt(text))
        raw = await call_extract(prompt)
        facts = parse_open(raw) if open_schema else memory.parse_extracted_facts(raw)
        rows.append((group, text, remembered(must, facts), facts, must, note))
    return rows


def report(name: str, rows: list):
    n = len(rows)
    ok = sum(1 for r in rows if r[2])
    lo, hi = wilson(ok, n)
    sup = [r for r in rows if r[0] in SUPPORTED_GROUPS]
    oth = [r for r in rows if r[0] not in SUPPORTED_GROUPS]
    neg = [r for r in rows if "ปฏิเสธ" in r[5]]
    print(f" {name:<22} {ok:>3}/{n:<4} ({ok/n*100:>3.0f}%)  ช่วง {lo*100:>3.0f}-{hi*100:<3.0f}%"
          f"   มีหมวด {sum(1 for r in sup if r[2])}/{len(sup)}"
          f"  ไม่มีหมวด {sum(1 for r in oth if r[2])}/{len(oth)}"
          f"  ปฏิเสธ {sum(1 for r in neg if r[2])}/{len(neg)}")
    return ok


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="baseline,B,A,AB")
    ap.add_argument("--save", help="เซฟผลดิบ")
    args = ap.parse_args()

    variants = {
        "baseline": ("baseline (ปัจจุบัน)", False, False),
        "B": ("B ตัดด่าน 1", True, False),
        "A": ("A open schema", False, True),
        "AB": ("A+B ทั้งสองอย่าง", True, True),
    }
    want = [v.strip() for v in args.variants.split(",")]

    print("=" * 104)
    print(" เทียบวิธีแก้ write path — ชุดเดียวกับ baseline")
    print(f" เคส {len(CASES)} · กลุ่ม 10 · ปฏิเสธ {sum(1 for c in CASES if 'ปฏิเสธ' in c[3])} เคส")
    print("=" * 104)

    results, raw_all = {}, {}
    t0 = time.perf_counter()
    for key in want:
        label, skip_gate, open_schema = variants[key]
        calls = len(CASES) if skip_gate else sum(1 for c in CASES if memory.should_try_extract(c[0]))
        print(f"\n กำลังรัน {label} (เรียกโมเดล {calls} ครั้ง)...")
        rows = await run_variant(label, skip_gate, open_schema)
        results[key] = (label, rows)
        raw_all[key] = [{"group": r[0], "text": r[1], "ok": r[2],
                         "facts": r[3], "must": r[4], "note": r[5]} for r in rows]

    print("\n" + "=" * 104)
    print(f" {'วิธี':<22} {'จำได้':>12}  {'ช่วง 95%':>12}   รายละเอียด")
    print("-" * 104)
    for key in want:
        label, rows = results[key]
        report(label, rows)
    print("=" * 104)

    # หมวดที่โมเดลตั้งเองในแนว A
    for key in want:
        if key in ("A", "AB"):
            cats = collections.Counter(f["category"] for _, rows in [results[key]]
                                       for r in rows for f in r[3] if f["category"])
            print(f"\n หมวดที่โมเดลตั้งเองใน {results[key][0]} ({len(cats)} หมวด):")
            print("  ", ", ".join(f"{c}({v})" for c, v in cats.most_common(18)))
            break

    print(f"\n เวลารวม {time.perf_counter() - t0:.0f}s")
    if args.save:
        json.dump(raw_all, open(args.save, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f" เซฟผลดิบไว้ที่ {args.save}")


if __name__ == "__main__":
    asyncio.run(main())
