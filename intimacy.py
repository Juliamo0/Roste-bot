# ============================================================
#  💞 intimacy.py — ค่าความสนิทสนม (ร่างตาม docs/roste-plan.md)
#
#  คุมแค่ "สำเนียง" ที่รอสเต้ใช้คุย ไม่คุมข้อมูล/สิทธิ์ tool ใดๆ ทั้งสิ้น (ข้อห้ามตรงๆ
#  ในแผน) — input เดียวที่ใช้คือ "วันที่คุยจริง" (ผ่านเกณฑ์กันสแปม) ไม่วัดเนื้อหา/
#  ความลึกของบทสนทนาเลย แม้จะมีงานวิจัยรองรับเรื่อง partner responsiveness
#  (Manne et al. 2004, Laurenceau et al. 1998) ก็ตาม — ตั้งใจไม่ทำ เพราะ:
#    1. ต้องมี pipeline วิเคราะห์เนื้อหาเพิ่ม ชนเพดาน tool schema ~3,700 ตัวอักษร
#       ที่วัดไว้แล้วว่าเป็นจุดพัง (ดู README หัวข้อ "ระบบเลือกเครื่องมือ")
#    2. ขัดกับกฎ "ค่าความสนิทคุมแค่สำเนียง ไม่ใช่ข้อมูล" ตรงๆ
#
#  ที่มาของโมเดล 4 ระดับ (คุยออกแบบร่วมกับเจ้าของ repo ก่อนเขียน — ดูสรุปงานวิจัย
#  ในบทสนทนา Claude Code วันที่ออกแบบไฟล์นี้):
#    - Zajonc (1968) mere exposure effect + Bornstein (1989, meta-analysis 208 งาน)
#      + Girme, Overall & Simpson (2022) — ยืนยันว่าความสัมพันธ์ระหว่างความถี่
#      ปฏิสัมพันธ์กับความสนิทสนมเป็น non-linear (inverted-U / diminishing returns)
#      ไม่ใช่เส้นตรง → เหตุผลที่แบ่งเป็นระดับ (tier) ไม่ใช่ตัวเลขต่อเนื่อง
#    - Altman & Taylor, Social Penetration Theory — ความสัมพันธ์พัฒนาเป็น stage
#    - Knapp's Relational Development Model — ให้ชื่อ+นิยามของ 4 ใน 5 stage แรก
#      (ตัด "Bonding" ทิ้งเพราะเป็น public commitment ซึ่งไม่มีทางเกิดกับ AI)
#      "Intensifying" ของ Knapp นิยามไว้ว่ามี "verbal shortcuts" เกิดขึ้น — ตรงกับ
#      นิยามของ "สำเนียง" ที่แผนต้องการเป๊ะ (ใช้ชื่อเล่น/มุกที่เคยคุยได้ ไม่ต้อง
#      อธิบายบริบทซ้ำ) ไม่ใช่แค่ "พูดเป็นกันเองมากขึ้น" ลอยๆ
#
#  decay: ลดได้สูงสุด 1 tier จาก peak_tier ไม่ reset กลับ tier 1 (ตาม roste-plan.md
#  ตรงๆ: "หายไปเดือนนึงกลับมาแล้วทำเป็นไม่รู้จัก แย่กว่าไม่มีระบบนี้") สอดคล้องกับ
#  Knapp's "coming apart" stages ที่ก็เป็นกระบวนการถอยทีละขั้น ไม่ใช่ reset ทันที
# ============================================================
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import memory

logger = logging.getLogger("roste.intimacy")

# เกณฑ์ "วันคุยจริง" — กันคำสั่งเดียว/สแปมได้เครดิตวันฟรี (เจตนาเดียวกับ rate limiting
# ที่มีอยู่แล้วใน bot.py) ต้องมีข้อความจากผู้ใช้อย่างน้อยเท่านี้ในวันนั้นถึงนับ
MIN_MESSAGES_PER_DAY = 2

# ขนาด window ที่ใช้คำนวณ tier ปัจจุบัน (วัน) — ตัด interaction_days ที่เก่ากว่านี้ทิ้ง
# กันไฟล์โตไม่จำกัด (เจตนาเดียวกับเพดาน MAX_FACTS/MAX_SUMMARIES ใน memory.py)
WINDOW_DAYS = 60

# ชื่อระดับตาม Knapp's Relational Development Model (ตัด Bonding ออก — ดู comment บนสุด)
TIER_NAMES = {
    1: "initiating",
    2: "experimenting",
    3: "intensifying",
    4: "integrating",
}

