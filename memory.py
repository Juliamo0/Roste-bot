# ============================================================
#  🧠  memory.py — ระบบความจำของรอสเต้ (แยกตามผู้ใช้แต่ละคน)
#      เก็บในไฟล์ memory/<user_id>.json มีส่วนหลัก:
#        name    = ชื่อเรียกของผู้ใช้
#        facts   = ข้อเท็จจริงที่สั่งให้จำ (เช่น "อยู่ชุมพร")
#        history = บทสนทนาล่าสุด
#      → ปิด-เปิดบอทใหม่ก็ไม่หาย เพราะอยู่ในไฟล์
#
#      ฟีเจอร์ความจำที่รองรับ:
#        - เพดาน facts (กันโตไม่มีที่สิ้นสุด → เปลือง token/โมเดลสับสน)
#        - ลบ fact รายตัวได้ (ไม่ต้องล้างหมด)
#        - กันจำซ้ำ (fact เดิมไม่ถูกเพิ่มซ้ำ)
#        - selective recall (ดึงเฉพาะ fact ที่เกี่ยวกับบทสนทนาตอนนั้น)
# ============================================================
import os
import json
import logging
import re

# ไม่ต้อง config handler เอง — bot.py ตั้ง root logger ไว้แล้ว (rotating file + console)
logger = logging.getLogger("roste.memory")

MEMORY_DIR = "memory"
os.makedirs(MEMORY_DIR, exist_ok=True)


# ── การตัดคำสำหรับ keyword recall ──────────────────────────────────────────────
#
# ภาษาไทยไม่เขียนเว้นวรรคระหว่างคำ — user_message.split() จึงคืน "ทั้งประโยคเป็นก้อนเดียว"
# ไม่ใช่รายการคำ ทำให้ keyword match ไม่มีวันตรงกับอะไรเลย (วัดจริงบนเคสจากบทสนทนา Discord:
# recall_summaries คืน 0 อันทั้ง 5 เคส ทั้งที่ summary ที่ตรงมีอยู่ในไฟล์)
#   'ว่าแต่รอสเต้เราเคยคุยเรื่องการอ่าน...'.split()  → 1 ก้อน  → คะแนน 0 เสมอ
#   word_tokenize(...)                              → 15 คำ   → จับคู่ได้จริง
_STOPWORDS = {
    # คำที่โผล่ในแทบทุกคำถามถึงอดีต — ไม่ได้บอกว่า "หัวข้อ" คืออะไร ถ้าไม่ตัดทิ้งจะไปแมตช์
    # กับ summary ทุกอันเท่าๆ กัน แล้วกลบคำที่สื่อความหมายจริง
    "ว่าแต่", "เรา", "เคย", "คุย", "เรื่อง", "การ", "อะไร", "พวก", "นั้น", "ด้วย",
    "ไหม", "ก่อนหน้านี้", "ตอนนั้น", "กัน", "หรือเปล่า", "จำได้", "นะ", "พอ",
    "บ้าง", "รอ", "สเต้", "ที่", "ของ", "ให้", "และ", "มี", "ครับ", "ค่ะ", "คะ",
}

# คำพ้อง/คำใกล้เคียงเฉพาะโดเมนที่บอทคุยบ่อย — ปิดช่องว่างที่ keyword match ล้วนแก้ไม่ได้
# (ผู้ใช้ถาม "การอ่าน" แต่ summary เขียนว่า "นิยาย"/"หนังสือ" ไม่มีคำร่วมกันเลยสักคำ)
# วัดผลแล้วช่วยจาก 3/5 เป็น 4/5 เคส แลกกับดึงของไม่เกี่ยวมาเพิ่ม 2 อัน — คุ้ม เพราะการ
# "พลาดความทรงจำที่มีจริง" ทำให้บอทตอบว่าไม่เคยคุย ซึ่งแย่กว่าการเสนอ context เกินมานิดหน่อย
_SYNONYMS = {
    "อ่าน":     ["หนังสือ", "นิยาย"],
    "หนังสือ":  ["นิยาย", "อ่าน"],
    "นิยาย":    ["หนังสือ", "อ่าน"],
    "ของหวาน":  ["ขนม", "ไอศกรีม", "เจลาโต้"],
    "ขนม":      ["ของหวาน", "ไอศกรีม"],
    "อากาศ":    ["ฝน", "ร้อน", "หนาว", "อุณหภูมิ"],
    "น้ำมัน":   ["ดีเซล", "เบนซิน"],
    "กิน":      ["อาหาร", "ร้าน", "เมนู"],
    "อาหาร":    ["กิน", "ร้าน", "เมนู"],
}


def _keywords(text: str, expand: bool = True) -> list:
    """ตัดข้อความไทยเป็น "คำที่สื่อความหมาย" สำหรับเอาไปจับคู่กับ fact/summary

    ตัด stopword ทิ้งแล้วขยายด้วยคำพ้อง (ถ้า expand) — ถ้า pythainlp ใช้ไม่ได้
    ถอยไปใช้ split() แบบเดิม ซึ่งแม้จะด้อยกว่ามากแต่ยังดีกว่าพังทั้งฟังก์ชัน
    """
    try:
        from pythainlp.tokenize import word_tokenize
        toks = [t for t in word_tokenize(text, engine="newmm") if t.strip()]
    except Exception:
        toks = text.split()
    words = {t for t in toks if len(t) >= 2 and t not in _STOPWORDS}
    if expand:
        for w in list(words):
            words.update(_SYNONYMS.get(w, []))
            # newmm รวมคำประสมเป็น token เดียวได้ ("อ่านหนังสือ" ไม่ใช่ "อ่าน"+"หนังสือ")
            # ทำให้ key คำพ้องที่เป็นคำเดี่ยวไม่ถูกจับ — เช็คแบบ substring เพิ่มอีกชั้น
            # (เจอจริง: "เรื่องเกี่ยวกับการอ่านหนังสือนะพอจำได้ไหม" ได้ token 'อ่านหนังสือ'
            #  แล้วพลาด summary เรื่อง 'นิยาย' ทั้งที่ควรเจอ)
            for key, syns in _SYNONYMS.items():
                if key != w and key in w:
                    words.add(key)
                    words.update(syns)
    return list(words)

# จำนวนคู่บทสนทนา (ถาม-ตอบ) ที่จะจำย้อนหลังต่อหนึ่งคน
MAX_HISTORY_PAIRS = 8

# เพดานจำนวน facts ต่อคน — เกินนี้จะตัดอันเก่าสุดทิ้ง (กัน context ล้น)
MAX_FACTS = 40

# จำนวน fact สูงสุดที่ดึงมาใส่ context ต่อหนึ่งข้อความ (selective recall)
# ถ้า facts น้อยกว่านี้ ใช้ทั้งหมด; ถ้าเยอะกว่า เลือกเฉพาะที่เกี่ยวข้อง
MAX_FACTS_IN_CONTEXT = 12

# จำนวนบทสรุปสูงสุดที่เก็บไว้ต่อคน — เก็บเยอะได้เพราะ inject เฉพาะตอนถาม
MAX_SUMMARIES = 100


def _memory_path(user_id):
    return os.path.join(MEMORY_DIR, f"{user_id}.json")


def load_memory(user_id):
    """อ่านความจำของผู้ใช้คนหนึ่งจากไฟล์ (ถ้าไม่มีก็คืนค่าว่าง)"""
    path = _memory_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                mem = json.load(f)
            # กันไฟล์เก่าที่ยังไม่มี key ครบ
            mem.setdefault("name", "")
            mem.setdefault("preferred_name", "")
            mem.setdefault("facts", [])
            mem.setdefault("history", [])
            mem.setdefault("summaries", [])
            return mem
        except Exception as e:
            logger.warning(f"   ↳ อ่านความจำไม่สำเร็จ: {e}")
    return {"name": "", "preferred_name": "", "facts": [], "history": [], "summaries": []}


