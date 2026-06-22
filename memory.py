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

MEMORY_DIR = "memory"
os.makedirs(MEMORY_DIR, exist_ok=True)

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
            mem.setdefault("facts", [])
            mem.setdefault("history", [])
            mem.setdefault("summaries", [])
            return mem
        except Exception as e:
            print(f"   ↳ อ่านความจำไม่สำเร็จ: {e}")
    return {"name": "", "facts": [], "history": [], "summaries": []}


def save_memory(user_id, mem):
    """บันทึกความจำของผู้ใช้ลงไฟล์"""
    try:
        with open(_memory_path(user_id), "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   ↳ บันทึกความจำไม่สำเร็จ: {e}")


def add_fact(mem, fact):
    """เพิ่ม fact เข้าความจำ พร้อมกันซ้ำ + คุมเพดาน
    คืน True ถ้าเพิ่มจริง, False ถ้าซ้ำ (ไม่ได้เพิ่ม)"""
    fact = fact.strip()
    if not fact:
        return False
    facts = mem.setdefault("facts", [])
    # กันจำซ้ำ — ถ้ามี fact ที่เหมือนกันเป๊ะอยู่แล้ว ไม่เพิ่ม
    if fact in facts:
        return False
    facts.append(fact)
    # คุมเพดาน — เกิน MAX_FACTS ตัดอันเก่าสุด (ต้นลิสต์) ทิ้ง
    if len(facts) > MAX_FACTS:
        del facts[: len(facts) - MAX_FACTS]
    return True


def remove_fact(mem, keyword):
    """ลบ fact ที่มีคำว่า keyword อยู่ (ลบรายตัว ไม่ต้องล้างหมด)
    คืนรายการ fact ที่ถูกลบ (อาจมากกว่า 1 ถ้า keyword ตรงหลายอัน)"""
    keyword = keyword.strip()
    if not keyword:
        return []
    facts = mem.get("facts", [])
    removed = [f for f in facts if keyword in f]
    mem["facts"] = [f for f in facts if keyword not in f]
    return removed


