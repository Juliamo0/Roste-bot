"""🧪 prototype: ให้โมเดลค้นความทรงจำเองผ่าน tool แทนการยัดเข้า context ล่วงหน้า

⚠️ ยังไม่ถูก import จาก production — ไฟล์นี้เป็นตัวทดลองล้วน

แนวคิด (P2): ปัจจุบัน chat.py:590 ดึง summary 5 อันยัดเข้า system prompt ทุกครั้งที่เจอ
คำถามอดีต โดย recall_summaries เป็นคนเดาว่าอันไหนเกี่ยวข้อง — โมเดลไม่มีสิทธิ์เลือก
P2 กลับด้าน: ไม่ยัดอะไรเลย แต่ให้ tool ไว้ให้โมเดลเรียกเองเมื่อรู้ว่าต้องการ

ทำไมน่าจะดีกว่า:
  1. คำถามที่ไม่เกี่ยวกับความจำ ไม่เปลือง context เลย (ตอนนี้เปลือง ~600c ทุกครั้งที่ trigger)
  2. โมเดลบอกเองว่าอยากรู้อะไร แม่นกว่าให้ keyword เดา
  3. กรอง "ของใคร" ได้ที่ระดับ parameter จริง — ไม่ใช่ prefix ในข้อความที่โมเดลต้องตีความเอง
     (แก้จุดอ่อนของวิธี F ที่บันทึกแยกเจ้าของได้ 87% แต่ตอน recall กลายเป็นข้อความดิบ)

ความเสี่ยงที่ต้องวัด:
  - เพิ่ม tool = เพิ่มขนาด schema ซึ่งวัดแล้วว่า >3,700c ทำให้โมเดลลืม summary
    ตอนนี้คำถามความจำได้ 0 tool แล้วทำงาน 100% — P2 จะทำให้มี tool กลับมา
  - qwen3:8b ต้องตัดสินใจเองว่าเมื่อไหร่ควรค้น ซึ่งพลาดบ่อย (มี _TOOL_REASONING_LEAK_RE
    กับ forced_tool_calls อยู่แล้วเพราะเจอปัญหานี้)
"""
import json
import re

# ── tool schema ───────────────────────────────────────────────────────────────
#
# เขียนสั้นที่สุดเท่าที่สื่อความได้ เพราะทุกตัวอักษรมีราคา (เกณฑ์ ~3,700c)
# เทียบ: get_weather = 1,053c ตัวนี้ตั้งใจให้ต่ำกว่า 600c
SEARCH_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": (
            "ค้นความทรงจำบทสนทนาเก่าที่เคยคุยกับผู้ใช้คนนี้ ใช้เมื่อผู้ใช้ถามถึงอดีต "
            "เช่น 'เคยคุยเรื่อง...ไหม' 'จำได้ไหมว่า' 'ผมชอบอะไร' 'รอสเต้ชอบอะไร' "
            "ห้ามเดาคำตอบเองถ้ายังไม่ได้ค้น"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "เรื่องที่ต้องการค้น เป็นคำสั้นๆ เช่น 'การอ่าน' 'ของหวาน'",
                },
                "whose": {
                    "type": "string",
                    "enum": ["user", "me", "any"],
                    "description": (
                        "ค้นความทรงจำของใคร: user=เรื่องของผู้ใช้ "
                        "me=เรื่องของรอสเต้เอง any=ทั้งหมด (ค่าตั้งต้น)"
                    ),
                },
            },
            "required": ["query"],
        },
    },
}


# ── ฝั่ง handler ─────────────────────────────────────────────────────────────

def _entry_text(entry) -> str:
    return entry["text"] if isinstance(entry, dict) else str(entry)


def split_owner_tags(text: str) -> dict:
    """แยก tag ตามเจ้าของจาก summary รูปแบบ F ("... | user_pref:x me_pref:y")

    คืน {"summary": ..., "user": [...], "me": [...]}
    ถ้าไม่มี tag เลย (summary แบบเก่า) คืน user/me ว่าง — ผู้เรียกต้องรับมือได้
    """
    head = text.split("|", 1)[0].strip()
    marks = list(re.finditer(r"(user_pref|user_fact|me_pref|me_fact)\s*:", text))
    user, me = [], []
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[mk.end():end].strip(" |,")
        if not seg:
            continue
        (me if mk.group(1).startswith("me") else user).append(seg)
    return {"summary": head, "user": user, "me": me}


