"""เทียบ "รูปแบบการวางความทรงจำใน prompt" ของโปรเจกต์จริง 5 แบบ บนข้อมูลชุดเดียวกัน

⚠️ ไม่แตะ production — ทุกแบบประกอบ prompt ในไฟล์นี้เอง

ที่มาของแต่ละแบบ (อ่านจากซอร์สจริงของเขา ไม่ได้เดา):
  M0 ปัจจุบัน   — chat.py:590 ประโยคไทยเล่าเรื่อง ต่อท้าย SYSTEM_PROMPT
  M1 Qwen       — qwen_agent/agents/assistant.py: "# Knowledge Base" + "## The content
                  from {source}:" + เนื้อหาใน code fence  ← รูปแบบที่ผู้สร้างโมเดลเองใช้
  M2 ProjectBEA — src/core/skills/memory/memory.py: "[LONG TERM MEMORY]" +
                  "RELEVANT DIARY ENTRIES:\n- [date]: ..."
  M3 mindcraft  — profiles/defaults/_default.json: "Summarized memory:'...'"
  M4 Qwen+ไทย   — โครงแบบ M1 แต่หัวข้อเป็นไทย (เช็คว่าที่ได้ผลคือ *โครงสร้าง* หรือ *ภาษา*)

ทำไมต้องวัด: วัดแล้วว่ารอสเต้ตอบคำถาม "เรื่องของผู้ใช้" ถูกแค่ 25% (9/36) แต่ "เรื่องของ
ตัวเอง" ถูก 86% (31/36) — ต่างกัน 3.4 เท่าบนข้อมูลชุดเดียวกัน สมมติฐาน: บล็อกความทรงจำของ
เราเขียนกลมกลืนกับ persona จนโมเดลอ่านเป็น "ตัวตน" ไม่ใช่ "ข้อมูลที่ต้องใช้ตอบ"
ทุกโปรเจกต์อื่นมี marker ที่ตัดขาดชัดเจน เรามีที่เดียวที่ไม่มี

วัดแยกสองฝั่งเสมอ — ฝั่งผู้ใช้คือตัวปัญหา ฝั่งรอสเต้เป็นตัวคุมว่าไม่ทำให้ของเดิมพัง
"""
import argparse
import asyncio
import copy
import math
import os
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import logging  # noqa: E402

import ollama_client  # noqa: E402
import persona  # noqa: E402

logging.disable(logging.CRITICAL)

# ข้อมูลดิบชุดเดียวกันทุกแบบ (เนื้อหาเท่ากันเป๊ะ ต่างแค่วิธีห่อ)
FACTS = [
    ("31 ก.ค.", "คุยเรื่องแนวนิยาย ผู้ใช้ชอบนิยายสืบสวน รอสเต้ชอบแนวแฟนตาซี"),
    ("30 ก.ค.", "คุยเรื่องอาหาร ผู้ใช้กินเผ็ดไม่ได้ รอสเต้ไม่ชอบของหวาน"),
    ("29 ก.ค.", "คุยงานอดิเรก ผู้ใช้ชอบเล่นเกม รอสเต้ชอบซ่อมหุ่นยนต์"),
]


def fmt_m0() -> str:
    return ("\n\nเรื่องที่เคยคุยกันก่อนหน้า (รอสเต้จำได้จริง — นี่คือความทรงจำของคุณเอง):\n"
            + "\n".join(f"- {d}: {t}" for d, t in FACTS)
            + "\nถ้าผู้ใช้ถามถึงเรื่องพวกนี้ ให้ตอบตามที่จำได้ ห้ามบอกว่าจำไม่ได้")


def fmt_m1_qwen() -> str:
    """รูปแบบ Qwen-Agent: # Knowledge Base + ## The content from {source} + code fence"""
    snippets = "\n\n".join(
        f"## The content from บทสนทนาวันที่ {d}:\n\n```\n{t}\n```" for d, t in FACTS)
    return ("\n\n# Knowledge Base\n\n" + snippets
            + "\n\nใช้ข้อมูลใน Knowledge Base ข้างบนตอบคำถามของผู้ใช้ ห้ามเดาเอง")


def fmt_m2_bea() -> str:
    return ("\n\n[LONG TERM MEMORY]\nRELEVANT DIARY ENTRIES:\n"
            + "\n".join(f"- [{d}]: {t}" for d, t in FACTS))


def fmt_m3_mindcraft() -> str:
    mem = " ".join(f"{d}: {t}" for d, t in FACTS)
    return f"\n\nSummarized memory:'{mem}'"


