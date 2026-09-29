# ============================================================
#  💞 intimacy.py — ค่าความสนิทสนม (ร่างตาม docs/roste-plan.md)
#
#  คุมแค่ "สำเนียง" ที่รอสเต้ใช้คุย ไม่คุมข้อมูล/สิทธิ์ tool ใดๆ ทั้งสิ้น (ข้อห้ามตรงๆ
#  ในแผน) ไม่ให้ LLM ประเมิน "ลึกแค่ไหน" ตรงๆ เพราะจะกลายเป็นการวัดเนื้อหาบทสนทนา —
#  แทนที่ด้วย fact hierarchy ใน memory.py (roste facts + mentioned_by) ที่มีอยู่แล้ว
#  เป็น proxy ของความลึกโดยไม่ต้อง compute เพิ่ม (ดู memory.fact_depth/roste_fact_credit)
#
#  ที่มาของโมเดล 4 ระดับ (คุยออกแบบร่วมกับเจ้าของ repo ก่อนเขียน — ดูสรุปงานวิจัย
#  ในบทสนทนา Claude Code วันที่ออกแบบไฟล์นี้):
#    - Zajonc (1968) mere exposure effect + Bornstein (1989, meta-analysis 208 งาน)
#      + Girme, Overall & Simpson (2022) — ยืนยันว่าความสัมพันธ์ระหว่างความถี่
#      ปฏิสัมพันธ์กับความสนิทสนมเป็น non-linear (inverted-U / diminishing returns)
#      ไม่ใช่เส้นตรง → เหตุผลที่แบ่งเป็นระดับ (tier) ไม่ใช่ตัวเลขต่อเนื่อง
#    - Altman & Taylor, Social Penetration Theory — intimacy = breadth × depth
#      (ไม่ใช่แค่ breadth หรือแค่ depth เดี่ยวๆ) ความสัมพันธ์พัฒนาเป็น stage
#    - Knapp's Relational Development Model — ให้ชื่อ+นิยามของ 4 ใน 5 stage แรก
#      (ตัด "Bonding" ทิ้งเพราะเป็น public commitment ซึ่งไม่มีทางเกิดกับ AI)
#      "Intensifying" ของ Knapp นิยามไว้ว่ามี "verbal shortcuts" เกิดขึ้น — ตรงกับ
#      นิยามของ "สำเนียง" ที่แผนต้องการเป๊ะ (ใช้ชื่อเล่น/มุกที่เคยคุยได้ ไม่ต้อง
#      อธิบายบริบทซ้ำ) ไม่ใช่แค่ "พูดเป็นกันเองมากขึ้น" ลอยๆ
#
#  ── score = frequency × depth (ไม่ใช่ max()) ──────────────────────────────────
#  เหตุผลที่ใช้ผลคูณ ไม่ใช่ max(): คุยกับเจ้าของ repo แล้วพบว่า max() มีช่องโหว่ —
#  ถ้า breadth/depth "ลาก" tier ขึ้นได้อิสระ จะเกิดเคส "คุยลึก 2 ชม. วันเดียว ได้
#  tier 4 ทันที" ทั้งที่ frequency ยังต่ำมาก (Bornstein/Zajonc ต้องการความถี่ที่
#  กระจายข้ามเวลา ไม่ใช่ปริมาณมากในครั้งเดียว) การคูณทำให้ตัวใดตัวหนึ่งต่ำ ผลลัพธ์
#  ก็ต่ำตาม ตรงกับนิยาม intimacy = breadth × depth ของ SPT ตรงๆ ด้วย
#
#  threshold (0.00-0.02/0.02-0.15/0.15-0.35/0.35+) กำหนดเองแบบสมเหตุสมผล ไม่มี
#  paper รองรับตรงๆ (ไม่มีงานวิจัยไหนให้ threshold ของสูตรคูณแบบนี้) — คัดเลือกจาก
#  การ test กับ 3 เคสที่คุยกันไว้:
#    1. คุยลึก 2 ชม. วันเดียว (freq=1/60≈0.017, depth=1.0) → score=0.017 → tier 1
#    2. คุย 90 วันติดแต่ตื้นตลอด (freq=1.0, depth≈0.1) → score=0.1 → tier 2
#       (ไม่ควรเกิน 2 — "คุยกันนานแต่ตื้น ไม่ควรเกิน tier 2")
#    3. คุย 60 วัน + depth กลางๆ (freq≈1.0, depth≈0.5) → score=0.5 → tier 4
#       (ใกล้เคียงพฤติกรรมเดิมที่ใช้ days เพียวๆ)
#
#  depth_component = 0 เมื่อ user คนนั้นไม่เคยมี roste fact ที่เกี่ยวข้องเลย (ตัดสินใจ
#  ไว้ตรงๆ: "ไม่มีข้อมูล = ไม่เปิดเผย") — ผลคือ deploy สูตรนี้ครั้งแรก user เก่าทุกคน
#  จะร่วงกลับ tier 1 หมด (ยอมรับผลกระทบนี้แล้ว ไม่ทำ migration พิเศษ เพราะยังไม่เคยมี
#  roste facts มาก่อนในระบบเดิมเลย ไม่มีอะไรให้ migrate จริงๆ)
#
#  first-mover credit (memory.roste_fact_credit): "คนที่ทำให้ fact นั้นเกิดขึ้นเป็น
#  คนแรกต่างหากที่สำคัญ" ไม่ใช่หารแต้มเท่ากันทุกคน (จะทำให้คนแรกเสียเปรียบ) และไม่ใช่
#  ทุกคนได้เต็ม 100% เท่ากันหมด (จะทำให้ "first-mover" ไม่มีความหมายอะไรเลย)
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