def search_memory(summaries: list, query: str, whose: str = "any",
                  top_k: int = 3) -> str:
    """ค้น summary ที่เกี่ยวกับ query แล้วคืนข้อความสำหรับป้อนกลับให้โมเดล

    ใช้ keyword matching เดียวกับ memory.recall_summaries (ตัดคำไทยจริง) — ตั้งใจไม่ใช้
    vector search ในตัว prototype เพื่อแยกตัวแปร: รอบนี้วัดว่า "ให้โมเดลเลือกเอง" ดีกว่า
    "ยัดให้ล่วงหน้า" ไหม ไม่ได้วัดว่า embedding ดีกว่า keyword ไหม
    """
    try:
        from memory import _keywords
        words = [w for w in _keywords(query) if len(w) >= 2]
    except Exception:
        words = [w for w in query.split() if len(w) >= 2]

    scored = []
    for entry in summaries:
        text = _entry_text(entry)
        parts = split_owner_tags(text)
        # เลือกเฉพาะฝั่งที่ถาม — จุดสำคัญที่ทำไม่ได้ตอนยัดเข้า context
        if whose == "user":
            hay = parts["summary"] + " " + " ".join(parts["user"])
        elif whose == "me":
            hay = parts["summary"] + " " + " ".join(parts["me"])
        else:
            hay = text
        score = sum(1 for w in words if w in hay)
        # ถามเจาะจงฝั่งแต่ฝั่งนั้นไม่มี tag เลย → ไม่ควรคืน (กันตอบเรื่องผิดเจ้าของ)
        if whose in ("user", "me") and not parts[whose]:
            score = 0
        if score > 0:
            # ⚠️ ต้องคืนเฉพาะ *ฝั่งที่ถาม* ไม่ใช่บรรทัดเต็ม — ทดสอบแล้วเจอว่าการคืน text
            # ทั้งบรรทัดทำให้ tag ของอีกฝ่ายติดไปด้วย ถาม "ผู้ใช้ชอบอะไร" แล้วได้
            # "me_pref:ชอบแฟนตาซี" ปนมา ซึ่งเป็นสิ่งที่ P2 ตั้งใจจะแก้พอดี
            # (การกรองตอน *เลือก* ไม่พอ ต้องกรองตอน *คืน* ด้วย)
            if whose == "user":
                shown = f"{parts['summary']} — ผู้ใช้: {', '.join(parts['user'])}"
            elif whose == "me":
                shown = f"{parts['summary']} — รอสเต้: {', '.join(parts['me'])}"
            else:
                shown = text
            scored.append((score, shown))

    if not scored:
        return "[ระบบ: ไม่พบความทรงจำเกี่ยวกับเรื่องนี้ ให้ตอบตามตรงว่าจำไม่ได้]"

    scored.sort(key=lambda x: -x[0])
    lines = [t for _, t in scored[:top_k]]
    return (
        "[ระบบ: ความทรงจำที่ค้นเจอ — นี่คือเรื่องที่เคยคุยกันจริง ให้ยืนยันแล้วเล่าตามนี้ "
        "ห้ามบอกว่าจำไม่ได้]\n" + "\n".join(f"- {x}" for x in lines)
    )


def tool_size(tool: dict) -> int:
    return len(json.dumps(tool, ensure_ascii=False))


