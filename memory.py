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
    """สร้าง prompt ให้โมเดลสรุปบทสนทนาเป็น 1 บรรทัด — เน้นกัน hallucinate"""
    convo = "\n".join(
        f"{'ผู้ใช้' if m['role'] == 'user' else 'รอสเต้'}: {m.get('content', '')}"
        for m in pairs
    )
    return (
        "สรุปบทสนทนาต่อไปนี้เป็น 1 บรรทัดสั้นๆ ภาษาไทย ว่าคุยเรื่องอะไร\n"
        "กฎเข้มงวด:\n"
        "- เขียนเฉพาะสิ่งที่ปรากฏในบทสนทนาข้างล่างเท่านั้น\n"
        "- ห้ามเติมชื่อหนังสือ/สถานที่/ตัวเลข/รายละเอียดที่ผู้ใช้ไม่ได้พูดถึง\n"
        "- ถ้าไม่แน่ใจว่ามีในบทจริง ไม่ต้องใส่\n"
        "- สั้นที่สุดเท่าที่จะบอกหัวข้อได้ (1 บรรทัด ไม่มีคำอธิบายเพิ่ม)\n"
        "ตอบมาแค่ประโยคสรุปเดียวเท่านั้น ห้ามมีคำนำหรือคำอธิบายเพิ่มเติม:\n\n"
        + convo
    )


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


def recall_summaries(mem, user_message: str) -> list:
    """คืน summaries ที่เกี่ยวข้อง เฉพาะเมื่อข้อความมีสัญญาณถามถึงอดีต
    ปกติคืน [] เพื่อไม่ inject ทุกครั้ง (ประหยัด context)
    เมื่อถามอดีต: keyword match กับ summaries → คืนสูงสุด 5 อัน เป็น string พร้อม inject"""
    summaries = mem.get("summaries", [])
    if not summaries:
        return []
    has_clear_hint = any(h in user_message for h in PAST_HINTS)
    # คำกำกวม ("เมื่อวาน") ถือเป็นสัญญาณถามอดีตด้วย เว้นแต่ประโยคเดียวกันมีคำถามข้อมูลสด
    # (อากาศ/น้ำมัน/ไฟดับ) ปนอยู่ — กรณีนั้นน่าจะหมายถึง "เมื่อวานเทียบกับวันนี้" ไม่ใช่ถามบทสนทนาเก่า
    has_ambiguous_hint = (
        any(h in user_message for h in AMBIGUOUS_PAST_HINTS)
        and not any(s in user_message for s in _LIVE_DATA_SIGNALS)
    )
    if not (has_clear_hint or has_ambiguous_hint):
        return []

    # ตัดคำไทยจริง + ขยายคำพ้อง — split() ตามช่องว่างใช้กับภาษาไทยไม่ได้ (ดู _keywords)
    words = _keywords(user_message)

    scored = []
    for entry in summaries:
        text = entry["text"] if isinstance(entry, dict) else entry
        score = sum(1 for w in words if w in text)
        if score > 0:
            scored.append((score, text))

    # ถ้าถามอดีตแต่ไม่มีคำตรงกับ summary ไหน คืน [] (ไม่ inject สุ่ม)
    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:5]]


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