# ช่วงวัน (นับจากจำนวน "วันคุยจริง" แยกกันใน WINDOW_DAYS) → tier
# อิง mere exposure curve (Zajonc 1968 / Bornstein 1989 meta-analysis) — ช่วงแรกชันสุด
# แล้วค่อยๆ แบนลง ไม่ใช่ช่วงเท่ากันทุกขั้น
_TIER_THRESHOLDS = (
    (2, 1),    # 0-2 วัน   → initiating
    (14, 2),   # 3-14 วัน  → experimenting
    (60, 3),   # 15-60 วัน → intensifying
)
_MAX_TIER = 4  # เกิน threshold บนสุด → integrating

# คำสั่งโทน 1 บรรทัดต่อ tier — ห้ามส่งตัวเลข tier เข้า prompt ตรงๆ (สเปกในแผน) แปลง
# เป็นประโยคคำสั่งโทนแทนเสมอ วางในส่วนคงที่ของ system prompt (รักษา KV cache)
TIER_TONE = {
    1: "คุยกับคนที่เพิ่งรู้จักกัน ใช้คำสุภาพเต็มรูป อธิบายบริบทให้ครบทุกครั้ง",
    2: "คุยกับคนที่เริ่มคุ้นเคยกันแล้ว ผ่อนคลายขึ้นได้บ้างแต่ยังสุภาพอยู่",
    3: "คุยกับเพื่อนสนิท ใช้มุก/คำย่อที่เคยคุยกันมาได้เลย ไม่ต้องอธิบายบริบทซ้ำ",
    4: "คุยกับคนสนิทมาก เป็นกันเองเต็มที่ พูดสั้นตรงประเด็นได้ ไม่ต้องทางการ",
}


def _tier_from_day_count(n_days: int) -> int:
    for threshold, tier in _TIER_THRESHOLDS:
        if n_days <= threshold:
            return tier
    return _MAX_TIER


def record_interaction(mem: dict, *, message_count_today: int, today: date | None = None) -> None:
    """เรียกครั้งเดียวต่อข้อความ (หรือรวมเรียกท้ายๆ ก็ได้) — บันทึกว่าวันนี้คุยกี่ข้อความ
    แล้วเท่านั้น ยังไม่ตัดสินว่า "นับเป็นวันคุยจริง" (นับตอน get_tier() แทน เพื่อให้
    ข้อความสุดท้ายของวันก็ยังทำให้วันนั้นนับได้ ไม่ต้องรอ flush/สิ้นวัน)

    mem: dict ความจำของ user คนเดียว (จาก memory.load_memory) — แก้ตรงนี้แล้วต้อง
    เรียก memory.save_memory ต่อเอง (ไฟล์นี้ไม่ persist เอง เพื่อไม่ผูกกับ I/O ของ
    memory.py โดยตรง — เรียกจาก bot.py/chat.py ตรงจุดที่มี mem อยู่แล้วในมือ)
    """
    today = today or datetime.now().date()
    state = mem.setdefault("intimacy", {"daily_counts": {}, "peak_tier": 1})
    key = today.isoformat()
    state["daily_counts"][key] = state["daily_counts"].get(key, 0) + 1

    # ตัด window เก่าทิ้งกัน daily_counts โตไม่จำกัด — ระยะ 2 เท่าของ WINDOW_DAYS กัน
    # ขอบ window เลื่อนแล้ววันที่เพิ่งพ้น window ไปหมาดๆ หายไปก่อนได้ใช้คำนวณ peak
    cutoff = (today - timedelta(days=WINDOW_DAYS * 2)).isoformat()
    state["daily_counts"] = {d: c for d, c in state["daily_counts"].items() if d >= cutoff}


def get_tier(mem: dict, *, today: date | None = None) -> int:
    """คืน tier ปัจจุบัน (1-4) — คำนวณจาก daily_counts ใน window + บังคับพื้นจาก peak_tier

    เรียกได้ทุกครั้งที่ต้องใช้ (ไม่แพง — นับ dict ใน window ล้วนๆ ไม่มี I/O) ไม่ cache
    เพราะ mem เปลี่ยนได้ทุกข้อความ cache ไว้จะเสี่ยง stale
    """
    today = today or datetime.now().date()
    state = mem.get("intimacy")
    if not state:
        return 1

    cutoff = today - timedelta(days=WINDOW_DAYS)
    n_days = sum(
        1 for d, c in state.get("daily_counts", {}).items()
        if c >= MIN_MESSAGES_PER_DAY and cutoff <= date.fromisoformat(d) <= today
    )
    computed = _tier_from_day_count(n_days)

    peak = state.get("peak_tier", 1)
    if computed > peak:
        state["peak_tier"] = computed   # สร้าง peak ใหม่ — เรียก save_memory เองที่ผู้เรียก
        return computed

    # มีพื้น: ลดได้สูงสุด 1 tier จาก peak (roste-plan.md — ห้าม reset กลับ tier 1)
    return max(computed, peak - 1)