def save_memory(user_id, mem):
    """บันทึกความจำของผู้ใช้ลงไฟล์"""
    try:
        with open(_memory_path(user_id), "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"   ↳ บันทึกความจำไม่สำเร็จ: {e}")


# ============================================================
#  หมวดหมู่ fact — ปิด (closed set) ให้ write path เทียบ "key เดียวกัน" แบบ rule-based ได้
#  single-value: มีค่า "จริง" ได้ค่าเดียวต่อช่วงเวลา — ค่าใหม่ supersede ค่าเก่า (ไม่ลบ)
#  multi-value: สะสมได้หลายอัน ไม่มี supersede (เช่น ความชอบมีได้หลายเรื่องพร้อมกัน)
# ============================================================
SINGLE_VALUE_CATEGORIES = {"ชื่อ", "ที่อยู่", "งาน"}
MULTI_VALUE_CATEGORIES = {"ความชอบ", "ของที่มี", "เรื่องที่สนใจ", "หัวข้อสนทนา"}
FACT_CATEGORIES = SINGLE_VALUE_CATEGORIES | MULTI_VALUE_CATEGORIES


def _now_th_iso() -> str:
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds")


def _fact_text(f) -> str:
    """คืนข้อความของ fact ไม่ว่าจะเก็บแบบเก่า (str ล้วน ก่อนมี category) หรือแบบใหม่ (dict)"""
    return f["text"] if isinstance(f, dict) else f


def _fact_category(f):
    """คืนหมวดของ fact — None ถ้าเป็นแบบเก่า/ไม่มีหมวด (แบบนี้ยกเว้นจาก supersede เสมอ)"""
    return f.get("category") if isinstance(f, dict) else None


def _fact_superseded(f) -> bool:
    """fact นี้ถูกแทนที่ไปแล้วหรือยัง — ยังอยู่ในเมมโมรีเสมอ (ไม่ลบ) แค่ไม่ใช่ค่าปัจจุบันแล้ว"""
    return isinstance(f, dict) and bool(f.get("superseded"))


# คำที่ต้องมีในเนื้อหา ถึงจะรับว่าเป็นหมวด single-value นั้นจริง
#
# 🚨 บั๊กที่เจอตอนคุยกับรอสเต้จริง (11 ส.ค. 2569) — เทส 626 ตัว + bench n=117 จับไม่ได้เลย:
#     ผู้ใช้พูด: "เกมที่ชอบที่สุดคือ Valorant เล่นมา 3 ปีแล้ว"
#     โมเดลสกัด: [งาน] "เล่นเกมมา 3 ปีแล้ว"        ← จัดหมวดผิด
#     ผลลัพธ์:   ไป supersede "ทำงานเป็นช่างซ่อมแอร์" ทิ้ง = ข้อมูลอาชีพจริงหาย
# ทำซ้ำได้: สำนวน "…มา N ปีแล้ว" ทำให้โมเดลเดาเป็นหมวด "งาน" แม้เนื้อหาเป็นเรื่องเกม
#
# ตรวจเฉพาะ SINGLE_VALUE_CATEGORIES เพราะมีแค่หมวดพวกนี้ที่ supersede ของเก่าทิ้ง
# หมวด multi-value สะสมได้อยู่แล้ว จัดผิดก็แค่รกไม่ถึงกับทำข้อมูลหาย → ไม่ต้องตรวจ
#
# ⚠️ ลิสต์คำไม่มีวันครบ (บทเรียนซ้ำจาก _HAIR_NEXT / _CHANGE_SIGNALS) จึงออกแบบให้
# "พลาดไปทางปลอดภัย": ไม่ผ่านเกณฑ์ = ไม่ทิ้งข้อมูล แค่ลดเป็น category=None ซึ่งยังเก็บไว้
# แต่ไม่มีสิทธิ์ supersede ใคร — เสีย precision ดีกว่าลบของจริงทิ้ง
_CATEGORY_REQUIRED_HINTS = {
    "งาน": ("ทำงาน", "อาชีพ", "เป็น", "ตำแหน่ง", "บริษัท", "ธุรกิจ", "ค้าขาย", "รับจ้าง",
            "พนักงาน", "ช่าง", "หมอ", "ครู", "วิศวกร", "โปรแกรมเมอร์", "นักเรียน", "นักศึกษา"),
    "ที่อยู่": ("อยู่", "บ้าน", "พัก", "ย้าย", "ภูมิลำเนา", "จังหวัด", "อาศัย"),
    "ชื่อ": ("ชื่อ", "เรียก"),
}

# คำที่บอกว่า *ไม่ใช่* หมวดนั้นแน่ๆ แม้จะมีคำใบ้ข้างบนปนอยู่
# ("ชอบเล่นเกม Valorant" มีคำว่า "เป็น" ไม่ได้ แต่ "เกมที่ชอบเป็น X" มี)
_CATEGORY_EXCLUDE_HINTS = {
    "งาน": ("เกม", "เล่น", "อ่านหนังสือ", "ดูหนัง", "ฟังเพลง", "งานอดิเรก", "ยามว่าง"),
}


def category_matches_text(category, text: str) -> bool:
    """เนื้อหานี้เข้ากับหมวดที่โมเดลบอกจริงไหม — ตรวจเฉพาะหมวดที่ supersede ได้

    คืน True เสมอสำหรับหมวด multi-value และหมวดที่ไม่มีเกณฑ์กำกับ (ไม่ไปขวางของเดิม)
    """
    if category not in _CATEGORY_REQUIRED_HINTS:
        return True
    if any(bad in text for bad in _CATEGORY_EXCLUDE_HINTS.get(category, ())):
        return False
    return any(h in text for h in _CATEGORY_REQUIRED_HINTS[category])


def add_fact(mem, text, category=None):
    """เพิ่ม fact เข้าความจำ พร้อมกันซ้ำ + คุมเพดาน

    ถ้า category อยู่ในกลุ่ม single-value (เช่น "ที่อยู่") และมี fact เดิมหมวดเดียวกันที่ยัง
    valid (ไม่ใช่ superseded) → mark อันเก่าเป็น superseded ก่อน (ไม่ลบทิ้ง) แล้วค่อยเพิ่มอันใหม่
    เทียบแค่ category ตรงกันไหม (rule-based ล้วน ไม่เรียก LLM)

    category ที่ไม่อยู่ใน FACT_CATEGORIES (หรือไม่ระบุ) → เก็บเป็น category=None
    fact แบบนี้จะไม่ถูก supersede อัตโนมัติ (ไม่มี key ให้เทียบ) แต่ยัง evict ได้ตาม MAX_FACTS ปกติ

    คืน True ถ้าเพิ่มจริง, False ถ้าซ้ำ (ไม่ได้เพิ่ม)"""
    text = text.strip()
    if not text:
        return False
    if category not in FACT_CATEGORIES:
        category = None
    # หมวด single-value ที่เนื้อหาไม่เข้าเกณฑ์ → ลดเป็นไม่มีหมวด (ยังเก็บ แต่ห้าม supersede)
    # กันเคสจริง: [งาน]"เล่นเกมมา 3 ปีแล้ว" ไปลบ "ทำงานเป็นช่างซ่อมแอร์" ทิ้ง
    if category and not category_matches_text(category, text):
        category = None

    facts = mem.setdefault("facts", [])

    # กันจำซ้ำ — ถ้ามี fact ข้อความเดียวกันเป๊ะที่ยัง valid อยู่แล้ว ไม่เพิ่มซ้ำ
    # (fact ที่เคยถูก supersede ไปแล้วไม่นับ — เผื่อผู้ใช้ย้ายกลับที่เดิม ต้องเพิ่มใหม่เป็นค่าปัจจุบันได้)
    for f in facts:
        if _fact_text(f) == text and not _fact_superseded(f):
            return False

    now_iso = _now_th_iso()

    if category in SINGLE_VALUE_CATEGORIES:
        for f in facts:
            if isinstance(f, dict) and f.get("category") == category and not f.get("superseded"):
                f["superseded"] = True
                f["superseded_at"] = now_iso
                f["superseded_by"] = text

    facts.append({
        "category": category,
        "text": text,
        "created": now_iso,
        "superseded": False,
        "superseded_at": None,
        "superseded_by": None,
    })

    # คุมเพดาน — เกิน MAX_FACTS ตัดอันเก่าสุด (ต้นลิสต์) ทิ้งจริง (self-heal ของ fact เก่า/ไม่มีหมวดด้วย)
    if len(facts) > MAX_FACTS:
        del facts[: len(facts) - MAX_FACTS]
    return True


def remove_fact(mem, keyword):
    """ลบ fact ที่มีคำว่า keyword อยู่ (ลบรายตัว ไม่ต้องล้างหมด) — เป็นคำสั่งผู้ใช้ตรงๆ จึงลบจริง
    (ต่างจาก supersede อัตโนมัติใน add_fact ที่ไม่ลบ — อันนี้ผู้ใช้ตั้งใจสั่งให้ลืมเอง)
    คืนรายการข้อความ fact ที่ถูกลบ (อาจมากกว่า 1 ถ้า keyword ตรงหลายอัน)"""
    keyword = keyword.strip()
    if not keyword:
        return []
    facts = mem.get("facts", [])
    removed = [f for f in facts if keyword in _fact_text(f)]
    mem["facts"] = [f for f in facts if keyword not in _fact_text(f)]
    return [_fact_text(f) for f in removed]


def recall_facts(mem, user_message):
    """ดึง fact ที่ "เกี่ยวข้อง" กับข้อความปัจจุบันมาใช้ (selective recall)
    - ไม่รวม fact ที่ถูก superseded แล้ว (กันโมเดลเห็นข้อมูลเก่า+ใหม่พร้อมกันแล้วสับสนว่าอันไหนจริง
      — เช่น "อยู่ชุมพร" กับ "อยู่กรุงเทพ" พร้อมกัน) ของเก่ายังอยู่ในไฟล์เสมอ แค่ไม่ถูกเสนอเป็น
      "ค่าปัจจุบัน" ในบทสนทนาปกติ — ยังใช้เป็นวัตถุดิบให้ฟีเจอร์อื่น query ย้อนหลังได้
    - ถ้า facts (ที่ยัง valid) น้อย (<= MAX_FACTS_IN_CONTEXT) คืนทั้งหมด
    - ถ้าเยอะ ให้คะแนนตามจำนวนคำที่ตรงกับข้อความ แล้วเลือกอันคะแนนสูงสุด
      (อันที่ไม่ตรงเลยก็ยังเก็บบางส่วนไว้ เผื่อเป็นข้อมูลพื้นฐานสำคัญ)"""
    facts = [f for f in mem.get("facts", []) if not _fact_superseded(f)]
    if len(facts) <= MAX_FACTS_IN_CONTEXT:
        return [_fact_text(f) for f in facts]

    # แตกข้อความเป็นคำ — ต้องตัดคำไทยจริง ไม่ใช่ split() ตามช่องว่าง (ดู _keywords)
    words = [w.lower() for w in _keywords(user_message)]

    scored = []
    for f in facts:
        text = _fact_text(f)
        fl = text.lower()
        score = sum(1 for w in words if w in fl)
        scored.append((score, text))

    # เรียงตามคะแนน (มากก่อน) — อันที่เกี่ยวข้องขึ้นก่อน
    scored.sort(key=lambda x: x[0], reverse=True)

    # เลือกอันที่มีคะแนน (เกี่ยวข้องจริง) ก่อน
    relevant = [t for s, t in scored if s > 0][:MAX_FACTS_IN_CONTEXT]

    # ถ้ายังไม่เต็มโควต้า เติมด้วย fact ล่าสุด (เผื่อข้อมูลพื้นฐานที่ไม่ได้ตรงคำ)
    if len(relevant) < MAX_FACTS_IN_CONTEXT:
        all_texts = [_fact_text(f) for f in facts]
        for text in reversed(all_texts):
            if text not in relevant:
                relevant.append(text)
            if len(relevant) >= MAX_FACTS_IN_CONTEXT:
                break
    return relevant


# ============================================================
#  🪄  จำเอง (auto-memory) — สกัดข้อเท็จจริงถาวรเกี่ยวกับผู้ใช้จากบทสนทนา
#      จำเฉพาะ: ชื่อ / ที่อยู่ / งาน-เรียน / ความชอบ / ของที่มี / เรื่องที่สนใจ
#      ไม่จำ: คำถามทั่วไป ความรู้สึกชั่วคราว เรื่องที่ไม่เกี่ยวกับตัวผู้ใช้
# ============================================================

# กรองหยาบก่อนเรียกโมเดล — ข้อความต้องมีสัญญาณว่า "พูดถึงตัวเอง" ถึงจะลองสกัด
# (ประหยัด LLM call: ทักทาย/ถามข้อมูล/คุยเรื่องอื่น จะถูกข้าม)
SELF_REFERENCE_HINTS = (
    "เรา", "ผม", "ฉัน", "หนู", "ชื่อ", "อยู่", "ทำงาน", "เรียน", "ชอบ",
    "สนใจ", "เรามี", "ผมมี", "ฉันมี", "หนูมี", "เลี้ยง",
    "ของฉัน", "ของเรา", "บ้าน", "อาชีพ", "ถนัด",
)


def should_try_extract(text: str) -> bool:
    """ข้อความนี้ควรลองสกัดข้อมูลตัวตนไหม (กรองหยาบ ก่อนเปลือง LLM call)"""
    t = text.strip()
    if len(t) < 6:                       # สั้นเกินไป (ทักทาย/คำเดียว) ข้าม
        return False
    return any(h in t for h in SELF_REFERENCE_HINTS)


def build_extract_prompt(user_message: str) -> str:
    """สร้าง prompt สั่งโมเดลสกัดข้อเท็จจริงถาวรเกี่ยวกับผู้ใช้ พร้อมระบุหมวดจาก set ปิด
    (โมเดลจัดหมวดอยู่แล้วในหัวตอนตัดสินใจว่าเข้าเกณฑ์สกัดไหม — ให้บอกหมวดออกมาด้วยเลย
    ไม่ต้องเรียก LLM เพิ่มรอบ — หมวดนี้ทำให้ write path เทียบ "key เดียวกัน" แบบ rule-based ได้)"""
    categories_list = ", ".join(sorted(FACT_CATEGORIES))
    return (
        "ดึง \"ข้อเท็จจริงถาวรเกี่ยวกับตัวผู้ใช้\" จากข้อความด้านล่าง "
        f"เฉพาะหมวดเหล่านี้เท่านั้น: {categories_list}\n"
        "กฎ:\n"
        "- เอาเฉพาะข้อมูลที่เป็นความจริงถาวรเกี่ยวกับ \"ตัวผู้ใช้เอง\" เท่านั้น\n"
        "- ห้ามเอา: คำถาม, ความรู้สึกชั่วคราว, เรื่องทั่วไป, เรื่องคนอื่น, สิ่งที่ไม่แน่ใจ\n"
        "- หมวด \"หัวข้อสนทนา\" ให้เขียนเป็น pattern ถาวร เช่น \"ชอบคุยเรื่องปรัชญา\" "
        "ไม่ใช่เหตุการณ์เฉพาะ เช่น \"ถามเรื่องหนังสือเมื่อกี้\"\n"
        "- เขียนแต่ละข้อสั้นๆ กระชับ เป็นภาษาไทย\n"
        "- category ต้องเป็นคำในลิสต์ข้างบนเป๊ะๆ เท่านั้น ห้ามสร้างหมวดใหม่เอง\n"
        "- ถ้าไม่มีข้อมูลที่เข้าเกณฑ์เลย ให้ตอบ []\n"
        "ตอบเป็น JSON array ของ object ที่มี \"category\" กับ \"text\" เท่านั้น "
        "ห้ามมีคำอธิบายอื่น เช่น:\n"
        "[{\"category\": \"ชื่อ\", \"text\": \"ชื่อจูเลีย\"}, "
        "{\"category\": \"ที่อยู่\", \"text\": \"อยู่ชุมพร\"}]\n\n"
        f"ข้อความ: {user_message}"
    )


def parse_extracted_facts(model_output: str) -> list:
    """แปลงผลที่โมเดลตอบ (ควรเป็น JSON array ของ {category, text}) เป็น list ของ dict
    ทนทานต่อกรณีโมเดลใส่ข้อความเกินมา — ดึงเฉพาะส่วน [...] ออกมา parse
    - category ที่หลุด FACT_CATEGORIES → category=None (ไม่มีหมวด แต่ยังเก็บ fact ไว้ ไม่ทิ้ง)
    - รองรับกรณีโมเดลเผลอตอบเป็น list ของสตริงล้วน (รูปแบบเก่า) ด้วย เพื่อความทนทาน
    คืน list ของ {"category": str|None, "text": str}"""
    import json as _json
    import re as _re
    if not model_output:
        return []
    # ตัด <think>...</think> ถ้ามี
    if "</think>" in model_output:
        model_output = model_output.rsplit("</think>", 1)[-1]
    # หาส่วนที่เป็น array [...] อันแรก
    m = _re.search(r"\[.*?\]", model_output, _re.DOTALL)
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
            text, category = it.get("text"), it.get("category")
        elif isinstance(it, str):
            text, category = it, None
        else:
            continue
        if not isinstance(text, str):
            continue
        text = text.strip()
        if not (2 <= len(text) <= 60):   # ยาวเกิน 60 ตัว = น่าจะไม่ใช่ fact สั้นๆ
            continue
        if category not in FACT_CATEGORIES:
            category = None
        out.append({"category": category, "text": text})
    return out


def build_summary_prompt(pairs: list) -> str:
    """สร้าง prompt ให้โมเดลสรุปบทสนทนา — เก็บ *เนื้อหา* พร้อม tag บอกว่าเรื่องไหนของใคร

    รูปแบบที่ได้ (เรียกว่า "วิธี F" ใน docs/MEMORY_EXPERIMENTS.md):
        คุยเรื่องแนวนิยาย | user_pref:ชอบนิยายสืบสวน me_pref:ชอบแนวแฟนตาซี

    ⚠️ เดิม prompt นี้สั่งว่า "สั้นที่สุดเท่าที่จะบอกหัวข้อได้" + "ห้ามเติมรายละเอียด"
    ซึ่งกันการแต่งข้อมูลได้จริง แต่เหวี่ยงเกินจนห้ามทั้งของแต่งขึ้น *และ* ของที่ผู้ใช้พูดจริง
    ผลคือ summary บอกได้แค่ว่า "คุยเรื่องอะไร" แต่บอกไม่ได้ว่า "ใครชอบอะไร" —
    วัดได้ว่าเก็บรายละเอียดของผู้ใช้ 0% (10 รอบ ไม่ผ่านสักครั้ง)

    ทำไมต้องมี tag แยกเจ้าของ: ถ้าเขียนรวมกันเป็นประโยคเดียว ตอน recall กลับมาโมเดลแยก
    ไม่ออกว่าอันไหนของผู้ใช้ อันไหนของรอสเต้ — วัดได้ว่าจำสลับเจ้าของ 29% (1 ใน 3 ครั้ง)
    ซึ่งแย่กว่าการจำไม่ได้ เพราะรอสเต้จะเชื่อว่าผู้ใช้ชอบสิ่งที่ตัวเองชอบ
    การมี tag ทำให้ chat.py กรองเหลือเฉพาะฝั่งที่ถูกถามได้ก่อนส่งเข้า context (สลับ → 0%)

    เทียบ 6 วิธีแล้ว (ดู tools/bench_summary_compare.py) วิธีนี้เป็นวิธีเดียวที่รอสเต้
    "จำเรื่องของตัวเองได้" — อีก 5 วิธีได้ 0% เพราะไม่มีที่ให้เก็บฝั่งรอสเต้เลย
    """
    convo = "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'รอสเต้'}: {m.get('content', '')}"
        for m in pairs
    )
    return (
        "สรุปบทสนทนาต่อไปนี้ ตอบเป็น JSON เท่านั้น\n"
        "คุณคือรอสเต้ กำลังบันทึกความทรงจำของตัวเอง — ต้องแยกให้ชัดว่าเรื่องไหนของใคร\n"
        '{"summary": "<หัวข้อที่คุย 1 บรรทัดสั้นๆ>", "tags": [...]}\n'
        "ชนิดของ tag (เลือกใช้เท่าที่มีจริงในบท):\n"
        '- "user_pref:<สิ่งที่ผู้ใช้ชอบ/ไม่ชอบ>"\n'
        '- "user_fact:<ข้อเท็จจริงของผู้ใช้>"\n'
        '- "me_pref:<สิ่งที่รอสเต้เองชอบ/ไม่ชอบ>"\n'
        '- "me_fact:<สิ่งที่รอสเต้ทำหรือเป็น>"\n'
        "กฎ:\n"
        "- ใส่ tag เฉพาะเรื่องที่ *มีอยู่จริงในบทสนทนาข้างล่าง* เท่านั้น ถ้าไม่มีอย่าใส่\n"
        "- ฝั่งไหนไม่มีอะไรน่าจำ ปล่อยว่างได้ ไม่ต้องหาอะไรมาเติมให้ครบทุกฝั่ง\n"
        "- ห้ามสลับเจ้าของ: สิ่งที่ผู้ใช้พูดต้องเป็น user_* สิ่งที่รอสเต้พูดต้องเป็น me_*\n"
        "- ห้ามบันทึกข้อมูลสดที่หมดอายุ (ราคาน้ำมัน พยากรณ์อากาศ เวลา)\n"
        "- ห้ามแต่งชื่อเฉพาะ/ตัวเลขที่ไม่ได้อยู่ในบท\n"
        "- ไม่เกิน 4 tags ถ้าไม่มีอะไรน่าจำใส่ [] ได้\n"
        "ตอบ JSON อย่างเดียว:\n\n"
        + convo
    )