# ── P3: เดาเจ้าของจากคำถาม แล้วกรองก่อนยัดเข้า context ────────────────────────
#
# ทำไมถึงมีวิธีนี้: วัดแล้วพบว่าทั้ง P1 และ P2 พังคนละแบบ
#   P1 ยัดทั้งบรรทัด → โมเดลเห็น user_pref กับ me_pref พร้อมกัน แยกไม่ออก (สลับ 10/25)
#   P2 ให้โมเดลเรียก tool เอง → qwen3:8b เรียกแค่ 36% ที่เหลือเดาคำตอบมั่ว (ความจำ 28%)
# ปัญหาจริงจึงไม่ใช่ "ใครเลือก" แต่คือ "ยัดทั้งบรรทัดโดยไม่กรองฝั่ง"
#
# P3 กรองด้วย rule ตั้งแต่ก่อนยัด — ไม่ต้องพึ่งโมเดลตัดสินใจ (ซึ่งพิสูจน์แล้วว่าเชื่อไม่ได้)
# และไม่ต้องเพิ่ม tool (ไม่กระทบเกณฑ์ 3,700c ที่วัดได้)
# ⚠️ จับที่ *ตัวประธาน* อย่างเดียว ไม่จับคู่กับกริยา
#
# รุ่นแรกเขียนเป็น "<ประธาน> + <กริยา>" (เช่น รอสเต้ + ชอบ/สนใจ/ถนัด) แล้ววัดด้วยชุดเคสหิน
# พบว่าพังทันทีที่เจอกริยานอกลิสต์:
#     "ผมอ่านหนังสือแนวไหนบ้าง"  → "อ่าน" ไม่อยู่ในลิสต์ → เดาเป็น any → ไม่กรองเลย
#     "รอสเต้ทำงานอะไร"          → "ทำงาน" ไม่อยู่ในลิสต์ → คืน fact ของผู้ใช้มาแทน
# การไล่เติมกริยาทีละคำเป็น whack-a-mole (บทเรียนเดียวกับ _TOOL_REASONING_LEAK_RE ที่เคย
# ติดกับดักนี้) — ประธานมีจำกัดและนับได้ ส่วนกริยาไม่มีวันครบ จึงจับแค่ประธานพอ
#
# ความเสี่ยงที่ยอมรับ: ประโยคที่เอ่ยชื่อลอยๆ โดยไม่ได้ถามถึงเจ้าของนั้น ("บอกรอสเต้หน่อยว่า
# ราคาน้ำมันเท่าไหร่") จะถูกเดาเป็น me — แต่เคสนั้นไม่ใช่คำถามความจำอยู่แล้ว จึงไม่ถึง
# ตัวกรองนี้ (chat.py เรียก recall เฉพาะตอนมีสัญญาณถามอดีต)
_ASK_ABOUT_ROSTE = re.compile(r"รอสเต้|เธอ|น้อง")
_ASK_ABOUT_USER = re.compile(r"ผม|ฉัน|หนู|ข้าพเจ้า|ตัวเรา")
# ประโยคที่ถามถึง *ทั้งสองฝ่าย* พร้อมกัน — ต้องคืนทั้งคู่ ไม่ใช่เลือกฝั่งใดฝั่งหนึ่ง
_ASK_BOTH = re.compile(r"เราสองคน|ทั้งสอง|ต่างกัน|เหมือนกัน|คนละ")


def guess_owner(question: str) -> str:
    """เดาว่าคำถามถามถึงความทรงจำของใคร — คืน 'user' / 'me' / 'any'

    ลำดับสำคัญ:
      1. ถามทั้งสองฝ่าย ("เราสองคนชอบอะไรต่างกัน") → any ต้องมาก่อน ไม่งั้นโดนตัดฝั่ง
      2. รอสเต้ → me   (มาก่อนผู้ใช้ เพราะ "เราเคยคุยเรื่องที่รอสเต้ชอบไหม" มีทั้งคู่
                        แต่เจตนาคือถามรอสเต้)
      3. ผู้ใช้ → user
    """
    if _ASK_BOTH.search(question):
        return "any"
    if _ASK_ABOUT_ROSTE.search(question):
        return "me"
    if _ASK_ABOUT_USER.search(question):
        return "user"
    return "any"


def filter_by_owner(texts: list, whose: str) -> list:
    """กรองรายการ summary ดิบ (เช่นผลจาก vector search) ให้เหลือเฉพาะฝั่งที่ถาม

    ⚠️ จำเป็นเพราะ vector search ไม่รู้จัก tag เลย — คืนทั้งบรรทัดเสมอ ทำให้ของอีกฝั่งปน
    (วัดแล้ว: vector ได้ 7/17 ส่วนใหญ่พลาดเพราะเหตุนี้ ไม่ใช่เพราะค้นผิดอัน)
    """
    if whose not in ("user", "me"):
        return list(texts)
    out = []
    for t in texts:
        parts = split_owner_tags(t)
        own = parts[whose]
        if not own:
            continue                     # บรรทัดนี้ไม่มีฝั่งที่ถาม → ทิ้ง
        label = "ผู้ใช้" if whose == "user" else "รอสเต้"
        out.append(f"{parts['summary']} — {label}: {', '.join(own)}")
    return out


