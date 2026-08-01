"""เทียบวิธีทำ summary 5 แบบบนข้อมูลชุดเดียวกัน — เอาแนวคิดจากโปรเจกต์อื่นมาวัดจริง

⚠️ ไม่แตะ production — ทุกวิธีนิยามในไฟล์นี้ ยกเว้น A ที่เรียก memory.build_summary_prompt
ตัวจริงมาเป็น baseline

วิธีที่เทียบ (มาจากไหน):
  A. ปัจจุบัน     — memory.build_summary_prompt ของรอสเต้เอง ("สั้นที่สุดเท่าที่บอกหัวข้อได้")
  B. v2           — ขอรายละเอียดตรงๆ (ที่พัฒนามาในเซสชันนี้)
  C. ห้ามแบบระบุ  — แนวคิดจาก mindcraft: บอก *ประเภทที่ห้ามเก็บ* ตรงๆ แทนสั่งให้สั้น
                    ("Do Not record stats, inventory, or docs!")
  D. tags แยกชนิด — แนวคิดจาก ProjectBEA: แยกข้อเท็จจริงออกจากเรื่องเล่าด้วย prefix
                    ("user_preference:likes_blue") ปรับให้เป็นบรรทัดเดียว ไม่ใช่ diary 1-3 ย่อหน้า
                    (diary ยาวเกินไปสำหรับ qwen3:8b + เพดาน context ~3,700c ที่วัดได้)
  E. C + D        — รวมสองแนวคิด

สิ่งที่ *ไม่* เอามาเทียบ:
  - memory ก้อนเดียวเขียนทับแบบ mindcraft — ขนาดคงที่จริง แต่ข้อมูลเก่าหายถาวร
    ขัดกับความสามารถหลักของรอสเต้ (ผู้ใช้ถามย้อนหลังเป็นเดือน) จึงไม่ใช่ตัวเลือก
  - ไม่สรุปเลยแบบ Open-LLM-VTuber — ไม่มีความจำระยะยาว ไม่ตอบโจทย์

วัด 5 อย่างพร้อมกัน (ต้องดูรวม ไม่งั้นแก้ทางหนึ่งพังอีกทาง):
  1. เก็บเนื้อหา  — มีคำที่เป็นรายละเอียดจริงไหม
  2. hallucinate  — แต่งตัวเลข/ชื่อที่ไม่มีในบทไหม (find_ungrounded)
  3. บรรยายตัวเอง — เก็บคำที่รอสเต้พูดถึงตัวเองไหม (find_self_description)
  4. ขนาด        — c ต่ออัน (มีราคาจริง: >3,700c ในบริบททำให้โมเดลลืม)
  5. เสถียร      — ผลแกว่งแค่ไหนระหว่างรอบ
"""
import argparse
import asyncio
import json
import os
import pathlib
import re
import statistics
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
    build_summary_prompt_v2, find_self_description, find_ungrounded,
)

logging.disable(logging.CRITICAL)


def _convo(pairs):
    return "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'รอสเต้'}: {m.get('content', '')}"
        for m in pairs
    )


# ── C: ห้ามแบบระบุประเภท (แนวคิด mindcraft) ───────────────────────────────────
def build_prompt_explicit_ban(pairs: list) -> str:
    """mindcraft ไม่สั่งว่า "สั้นที่สุด" แต่ระบุประเภทที่ห้ามเก็บตรงๆ แล้วให้เก็บที่เหลือเต็มที่
    ("Prioritize preserving important facts... Do Not record stats, inventory, or docs!")
    """
    return (
        "สรุปบทสนทนาต่อไปนี้เป็นภาษาไทย 1 บรรทัด\n"
        "เก็บให้ครบ: สิ่งที่ผู้ใช้ชอบ/ไม่ชอบ/ทำ/ตัดสินใจ และสิ่งที่รอสเต้ทำให้ผู้ใช้\n"
        "ห้ามบันทึกสิ่งเหล่านี้เด็ดขาด:\n"
        "- คำแนะนำตัวของรอสเต้ (ชื่อ อายุ หน้าที่ ประวัติ นิสัยของตัวเอง)\n"
        "- ความชอบส่วนตัวของรอสเต้ (รอสเต้ชอบอะไร ไม่ชอบอะไร)\n"
        "- ข้อมูลสดที่หมดอายุ (ราคาน้ำมันวันนี้ พยากรณ์อากาศ เวลา)\n"
        "- ชื่อเฉพาะ/ตัวเลขที่ไม่ได้อยู่ในบทข้างล่าง\n"
        "ตอบมาแค่ประโยคสรุปเท่านั้น ห้ามมีคำนำ:\n\n" + _convo(pairs)
    )