# ── แปลงผล JSON จาก build_summary_prompt เป็นบรรทัดเดียวสำหรับเก็บ ──────────────

def parse_summary_json(raw: str) -> str:
    """แปลง {"summary":..., "tags":[...]} → "หัวข้อ | tag1 tag2"

    คืน "" ถ้า parse ไม่ได้เลย — ผู้เรียกต้องถือว่าสรุปรอบนั้นใช้ไม่ได้ (fail-conservative
    แบบเดียวกับ DISCARD ใน verify pass) ดีกว่าเก็บข้อความดิบที่อาจมีคำนำของโมเดลปนมา

    รองรับกรณีโมเดลพูดนำหน้า/ตามหลัง JSON (เจอบ่อยกับ qwen3:8b) โดยตัดเอาเฉพาะช่วง {...}
    """
    import json as _json
    txt = (raw or "").strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start < 0 or end <= start:
        return ""
    try:
        d = _json.loads(txt[start:end + 1])
    except Exception:
        return ""
    head = str(d.get("summary") or "").strip()
    tags = d.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    clean = [str(t).strip() for t in tags if str(t).strip()]
    clean = [t for t in clean if not _is_leaked_example(t)]
    # ตัด tag ที่พูดถึงตัวการสนทนาเอง ("เคยคุยเรื่อง…") — ดู is_meta_summary_tag
    clean = [t for t in clean
             if not ((m := _OWNER_TAG_RE.match(t.strip()))
                     and is_meta_summary_tag(t.strip()[m.end():]))]
    if not head and not clean:
        return ""
    return f"{head} | {' '.join(clean)}" if clean else head