# score = frequency_component * depth_component → tier (ดู comment บนสุดของไฟล์
# เรื่องที่มาของ threshold แต่ละช่วง — test กับ 3 เคสที่คุยออกแบบไว้แล้ว)
_SCORE_THRESHOLDS = (
    (0.02, 1),   # initiating
    (0.15, 2),   # experimenting
    (0.35, 3),   # intensifying
)
_MAX_TIER = 4  # เกิน threshold บนสุด → integrating

# ความลึกสูงสุดที่ถือว่า "เต็มสเกล" (fact_depth หน่วยเป็นจำนวนชั้น parent) — ตัวอย่าง
# ที่คุยกันไว้ (หนังสือ→นิยาย→นิยายไซไฟ→ตัวละคร) ลึกสุดจริงไม่เกิน 3-4 ชั้น ลึกกว่านี้
# ก็ยัง cap ที่ 1.0 ไม่ใช่ยิ่งลึกยิ่งได้คะแนนไม่จำกัด
MAX_MEANINGFUL_DEPTH = 3

# credit ขั้นต่ำที่ user คนหนึ่งต้องมีกับ roste fact ถึงจะถูกนับเข้า depth_component
# (>0 เท่านั้น — fact ที่ user คนนั้นไม่เคยพูดถึงเลยได้ credit 0.0 จาก
# memory.roste_fact_credit อยู่แล้ว กรองออกตรงนี้กันหารด้วย 0/ค่าเฉลี่ยเพี้ยน)

# คำสั่งโทน 1 บรรทัดต่อ tier — ห้ามส่งตัวเลข tier เข้า prompt ตรงๆ (สเปกในแผน) แปลง
# เป็นประโยคคำสั่งโทนแทนเสมอ วางในส่วนคงที่ของ system prompt (รักษา KV cache)
TIER_TONE = {
    1: "คุยกับคนที่เพิ่งรู้จักกัน ใช้คำสุภาพเต็มรูป อธิบายบริบทให้ครบทุกครั้ง",
    2: "คุยกับคนที่เริ่มคุ้นเคยกันแล้ว ผ่อนคลายขึ้นได้บ้างแต่ยังสุภาพอยู่",
    3: "คุยกับเพื่อนสนิท ใช้มุก/คำย่อที่เคยคุยกันมาได้เลย ไม่ต้องอธิบายบริบทซ้ำ",
    4: "คุยกับคนสนิทมาก เป็นกันเองเต็มที่ พูดสั้นตรงประเด็นได้ ไม่ต้องทางการ",
}


def _tier_from_score(score: float) -> int:
    for threshold, tier in _SCORE_THRESHOLDS:
        if score <= threshold:
            return tier
    return _MAX_TIER