# ── D: tags แยกชนิด (แนวคิด ProjectBEA) ──────────────────────────────────────
def build_prompt_tags(pairs: list) -> str:
    """ProjectBEA แยก diary_content (เรื่องเล่า) ออกจาก tags (ข้อเท็จจริงมี prefix)
    ปรับให้เบาลง: บรรทัดเดียว + tags ไม่เกิน 3 อัน (diary 1-3 ย่อหน้าใหญ่เกินสำหรับที่นี่)
    """
    return (
        "สรุปบทสนทนาต่อไปนี้ ตอบเป็น JSON เท่านั้น:\n"
        '{"summary": "<หัวข้อที่คุย 1 บรรทัดสั้นๆ>", '
        '"tags": ["user_pref:<สิ่งที่ผู้ใช้ชอบ>", "user_fact:<ข้อเท็จจริงของผู้ใช้>"]}\n'
        "กฎ:\n"
        "- tags เก็บเฉพาะเรื่องของ *ผู้ใช้* เท่านั้น ไม่เก็บเรื่องของรอสเต้\n"
        "- ไม่เกิน 3 tags ถ้าไม่มีอะไรน่าจำใส่ [] ได้\n"
        "- ใช้คำที่ปรากฏในบทจริง ห้ามแต่งชื่อเฉพาะ/ตัวเลขเพิ่ม\n"
        "ตอบ JSON อย่างเดียว:\n\n" + _convo(pairs)
    )


# ── E: รวม C + D ──────────────────────────────────────────────────────────────
def build_prompt_combined(pairs: list) -> str:
    return (
        "สรุปบทสนทนาต่อไปนี้ ตอบเป็น JSON เท่านั้น:\n"
        '{"summary": "<หัวข้อที่คุย 1 บรรทัดสั้นๆ>", '
        '"tags": ["user_pref:<สิ่งที่ผู้ใช้ชอบ>", "user_fact:<ข้อเท็จจริงของผู้ใช้>"]}\n'
        "กฎ:\n"
        "- tags เก็บเฉพาะเรื่องของ *ผู้ใช้* เท่านั้น\n"
        "- ห้ามบันทึก: คำแนะนำตัว/ความชอบของรอสเต้, ข้อมูลสดที่หมดอายุ (ราคา อากาศ เวลา),\n"
        "  ชื่อเฉพาะ/ตัวเลขที่ไม่ได้อยู่ในบท\n"
        "- ไม่เกิน 3 tags ถ้าไม่มีอะไรน่าจำใส่ [] ได้\n"
        "ตอบ JSON อย่างเดียว:\n\n" + _convo(pairs)
    )