# ข้อความที่เคยเป็น "ตัวอย่าง" ใน build_summary_prompt แล้วโมเดลลอกมาใช้จริง
#
# 🚨 วัดกับความจำจริง: "แนะนำร้านให้" โผล่ 17/55 ครั้ง · "ชอบหนังสือเก่า" 14/55 ครั้ง
# ทั้งที่เป็นแค่ตัวอย่างใน prompt — ส่วนตัวอย่างฝั่ง user ("ชอบนิยายสืบสวน"/"กินเผ็ดไม่ได้")
# ไม่หลุดเลยสักครั้ง เพราะกฎเดิมกดดันให้ *ต้องมี* tag ฝั่ง me ทุกครั้ง
# (วัดได้: ฝั่ง me ว่าง 0/55 แต่ฝั่ง user ว่าง 17/55) พอไม่มีของจริงก็ลอกตัวอย่างมาแทน
#
# แก้ที่ prompt แล้ว (ถอดตัวอย่าง + เลิกบังคับให้ครบทุกฝั่ง) แต่ MEMORY_EXPERIMENTS §4
# เตือนซ้ำ 3 ครั้งว่า "prompt แก้พฤติกรรมโมเดลไม่ได้ ต้องมี validation layer" — นี่คือด่านนั้น
#
# ⚠️ ลิสต์นี้ตั้งใจให้แคบมาก: เฉพาะข้อความที่ *เคยเป็นตัวอย่างใน prompt จริงๆ* เท่านั้น
# ไม่ใช่ blacklist คำทั่วไป เพราะถ้าผู้ใช้คุยเรื่องร้านอาหารจริง "แนะนำร้าน" ก็ควรถูกเก็บได้
# จึงเทียบแบบ *ตรงเป๊ะทั้ง tag* ไม่ใช่ substring
_LEAKED_EXAMPLE_VALUES = {
    "แนะนำร้านให้",
    "ชอบหนังสือเก่า",
}


# คำที่บอกว่า tag นี้พูดถึง "ตัวการสนทนา" ไม่ใช่ข้อเท็จจริงของใคร
#
# 🚨 บั๊กที่เจอตอนคุยจริง: ผู้ใช้ถาม "เราเคยคุยเรื่องอะไรกันบ้าง" รอสเต้ตอบไป
# แล้วรอบสรุปถัดมาเก็บคำตอบนั้นเป็น `user_fact:เคยคุยเรื่องงาน ความชอบเกม และอาหาร`
# = เอาคำพูดของตัวเองมาเก็บเป็นข้อเท็จจริงของผู้ใช้ (attribution error ตอนเขียน)
#
# อันตรายเพราะสะสม: ทุกครั้งที่ผู้ใช้ถามเรื่องความจำ จะได้ tag แบบนี้เพิ่มอีกอัน
# ความทรงจำจะค่อยๆ เต็มไปด้วย "บันทึกว่าเคยบันทึกอะไร" แทนข้อมูลจริง
#
# ⚠️ ต้องระวังไม่ให้ตัดของจริง: "เบื่อเกมยิงปืน หันมาเล่นเกมปลูกผัก" มีคำว่า "เล่น"
# แต่ไม่ใช่ meta — จึงเทียบเฉพาะคำที่ *ขึ้นต้น* ด้วยกริยาพูดคุย ไม่ใช่มีคำนั้นที่ไหนก็ได้
_META_TAG_PREFIXES = (
    "เคยคุย", "คุยกัน", "คุยเรื่อง", "พูดคุย", "สนทนา", "ถามเรื่อง", "ถามถึง",
    "เล่าเรื่อง", "อธิบายเรื่อง", "แลกเปลี่ยน",
)


