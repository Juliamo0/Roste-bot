"""ล้าง tag ที่โมเดลลอกมาจากตัวอย่างใน prompt ออกจากความจำที่เก็บไปแล้ว

ที่มา: build_summary_prompt เดิมมีตัวอย่าง `me_fact:แนะนำร้านให้` / `me_pref:ชอบหนังสือเก่า`
โมเดลลอกมาใช้จริง 17/55 และ 14/55 ครั้ง (ดู commit 68b6382) — แก้ prompt + เพิ่ม
validation layer ไปแล้ว แต่ **ของที่เก็บไปก่อนหน้ายังค้างอยู่ 34 อัน**

⚠️ แตะข้อมูลผู้ใช้จริง จึงออกแบบให้ปลอดภัยที่สุด:
  - dry-run เป็นค่าเริ่มต้น ต้อง --apply ถึงเขียน
  - สำรองไฟล์ก่อนเขียนทุกครั้ง (.bak ข้างไฟล์เดิม)
  - **ลบเฉพาะ tag ไม่ลบทั้งบรรทัด** — หัวเรื่องยังมีค่า (เป็นบันทึกว่าคุยอะไรกัน)
    ตรวจแล้วว่ามีแค่ 3/55 ที่ลบ tag แล้วไม่เหลือ tag เลย แต่ยังมีหัวเรื่องอยู่
  - เทียบแบบ **ค่าตรงเป๊ะ** เท่านั้น (ไม่ใช่ substring) — ถ้าผู้ใช้คุยเรื่องร้านอาหารจริง
    "แนะนำร้านให้" ที่มาจากบทสนทนาจริงก็จะถูกลบด้วย ซึ่งรับได้เพราะแยกไม่ออก
    และของจริงจะถูกบันทึกใหม่ตอนคุยครั้งหน้า

หลังล้างต้องรัน tools/repair_vector_sync.py --apply ด้วย เพราะข้อความ summary เปลี่ยน
= id (hash เนื้อหา) เปลี่ยนตาม ของเดิมใน Chroma จะกลายเป็นขยะ
"""
import argparse
import glob
import io
import json
import os
import pathlib
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402


def clean_text(text: str) -> str:
    """ลบเฉพาะ tag ที่ค่าตรงกับตัวอย่างใน prompt — คืนบรรทัดที่ล้างแล้ว"""
    marks = list(memory._OWNER_TAG_RE.finditer(text))
    if not marks:
        return text
    head = text.split("|", 1)[0].strip()
    kept = []
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[mk.end():end].strip(" |,")
        if seg and seg not in memory._LEAKED_EXAMPLE_VALUES:
            kept.append(f"{mk.group(1)}:{seg}")
    return f"{head} | {' '.join(kept)}" if kept else head


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="เขียนจริง (ค่าเริ่มต้น = dry-run)")
    args = ap.parse_args()

    print("=" * 96)
    print(" ล้าง tag ที่ลอกจากตัวอย่างใน prompt ออกจากความจำที่เก็บไปแล้ว")
    print(f" ค่าที่ถือว่าเป็นของลอก: {sorted(memory._LEAKED_EXAMPLE_VALUES)}")
    print(f" โหมด: {'APPLY (เขียนจริง)' if args.apply else 'DRY-RUN (ไม่เขียน)'}")
    print("=" * 96)
    print(f" {'ไฟล์':<26} {'summary':>8} {'tag ลอก':>9} {'เหลือแต่หัวเรื่อง':>18}")
    print("-" * 96)

    total_tags = total_bare = 0
    for f in sorted(glob.glob("memory/*.json")):
        d = json.load(open(f, encoding="utf-8"))
        S = d.get("summaries", [])
        if not S:
            continue
        removed = bare = 0
        new_S = []
        for e in S:
            txt = e["text"] if isinstance(e, dict) else e
            cleaned = clean_text(txt)
            if cleaned != txt:
                before = sum(len(memory.split_owner_tags(txt)[k])
                             for k in ("user_pref", "user_fact", "me_pref", "me_fact"))
                after = sum(len(memory.split_owner_tags(cleaned)[k])
                            for k in ("user_pref", "user_fact", "me_pref", "me_fact"))
                removed += before - after
                if after == 0:
                    bare += 1
            new_S.append({**e, "text": cleaned} if isinstance(e, dict) else cleaned)

        if removed:
            print(f" {os.path.basename(f)[:24]:<26} {len(S):>8} {removed:>9} {bare:>18}")
            total_tags += removed
            total_bare += bare
            if args.apply:
                shutil.copy2(f, f + ".bak")
                d["summaries"] = new_S
                json.dump(d, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("-" * 96)
    print(f" รวม: ลบ tag {total_tags} อัน · summary ที่เหลือแต่หัวเรื่อง {total_bare} อัน")
    if args.apply:
        print("\n ✅ เขียนแล้ว (สำรองไว้เป็น .bak ข้างไฟล์เดิม)")
        print(" ⚠️ ต้องรัน tools/repair_vector_sync.py --apply ต่อ")
        print("    เพราะข้อความเปลี่ยน = id (hash) เปลี่ยน ของเดิมใน Chroma กลายเป็นขยะ")
    elif total_tags:
        print("\n รันด้วย --apply เพื่อล้างจริง")
    print("=" * 96)


if __name__ == "__main__":
    main()