# ── F: แยกเจ้าของความทรงจำ ───────────────────────────────────────────────────
def build_prompt_owner_tagged(pairs: list) -> str:
    """ให้รอสเต้บันทึกเรื่องตัวเองได้ แต่ต้อง *รู้ว่าอันไหนเป็นของใคร*

    ต่างจาก C ที่ "ห้ามบันทึกเรื่องรอสเต้" — วิธีนี้อนุญาต แต่บังคับติดป้ายเจ้าของ
    เหตุผล: รอสเต้เป็นคนที่มีความชอบของตัวเอง (persona.py:44-51) การห้ามจำเรื่องตัวเอง
    ทำให้เธอตอบไม่ได้เวลาผู้ใช้ถามย้อนหลังว่า "รอสเต้ชอบอะไรนะ" ซึ่งผู้ใช้ถามจริง
    (บทจริงก้อนที่ 1 เริ่มด้วย "รอสเต้ชอบอ่านนิยายแบบไหนเหรอ")

    ปัญหาจริงไม่ใช่ "บันทึกเรื่องตัวเอง" แต่คือ "บันทึกโดยไม่รู้ว่าเป็นของใคร" — พอปนกัน
    แล้ว recall กลับมา โมเดลแยกไม่ออกว่าอันไหนผู้ใช้ชอบ อันไหนตัวเองชอบ
    (ต่อยอดจาก ProjectBEA ที่ใช้ prefix user_pref:/user_fact: แต่เขาแยกแค่ฝั่งผู้ใช้)

    ⚠️ รุ่นแรกเขียน prefix กว้างๆ ว่า "user:<เรื่องของผู้ใช้>" แล้ววัดได้รายละเอียดผู้ใช้
    แค่ 50% (D ที่ระบุชนิดชัดได้ 100%) — เพราะโมเดลตีความ "เรื่องของผู้ใช้" เป็น *การกระทำ*
    ("user:ถามเรื่องนิยายที่ชอบ") แทนที่จะเป็น *ความชอบ* ("user_pref:ชอบนิยายมีชั้นเชิง")
    รอบนี้จึงระบุชนิดใน prefix เหมือน D แต่ทำครบทั้งสองฝั่ง (เพิ่ม me_pref/me_fact)
    """
    return (
        "สรุปบทสนทนาต่อไปนี้ ตอบเป็น JSON เท่านั้น\n"
        "คุณคือรอสเต้ กำลังบันทึกความทรงจำของตัวเอง — ต้องแยกให้ชัดว่าเรื่องไหนของใคร\n"
        '{"summary": "<หัวข้อที่คุย 1 บรรทัดสั้นๆ>", "tags": [...]}\n'
        "ชนิดของ tag (เลือกใช้เท่าที่มีจริงในบท):\n"
        '- "user_pref:<สิ่งที่ผู้ใช้ชอบ/ไม่ชอบ>"   เช่น user_pref:ชอบนิยายสืบสวน\n'
        '- "user_fact:<ข้อเท็จจริงของผู้ใช้>"      เช่น user_fact:กินเผ็ดไม่ได้\n'
        '- "me_pref:<สิ่งที่รอสเต้เองชอบ/ไม่ชอบ>"  เช่น me_pref:ชอบหนังสือเก่า\n'
        '- "me_fact:<สิ่งที่รอสเต้ทำหรือเป็น>"     เช่น me_fact:แนะนำร้านให้\n'
        "กฎ:\n"
        "- รอสเต้จำความชอบของตัวเองได้ ให้ใส่ me_pref: ถ้ารอสเต้บอกว่าชอบ/ไม่ชอบอะไรในบท\n"
        "- ห้ามสลับเจ้าของ: สิ่งที่ผู้ใช้พูดต้องเป็น user_* สิ่งที่รอสเต้พูดต้องเป็น me_*\n"
        "- ห้ามบันทึกข้อมูลสดที่หมดอายุ (ราคาน้ำมัน พยากรณ์อากาศ เวลา)\n"
        "- ห้ามแต่งชื่อเฉพาะ/ตัวเลขที่ไม่ได้อยู่ในบท\n"
        "- ไม่เกิน 4 tags ถ้าไม่มีอะไรน่าจำใส่ [] ได้\n"
        "ตอบ JSON อย่างเดียว:\n\n" + _convo(pairs)
    )


def parse_json_summary(raw: str) -> str:
    """แปลงผล JSON เป็นข้อความเดียวสำหรับวัด — รวม summary + tags

    ถ้า parse ไม่ได้ คืน raw ทั้งก้อน (นับเป็นผลของวิธีนั้นตามจริง ไม่ช่วยแก้ให้)
    """
    txt = raw.strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start >= 0 and end > start:
        try:
            d = json.loads(txt[start:end + 1])
            parts = [str(d.get("summary", "")).strip()]
            tags = d.get("tags") or []
            if isinstance(tags, list) and tags:
                parts.append(" ".join(str(t) for t in tags))
            return " | ".join(p for p in parts if p)
        except Exception:
            pass
    return txt