def recall_facts(mem, user_message):
    """ดึง fact ที่ "เกี่ยวข้อง" กับข้อความปัจจุบันมาใช้ (selective recall)
    - ถ้า facts น้อย (<= MAX_FACTS_IN_CONTEXT) คืนทั้งหมด
    - ถ้าเยอะ ให้คะแนนตามจำนวนคำที่ตรงกับข้อความ แล้วเลือกอันคะแนนสูงสุด
      (อันที่ไม่ตรงเลยก็ยังเก็บบางส่วนไว้ เผื่อเป็นข้อมูลพื้นฐานสำคัญ)"""
    facts = mem.get("facts", [])
    if len(facts) <= MAX_FACTS_IN_CONTEXT:
        return list(facts)

    # แตกข้อความเป็นคำ (กรองคำสั้นเกินทิ้ง)
    words = [w for w in user_message.lower().split() if len(w) >= 2]

    scored = []
    for fact in facts:
        fl = fact.lower()
        score = sum(1 for w in words if w in fl)
        scored.append((score, fact))

    # เรียงตามคะแนน (มากก่อน) — อันที่เกี่ยวข้องขึ้นก่อน
    scored.sort(key=lambda x: x[0], reverse=True)

    # เลือกอันที่มีคะแนน (เกี่ยวข้องจริง) ก่อน
    relevant = [f for s, f in scored if s > 0][:MAX_FACTS_IN_CONTEXT]

    # ถ้ายังไม่เต็มโควต้า เติมด้วย fact ล่าสุด (เผื่อข้อมูลพื้นฐานที่ไม่ได้ตรงคำ)
    if len(relevant) < MAX_FACTS_IN_CONTEXT:
        for fact in reversed(facts):
            if fact not in relevant:
                relevant.append(fact)
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
    """สร้าง prompt สั่งโมเดลสกัดข้อเท็จจริงถาวรเกี่ยวกับผู้ใช้ออกมาเป็น JSON"""
    return (
        "ดึง \"ข้อเท็จจริงถาวรเกี่ยวกับตัวผู้ใช้\" จากข้อความด้านล่าง "
        "เฉพาะหมวดเหล่านี้เท่านั้น: ชื่อ, ที่อยู่/จังหวัด, งานหรือการเรียน, "
        "ความชอบ, ของที่ครอบครอง, เรื่องที่สนใจ, "
        "หัวข้อ/ประเด็นที่ผู้ใช้ชอบคุยหรือกลับมาถามบ่อย\n"
        "กฎ:\n"
        "- เอาเฉพาะข้อมูลที่เป็นความจริงถาวรเกี่ยวกับ \"ตัวผู้ใช้เอง\" เท่านั้น\n"
        "- ห้ามเอา: คำถาม, ความรู้สึกชั่วคราว, เรื่องทั่วไป, เรื่องคนอื่น, สิ่งที่ไม่แน่ใจ\n"
        "- หมวด \"หัวข้อที่ชอบคุย\" ให้เขียนเป็น pattern ถาวร เช่น \"ชอบคุยเรื่องปรัชญา\" "
        "ไม่ใช่เหตุการณ์เฉพาะ เช่น \"ถามเรื่องหนังสือเมื่อกี้\"\n"
        "- เขียนแต่ละข้อสั้นๆ กระชับ เป็นภาษาไทย (เช่น \"ชื่อจูเลีย\", \"อยู่ชุมพร\", \"ชอบคุยเรื่อง sci-fi\")\n"
        "- ถ้าไม่มีข้อมูลที่เข้าเกณฑ์เลย ให้ตอบ []\n"
        "ตอบเป็น JSON array ของสตริงเท่านั้น ห้ามมีคำอธิบายอื่น เช่น [\"ชื่อจูเลีย\",\"อยู่ชุมพร\"]\n\n"
        f"ข้อความ: {user_message}"
    )


def parse_extracted_facts(model_output: str) -> list:
    """แปลงผลที่โมเดลตอบ (ควรเป็น JSON array) เป็น list ของ fact
    ทนทานต่อกรณีโมเดลใส่ข้อความเกินมา — ดึงเฉพาะส่วน [...] ออกมา parse"""
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
    # กรองให้เหลือเฉพาะสตริงสั้นๆ ที่สมเหตุสมผล (กันโมเดลคืนของแปลก)
    out = []
    for it in items:
        if isinstance(it, str):
            it = it.strip()
            if 2 <= len(it) <= 60:        # ยาวเกิน 60 ตัว = น่าจะไม่ใช่ fact สั้นๆ
                out.append(it)
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
    "เมื่อก่อน", "เมื่อวาน", "เมื่อกี้",
    "ก่อนหน้านี้", "ก่อนหน้า",
    "ที่เคยคุย", "ที่เคยพูด", "ที่เคยบอก",
    "เคยคุย", "เคยบอก", "เคยพูด", "เคยถาม",
    "ต้นเดือน", "ปลายเดือน", "กลางเดือน",
    "อาทิตย์ที่แล้ว", "เดือนที่แล้ว", "วันก่อน",
)


def recall_summaries(mem, user_message: str) -> list:
    """คืน summaries ที่เกี่ยวข้อง เฉพาะเมื่อข้อความมีสัญญาณถามถึงอดีต
    ปกติคืน [] เพื่อไม่ inject ทุกครั้ง (ประหยัด context)
    เมื่อถามอดีต: keyword match กับ summaries → คืนสูงสุด 5 อัน เป็น string พร้อม inject"""
    summaries = mem.get("summaries", [])
    if not summaries:
        return []
    if not any(h in user_message for h in PAST_HINTS):
        return []

    words = [w for w in user_message.split() if len(w) >= 2]

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
        facts = mem.get("facts", [])
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