def is_meta_summary_tag(value: str) -> bool:
    """tag นี้พูดถึงตัวการสนทนาเอง (ไม่ใช่ข้อเท็จจริงของใคร) หรือเปล่า"""
    v = value.strip()
    return any(v.startswith(p) for p in _META_TAG_PREFIXES)


def _is_leaked_example(tag: str) -> bool:
    """tag นี้เป็นข้อความที่ลอกมาจากตัวอย่างใน prompt หรือเปล่า"""
    m = _OWNER_TAG_RE.match(tag.strip())
    if not m:
        return False
    return tag.strip()[m.end():].strip() in _LEAKED_EXAMPLE_VALUES


# จำนวน summary ล่าสุดที่ใช้เทียบหาของซ้ำ
#
# ไม่เทียบทั้ง 100 อันเพราะ (1) เปลืองเวลาโดยไม่จำเป็น (2) เรื่องที่พูดเมื่อ 3 เดือนก่อน
# แล้วพูดซ้ำวันนี้ ถือว่า "ย้ำ" ซึ่งมีความหมาย ไม่ใช่ของซ้ำที่ต้องตัด
_DEDUPE_LOOKBACK = 20


def dedupe_tags_against(new_summary: str, old_texts) -> str:
    """ตัด tag ที่มีอยู่แล้วในความจำออกจาก summary ใหม่ — คืนบรรทัดที่ตัดแล้ว

    ⚠️ กรอบ LTM ข้อ 2 (Deduplication): "ข้อเท็จจริงเดิมที่พูดซ้ำไม่ควรกลายเป็น 5 records"
    วัดกับความจำจริง: tag ซ้ำ 31/144 = 22% (นับเฉพาะที่ไม่ใช่ของลอกจาก prompt)
        4x user_pref:ต้องการคำพูดเป็นทางการ · 3x user_fact:ทำงานหนัก

    ต้นเหตุ: chat.py เขียนด้วย `summaries.append(entry)` ตรงๆ ไม่เทียบของเดิมเลย
    ต่างจากฝั่ง facts ที่ add_fact() กันซ้ำมาตั้งแต่ต้น

    ⚠️ กันซ้ำ *ระดับ tag* ไม่ใช่ระดับบรรทัด — บรรทัดเดียวมีหลาย tag และหัวเรื่องต่างกัน
    (เป็นคนละบทสนทนา) ถ้าลบทั้งบรรทัดจะเสียหัวเรื่องที่ยังมีค่าไปด้วย

    เทียบแบบ "ชนิด+ค่า ตรงกันเป๊ะ" เท่านั้น — user_pref:อ่านหนังสือ กับ me_pref:อ่านหนังสือ
    เป็นคนละคน ไม่ใช่ของซ้ำ ส่วนคำที่ใกล้เคียงกัน ("แนะนำคำกล่าว" vs "แนะนำคำกล่าวขอบคุณ")
    ไม่ตัด เพราะการเดาว่าอันไหน "เหมือนพอ" คือปัญหาเดียวกับ conflict resolution ที่วัดแล้วว่ายาก
    """
    marks = list(_OWNER_TAG_RE.finditer(new_summary))
    if not marks or not old_texts:
        return new_summary

    seen = set()
    for t in list(old_texts)[-_DEDUPE_LOOKBACK:]:
        text = t["text"] if isinstance(t, dict) else t
        p = split_owner_tags(text)
        for kind in ("user_pref", "user_fact", "me_pref", "me_fact"):
            for v in p[kind]:
                seen.add((kind, v))

    head = new_summary.split("|", 1)[0].strip()
    kept = []
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(new_summary)
        seg = new_summary[mk.end():end].strip(" |,")
        kind = mk.group(1).rstrip(":")
        if seg and (kind, seg) not in seen:
            kept.append(f"{kind}:{seg}")
    return f"{head} | {' '.join(kept)}" if kept else head


def build_verify_prompt(pairs: list, summary: str) -> str:
    """สร้าง prompt ให้โมเดลตรวจว่าสรุปมีข้อมูลที่ไม่ได้อยู่ในบทสนทนาจริงไหม"""
    convo = "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'รอสเต้'}: {m.get('content', '')}"
        for m in pairs
    )
    return (
        "ตรวจสอบสรุปบทสนทนาต่อไปนี้:\n\n"
        f"บทสนทนาจริง:\n{convo}\n\n"
        f"สรุป: {summary}\n\n"
        "คำถาม: สรุปมีข้อมูลที่ไม่ปรากฏในบทสนทนาจริงข้างบนไหม?\n"
        "(เช่น ชื่อหนังสือ/สถานที่/ตัวเลข/รายละเอียดเฉพาะที่ผู้ใช้ไม่ได้พูดถึง)\n\n"
        "ถ้าสรุปถูกต้อง ตอบ: OK\n"
        "ถ้ามีข้อมูลแต่งเพิ่ม แต่แก้ได้ ตอบ: FIX: <สรุปที่ถูกต้อง 1 บรรทัด>\n"
        "ถ้าแก้ไม่ได้หรือสรุปผิดพลาดมาก ตอบ: DISCARD\n"
        "ตอบสั้นๆ ตรงประเด็น ไม่มีคำอธิบายเพิ่ม"
    )


# ── กรองความทรงจำตามเจ้าของ (ใช้คู่กับ tag จาก build_summary_prompt) ───────────
#
# ทำไมต้องกรอง: summary รูปแบบ F เก็บทั้งฝั่งผู้ใช้และฝั่งรอสเต้ไว้ในบรรทัดเดียว
#     "คุยแนวนิยาย | user_pref:ชอบสืบสวน me_pref:ชอบแฟนตาซี"
# ถ้ายัดทั้งบรรทัดเข้า context โมเดลเห็นสองฝั่งพร้อมกันแล้วแยกไม่ออก — วัดได้ว่าจำสลับ
# เจ้าของ 29% พอกรองเหลือเฉพาะฝั่งที่ถูกถามก่อนส่ง เหลือ 0% (ดู docs/MEMORY_EXPERIMENTS.md)

_OWNER_TAG_RE = re.compile(r"(user_pref|user_fact|me_pref|me_fact)\s*:")

# ⚠️ จับที่ *ตัวประธาน* อย่างเดียว ไม่จับคู่กับกริยา — รุ่นแรกเขียนเป็น "<ประธาน> + <กริยา>"
# (รอสเต้ + ชอบ/สนใจ/ถนัด) แล้วพังทันทีที่เจอกริยานอกลิสต์ ("รอสเต้ทำงานอะไร" → เดาไม่ออก
# → คืน fact ของผู้ใช้มาแทน) การไล่เติมกริยาทีละคำเป็น whack-a-mole แบบเดียวกับที่
# _TOOL_REASONING_LEAK_RE เคยติดกับดัก — ประธานมีจำกัดและนับได้ ส่วนกริยาไม่มีวันครบ
_ASK_ABOUT_ROSTE_RE = re.compile(r"รอสเต้|เธอ|น้อง")
_ASK_ABOUT_USER_RE = re.compile(r"ผม|ฉัน|หนู|ข้าพเจ้า|ตัวเรา")
# ถามถึงทั้งสองฝ่ายพร้อมกัน — ต้องคืนทั้งคู่ ไม่ใช่เลือกฝั่งใดฝั่งหนึ่ง
_ASK_BOTH_RE = re.compile(r"เราสองคน|ทั้งสอง|ต่างกัน|เหมือนกัน|คนละ")


def split_owner_tags(text: str) -> dict:
    """แยก summary รูปแบบ F เป็น {"summary","user","me"}

    summary แบบเก่า (ไม่มี tag) จะได้ user/me ว่าง — ผู้เรียกต้องรับมือได้
    """
    head = text.split("|", 1)[0].strip()
    marks = list(_OWNER_TAG_RE.finditer(text))
    out = {"summary": head, "user": [], "me": [],
           "user_pref": [], "user_fact": [], "me_pref": [], "me_fact": []}
    for i, mk in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        seg = text[mk.end():end].strip(" |,")
        if not seg:
            continue
        kind = mk.group(1).rstrip(":")            # user_pref / me_fact / ...
        out["me" if kind.startswith("me") else "user"].append(seg)
        if kind in out:                           # แยกละเอียดอีกชั้น (ดู B1 ด้านล่าง)
            out[kind].append(seg)
    return out