def has_owner_data(summaries: list, whose: str) -> bool:
    """ความทรงจำมีข้อมูลฝั่งนี้อยู่บ้างไหม (ไม่สนว่าเกี่ยวกับคำถามหรือเปล่า)

    ใช้แยก 2 กรณีที่ build_memory_block คืนว่างเหมือนกันแต่ความหมายต่างกันสิ้นเชิง:
      - ว่างเพราะ *หาไม่เจอ* (keyword ไม่ตรง)     → vector ช่วยได้ ควรเรียก
      - ว่างเพราะ *ไม่มีฝั่งนั้นเลย* (กรองถูกแล้ว) → ต้องว่างต่อไป ห้ามเรียก vector

    เจอจริงตอนทดสอบ: "รอสเต้ทำงานอะไร" P3 คืนว่างถูกต้อง (ไม่มี me_fact เรื่องงาน)
    แต่ตรรกะผสมรุ่นแรกเห็นว่าว่างแล้วไปดึง vector มา ได้ user_fact:ทำงานสายไอที
    ของผู้ใช้มาตอบแทน — ทำให้ผลรวมแย่ลงจาก 16 เหลือ 15
    """
    if whose not in ("user", "me"):
        return True
    return any(split_owner_tags(_entry_text(s))[whose] for s in summaries)


def build_memory_block(summaries: list, question: str, top_k: int = 5) -> tuple:
    """สร้างบล็อกความทรงจำที่ *กรองฝั่งแล้ว* สำหรับยัดเข้า system prompt

    คืน (ข้อความ, เจ้าของที่เดาได้) — ข้อความว่างถ้าไม่มีอะไรเกี่ยว
    ใช้ search_memory ตัวเดียวกับ P2 ต่างแค่ใครเป็นคนเรียก (rule แทนโมเดล)
    """
    whose = guess_owner(question)
    try:
        from memory import _keywords
        words = [w for w in _keywords(question) if len(w) >= 2]
    except Exception:
        words = [w for w in question.split() if len(w) >= 2]

    scored = []
    for entry in summaries:
        text = _entry_text(entry)
        parts = split_owner_tags(text)
        if whose == "user":
            own, label = parts["user"], "ผู้ใช้"
        elif whose == "me":
            own, label = parts["me"], "รอสเต้"
        else:
            own, label = None, None
        if own is not None and not own:
            continue                      # ถามเจาะจงฝั่ง แต่บรรทัดนี้ไม่มีฝั่งนั้น
        hay = parts["summary"] + " " + " ".join(own if own is not None else [])
        score = sum(1 for w in words if w in (hay if own is not None else text))
        if score <= 0:
            continue
        shown = (f"{parts['summary']} — {label}: {', '.join(own)}"
                 if own is not None else text)
        scored.append((score, shown))

    if not scored:
        return "", whose
    scored.sort(key=lambda x: -x[0])
    return "\n".join(f"- {t}" for _, t in scored[:top_k]), whose


async def build_memory_block_hybrid(summaries: list, question: str,
                                    user_id: int | None = None,
                                    top_k: int = 5) -> tuple:
    """P3 + vector เสริม — เรียก vector เฉพาะตอนที่ *ควรเรียกจริง*

    ตรรกะ (แก้จากรุ่นแรกที่ทำผลแย่ลง):
      1. P3 เจอของ            → ใช้เลย ไม่ต้องเรียก vector (เร็ว + ไม่เสี่ยงของปน)
      2. P3 ว่าง + ฝั่งนั้นไม่มีข้อมูลเลย → คืนว่าง (ถูกต้องแล้ว ห้ามเรียก vector)
      3. P3 ว่าง + ฝั่งนั้นมีข้อมูล      → keyword พลาด ให้ vector ช่วย
                                          แล้ว *กรองฝั่งผลลัพธ์* ก่อนคืน

    ข้อ 3 คือเคสที่ vector มีค่าจริง: "จำได้ไหมว่าผมเลี้ยงสัตว์อะไร" — newmm ตัดได้
    "เลี้ยงสัตว์" แต่ summary เขียน "เลี้ยงแมว" ไม่มีคำตรงกันเลย keyword จึงคะแนน 0
    ส่วน vector ค้นด้วยความหมายจึงเจอ
    """
    block, whose = build_memory_block(summaries, question, top_k)
    if block.strip():
        return block, whose, "keyword"
    if not has_owner_data(summaries, whose):
        return "", whose, "ไม่มีฝั่งนี้"
    if user_id is None:
        return "", whose, "ไม่ได้เรียก vector"

    import vectormemory as V
    try:
        hits = await V.query_conversation_memory(user_id, question, top_k=top_k)
    except Exception:
        return "", whose, "vector error"
    kept = filter_by_owner(hits, whose)
    if not kept:
        return "", whose, "vector ไม่เจอฝั่งนี้"
    return "\n".join(f"- {t}" for t in kept[:top_k]), whose, "vector"