def fmt_m4_qwen_th() -> str:
    """โครงเดียวกับ M1 แต่หัวข้อเป็นไทย — แยกว่าที่ได้ผลคือโครงสร้างหรือภาษา"""
    snippets = "\n\n".join(
        f"## เนื้อหาจากบทสนทนาวันที่ {d}:\n\n```\n{t}\n```" for d, t in FACTS)
    return ("\n\n# ฐานข้อมูลความทรงจำ\n\n" + snippets
            + "\n\nใช้ข้อมูลในฐานข้อมูลข้างบนตอบคำถามของผู้ใช้ ห้ามเดาเอง")


def fmt_m5_qwen_zh() -> str:
    """เทมเพลตจีนของ Qwen แบบคำต่อคำ (KNOWLEDGE_TEMPLATE_ZH/KNOWLEDGE_SNIPPET_ZH)

    ทำไมต้องลอง: qwen3 เป็นโมเดลจีน เทมเพลตจีนคือเส้นทางที่มันเจอบ่อยที่สุดตอนเทรน
    ถ้าชนะ = โมเดลรู้จัก "# 知识库" ดีกว่าหัวข้อภาษาอื่น
    ⚠️ ความเสี่ยง: persona.py ห้ามตัวอักษรจีนในคำตอบเด็ดขาด (fix_persona_slips ลบทิ้ง)
    ถ้าหัวข้อจีนทำให้โมเดลตอบปนจีน จะแลกปัญหาหนึ่งกับอีกปัญหา — bench วัดให้ด้วย
    """
    snippets = "\n\n".join(
        f"## 来自 บทสนทนาวันที่ {d} 的内容：\n\n```\n{t}\n```" for d, t in FACTS)
    return ("\n\n# 知识库\n\n" + snippets
            + "\n\nใช้ข้อมูลข้างบนตอบคำถามของผู้ใช้ ห้ามเดาเอง")


def fmt_m6_qwen_th_pure() -> str:
    """โครง Qwen + ไทยล้วน ไม่มีคำอังกฤษปนเลย (M4 ยังมี 'Knowledge Base' ในบรรทัดท้าย)

    แยกตัวแปรจาก M4: ถ้า M6 ≥ M4 แปลว่าคำอังกฤษที่เหลือใน M4 ไม่ได้ช่วย
    ตัดทิ้งได้เพื่อความสม่ำเสมอของภาษา
    """
    snippets = "\n\n".join(
        f"## เนื้อหาจากบทสนทนาวันที่ {d}:\n\n```\n{t}\n```" for d, t in FACTS)
    return ("\n\n# ฐานความรู้\n\n" + snippets
            + "\n\nใช้ข้อมูลในฐานความรู้ข้างบนตอบคำถามของผู้ใช้ ห้ามเดาเอง")


FORMATS = {
    "M0 ปัจจุบัน (ไทยเล่าเรื่อง)": fmt_m0,
    "M1 Qwen official (EN)": fmt_m1_qwen,
    "M2 ProjectBEA": fmt_m2_bea,
    "M3 mindcraft": fmt_m3_mindcraft,
    "M4 Qwen โครง + ไทย": fmt_m4_qwen_th,
    "M5 Qwen official (ZH)": fmt_m5_qwen_zh,
    "M6 Qwen โครง + ไทยล้วน": fmt_m6_qwen_th_pure,
}

# (คำถาม, ฝั่ง, ต้องมี, ห้ามมี)
CASES = [
    ("ผมชอบอ่านนิยายแนวไหนนะ จำได้ไหม", "user", ["สืบสวน"], ["แฟนตาซี"]),
    ("ผมกินเผ็ดได้ไหมนะ", "user", ["ไม่ได้", "ไม่ค่อย"], []),
    ("งานอดิเรกผมคืออะไรนะ", "user", ["เกม"], ["หุ่นยนต์"]),
    ("รอสเต้ชอบอ่านแนวไหนเหรอ", "me", ["แฟนตาซี"], ["สืบสวน"]),
    ("รอสเต้ไม่ชอบกินอะไร", "me", ["หวาน"], ["เผ็ด"]),
    ("รอสเต้ชอบทำอะไรตอนว่าง", "me", ["หุ่นยนต์"], ["เกม"]),
]

DENIAL = ["ไม่เคย", "จำไม่ได้", "ไม่ค่อยจำ", "ไม่มีข้อมูล", "ไม่แน่ใจ"]