def guess_owner(question: str) -> str:
    """เดาว่าคำถามถามถึงความทรงจำของใคร — 'user' / 'me' / 'any'

    ลำดับสำคัญ: ถามทั้งสองฝ่ายต้องมาก่อน ("เราสองคนชอบอะไรต่างกัน" ไม่ควรถูกตัดฝั่ง)
    แล้วตรวจรอสเต้ก่อนผู้ใช้ เพราะ "เราเคยคุยเรื่องที่รอสเต้ชอบไหม" มีคำชี้ทั้งคู่
    แต่เจตนาคือถามรอสเต้
    """
    if _ASK_BOTH_RE.search(question):
        return "any"
    if _ASK_ABOUT_ROSTE_RE.search(question):
        return "me"
    if _ASK_ABOUT_USER_RE.search(question):
        return "user"
    return "any"


# คำที่บอกว่าผู้ใช้ถามถึง "ความชอบ/นิสัย" ไม่ใช่ "สิ่งที่ทำให้"
#
# ⚠️ B1 (attribution error) — วัดกับความจำจริง: ถาม "รอสเต้ชอบอะไร" แล้วได้
# "แนะนำร้านให้" ปนมาทุกครั้ง ทั้งที่นั่นคือ *สิ่งที่รอสเต้ทำให้ผู้ใช้* ไม่ใช่ *ความชอบ*
# เพราะ filter_by_owner ยัด me_pref กับ me_fact รวมกันเป็น "รอสเต้: ..." ก้อนเดียว
#
# ตรงกับ "attribution error" ในกรอบ LTM: สับสนระหว่างสิ่งที่เป็น กับสิ่งที่ทำ
_PREF_QUESTION_HINTS = ("ชอบ", "ไม่ชอบ", "โปรด", "ถนัด", "สนใจ", "เกลียด", "นิสัย", "ทัศนคติ")
_ACTION_QUESTION_HINTS = ("แนะนำ", "ทำอะไรให้", "ช่วยอะไร", "บอกอะไร", "สอน")


def asks_about_preference(question: str) -> bool:
    """คำถามนี้ถามถึง "ความชอบ/นิสัย" ล้วนๆ (ไม่ได้ถามว่าทำอะไรให้) หรือเปล่า"""
    if any(h in question for h in _ACTION_QUESTION_HINTS):
        return False        # ถามทั้งสองอย่างปนกัน → ไม่กรอง (ปลอดภัยกว่า)
    return any(h in question for h in _PREF_QUESTION_HINTS)


def filter_by_owner(texts, whose: str, kind: str = None) -> list:
    """กรองรายการ summary ให้เหลือเฉพาะฝั่งที่ถาม แล้วเขียนใหม่ให้อ่านง่าย

    whose='any' → คืนตามเดิมทั้งหมด
    บรรทัดที่ไม่มี tag ฝั่งที่ถาม จะถูกตัดทิ้ง — รวมถึง summary แบบเก่าที่ไม่มี tag เลย
    (ตั้งใจ: ถามเจาะจงฝั่งแล้วไม่มีข้อมูลฝั่งนั้น ควรตอบว่าจำไม่ได้ ดีกว่าเอาของอีกฝั่งมาตอบ)

    kind='pref' → เอาเฉพาะ <whose>_pref (ความชอบ) ไม่เอา _fact (สิ่งที่ทำ) — ดู B1
    kind=None   → เอาทั้งหมดเหมือนเดิม (พฤติกรรมเดิม ไม่กระทบผู้เรียกที่มีอยู่)
    """
    if whose not in ("user", "me"):
        return list(texts)
    label = "ผู้ใช้" if whose == "user" else "รอสเต้"
    key = f"{whose}_{kind}" if kind else whose
    out = []
    for t in texts:
        parts = split_owner_tags(t)
        own = parts.get(key) or []
        if not own:
            # ไม่มีของชนิดที่ขอ — ถ้ากรองชนิดอยู่ให้ข้ามไปเลย (ตอบว่าจำไม่ได้ดีกว่าตอบผิดชนิด)
            continue
        out.append(f"{parts['summary']} — {label}: {', '.join(own)}")
    return out


# คำบ่งชี้ว่าผู้ใช้ถามถึงอดีต — trigger ให้ดึง summaries ขึ้นมา
PAST_HINTS = (
    "จำได้ไหม", "จำได้ว่า",
    "เมื่อก่อน", "เมื่อกี้",
    "ก่อนหน้านี้", "ก่อนหน้า",
    "ที่เคยคุย", "ที่เคยพูด", "ที่เคยบอก",
    "เคยคุย", "เคยบอก", "เคยพูด", "เคยถาม",
    "ต้นเดือน", "ปลายเดือน", "กลางเดือน",
    "อาทิตย์ที่แล้ว", "เดือนที่แล้ว", "วันก่อน",
)

# คำบ่งชี้ "อดีต" ที่กำกวม — คนจริงก็ใช้คำว่า "เมื่อวาน" ถามอดีตบทสนทนาได้จริง
# ("เมื่อวานคุยเรื่องหนังสือกันใช่ไหม") จึงไม่ตัดออกจาก PAST_HINTS แต่คำนี้ยังถูกใช้ถามข้อมูล
# สดบ่อยพอๆ กัน ("เมื่อวานฝนตกไหม เย็นนี้จะตกอีกไหม", "เมื่อวานน้ำมันเท่าไหร่") — ต่างจากคำอื่นใน
# PAST_HINTS ที่ไม่กำกวม (เช่น "จำได้ไหม", "ที่เคยคุย") ดังนั้นให้ trigger เฉพาะตอนไม่มีสัญญาณ
# คำถามข้อมูลสด (อากาศ/น้ำมัน/ไฟดับ) ปนอยู่ในประโยคเดียวกัน — ดู recall_summaries
AMBIGUOUS_PAST_HINTS = ("เมื่อวาน",)
_LIVE_DATA_SIGNALS = (
    "ฝน", "อากาศ", "อุณหภูมิ", "องศา", "ร้อน", "หนาว", "พรุ่งนี้", "วันนี้", "เย็นนี้",
    "น้ำมัน", "เบนซิน", "ดีเซล", "แก๊สโซฮอล",
    "ไฟดับ", "ตัดไฟ", "งดจ่ายไฟ",
)


def has_live_data_signal(text: str) -> bool:
    """ข้อความนี้ถามข้อมูลสด (อากาศ/ราคาน้ำมัน/ไฟดับ) หรือเปล่า — เทียบระดับ *โทเคน*

    ⚠️ เดิมเช็คด้วย `any(s in text for s in _LIVE_DATA_SIGNALS)` ซึ่งเป็นการเทียบสตริงย่อย
    ภาษาไทยเขียนติดกัน จึงจับคำที่ไม่ได้ตั้งใจ — วัดกับความจำจริงพบว่า:
        "หน้าร้อนผมชอบไปเที่ยวไหน"  →  "ร้อน" อยู่ใน "หน้าร้อน"  →  ถูกตัดเป็นคำถามอากาศ
        คืน [] ทันที **ทั้งที่คะแนนจับคู่จริง = 2 (หยิบได้)**
    โดนหมด: หน้าร้อน / หน้าหนาว / หน้าฝน / ของร้อนๆ — คิดเป็น 4 ใน 8 เคสที่ oracle พลาด

    ต้นเหตุเดียวกับ _looks_like_hair ใน persona.py ("ผม" สรรพนาม vs "สระผม" เส้นผม) และกับ
    บั๊ก keyword recall เดิม — ทางแก้เดียวกัน: **ตัดคำก่อนแล้วเทียบทั้งโทเคน**

    ทำไมไม่ใช้ blacklist ("หน้าร้อน" ไม่นับ): คำประสมที่มี "ร้อน/หนาว/ฝน" มีไม่จำกัด
    (หน้าร้อน, ของร้อน, ใจร้อน, ร้อนใจ, ร้อนวิชา...) blacklist ครอบได้แค่ที่นึกออก
    — บทเรียนตรงกับ MEMORY_EXPERIMENTS §4 "อย่าจับคู่ประธาน+กริยา กริยาไม่มีวันครบ"
    """
    toks = set(_keywords(text, expand=False))
    if toks & set(_LIVE_DATA_SIGNALS):
        return True
    # tokenizer พังแล้วถอยไป split() → คืนทั้งประโยคเป็นก้อนเดียว ทำให้ set ข้างบนไม่มีวันตรง
    # กรณีนั้นถอยไปใช้การเทียบสตริงย่อยแบบเดิม (ยอมพลาดทาง false positive ดีกว่าไม่กันเลย)
    if not toks:
        return any(s in text for s in _LIVE_DATA_SIGNALS)
    return False