METHODS = [
    ("A ปัจจุบัน",        memory.build_summary_prompt,  False),
    ("B v2 ขอรายละเอียด", build_summary_prompt_v2,      False),
    ("C ห้ามแบบระบุ",     build_prompt_explicit_ban,    False),
    ("D tags แยกชนิด",    build_prompt_tags,            True),
    ("E C+D รวมกัน",      build_prompt_combined,        True),
    ("F แยกเจ้าของ",      build_prompt_owner_tagged,    True),
]

# prefix ที่ *เราสั่งให้โมเดลเขียนเอง* — ต้องไม่นับเป็น hallucinate
#
# ⚠️ บั๊กที่เจอในรอบก่อน: find_ungrounded จับ "user_pref" เป็นคำอังกฤษที่ไม่มีในบท แล้ว
# รายงานว่า D/E hallucinate 100% ทั้งที่เป็นคำที่ prompt ของเราเองสั่งให้ใส่ — false positive
# ล้วน ถ้าไม่แก้จะตัดสองวิธีนี้ทิ้งด้วยตัวเลขที่ผิด
_OUR_PREFIXES = ("user_pref", "user_fact", "user", "me", "topic", "summary", "tags")


def strip_our_prefixes(text: str) -> str:
    """ตัด prefix ที่เราสั่งเองออกก่อนตรวจ hallucinate"""
    out = text
    for p in _OUR_PREFIXES:
        out = out.replace(f"{p}:", " ")
    return out


async def _gen(prompt: str) -> str:
    msg = await ollama_client._chat_once(
        [{"role": "user", "content": prompt}], temperature=0.1)
    raw = ollama_client._strip_think(msg.get("content", "") or "")
    return raw.strip()


def load_chunks(path: str, per_chunk: int = 4) -> list:
    d = json.load(open(path, encoding="utf-8"))
    hist = d.get("history", [])
    chunks, cur = [], []
    for m in hist:
        cur.append(m)
        if len(cur) >= per_chunk * 2:
            chunks.append(cur)
            cur = []
    if len(cur) >= 4:
        chunks.append(cur)
    return chunks


# ── บททดสอบ "ใครชอบอะไร" — เขียนขึ้นเพราะบทจริงไม่มีเคสนี้ ──────────────────────
#
# บทจริง 2 ก้อนในไฟล์ความจำไม่มีเคสที่ *ทั้งสองฝ่าย* บอกความชอบตัวเองในบทเดียวกันเลย
# จึงทดสอบไม่ได้ว่าโมเดลแยกเจ้าของถูกไหม (F ได้ "มีเรื่องรอสเต้ 0%" เพราะไม่มีให้เก็บ
# ไม่ใช่เพราะเก็บไม่ได้) — บทพวกนี้ออกแบบให้มีทั้งสองฝั่งชัดเจน และรู้คำตอบที่ถูกล่วงหน้า
#
# ที่สำคัญ: ใส่เคส "ชอบคนละอย่าง" กับ "ไม่ชอบ" ไว้ด้วย เพราะเป็นจุดที่สลับเจ้าของแล้วพังชัด
# — ถ้าโมเดลจำสลับ รอสเต้จะเชื่อว่าผู้ใช้ชอบสิ่งที่ตัวเองชอบ ซึ่งแย่กว่าการไม่จำเลย
OWNER_CASES = [
    {
        "name": "ชอบคนละอย่าง",
        "pairs": [
            {"role": "user", "content": "รอสเต้ชอบอ่านแนวไหนเหรอ ผมชอบสืบสวนนะ"},
            {"role": "assistant", "content": "รอสเต้ชอบแนวแฟนตาซีค่ะ พวกเวทมนตร์ โลกอีกใบ "
                                              "แนวสืบสวนก็สนุกนะคะ แต่ส่วนตัวไม่ค่อยถนัดเท่าไหร่"},
        ],
        "user_should": ["สืบสวน"],
        "me_should": ["แฟนตาซี"],
    },
    {
        "name": "ไม่ชอบคนละอย่าง",
        "pairs": [
            {"role": "user", "content": "ผมกินเผ็ดไม่ได้เลย รอสเต้ล่ะ"},
            {"role": "assistant", "content": "รอสเต้กินเผ็ดได้ค่ะ แต่ไม่ชอบของหวานมากเท่าไหร่ "
                                              "หวานจัดๆ แล้วเลี่ยนน่ะค่ะ"},
        ],
        "user_should": ["เผ็ด"],
        "me_should": ["หวาน"],
    },
    {
        "name": "รอสเต้บอกความชอบเอง",
        "pairs": [
            {"role": "user", "content": "ว่างๆ รอสเต้ทำอะไรบ้าง"},
            {"role": "assistant", "content": "ชอบนั่งอ่านหนังสือเก่าๆ ค่ะ กลิ่นกระดาษเก่ามันดีนะคะ "
                                              "แล้วก็ชอบซ่อมของพวกหุ่นยนต์เล็กๆ ด้วย"},
            {"role": "user", "content": "น่าสนใจดีนะ ผมชอบเล่นเกมมากกว่า"},
            {"role": "assistant", "content": "เกมก็สนุกค่ะ~ รอสเต้เล่นไม่ค่อยเก่งเท่าไหร่"},
        ],
        "user_should": ["เกม"],
        "me_should": ["หนังสือเก่า", "หุ่นยนต์", "อ่านหนังสือ"],
    },
]


