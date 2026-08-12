"""วัดกับ **ความจำจริงของ production** ไม่ใช่ fixture แต่งขึ้น

ทำไมต้องมีไฟล์นี้: ตัวเลขทั้งหมดใน Phase 0/1 มาจาก fixture ที่ผมแต่งเอง ซึ่งพิสูจน์ได้แค่ว่า
"วิธีไหนดีกว่าในสถานการณ์ที่ผมออกแบบ" ไม่ได้พิสูจน์ว่า **บอทที่รันอยู่ตอนนี้ดีขึ้นจริงไหม**

⚠️ อ่านอย่างเดียว ไม่เขียนอะไรกลับลงไฟล์ผู้ใช้เลย

สิ่งที่วัดได้จริงกับข้อมูลจริง (และสิ่งที่วัดไม่ได้):
  ✅ ความซ้ำซ้อนของ summary/tag — วัดได้ตรงๆ
  ✅ ขนาด context ที่ส่งเข้าโมเดลจริง — เทียบกับ attention cliff ~3,700c ได้
  ✅ noise rate: บรรทัดที่ดึงมาแต่ไม่เกี่ยวกับคำถาม
  ❌ ความแม่นของการแก้ conflict — ข้อมูลจริงยังไม่มีคู่ขัดแย้ง (สรุปแค่ 5 วัน)
     ต้องรอให้ผู้ใช้เปลี่ยนใจเรื่องอะไรสักอย่างข้ามสัปดาห์ก่อน
"""
import argparse
import collections
import glob
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

import conflict_proto as proto  # noqa: E402
import memory  # noqa: E402

logging.disable(logging.CRITICAL)

# คำถามที่ผู้ใช้ถามบอทจริงบ่อยที่สุด — ใช้วัด context ที่จะถูกส่งเข้าโมเดล
# (ไม่มีเฉลย เพราะข้อมูลจริงไม่มี ground truth — วัด "ขนาด/ความซ้ำ" ไม่ใช่ "ถูก/ผิด")
PROBE_QUESTIONS = [
    "เราเคยคุยเรื่องอะไรกันบ้าง",
    "จำได้ไหมว่าผมชอบอะไร",
    "รอสเต้ชอบอะไร",
    "ผมทำงานอะไร",
    "เคยคุยเรื่องหนังสือกันไหม",
    "ผมเบื่ออะไรอยู่",
]


def tag_payload(text: str) -> list:
    """ดึงเนื้อหาในแต่ละ tag ออกมาเป็นรายการ"""
    out = []
    marks = list(memory._OWNER_TAG_RE.finditer(text))
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[mk.end():end].strip(" |,")
        if seg:
            out.append(f"{mk.group(1)}:{seg}")
    return out


def analyse_user(path: str, verbose: bool = False) -> dict:
    d = json.load(open(path, encoding="utf-8"))
    S = d.get("summaries", [])
    if not S:
        return {}
    texts = [e["text"] if isinstance(e, dict) else e for e in S]

    tags = collections.Counter()
    for t in texts:
        for p in tag_payload(t):
            tags[p] += 1
    total_tags = sum(tags.values())
    dup_tags = sum(v - 1 for v in tags.values() if v > 1)

    # summary ที่ข้อความซ้ำกันเป๊ะ
    dup_lines = sum(v - 1 for v in collections.Counter(texts).values() if v > 1)

    # conflict ที่ M3 ตรวจพบ
    sup = [e for e in proto.m3_consolidate(S) if e.get("superseded")]

    # ขนาด context จริงที่จะส่งเข้าโมเดล + noise
    ctx_sizes, recalled_counts = [], []
    for q in PROBE_QUESTIONS:
        got = memory.recall_summaries({"summaries": S}, q)
        block = "\n".join(f"- {x}" for x in got)
        ctx_sizes.append(len(block))
        recalled_counts.append(len(got))

    dates = [e.get("date") for e in S if isinstance(e, dict) and e.get("date")]
    return {
        "path": os.path.basename(path),
        "n": len(S),
        "span": f"{min(dates)} → {max(dates)}" if dates else "-",
        "dup_lines": dup_lines,
        "tags_total": total_tags,
        "tags_dup": dup_tags,
        "dup_pct": (dup_tags / total_tags * 100) if total_tags else 0,
        "conflicts": len(sup),
        "ctx_avg": sum(ctx_sizes) / len(ctx_sizes),
        "ctx_max": max(ctx_sizes),
        "recall_avg": sum(recalled_counts) / len(recalled_counts),
        "top_tags": tags.most_common(5),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print("=" * 96)
    print(" วัดกับความจำจริงของ production (อ่านอย่างเดียว ไม่แก้ไฟล์)")
    print("=" * 96)

    rows = []
    for f in sorted(glob.glob("memory/*.json"), key=os.path.getsize, reverse=True):
        r = analyse_user(f, args.verbose)
        if r:
            rows.append(r)

    if not rows:
        print(" ไม่พบไฟล์ความจำที่มี summary")
        return

    print(f"\n {'ไฟล์':<26} {'summary':>8} {'ซ้ำเป๊ะ':>8} {'tag ซ้ำ':>10} {'conflict':>9}")
    print("-" * 96)
    for r in rows:
        print(f" {r['path']:<26} {r['n']:>8} {r['dup_lines']:>8} "
              f"{r['tags_dup']:>4}/{r['tags_total']:<5} {r['conflicts']:>9}")

    main_row = max(rows, key=lambda r: r["n"])
    print("\n" + "=" * 96)
    print(f" ผู้ใช้ที่มีข้อมูลมากสุด: {main_row['path']}  ({main_row['n']} summary)")
    print(f" ช่วงเวลา: {main_row['span']}")
    print("=" * 96)
    print(f"\n ความซ้ำซ้อน:")
    print(f"   summary ที่ข้อความซ้ำกันเป๊ะ: {main_row['dup_lines']}")
    print(f"   tag ที่ซ้ำ: {main_row['tags_dup']}/{main_row['tags_total']} "
          f"({main_row['dup_pct']:.0f}%)")
    print(f"   tag ที่ซ้ำมากสุด:")
    for k, v in main_row["top_tags"]:
        print(f"      {v:>3}x  {k[:60]}")

    print(f"\n context ที่ส่งเข้าโมเดลจริง (จาก {len(PROBE_QUESTIONS)} คำถามที่ถามบ่อย):")
    print(f"   เฉลี่ย {main_row['ctx_avg']:.0f}c  สูงสุด {main_row['ctx_max']}c  "
          f"(ดึงเฉลี่ย {main_row['recall_avg']:.1f} บรรทัด)")
    print(f"   ⚠️ attention cliff วัดไว้ที่ ~3,700c — นี่เป็นแค่ส่วน summary")
    print(f"      ยังไม่รวม SYSTEM_PROMPT + FEWSHOT + tool schema + history")

    print(f"\n conflict ที่ M3 ตรวจพบในข้อมูลจริง: {main_row['conflicts']}")
    if main_row["conflicts"] == 0:
        print("   → ยังไม่มีคู่ขัดแย้งจริงให้วัด (สรุปทั้งหมดอยู่ในช่วงเวลาสั้น)")
        print("   → **วัดความแม่นของการแก้ conflict กับข้อมูลจริงยังไม่ได้**")
        print("      ต้องรอผู้ใช้เปลี่ยนใจเรื่องอะไรสักอย่างข้ามสัปดาห์ก่อน")


if __name__ == "__main__":
    main()