# ข้อความทักทาย/ขอบคุณ/รับคำ — เป็นการเข้าสังคม ไม่ใช่คำถาม จึงไม่ควรดึงความทรงจำ
#
# ⚠️ เจอจากการวัดกับความจำจริง: "ขอบคุณนะ" ดึง summary มา 5 อัน เพราะผู้ใช้เคยคุยเรื่อง
# "การเขียนคำกล่าวขอบคุณ" จริง → โทเคน "ขอบคุณ" แมตช์ตรงเป๊ะ **retrieval ทำงานถูกต้อง**
# แต่ผลลัพธ์ผิดในระดับ UX: ผู้ใช้แค่ขอบคุณ ไม่ได้ถามอะไร การยัดความทรงจำเข้าไปคือ
# intrusiveness (กรอบ LTM ข้อ 7) ซึ่งทำให้ประสบการณ์แย่กว่าไม่มี memory เลย
#
# เทียบทั้งข้อความหลังตัดช่องว่าง (ไม่ใช่ substring) — "ขอบคุณนะ" ใช่ แต่
# "จำได้ไหมว่าเคยคุยเรื่องคำกล่าวขอบคุณ" ไม่ใช่ เพราะเป็นประโยคยาวที่มีเจตนาถามจริง
_SOCIAL_ONLY_RE = re.compile(
    r"^(ขอบคุณ|ขอบใจ|thx|thanks?|สวัสดี|หวัดดี|ดีจ้า|โอเค|โอเคร|ok|okay|เยี่ยม|เจ๋ง|"
    r"สุดยอด|เข้าใจแล้ว|ได้เลย|จ้า|ครับ|ค่ะ|คะ)"
    r"[\s่้๊๋]*(มาก|เลย|นะ|น่ะ|จ้า|ครับ|ค่ะ|คะ|เด้อ|เน้อ|ๆ|!|~|\.)*$",
    re.IGNORECASE)


def is_social_pleasantry(text: str) -> bool:
    """ข้อความนี้เป็นแค่คำทักทาย/ขอบคุณ ไม่ใช่คำถาม → ไม่ต้องดึงความทรงจำ"""
    return bool(_SOCIAL_ONLY_RE.match(text.strip()))


def recall_summaries(mem, user_message: str, top_k: int = 5) -> list:
    """คืน summaries ที่เกี่ยวข้อง — กรองเหลือเฉพาะฝั่งเจ้าของที่ถูกถามแล้ว

    ⚠️ เดิมด่านแรกเช็คว่า "มีคำใน PAST_HINTS ไหม ไม่มีก็คืน [] ทันที" — วัดแล้วพบว่าด่านนี้
    ตัดคำถามที่คนถามบ่อยที่สุดทิ้ง: "ผมชอบอ่านอะไร" / "รอสเต้ชอบทำอะไรยามว่าง" ไม่มีคำว่า
    "จำได้ไหม" หรือ "เคยคุย" เลย จึงไม่ค้นอะไรทั้งที่ข้อมูลอยู่ครบ
    (ระบบเดิมได้ 5/17 บนชุดทดสอบ — ดู tools/bench_memory_read.py)

    แต่จะลบด่านทิ้งเฉยๆ ก็ไม่ได้ — ทดสอบแล้วทำให้ inject มั่ว 3/9 ในคำถามข้อมูลสด
    ("วันนี้อากาศเป็นไง" ไปดึง summary เรื่องอากาศเก่ามาด้วย) ซึ่งเปลือง context ที่วัดแล้ว
    ว่ามีราคาจริง (>3,700c ทำให้โมเดลลืม)

    ต้นเหตุคือด่านเดิม *ใช้เกณฑ์ผิดด้าน* — ถามว่า "มีคำใบ้อดีตไหม" ทั้งที่ควรถามว่า
    "เป็นคำถามข้อมูลสดหรือเปล่า" กลับด้านเป็นกันเฉพาะข้อมูลสดจึงได้ทั้งสองอย่าง:
        "ผมชอบอ่านอะไร"      ไม่มีคำใบ้อดีต แต่ไม่ใช่ข้อมูลสด → ค้น ✅
        "วันนี้อากาศเป็นไง"   มีสัญญาณข้อมูลสดชัด            → ไม่ค้น ✅

    คุมเพิ่มอีก 2 ชั้น:
      1. ต้องมีคำตรงกับ summary จริงถึงจะคืน (คะแนน > 0) — ไม่ inject สุ่ม
      2. กรองฝั่งเจ้าของก่อนคืน — ถามเรื่องผู้ใช้ก็ได้แต่ของผู้ใช้ (จำสลับ 29% → 0%)

    summary แบบเก่าที่ไม่มี tag จะถูกกรองทิ้งเมื่อถามเจาะจงฝั่ง ซึ่งตั้งใจ — ตอบว่าจำไม่ได้
    ดีกว่าเอาของอีกฝั่งมาตอบ
    """
    summaries = mem.get("summaries", [])
    if not summaries:
        return []

    # กันคำถามข้อมูลสด — เว้นแต่มีคำใบ้อดีตชัดเจนปนอยู่ด้วย ("เมื่อวานคุยเรื่องอากาศไหม"
    # = ถามบทสนทนาเก่าจริง ไม่ใช่ถามพยากรณ์) ให้คำใบ้อดีตชนะสัญญาณข้อมูลสดเสมอ
    if (has_live_data_signal(user_message)
            and not any(h in user_message for h in PAST_HINTS)):
        return []

    # แค่ทักทาย/ขอบคุณ ไม่ได้ถามอะไร → ไม่ต้องยัดความทรงจำ (ดู is_social_pleasantry)
    if is_social_pleasantry(user_message):
        return []

    # ตัดคำไทยจริง + ขยายคำพ้อง — split() ตามช่องว่างใช้กับภาษาไทยไม่ได้ (ดู _keywords)
    words = _keywords(user_message)
    whose = guess_owner(user_message)

    texts = [e["text"] if isinstance(e, dict) else e for e in summaries]

    # ⚠️ ทางถอยสำหรับ summary รูปแบบเก่า (ไม่มี tag เจ้าของ)
    # ถ้าไม่มี summary อันไหนมี tag เลย การกรองฝั่งจะตัดทุกอันทิ้ง = ความจำหายทั้งหมด
    # เจอจริงตอนรันเทสเดิม: คำถามที่มีคำว่า "รอสเต้" ปนอยู่ (พบบ่อยมากเพราะผู้ใช้เรียกชื่อบอท)
    # ถูกเดาเป็น whose='me' แล้วกรอง summary เก่าทิ้งหมด — ผู้ใช้ที่มีความจำแบบเก่าอยู่จะ
    # เจอบอทลืมทุกอย่างทันทีที่ deploy ถอยไปโหมด 'any' เมื่อไม่มี tag ให้กรองจริงๆ
    if whose in ("user", "me") and not any(_OWNER_TAG_RE.search(t) for t in texts):
        whose = "any"

    scored = []
    for text in texts:
        parts = split_owner_tags(text)
        # ถามเจาะจงฝั่ง แต่บรรทัดนี้ไม่มีฝั่งนั้น → ข้าม (กันตอบผิดเจ้าของ)
        if whose in ("user", "me") and not parts[whose]:
            continue
        hay = (parts["summary"] + " " + " ".join(parts[whose])
               if whose in ("user", "me") else text)
        score = sum(1 for w in words if w in hay)
        if score > 0:
            scored.append((score, text))

    if not scored:
        # ไม่มี summary ไหนมีคำตรงเลย — อาจเป็นเพราะคำถามไม่มี keyword ให้จับคู่ตั้งแต่แรก
        # ("เราเคยคุยเรื่องอะไรกันบ้าง" ทุกคำเป็น stopword) ถ้าผู้ใช้ขอทบทวนความจำจริง
        # ให้คืนของล่าสุดแทนการเงียบ — ดู recall_recent_summaries
        if wants_broad_recall(user_message):
            return recall_recent_summaries(mem, user_message)
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    # ถามความชอบล้วนๆ → เอาเฉพาะ _pref กันคำตอบแบบ "รอสเต้ชอบ แนะนำร้านให้" (B1)
    kind = "pref" if asks_about_preference(user_message) else None
    return filter_by_owner([t for _, t in scored[:top_k]], whose, kind)


# คำที่บอกว่า "ขอให้ทบทวนความจำ" โดยไม่ได้ระบุหัวข้อ
#
# ต่างจาก PAST_HINTS ตรงที่ PAST_HINTS ใช้ตัดสินว่า *ถามอดีตไหม* ส่วนชุดนี้ใช้ตัดสินว่า
# *ขอให้เล่าว่าเคยคุยอะไรกันบ้าง* ซึ่งเป็นคำถามที่ไม่มีหัวข้อให้จับคู่เลย
_BROAD_RECALL_HINTS = (
    "คุยอะไร", "คุยเรื่องอะไร", "คุยกันบ้าง", "คุยอะไรกัน", "คุยกันเรื่องไหน",
    "เคยคุย", "คุยกันมา", "คุยกันไป", "เล่าเรื่องที่เคย", "ทบทวน",
)