def score_owner(text: str, case: dict) -> dict:
    """ตรวจว่าแยกเจ้าของถูกไหม — คืนผลละเอียดพอให้เห็นว่าพลาดแบบไหน

    แยก tag ตาม prefix แล้วดูว่าเนื้อหาไปอยู่ฝั่งถูกไหม:
      user_ok  = สิ่งที่ผู้ใช้ชอบ อยู่ในฝั่ง user จริง
      me_ok    = สิ่งที่รอสเต้ชอบ อยู่ในฝั่ง me จริง
      swapped  = สลับฝั่ง (แย่ที่สุด — จำผิดเจ้าของ)
    """
    # ⚠️ ต้องตัดที่ *ตำแหน่งของ prefix เอง* ไม่ใช่ที่ตัวคั่น — parse_json_summary รวม tags
    # ด้วยช่องว่าง ("user_pref:ชอบสืบสวน me_pref:ชอบแฟนตาซี") ถ้า split ด้วย [|,] เฉยๆ
    # ทั้งก้อนจะกลายเป็น zone เดียว แล้วทุกอย่างถูกนับว่าอยู่ฝั่ง user หมด (เจอจริงตอนทดสอบ:
    # สรุปที่ถูกต้องถูกรายงานว่า swapped=True)
    marks = list(re.finditer(r"(user_pref|user_fact|me_pref|me_fact|user|me)\s*:", text))
    user_zone, me_zone = [], []
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[mk.end():end].strip(" |,")
        (me_zone if mk.group(1).startswith("me") else user_zone).append(seg)
    u_txt, m_txt = " ".join(user_zone), " ".join(me_zone)

    user_ok = any(w in u_txt for w in case["user_should"])
    me_ok = any(w in m_txt for w in case["me_should"])
    swapped = (any(w in m_txt for w in case["user_should"])
               or any(w in u_txt for w in case["me_should"]))
    return {"user_ok": user_ok, "me_ok": me_ok, "swapped": swapped,
            "has_zones": bool(user_zone or me_zone)}


# ── วัด "เก็บรายละเอียดของผู้ใช้ได้ไหม" แบบที่แยกวิธีออกจากกันได้จริง ─────────────
#
# ⚠️ รอบก่อนใช้ DETAIL_HINTS = ["ลึกลับ", "นิยาย", ...] แล้วนับว่ามีคำใดคำหนึ่งไหม —
# ทุกวิธีได้ 100% รวมทั้ง A ที่สั้น 52c เพราะคำพวกนั้นอยู่ในชื่อหัวข้ออยู่แล้ว metric จึง
# แยกอะไรไม่ออกเลย ไร้ประโยชน์
#
# รอบนี้วัดสองอย่างที่ต่างกันจริง:
#   user_detail — summary บอกได้ไหมว่า "ผู้ใช้" เป็นคนชอบ/ทำ (ต้องมีคำชี้ตัวผู้ใช้ + คำเนื้อหา)
#   ระบุเจ้าของ — summary แยกออกไหมว่าเรื่องไหนของใคร (ตัวชี้ขาดของแนวคิด F)
_USER_MARKERS = ("ผู้ใช้", "user:", "user_pref", "user_fact", "เขา", "คุณ")
_ROSTE_MARKERS = ("รอสเต้", "me:", "เธอ")
# คำเนื้อหาที่ผู้ใช้พูดถึงจริงในบททดสอบ (ไม่ใช่ชื่อหัวข้อกว้างๆ)
_CONTENT_WORDS = ("ลึกลับ", "ซับซ้อน", "หักมุม", "เพลง", "ClueAngel", "อ่าน", "หนังสือ")