# ── breadth signal (เสริม ไม่ใช่ input หลัก) ───────────────────────────────────
#
# Social Penetration Theory นิยาม intimacy = breadth (จำนวนหัวข้อ) × depth (ความลึก
# ของแต่ละหัวข้อ) — tier หลักด้านบนวัดแค่ "ความถี่การคุย" (proxy คร่าวๆ ของภาพรวม)
# ไม่ได้แตะ breadth/depth เลย
#
# ทำไมไม่ให้ LLM ประเมิน "ลึกแค่ไหน" ตรงๆ: จะกลายเป็นการวัดเนื้อหาบทสนทนา ขัดกับ
# ข้อห้ามในแผนที่ว่า "ค่าความสนิทคุมแค่สำเนียง ไม่ใช่ข้อมูล" ตรงๆ (ต้องมี pipeline
# วิเคราะห์ความหมายเพิ่ม ไม่ใช่แค่กันสแปมด้วย timestamp เหมือน tier หลัก)
#
# แทนที่ด้วย breadth proxy ที่ไม่ต้อง compute เพิ่มเลย: นับจำนวน me_pref/me_fact
# ที่ไม่ซ้ำกันซึ่ง auto-remember (memory.build_summary_prompt) สกัดไว้แล้วต่อ user
# คนนี้อยู่แล้ว — เรื่องที่รอสเต้ "เผยตัวตน" ให้ user คนนี้ฟังหลายเรื่อง มากกว่า user
# อื่น เป็นสัญญาณทางอ้อมว่าบทสนทนากับคนนี้ลึกกว่า ไม่ใช่การให้ LLM ตัดสินคะแนนเอง
#
# ⚠️ เนื้อหา me_pref/me_fact มาจาก persona.py (SYSTEM_PROMPT+few-shot) ที่กำหนด
# บุคลิกรอสเต้ไว้แล้ว ระบบสรุปแค่ "จับสิ่งที่รอสเต้พูดไปจริงในบทนั้น" มาเก็บ — ไม่ได้
# สร้างความชอบ/lore ใหม่ขึ้นมาลอยๆ (ดู memory.py build_summary_prompt docstring)
#
# ⚠️ เป็นแค่สัญญาณเสริม ไม่ใช้เปลี่ยน tier ที่คำนวณจาก get_tier() — Bornstein/Zajonc
# ให้หลักฐานเรื่อง "ความถี่" หนักแน่นกว่ามาก breadth signal นี้ยังไม่มีงานวิจัยรองรับ
# โดยตรงว่าควรถ่วงน้ำหนักเท่าไหร่ จึงเก็บไว้แค่เป็นตัวเลขให้ debug/ดูเฉยๆ ก่อน
def breadth_count(mem: dict) -> int:
    """จำนวนเรื่อง (me_pref/me_fact ไม่ซ้ำกัน) ที่รอสเต้เคยเผยให้ user คนนี้ฟัง
    สะสมจาก summaries ที่มีอยู่แล้ว — ไม่ต้อง parse/คำนวณอะไรเพิ่มนอกจากนับ"""
    seen: set[str] = set()
    for entry in mem.get("summaries", []):
        text = entry["text"] if isinstance(entry, dict) else entry
        parsed = memory.split_owner_tags(text)
        seen.update(parsed.get("me_pref", []))
        seen.update(parsed.get("me_fact", []))
    return len(seen)


def tone_instruction(mem: dict, *, today: date | None = None) -> str:
    """1 บรรทัดพร้อมใส่ system prompt ตรงๆ — ผู้เรียกต้องเช็คคำสั่งโทนตรงจากผู้ใช้
    ก่อนเสมอ (เช่น "พูดสุภาพหน่อย") แล้วใช้ค่านั้นแทนถ้ามี — คำสั่งผู้ใช้ชนะค่าที่
    คำนวณเสมอ (สเปกในแผน) ฟังก์ชันนี้ไม่รู้จักคำสั่ง override เอง ผู้เรียกต้อง
    จัดการ precedence เอง
    """
    return TIER_TONE[get_tier(mem, today=today)]