def _frequency_component(mem: dict, *, today: date) -> float:
    """0.0-1.0 — normalize จากจำนวน "วันคุยจริง" ใน WINDOW_DAYS (ของเดิมก่อนมีสูตร
    คูณ เคยเป็น output ตรงๆ ของ tier ทั้งก้อน ตอนนี้เป็นแค่ตัวคูณตัวหนึ่ง)"""
    state = mem.get("intimacy")
    if not state:
        return 0.0
    cutoff = today - timedelta(days=WINDOW_DAYS)
    n_days = sum(
        1 for d, c in state.get("daily_counts", {}).items()
        if c >= MIN_MESSAGES_PER_DAY and cutoff <= date.fromisoformat(d) <= today
    )
    return min(n_days / WINDOW_DAYS, 1.0)


def _depth_component(roste_mem: dict, user_id) -> float:
    """0.0-1.0 — เฉลี่ยถ่วงน้ำหนักของ fact_depth ทุก roste fact ที่ user_id เคยพูดถึง
    จริง (credit > 0 จาก memory.roste_fact_credit) normalize ด้วย MAX_MEANINGFUL_DEPTH

    ไม่มี roste fact ที่เกี่ยวข้องกับ user คนนี้เลย → 0.0 ("ไม่มีข้อมูล = ไม่เปิดเผย"
    — ตัดสินใจไว้ตรงๆ ตอนออกแบบ ดู comment บนสุดของไฟล์)"""
    facts = roste_mem.get("facts", [])
    weighted = []
    for f in facts:
        if not isinstance(f, dict) or f.get("superseded"):
            continue
        credit = memory.roste_fact_credit(f, user_id)
        if credit <= 0:
            continue
        depth = memory.fact_depth(roste_mem, f["id"])
        weighted.append(depth * credit)
    if not weighted:
        return 0.0
    avg = sum(weighted) / len(weighted)
    return min(avg / MAX_MEANINGFUL_DEPTH, 1.0)


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


def get_tier(mem: dict, roste_mem: dict, user_id, *, today: date | None = None) -> int:
    """คืน tier ปัจจุบัน (1-4) — score = frequency_component * depth_component
    (ดู comment บนสุดของไฟล์เรื่องที่มาของสูตร) + บังคับพื้นจาก peak_tier

    mem: ความจำของ user คนเดียว (มี intimacy.daily_counts/peak_tier)
    roste_mem: ความจำของรอสเต้เอง (memory.load_roste_memory()) — ใช้คำนวณ depth
    user_id: ของ user คนเดียวกับ mem — ใช้หา credit ใน roste facts

    เรียกได้ทุกครั้งที่ต้องใช้ (ไม่แพง — นับ dict ใน window + ไล่ fact list ล้วนๆ
    ไม่มี I/O เพิ่ม) ไม่ cache เพราะ mem/roste_mem เปลี่ยนได้ทุกข้อความ
    """
    today = today or datetime.now().date()
    state = mem.setdefault("intimacy", {"daily_counts": {}, "peak_tier": 1})

    freq = _frequency_component(mem, today=today)
    depth = _depth_component(roste_mem, user_id)
    score = freq * depth
    computed = _tier_from_score(score)

    peak = state.get("peak_tier", 1)
    if computed > peak:
        state["peak_tier"] = computed   # สร้าง peak ใหม่ — เรียก save_memory เองที่ผู้เรียก
        return computed

    # มีพื้น: ลดได้สูงสุด 1 tier จาก peak (roste-plan.md — ห้าม reset กลับ tier 1)
    return max(computed, peak - 1)


def tone_instruction(mem: dict, roste_mem: dict, user_id, *, today: date | None = None) -> str:
    """1 บรรทัดพร้อมใส่ system prompt ตรงๆ — ผู้เรียกต้องเช็คคำสั่งโทนตรงจากผู้ใช้
    ก่อนเสมอ (เช่น "พูดสุภาพหน่อย") แล้วใช้ค่านั้นแทนถ้ามี — คำสั่งผู้ใช้ชนะค่าที่
    คำนวณเสมอ (สเปกในแผน) ฟังก์ชันนี้ไม่รู้จักคำสั่ง override เอง ผู้เรียกต้อง
    จัดการ precedence เอง
    """
    return TIER_TONE[get_tier(mem, roste_mem, user_id, today=today)]