def wants_broad_recall(user_message: str) -> bool:
    """ผู้ใช้ขอให้เล่าว่าเคยคุยอะไรกันบ้าง (ไม่ระบุหัวข้อ) ใช่ไหม"""
    return any(h in user_message for h in _BROAD_RECALL_HINTS)


def recall_recent_summaries(mem, user_message: str, limit: int = 5) -> list:
    """คืน summary ล่าสุดสำหรับ "คำถามทบทวนความจำแบบกว้าง" ที่ไม่มี keyword ให้จับคู่

    ⚠️ บั๊ก production ที่เจอตอนวัดกับความจำจริง (11 ส.ค. 2569):
        "เราเคยคุยเรื่องอะไรกันบ้าง" → _keywords() คืน [] → recall_summaries คืน 0 อัน
        ทั้งที่ผู้ใช้คนนั้นมี summary อยู่ 55 อัน (วัด 4 ใน 8 สำนวนที่คนใช้จริงเจอปัญหานี้)

    ต้นเหตุ: ทุกคำในประโยค (เรา/เคย/คุย/เรื่อง/อะไร/บ้าง) อยู่ใน _STOPWORDS ซึ่งถูกต้อง
    สำหรับ *การให้คะแนน* (คำพวกนี้แมตช์ทุก summary เท่ากันหมด จึงไม่ช่วยจัดอันดับ)
    แต่พอไม่เหลือ keyword เลย เงื่อนไข `score > 0` ก็เป็นจริงไม่ได้ → คืน [] เสมอ

    ทำไมต้องแยกฟังก์ชัน ไม่แก้ในลูปให้คะแนน: การให้ stopword มีคะแนนจะทำให้ทุก summary
    ได้คะแนนเท่ากันหมดในคำถาม *ทุกแบบ* แล้วอันดับจะมั่วไปหมด — ปัญหาเดียวกับที่คอมเมนต์
    _STOPWORDS อธิบายไว้ตั้งแต่ต้น ตรงนี้จึงเปลี่ยน *เกณฑ์จัดอันดับ* เป็น "ใหม่สุดก่อน" แทน

    ⚠️ ไม่ใช้ทางลัด "keyword ว่าง = คืนทุกอัน" เพราะจะ inject ทุกข้อความสั้นๆ ("ค่ะ", "นะ")
    ต้องมีสัญญาณว่าผู้ใช้ *ขอให้ทบทวน* จริงเท่านั้น
    """
    summaries = mem.get("summaries", [])
    if not summaries:
        return []
    whose = guess_owner(user_message)
    texts = [e["text"] if isinstance(e, dict) else e for e in summaries]
    if whose in ("user", "me") and not any(_OWNER_TAG_RE.search(t) for t in texts):
        whose = "any"                      # ทางถอยเดียวกับ recall_summaries
    # ไม่มี keyword ให้จัดอันดับ → ใหม่สุดเกี่ยวข้องที่สุด (summaries เรียงเก่า→ใหม่)
    return filter_by_owner(list(reversed(texts))[:limit], whose)


# จับประโยค "ฉันชื่อ X" / "ผมชื่อ X" / "หนูชื่อ X" ที่บ่งบอกชื่อที่ผู้ใช้อยากให้เรียก
# (ต่างจาก mem["name"] ที่เป็น Discord username — ดู preferred_name)
_SELF_NAME_RE = re.compile(r"^(?:ฉัน|ผม|หนู)ชื่อ(.+?)(?:นะ|น่ะ|ค่ะ|ครับ|จ้ะ|จ๊ะ)?$")


def handle_memory_command(user_id, user_name, text):
    """จัดการคำสั่งเกี่ยวกับความจำโดยตรง (ไม่ต้องเรียกโมเดล)
    คืนค่าข้อความตอบกลับถ้าเป็นคำสั่ง, คืน None ถ้าไม่ใช่"""
    stripped = text.strip()

    # ── สั่งให้จำ: "จำไว้ว่า ..." หรือ "จดไว้ว่า ..."
    for trigger in ("จำไว้ว่า", "จดไว้ว่า", "จำไว้นะว่า"):
        if stripped.startswith(trigger):
            fact = stripped[len(trigger):].strip(" :ว่า")
            if not fact:
                return "หืม... อยากให้จำเรื่องอะไรเหรอคะ ลองพิมพ์ว่า \"จำไว้ว่า ...\" ตามด้วยเรื่องนั้นนะคะ"
            mem = load_memory(user_id)
            if user_name:
                mem["name"] = user_name

            # ถ้า fact เป็นการบอกชื่อที่อยากให้เรียก ("ฉันชื่อ X") เก็บลง preferred_name แยกต่างหาก
            # จาก mem["name"] (Discord username) เด็ดขาด — เจอจริง (stress test): เดิม fact แบบนี้
            # ถูกเก็บปนกับ facts ทั่วไป แล้ว mem["name"] (Discord username) ก็ยังถูกอัปเดตทับทุกครั้ง
            # ที่คุย ทำให้ context มี "ชื่อเรียก: X" กับ "ฉันชื่อ Y" ขัดกันเอง โมเดล (qwen3:8b) สับสน
            # จนเดาชื่อที่สามมั่วๆ ไม่ว่าจะเขียนกฎ prompt ชัดแค่ไหนก็ยังพลาด ต้องแยก preferred_name
            # ให้เป็นค่าเดียวชัดเจน ไม่ปนกับ Discord username ตั้งแต่จุดบันทึกเลย
            name_match = _SELF_NAME_RE.match(fact)
            if name_match:
                mem["preferred_name"] = name_match.group(1).strip()

            added = add_fact(mem, fact)
            save_memory(user_id, mem)
            if added:
                return f"จำไว้แล้วค่ะ — \"{fact}\" จะไม่ลืมนะคะ"
            return f"อันนี้รอสเต้จำไว้อยู่แล้วค่ะ — \"{fact}\""

    # ── สั่งให้ลืมรายตัว: "ลืมเรื่อง ..." หรือ "ลืมว่า ..."
    for trigger in ("ลืมเรื่อง", "ลืมว่า", "ลบเรื่อง"):
        if stripped.startswith(trigger):
            keyword = stripped[len(trigger):].strip(" :ว่า")
            if not keyword:
                return "หืม... อยากให้ลืมเรื่องอะไรเหรอคะ ลองพิมพ์ \"ลืมเรื่อง ...\" ตามด้วยเรื่องนั้นนะคะ"
            mem = load_memory(user_id)
            removed = remove_fact(mem, keyword)
            save_memory(user_id, mem)
            if removed:
                items = ", ".join(f'"{r}"' for r in removed)
                return f"ลืมให้แล้วค่ะ — {items} ไม่อยู่ในหัวรอสเต้แล้วนะคะ"
            return f"หืม... รอสเต้ไม่เจอเรื่องที่มีคำว่า \"{keyword}\" ในความจำเลยค่ะ"

    # ── ถามว่าจำอะไรไว้บ้าง (จับแบบยืดหยุ่น เผื่อมีคำต่อท้าย เช่น "...บ้างละ")
    _s = stripped.replace(" ", "")
    asked_memory = (
        ("จำอะไร" in _s and "บ้าง" in _s)
        or ("จำอะไรได้" in _s)
        or ("รู้อะไรเกี่ยวกับ" in _s and "บ้าง" in _s)
    )
    if asked_memory:
        mem = load_memory(user_id)
        # ไม่แสดง fact ที่ถูก supersede แล้ว — ผู้ใช้ถามว่า "จำอะไรได้บ้าง" ควรได้ยินแต่ค่าปัจจุบัน
        facts = [_fact_text(f) for f in mem.get("facts", []) if not _fact_superseded(f)]
        if not facts:
            return "ตอนนี้รอสเต้ยังไม่ได้จำเรื่องอะไรเป็นพิเศษเลยค่ะ ถ้าอยากให้จำอะไรบอกได้นะคะ"
        lines = "\n".join(f"  • {f}" for f in facts)
        return f"เรื่องที่รอสเต้จำเกี่ยวกับคุณไว้ค่ะ:\n{lines}"

    # ── สั่งให้ลืมทั้งหมด
    if stripped in ("ลืมทุกอย่าง", "ลืมที่จำไว้ทั้งหมด", "ลบความจำ"):
        mem = load_memory(user_id)
        mem["facts"] = []
        save_memory(user_id, mem)
        return "หืม... ล้างกระดานในหัวเรียบร้อยค่ะ จำเรื่องที่สั่งไว้ไม่ได้แล้วนะคะ"

    return None  # ไม่ใช่คำสั่งความจำ