def wilson(ok, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = ok / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


async def ask(question: str, block: str) -> str:
    msgs = ([{"role": "system", "content": persona.SYSTEM_PROMPT + block}]
            + copy.deepcopy(persona.FEWSHOT_EXAMPLES)
            + [{"role": "system", "content": persona.build_author_note()},
               {"role": "user", "content": question}])
    m = await ollama_client._chat_once(msgs, temperature=0.8)
    return ollama_client._strip_think(m.get("content", "") or "").strip()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--model", default=None,
                    help="ทับโมเดลที่ใช้ทดสอบ เช่น qwen3:14b (ไม่แตะ .env/production)")
    ap.add_argument("--only", default=None,
                    help="รันเฉพาะรูปแบบที่ขึ้นต้นด้วยรหัสนี้ เช่น M0,M4,M6")
    a = ap.parse_args()

    if a.model:
        ollama_client.MODEL = a.model

    formats = FORMATS
    if a.only:
        keys = tuple(k.strip() for k in a.only.split(","))
        formats = {k: v for k, v in FORMATS.items() if k.startswith(keys)}

    print("=" * 100)
    print(f" เทียบรูปแบบวางความทรงจำ {len(formats)} แบบ — {len(CASES)} เคส × {a.reps} รอบ")
    print(f" โมเดล: {ollama_client.MODEL}")
    print(" (ข้อมูลเหมือนกันเป๊ะทุกแบบ ต่างแค่วิธีห่อใน prompt)")
    print("=" * 100)

    rows = []
    for label, fn in formats.items():
        block = fn()
        side = {"user": [0, 0], "me": [0, 0]}
        swap = den = cjk = 0
        bad = []
        for q, s, must, forbid in CASES:
            for _ in range(a.reps):
                try:
                    r = await ask(q, block)
                except Exception:
                    continue
                is_swap = bool(forbid) and any(w in r for w in forbid)
                is_den = any(d in r for d in DENIAL)
                # หัวข้อจีนอาจทำให้โมเดลตอบปนจีน — persona ห้ามเด็ดขาด ต้องนับไว้
                if persona._CJK_RE.search(r):
                    cjk += 1
                good = any(w in r for w in must) and not is_swap and not is_den
                side[s][0] += good
                side[s][1] += 1
                swap += is_swap
                den += is_den
                if not good and len(bad) < 2:
                    bad.append((q[:22], r[:62].replace("\n", " ")))
        u_ok, u_n = side["user"]
        m_ok, m_n = side["me"]
        tot_ok, tot_n = u_ok + m_ok, u_n + m_n
        lo, hi = wilson(u_ok, u_n)
        print(f"\n{'─' * 100}\n  {label}")
        print(f"     ขนาดบล็อก {len(block)}c")
        print(f"     ฝั่งผู้ใช้  {u_ok}/{u_n} ({u_ok/max(u_n,1)*100:3.0f}%)  "
              f"ช่วง 95% [{lo*100:.0f}-{hi*100:.0f}%]   ← ตัวปัญหา")
        print(f"     ฝั่งรอสเต้ {m_ok}/{m_n} ({m_ok/max(m_n,1)*100:3.0f}%)   ← ตัวคุม")
        print(f"     รวม {tot_ok}/{tot_n} ({tot_ok/max(tot_n,1)*100:3.0f}%)  "
              f"สลับ {swap}  ปฏิเสธ {den}"
              + (f"  ⚠️ ตอบปนจีน {cjk}" if cjk else ""))
        for q, r in bad:
            print(f"       ❌ {q} → {r}")
        rows.append(dict(label=label, u=u_ok, un=u_n, m=m_ok, mn=m_n,
                         tot=tot_ok, totn=tot_n, swap=swap, den=den, cjk=cjk,
                         size=len(block), lo=lo, hi=hi))

    print("\n" + "=" * 100)
    print(f" {'รูปแบบ':<30} {'ฝั่งผู้ใช้':>16} {'ฝั่งรอสเต้':>12} {'รวม':>12} {'ปนจีน':>7} {'ขนาด':>7}")
    print("-" * 100)
    for r in rows:
        print(f" {r['label']:<30} {r['u']:>3}/{r['un']:<3} ({r['u']/max(r['un'],1)*100:3.0f}%) "
              f"{r['m']:>3}/{r['mn']:<3} ({r['m']/max(r['mn'],1)*100:3.0f}%) "
              f"{r['tot']:>3}/{r['totn']:<3} ({r['tot']/max(r['totn'],1)*100:3.0f}%) "
              f"{r['cjk']:>6} {r['size']:>6}c")
    print("=" * 100)

    base = rows[0]
    print(f"\n เทียบกับ M0 ปัจจุบัน (ฝั่งผู้ใช้ [{base['lo']*100:.0f}-{base['hi']*100:.0f}%]):")
    for r in rows[1:]:
        sep = ("ดีกว่าจริง" if r["lo"] > base["hi"]
               else "แย่กว่าจริง" if r["hi"] < base["lo"] else "แยกไม่ออก")
        print(f"   {r['label']:<30} {sep}")


if __name__ == "__main__":
    asyncio.run(main())