def has_user_detail(text: str) -> bool:
    """summary ระบุได้ไหมว่า *ผู้ใช้* เกี่ยวข้องกับเนื้อหานั้น (ไม่ใช่แค่เอ่ยหัวข้อลอยๆ)"""
    return (any(m in text for m in _USER_MARKERS)
            and any(w in text for w in _CONTENT_WORDS))


def marks_owner(text: str) -> bool:
    """summary แยกเจ้าของได้ไหม — มีทั้งคำชี้ผู้ใช้และ/หรือคำชี้รอสเต้อย่างชัดเจน"""
    return any(m in text for m in _USER_MARKERS) or any(m in text for m in _ROSTE_MARKERS)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    args = ap.parse_args()

    path = resolve_memory_file()
    chunks = load_chunks(path)
    print("=" * 100)
    print(f" เทียบวิธีทำ summary 5 แบบ — {len(chunks)} ก้อนจริง × {args.reps} รอบ")
    print(f" ไฟล์: {path}")
    print("=" * 100)

    rows = []
    for label, fn, is_json in METHODS:
        sizes, details, halls, selfs, owners = [], 0, 0, 0, 0
        n = 0
        samples = []
        for ci, pairs in enumerate(chunks):
            for r in range(args.reps):
                raw = await _gen(fn(pairs))
                text = parse_json_summary(raw) if is_json else raw.splitlines()[0].strip()
                if not text:
                    continue
                n += 1
                sizes.append(len(text))
                if has_user_detail(text):
                    details += 1
                # ตัด prefix ที่เราสั่งเองก่อนตรวจ ไม่งั้น "user_pref" ถูกนับเป็นคำแต่งขึ้น
                if find_ungrounded(strip_our_prefixes(text), pairs):
                    halls += 1
                if marks_owner(text):
                    owners += 1
                # ตรวจแบบไม่ดูบริบท — วัดว่าวิธีไหนเก็บเรื่องรอสเต้เข้ามาบ่อยแค่ไหน
                # (ไม่ได้แปลว่าผิด — F ตั้งใจให้เก็บได้ แต่ต้องติดป้าย me: กำกับ)
                if find_self_description(text, None):
                    selfs += 1
                if r == 0 and len(samples) < 2:
                    samples.append(text)

        n = max(n, 1)
        row = dict(label=label,
                   detail=details / n * 100, hall=halls / n * 100,
                   selfd=selfs / n * 100, owner=owners / n * 100,
                   size=statistics.mean(sizes) if sizes else 0,
                   sd=statistics.pstdev(sizes) if len(sizes) > 1 else 0,
                   mx=max(sizes) if sizes else 0)
        rows.append(row)
        print(f"\n  【{label}】 รายละเอียดผู้ใช้ {row['detail']:.0f}%  "
              f"hallucinate {row['hall']:.0f}%  ระบุเจ้าของ {row['owner']:.0f}%  "
              f"มีเรื่องรอสเต้ {row['selfd']:.0f}%  ขนาด {row['size']:.0f}±{row['sd']:.0f}c")
        for s in samples:
            print(f"       {s[:120]}")

    print("\n" + "=" * 100)
    print(f" {'วิธี':<22} {'รายละเอียดผู้ใช้':>16} {'hallucinate':>12} "
          f"{'ระบุเจ้าของ':>12} {'มีเรื่องรอสเต้':>14} {'ขนาด':>11}")
    print("-" * 100)
    for r in rows:
        print(f" {r['label']:<22} {r['detail']:>14.0f}% {r['hall']:>11.0f}% "
              f"{r['owner']:>11.0f}% {r['selfd']:>13.0f}% {r['size']:>6.0f}±{r['sd']:<3.0f}c")
    print("=" * 100)
    print("\n อ่านผลยังไง:")
    print("   รายละเอียดผู้ใช้ ↑ ดี | hallucinate ↓ ดี | ระบุเจ้าของ ↑ ดี | ขนาด ↓ ดี")
    print("   'มีเรื่องรอสเต้' ไม่ใช่คะแนนดี/ไม่ดีในตัวเอง — ดูคู่กับ 'ระบุเจ้าของ':")
    print("     มีเรื่องรอสเต้สูง + ระบุเจ้าของสูง = จำเรื่องตัวเองได้แบบรู้ว่าเป็นของตัวเอง (ที่ต้องการ)")
    print("     มีเรื่องรอสเต้สูง + ระบุเจ้าของต่ำ = ปนกันจนแยกไม่ออก (ปัญหา)")
    print("\n   ขนาดมีราคาจริง: recall คืน 5 อัน + tool 1,520c ต้องไม่เกิน ~3,700c")
    for r in rows:
        total = 1520 + 5 * r["size"]
        flag = "  ⚠️ เกิน" if total > 3700 else ""
        print(f"     {r['label']:<22} 1520 + 5x{r['size']:.0f} = {total:.0f}c{flag}")

    # ── เฟส 2: รอสเต้รู้ไหมว่าอะไรคือของตัวเอง ────────────────────────────────
    print("\n\n" + "=" * 100)
    print(f" เฟส 2: แยกเจ้าของความชอบ — {len(OWNER_CASES)} เคส × {args.reps} รอบ")
    print(" (บทที่ *ทั้งสองฝ่าย* บอกความชอบตัวเอง — บทจริงในไฟล์ไม่มีเคสแบบนี้)")
    print("=" * 100)

    orows = []
    for label, fn, is_json in METHODS:
        u_ok = m_ok = swap = both = n = 0
        samples = []
        for case in OWNER_CASES:
            for r in range(args.reps):
                raw = await _gen(fn(case["pairs"]))
                text = parse_json_summary(raw) if is_json else raw.splitlines()[0].strip()
                if not text:
                    continue
                n += 1
                sc = score_owner(text, case)
                u_ok += sc["user_ok"]
                m_ok += sc["me_ok"]
                swap += sc["swapped"]
                both += (sc["user_ok"] and sc["me_ok"] and not sc["swapped"])
                if r == 0 and len(samples) < 3:
                    samples.append((case["name"], sc, text))
        n = max(n, 1)
        orows.append(dict(label=label, u=u_ok / n * 100, m=m_ok / n * 100,
                          swap=swap / n * 100, both=both / n * 100))
        print(f"\n  【{label}】 จำของผู้ใช้ {u_ok/n*100:.0f}%  จำของตัวเอง {m_ok/n*100:.0f}%  "
              f"สลับเจ้าของ {swap/n*100:.0f}%  ถูกทั้งคู่ {both/n*100:.0f}%")
        for cname, sc, s in samples:
            mark = "✅" if (sc["user_ok"] and sc["me_ok"] and not sc["swapped"]) else "❌"
            print(f"     {mark} [{cname}] {s[:104]}")

    print("\n" + "=" * 100)
    print(f" {'วิธี':<22} {'จำของผู้ใช้':>13} {'จำของตัวเอง':>13} {'สลับเจ้าของ':>13} {'ถูกทั้งคู่':>12}")
    print("-" * 100)
    for r in orows:
        print(f" {r['label']:<22} {r['u']:>12.0f}% {r['m']:>12.0f}% "
              f"{r['swap']:>12.0f}% {r['both']:>11.0f}%")
    print("=" * 100)
    print("\n 'ถูกทั้งคู่' คือตัวชี้ขาด — จำได้ทั้งของผู้ใช้และของตัวเอง โดยไม่สลับเจ้าของ")
    print(" 'สลับเจ้าของ' อันตรายที่สุด: รอสเต้จะเชื่อว่าผู้ใช้ชอบสิ่งที่ตัวเองชอบ")


if __name__ == "__main__":
    asyncio.run(main())
