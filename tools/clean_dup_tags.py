"""ล้าง tag ที่ซ้ำกันในความจำที่เก็บไปแล้ว — เก็บอันแรกสุด ตัดอันที่มาทีหลัง

ที่มา: dedupe_tags_against() กันซ้ำ **ตอนเขียน** ตั้งแต่ commit 6dc8fe8 แล้ว
แต่ของที่เก็บไว้ *ก่อนหน้านั้น* ยังค้างอยู่ — วัดได้ 31/144 = 22%
    4x user_pref:ต้องการคำพูดเป็นทางการ · 4x me_fact:แนะนำวิธีจัดการงาน
    4x me_pref:ชอบอ่านหนังสือ · 3x user_fact:ทำงานหนัก

ทำไมต้องล้าง: tag ซ้ำกินโควตา context ที่ชนเพดาน attention cliff 3,700c อยู่แล้ว
(วัดได้: ctx เฉลี่ย 403c ต่อคำถาม) — ตัดของซ้ำ = ได้ที่ว่างคืนฟรีๆ ไม่เสียข้อมูล

⚠️ แตะข้อมูลผู้ใช้จริง ใช้ข้อกำหนดความปลอดภัยชุดเดียวกับ clean_leaked_tags.py:
  - dry-run เป็นค่าเริ่มต้น ต้อง --apply ถึงเขียน
  - สำรองไฟล์ก่อนเขียนทุกครั้ง (.bak)
  - **ลบเฉพาะ tag ไม่ลบทั้งบรรทัด** — หัวเรื่องยังมีค่า (บันทึกว่าคุยอะไรกัน)
  - เทียบ "ชนิด+ค่า ตรงกันเป๊ะ" เท่านั้น
    user_pref:อ่านหนังสือ กับ me_pref:อ่านหนังสือ = คนละคน ไม่ใช่ซ้ำ
    "แนะนำคำกล่าว" vs "แนะนำคำกล่าวขอบคุณ" = ไม่ตัด (การเดาว่า "เหมือนพอ"
    คือปัญหาเดียวกับ conflict resolution ที่วัดแล้วว่ายาก)
  - **เก็บอันแรกสุด** (เรียงตามวันที่) เพราะเป็นครั้งที่ผู้ใช้พูดจริงครั้งแรก
    ส่วนครั้งหลังคือการพูดซ้ำ ไม่ใช่ข้อมูลใหม่

หลังล้างต้องรัน tools/repair_vector_sync.py --apply ด้วย เพราะข้อความเปลี่ยน
= id (hash เนื้อหา) เปลี่ยนตาม ของเดิมใน Chroma จะกลายเป็นขยะ
"""
import argparse
import glob
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

KINDS = ("user_pref", "user_fact", "user_ask", "me_pref", "me_fact", "me_suggest")


def dedupe_file(path: str, apply: bool) -> dict:
    """คืนสถิติ + เขียนไฟล์ถ้า apply — เก็บ tag ครั้งแรก ตัดครั้งถัดๆ ไป"""
    data = json.load(open(path, encoding="utf-8"))
    summaries = data.get("summaries") or []
    # เรียงตามวันที่เพื่อให้ "อันแรกสุด" เป็นครั้งที่พูดจริงครั้งแรก
    order = sorted(range(len(summaries)),
                   key=lambda i: str(summaries[i].get("date") or ""))

    seen = set()
    # (เคยลอง drop บรรทัดที่ tag ซ้ำหมด — วัดแล้วแย่ลง ดูหมายเหตุด้านล่าง)
    removed = 0
    total = 0
    emptied = 0
    for i in order:
        e = summaries[i]
        text = e["text"] if isinstance(e, dict) else e
        marks = list(memory._OWNER_TAG_RE.finditer(text))
        if not marks:
            continue
        head = text[:marks[0].start()].rstrip(" |")
        keep = []
        for j, mk in enumerate(marks):
            end = marks[j + 1].start() if j + 1 < len(marks) else len(text)
            kind = mk.group(1).rstrip(":")
            val = text[mk.end():end].strip(" |,")
            if not val:
                continue
            total += 1
            key = f"{kind}:{val}"
            if key in seen:
                removed += 1
                continue
            seen.add(key)
            keep.append(key)
        new_text = f"{head} | {' '.join(keep)}" if keep else head
        if not keep:
            # ⚠️ tag ซ้ำหมดทั้งบรรทัด เหลือแต่หัวเรื่อง — **เก็บบรรทัดไว้**
            # ลองลบทิ้งแล้ววัด: precision ตกจาก 73% -> 62% และ ctx โตขึ้น (322c -> 381c)
            # เพราะหัวเรื่องยังช่วยให้ vector หาเจอ แม้ filter_by_owner จะตัดตอนถามเจาะจงฝั่ง
            # -> การลบของที่ "ดูไร้ค่า" ทำให้แย่ลง ไม่ใช่ดีขึ้น
            emptied += 1
        if isinstance(e, dict):
            e["text"] = new_text
        else:
            summaries[i] = new_text


    if apply and removed:
        if not os.path.exists(path + ".bak"):   # ไม่ทับ .bak เดิมถ้ารันซ้ำ
            shutil.copy2(path, path + ".bak")
        json.dump(data, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
    return {"removed": removed, "total": total, "emptied": emptied,
            "n": len(summaries)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="เขียนจริง (ค่าเริ่มต้นคือ dry-run)")
    args = ap.parse_args()

    print("=" * 88)
    print(" ล้าง tag ซ้ำในความจำที่เก็บไปแล้ว"
          + ("  [เขียนจริง]" if args.apply else "  [dry-run — ยังไม่เขียน]"))
    print("=" * 88)

    tot_removed = tot_all = 0
    for path in sorted(glob.glob("memory/*.json")):
        st = dedupe_file(path, args.apply)
        tot_removed += st["removed"]
        tot_all += st["total"]
        if st["removed"]:
            pct = st["removed"] / st["total"] * 100 if st["total"] else 0
            print(f" {os.path.basename(path):<28} summary {st['n']:>3} · "
                  f"tag {st['total']:>3} · ตัด {st['removed']:>3} ({pct:.0f}%)"
                  + (f" · เหลือแต่หัวเรื่อง {st['emptied']}" if st["emptied"] else ""))

    print("-" * 88)
    pct = tot_removed / tot_all * 100 if tot_all else 0
    print(f" รวม: ตัด {tot_removed}/{tot_all} tag ({pct:.0f}%)")
    if not args.apply:
        print("\n ยังไม่ได้เขียนอะไร — ใส่ --apply ถ้าจะเขียนจริง (สำรอง .bak ให้อัตโนมัติ)")
    else:
        print("\n ⚠️ ต้องรัน tools/repair_vector_sync.py --apply ต่อ"
              " เพราะข้อความเปลี่ยน = id ใน Chroma เปลี่ยนตาม")


if __name__ == "__main__":
    main()
