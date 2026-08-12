"""สร้างชุดคำถามไทยจากความจำจริง **อัตโนมัติ** — ลด bias จากการที่ผมนึกคำถามเอง

⚠️ ทำไมต้อง generate ไม่ใช่เขียนเอง:
   ผมเคยพลาดใน C2 — แต่งคำถาม 10 ข้อเองแล้วสรุปว่า "ไม่ต้องแก้" ซึ่งผิด
   เพราะเผลอเลือกคำถามที่ระบบตอบได้ พอสร้างชุดอย่างเป็นระบบผลกลับด้าน
   ยิ่งต้องการ n เยอะ ยิ่งต้องเอาการตัดสินใจของผมออกจากการเลือกเคส

วิธี: ไล่ทุก tag ที่มีในความจำจริง แล้วประกอบคำถามด้วย **template ตายตัว**
      -> คำถามมาจากข้อมูล ไม่ใช่จากที่ผมเลือกว่าจะถามอะไร

เกณฑ์คัดออก (บังคับ ไม่ใช่ดุลพินิจ):
  1. คำถามต้องไม่มีคำเนื้อหาของ tag อยู่ในตัวเอง (ไม่งั้นวัดแค่ string match)
     -> เอาคำเนื้อหาหลักออกจากคำถาม เหลือแต่บริบท
  2. tag ต้องมีคำเนื้อหาอย่างน้อย 1 คำหลังตัด stopword
  3. ตัดซ้ำด้วยคำถามที่เหมือนกัน

ผลที่ได้ใช้แทน/เสริม thai_recall_cases.py ที่เขียนมือไว้ 40 ข้อ
"""
import collections
import io
import json
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import memory  # noqa: E402

REAL_UID = 434893254576701450

# template ตายตัว — คำถามจึงมาจาก *ข้อมูล* ไม่ใช่จากที่ผมเลือกถาม
# แต่ละชนิด tag มีสำนวนถามต่างกันตามธรรมชาติของภาษา
TEMPLATES = {
    "user_pref": ["ผมชอบ{h}อะไร", "ผมสนใจเรื่อง{h}ไหม", "เคยคุยเรื่อง{h}กับผมไหม"],
    "user_fact": ["ผมเป็นยังไงเรื่อง{h}", "ผมมีเรื่อง{h}ไหม", "จำเรื่อง{h}ของผมได้ไหม"],
    "me_pref": ["รอสเต้ชอบ{h}อะไร", "รอสเต้สนใจ{h}ไหม", "รอสเต้รู้สึกยังไงกับ{h}"],
    "me_fact": ["รอสเต้เคยทำเรื่อง{h}ไหม", "รอสเต้ช่วยเรื่อง{h}ยังไง"],
}

# คำที่ใช้เป็น "หัวเรื่อง" ในคำถามไม่ได้ (กว้างเกินไป/เป็นกริยาล้วน)
_TOO_GENERIC = {"ชอบ", "ไม่", "มี", "เป็น", "ทำ", "ได้", "ให้", "ต้องการ", "แนะนำ", "ขอ"}


def content_words(text: str) -> list:
    """คำเนื้อหาของ tag — ตัด stopword และคำกว้างเกินไปออก"""
    return [w for w in memory._keywords(text, expand=False)
            if w not in _TOO_GENERIC and len(w) >= 2]


def generate(summaries: list) -> list:
    """คืน [(คำถาม, [คำที่ต้องเจอ])] — สร้างจาก tag ทุกอันในความจำ"""
    tags = collections.Counter()
    for e in summaries:
        t = e["text"] if isinstance(e, dict) else e
        p = memory.split_owner_tags(t)
        for kind in ("user_pref", "user_fact", "me_pref", "me_fact"):
            for v in p[kind]:
                tags[(kind, v)] += 1

    seen_q = set()
    out = []
    for (kind, value), _ in tags.most_common():
        words = content_words(value)
        if not words:
            continue
        # คำที่ยาวที่สุด = คำหลัก (ใช้เป็น "คำตอบที่ต้องเจอ")
        answer = max(words, key=len)
        # หัวเรื่องสำหรับคำถาม = คำอื่นที่เหลือ (ไม่ใช่คำตอบ) กันวัดแค่ string match
        context = [w for w in words if w != answer]
        head = context[0] if context else ""
        for tpl in TEMPLATES[kind]:
            q = tpl.format(h=head) if head else tpl.format(h="").replace("  ", " ")
            q = q.replace("เรื่องไหม", "อะไรไหม").replace("เรื่องยังไง", "อะไรยังไง")
            if answer in q:            # กฎ 1: คำถามห้ามมีคำตอบอยู่ในตัว
                continue
            if q in seen_q:
                continue
            seen_q.add(q)
            out.append((q, [answer]))
            break                       # 1 คำถามต่อ 1 tag พอ
    return out


def main():
    summaries = json.load(open(f"memory/{REAL_UID}.json", encoding="utf-8"))["summaries"]
    cases = generate(summaries)
    blob = "\n".join(e["text"] for e in summaries)
    # คัดเฉพาะเคสที่คำตอบมีอยู่จริง (ทุกอันควรผ่านอยู่แล้วเพราะสร้างจาก tag)
    cases = [(q, m) for q, m in cases if any(x in blob for x in m)]

    print(f"สร้างคำถามได้ {len(cases)} ข้อ จาก summary {len(summaries)} อัน")
    print()
    for q, m in cases[:15]:
        print(f"  {q:<44} -> ต้องเจอ {m}")
    print(f"  ... อีก {max(0, len(cases) - 15)} ข้อ")

    out = "tools/thai_cases_generated.json"
    json.dump(cases, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nเซฟไว้ที่ {out}")


if __name__ == "__main__":
    main()
