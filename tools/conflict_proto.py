"""Phase 1: prototype ของวิธีแก้ความขัดแย้ง 5 แบบ — ยังไม่แตะ production

ทุกวิธีรับ (summaries, question) แล้วคืน list ของบรรทัดที่จะส่งเข้า context
เหมือน memory.recall_summaries เป๊ะ เพื่อให้ bench เทียบกันได้ตรงๆ

    M0  เกณฑ์คะแนนขั้นต่ำ    — ไม่แก้ความขัดแย้งเลย แค่ตัด noise (เจอใน Phase 0: 46%)
    M1  baseline             — recall_summaries ปัจจุบัน (append-only)
    M2  recency-wins         — เจอหลายอันชนกัน เอาอันใหม่สุด
    M3  deterministic        — จับคู่ key แล้ว supersede ของเก่า (ADD-only, soft)
    M4  LLM ตัดสินตอนเขียน   — ADD/UPDATE/NOOP แบบ mem0 รุ่นเดิม

⚠️ M3/M4 ทำงานที่ **write path** (ตอนเก็บ summary) ไม่ใช่ตอนอ่าน — prototype จึงจำลอง
   ด้วยการ "ประมวลผลกอง summary ล่วงหน้า" แล้วค่อยให้ recall ทำงานบนกองที่ประมวลผลแล้ว
   ซึ่งให้ผลเท่ากับการทำจริงตอนเขียน แต่ทดสอบง่ายกว่ามาก

อ้างอิงงานวิจัยที่ทำให้ออกแบบแบบนี้:
  - arXiv 2606.01435 — deterministic max(serial) ชนะ LLM judgment 78.0% vs 67.2%
    และ failure mode "prior-override" ตรงกับ MEMORY_EXPERIMENTS §7 ของโปรเจกต์นี้
  - mem0 — ถอยจาก UPDATE/DELETE กลับไป ADD-only ได้ +20.2 บน LoCoMo
    → M3 จึงเป็น soft supersede (ไม่ลบจริง) เหมือน memory.add_fact ที่มีอยู่แล้ว
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import memory  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
#  ส่วนกลาง — ใช้ซ้ำจาก memory.py ให้มากที่สุด (ไม่เขียนตรรกะซ้ำ)
# ══════════════════════════════════════════════════════════════════════════════


def _score_and_filter(summaries: list, question: str, min_score: int = 1,
                      top_k: int = 5) -> list:
    """คัดลอกตรรกะ memory.recall_summaries มาให้ปรับ min_score ได้

    ⚠️ ต้องคัดลอกเพราะ recall_summaries ฝัง `score > 0` กับ `[:5]` ไว้ตายตัว
       (memory.py:594,601) ถ้าแก้ที่ต้นทางจะกระทบ production ระหว่างยังไม่ตัดสินใจ
       ส่วนที่เหลือ (gate, guess_owner, split_owner_tags, filter_by_owner) เรียกของจริง
    """
    if not summaries:
        return []
    if (any(s in question for s in memory._LIVE_DATA_SIGNALS)
            and not any(h in question for h in memory.PAST_HINTS)):
        return []

    words = memory._keywords(question)
    whose = memory.guess_owner(question)
    texts = [e["text"] if isinstance(e, dict) else e for e in summaries]

    if whose in ("user", "me") and not any(memory._OWNER_TAG_RE.search(t) for t in texts):
        whose = "any"

    scored = []
    for text in texts:
        parts = memory.split_owner_tags(text)
        if whose in ("user", "me") and not parts[whose]:
            continue
        hay = (parts["summary"] + " " + " ".join(parts[whose])
               if whose in ("user", "me") else text)
        score = sum(1 for w in words if w in hay)
        if score >= min_score:
            scored.append((score, text))

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    return memory.filter_by_owner([t for _, t in scored[:top_k]], whose)


def _date_of(entry) -> str:
    """คืนวันที่ของ summary — ใช้เรียงว่าอันไหนใหม่กว่า (ISO เรียงแบบ string ได้เลย)"""
    return entry.get("date", "") if isinstance(entry, dict) else ""


# ══════════════════════════════════════════════════════════════════════════════
#  M0 — เกณฑ์คะแนนขั้นต่ำ (ไม่แตะความขัดแย้งเลย)
# ══════════════════════════════════════════════════════════════════════════════

def m0_min_score(summaries: list, question: str, min_score: int = 2) -> list:
    """ตัด summary ที่ตรงกับคำถามแค่คำเดียวทิ้ง

    Phase 0 วัดได้ว่า 46% ของบรรทัดที่ส่งเข้า context ไม่เกี่ยวกับคำถามเลย เพราะ
    memory.py:594 ใช้ `score > 0` — คำร่วมคำเดียวอย่าง "ชอบ" ก็ผ่านแล้ว

    วิธีนี้ไม่ได้แก้ความขัดแย้ง แต่ใส่ไว้เทียบเพราะ: ถ้าตัด noise แล้ว dynamic ดีขึ้นเอง
    (เพราะ summary ค่าเก่าที่ติดมาแบบ noise หายไป) แปลว่างานส่วนใหญ่จบด้วยการแก้บรรทัดเดียว
    """
    return _score_and_filter(summaries, question, min_score=min_score)


# ══════════════════════════════════════════════════════════════════════════════
#  M1 — baseline (ระบบปัจจุบัน)
# ══════════════════════════════════════════════════════════════════════════════

def m1_baseline(summaries: list, question: str) -> list:
    """เรียก memory.recall_summaries ตัวจริง — ไม่จำลอง"""
    return memory.recall_summaries({"summaries": summaries}, question)


# ══════════════════════════════════════════════════════════════════════════════
#  M2 — recency wins ตอน recall
# ══════════════════════════════════════════════════════════════════════════════

# คำที่บอกว่าผู้ใช้ถามถึง *อดีต* โดยเจตนา — ห้ามตัดของเก่าทิ้งในเคสแบบนี้
#
# ⚠️ จุดตายของ max() ที่เปเปอร์ 2606.01435 ระบุไว้: มันแก้ได้เฉพาะคำถาม "ตอนนี้ X คืออะไร"
#    ถ้าไม่มี gate นี้ M2/M3 จะทำชุด historical พังทันที ซึ่งจะทำให้รอสเต้ตอบไม่ได้ว่า
#    "เมื่อก่อนคุณชอบอะไร" — ความสามารถที่บอทคู่หูต้องมี (เหตุผลเดียวกับที่ mem0 ถอยไป ADD-only)
_HISTORY_INTENT = (
    "เมื่อก่อน", "ก่อนหน้านี้", "ก่อนหน้า", "แต่ก่อน", "เคยบอก", "เคยชอบ",
    "เปลี่ยนไป", "เปลี่ยนแปลง", "เมื่อไหร่", "ยังไงบ้าง", "เคย",
)


def wants_history(question: str) -> bool:
    """คำถามนี้ถามถึงอดีตโดยเจตนาไหม — ถ้าใช่ ห้ามยุบของเก่าทิ้ง"""
    return any(h in question for h in _HISTORY_INTENT)


def m2_recency_wins(summaries: list, question: str, min_score: int = 1) -> list:
    """ดึงตามปกติ แล้วถ้ามีคู่ขัดแย้ง เก็บเฉพาะอันใหม่สุด

    "ขัดแย้ง" นิยามแบบหลวมที่สุด: บรรทัดที่ token ทับกันเกินเกณฑ์ = เรื่องเดียวกัน
    เอาอันที่ date ใหม่กว่า (ถ้าเทียบวันไม่ได้ ถือว่าไม่ขัดแย้ง — fail-safe)
    """
    if wants_history(question):
        return _score_and_filter(summaries, question, min_score=min_score)

    got = _score_and_filter(summaries, question, min_score=min_score)
    if len(got) < 2:
        return got

    # map บรรทัดที่ถูก rewrite โดย filter_by_owner กลับไปหา entry ต้นทาง เพื่อดูวันที่
    # (filter_by_owner เปลี่ยนรูปข้อความ จึงเทียบตรงๆ ไม่ได้ ต้องจับคู่ด้วย substring)
    def find_date(line: str) -> str:
        head = line.split("—")[0].strip()
        for e in summaries:
            text = e["text"] if isinstance(e, dict) else e
            if head and head in text:
                return _date_of(e)
        return ""

    keep = []
    for line in got:
        d = find_date(line)
        dup_idx = None
        for i, (kline, kd) in enumerate(keep):
            if _same_topic(kline, line):
                dup_idx = i
                break
        if dup_idx is None:
            keep.append((line, d))
        elif d > keep[dup_idx][1]:
            keep[dup_idx] = (line, d)   # อันใหม่กว่าชนะ
    return [ln for ln, _ in keep]


# จำนวน token ที่ต้องทับกันถึงจะนับว่า "เรื่องเดียวกัน"
#
# ⚠️ นี่คือตัวแปรที่ Phase 0 ระบุว่าเป็นคำถามเปิด: summary ไม่มี category เหมือน facts
#    จึงไม่มี key ให้เทียบตรงๆ ต้องเดาจากคำที่ใช้ร่วมกัน
#    ตั้งไว้ 2 เพราะ 1 จะจับ "ชอบ" คำเดียวแล้วยุบทุกอย่างเข้าด้วยกัน (เหมือนบั๊ก noise ใน M1)
_SAME_TOPIC_MIN_OVERLAP = 2


# คำที่ต้อง *ไม่* นับเป็นหลักฐานว่า "เรื่องเดียวกัน"
#
# ⚠️ บั๊กชั้นที่สองที่เจอ (หลังแก้ให้เทียบเฉพาะ tag แล้ว): "เบื่อนิยายสืบสวนแล้ว เปลี่ยนมาชอบไซไฟ"
# ยังไป supersede "ย้ายมาอยู่เชียงใหม่แล้ว" เพราะ token ที่ทับกันคือ ['มา', 'แล้ว'] ล้วนๆ
# — คำไวยากรณ์ที่ไม่ได้บอกหัวข้ออะไรเลย
#
# ร้ายกว่านั้น: คำพวกนี้ส่วนใหญ่อยู่ใน _CHANGE_SIGNALS อยู่แล้ว (เพราะมันบ่งบอก "การเปลี่ยน")
# → summary ที่เป็นการเปลี่ยนแปลงทุกอันจะดู "เรื่องเดียวกัน" กันเองโดยอัตโนมัติ
# เป็นความลำเอียงเชิงระบบ ไม่ใช่ความบังเอิญของ fixture
#
# memory._STOPWORDS ครอบไม่ถึงเพราะออกแบบมาสำหรับ *คำถาม* ("ไหม", "จำได้", "เรา")
# ไม่ใช่สำหรับเนื้อความ summary — จึงเสริมเฉพาะที่นี่ ไม่ไปแก้ของ production ที่ใช้ร่วมกัน
_TOPIC_STOPWORDS = {
    "มา", "แล้ว", "ไป", "ยัง", "อยู่", "ตอน", "ทำ", "เป็น", "ได้", "ไม่",
    "เปลี่ยน", "ใหม่", "ตอนนี้", "หันมา", "เลิก", "แทน",
}


def _topic_tokens(text: str) -> set:
    """token ของ *เนื้อหาใน tag* เท่านั้น — ตัดส่วนพรรณนาหน้า | ทิ้ง

    ⚠️ บั๊กที่เจอจริงตอนรันรอบแรก (M3 ได้ static 0/6): เดิมเทียบทั้งบรรทัด ซึ่งทุกบรรทัด
    มีคำโครงร่างร่วมกันหมด ("คุย", "เรื่อง", "ผู้ใช้") แค่นั้นก็ทับกัน 2 token แล้ว
    ผลคือ "ย้ายมาอยู่เชียงใหม่" ไป supersede ทั้งแมว ทั้งหมา ทั้งงาน — ยุบทุกอย่างเข้าหากัน

    ต้นเหตุเดียวกับที่ memory.add_fact เทียบ *category* ไม่ใช่ข้อความทั้งก้อน:
    ต้องเทียบเฉพาะส่วนที่เป็น "ค่า" ไม่ใช่ส่วนที่เป็นโครงประโยค
    """
    parts = memory.split_owner_tags(text)
    payload = " ".join(parts["user"] + parts["me"])
    if not payload.strip():
        payload = parts["summary"]       # summary แบบเก่าไม่มี tag — ถอยไปใช้หัวเรื่อง
    return set(memory._keywords(payload, expand=False)) - _TOPIC_STOPWORDS


def _same_topic(a: str, b: str) -> bool:
    """สองบรรทัดนี้พูดเรื่องเดียวกันไหม — นับ token ที่ทับกันเฉพาะเนื้อหาใน tag

    expand=False — ไม่ขยายคำพ้องตรงนี้ เพราะคำพ้องจะทำให้ "นิยาย" กับ "หนังสือ" ทับกัน
    จนยุบเรื่องที่ไม่เกี่ยวเข้าด้วยกัน
    """
    wa, wb = _topic_tokens(a), _topic_tokens(b)
    if not wa or not wb:
        return False
    return len(wa & wb) >= _SAME_TOPIC_MIN_OVERLAP


# ══════════════════════════════════════════════════════════════════════════════
#  M3 — deterministic supersede ที่ write path
# ══════════════════════════════════════════════════════════════════════════════

def m3_consolidate(summaries: list) -> list:
    """ประมวลผลกอง summary: mark อันเก่าที่ถูกแทนที่แล้วเป็น superseded (ไม่ลบ)

    เลียนแบบ memory.add_fact (memory.py:187-201) ที่ทำกับ facts อยู่แล้ว:
      - จับคู่ด้วย token overlap (แทน category เพราะ summary ไม่มี)
      - อันใหม่กว่า supersede อันเก่า — soft delete เก็บของเก่าไว้เสมอ (ADD-only)

    ⚠️ ต้องมีสัญญาณ "เปลี่ยนแปลง" ด้วย ไม่ใช่แค่เรื่องเดียวกัน — ไม่งั้นชุด static พัง
       ("ทำงานสายไอที" กับ "เป็นโปรแกรมเมอร์" เรื่องเดียวกันแต่ไม่ได้แทนที่กัน)
    """
    out = [dict(e) if isinstance(e, dict) else {"date": "", "text": e} for e in summaries]
    for i, new in enumerate(out):
        if not _has_change_signal(new["text"]):
            continue
        for j, old in enumerate(out):
            if i == j or old.get("superseded"):
                continue
            if _date_of(old) >= _date_of(new):
                continue                       # ของเก่าต้องเก่ากว่าจริง
            if _same_topic(old["text"], new["text"]):
                old["superseded"] = True
                old["superseded_by"] = new["text"]
    return out


# คำที่บ่งบอกว่า summary นี้เป็น "การเปลี่ยนแปลงสถานะ" ไม่ใช่แค่พูดถึงเรื่องเดิม
#
# ⚠️ ลิสต์แบบนี้ไม่มีวันครบ (บทเรียนเดียวกับ _HAIR_NEXT ใน persona.py และ
#    "อย่าจับคู่ประธาน+กริยา" ใน MEMORY_EXPERIMENTS §4) จึงออกแบบให้พลาดไปทางปลอดภัย:
#    ไม่มีสัญญาณ = ไม่ supersede = เก็บทั้งคู่ไว้ (เสีย precision ดีกว่าลบของจริงทิ้ง)
_CHANGE_SIGNALS = (
    "เปลี่ยน", "ย้าย", "เลิก", "เบื่อ", "ไม่ชอบแล้ว", "แทน", "ตอนนี้", "หันมา",
    "ใหม่", "แล้ว",
)


def _has_change_signal(text: str) -> bool:
    return any(s in text for s in _CHANGE_SIGNALS)


def m3_deterministic(summaries: list, question: str, min_score: int = 1) -> list:
    """M3 เต็มรูป: consolidate ก่อน แล้ว recall เฉพาะอันที่ยัง valid

    ถามอดีต → ใช้กองเดิมทั้งหมด (รวม superseded) เพราะผู้ใช้ต้องการของเก่าจริงๆ
    """
    consolidated = m3_consolidate(summaries)
    if wants_history(question):
        pool = consolidated                                     # เอาหมด รวมของเก่า
    else:
        pool = [e for e in consolidated if not e.get("superseded")]
    return _score_and_filter(pool, question, min_score=min_score)


# ══════════════════════════════════════════════════════════════════════════════
#  M4 — LLM ตัดสินตอนเขียน (ADD / UPDATE / NOOP)
# ══════════════════════════════════════════════════════════════════════════════

# จำนวน candidate สูงสุดที่ยอมส่งให้ LLM ต่อหนึ่ง summary ใหม่
#
# ⚠️ บั๊กรอบแรกของ M5: ส่ง "ทุกคู่ที่ M3 จับไม่ได้" ซึ่งรวมทุกเรื่องที่ไม่เกี่ยวกันเลย
#    → 16-23 candidate ต่อครั้ง (M4 ส่งเฉลี่ย ~12) = pool ใหญ่ขึ้น ไม่ใช่เล็กลง
#    ผลคือ static ตกเหลือ 2/10 ซึ่งตรงกับที่เปเปอร์ 2606.01435 ทำนายไว้พอดี
#    (LLM เสื่อมเมื่อ pool ใหญ่: 75%@64K → 61%@262K)
#
# แก้: เรียงตามความใกล้เคียงแล้วตัดเหลือ top-N — เจตนาเดิมของ M5 คือ *ลด* pool
_M5_MAX_CANDIDATES = 3


def m3_undecided_pairs(summaries: list) -> list:
    """คืนคู่ที่ M3 *ตัดสินไม่ได้* แต่ยัง "พอมีเค้า" ว่าเกี่ยวกัน — ไว้ส่งต่อให้ LLM ใน M5

    M3 จับคู่ได้เฉพาะเมื่อมี token ร่วมกัน ≥ เกณฑ์ คู่ที่ไม่มี token ร่วมเลย
    ("ชุมพร"/"เชียงใหม่", "ครู"/"พยาบาล") จึงหลุดไปเงียบๆ โดยไม่มีสัญญาณอะไรบอก

    หัวใจของ M5: ให้ LLM ดูเฉพาะคู่ที่คัดมาแล้ว ไม่ใช่ทุกคู่
    คัดด้วย 2 ชั้น:
      1. ต้องมีสัญญาณการเปลี่ยนแปลงในฝั่งใหม่ (rule-based เหมือน M3)
      2. เรียงผู้เข้ารอบด้วยความใกล้เคียงเชิงโครงสร้าง แล้วตัดเหลือ _M5_MAX_CANDIDATES

    ชั้นที่ 2 ใช้ "ประเภทของ tag ตรงกันไหม" เป็นสัญญาณหลัก — user_fact ควรถูกแทนที่ด้วย
    user_fact ไม่ใช่ me_pref (ถูกกว่า embedding มาก และใช้ข้อมูลที่รูปแบบ F มีอยู่แล้ว)
    """
    out = [dict(e) if isinstance(e, dict) else {"date": "", "text": e} for e in summaries]
    decided = m3_consolidate(summaries)
    sup_texts = {e["text"] for e in decided if e.get("superseded")}

    pairs = []
    for i, new in enumerate(out):
        if not _has_change_signal(new["text"]):
            continue
        cands = []
        for j, old in enumerate(out):
            if i == j or old["text"] in sup_texts:
                continue                       # M3 ตัดสินไปแล้ว ไม่ต้องถาม LLM ซ้ำ
            if _date_of(old) >= _date_of(new):
                continue
            if _same_topic(old["text"], new["text"]):
                continue                       # M3 จับได้แล้ว
            aff = _affinity(old["text"], new["text"])
            if aff <= 0:
                continue                       # ไม่มีเค้าว่าเกี่ยวกันเลย ไม่ต้องถาม
            cands.append((aff, j))
        cands.sort(key=lambda x: -x[0])
        for _, j in cands[:_M5_MAX_CANDIDATES]:
            pairs.append((j, i))
    return pairs


def _owner_kinds(text: str) -> set:
    """ประเภท tag ที่มีในบรรทัดนี้ — {'user_pref','me_fact',...}"""
    return {m.group(1) for m in memory._OWNER_TAG_RE.finditer(text)}


def _affinity(old: str, new: str) -> int:
    """คะแนน "พอมีเค้าว่าเกี่ยวกันไหม" สำหรับคัด candidate ก่อนส่ง LLM

    ไม่ใช่การตัดสินว่าแทนที่กันจริง — แค่คัดผู้เข้ารอบ (ตัดสินจริงเป็นหน้าที่ LLM)
    เหมือนด่าน 1 ของ vectormemory ที่ embedding คัดผู้เข้ารอบให้ rerank ตัดสิน
    """
    ko, kn = _owner_kinds(old), _owner_kinds(new)
    if not (ko & kn):
        return 0                    # คนละประเภท tag = คนละชนิดข้อมูล ไม่ต้องเทียบ
    score = 2                       # ประเภทตรงกัน = พื้นฐาน
    score += len(_topic_tokens(old) & _topic_tokens(new))   # มีคำร่วมยิ่งดี
    return score


def build_conflict_prompt(new_text: str, candidates: list) -> str:
    """ถามโมเดลว่า summary ใหม่นี้ทับของเก่าอันไหนไหม

    รูปแบบตาม mem0 (ADD/UPDATE/NOOP) แต่ตัด DELETE ออก — โปรเจกต์นี้ใช้ soft delete
    เสมอ (memory.add_fact ไม่เคยลบจริง) และ mem0 เองก็ถอยจาก DELETE แล้ว

    ตอบเป็น JSON เพื่อ parse ได้แน่นอน — รูปแบบเดียวกับ build_summary_prompt
    """
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(candidates))
    return (
        "คุณคือระบบจัดการความทรงจำ ตัดสินว่าความทรงจำใหม่นี้ *แทนที่* อันเก่าอันไหนหรือไม่\n"
        "กฎ:\n"
        "- แทนที่ = เรื่องเดียวกันและค่าเปลี่ยนไปจริง (ย้ายบ้าน, เลิกชอบของเดิม)\n"
        "- ไม่แทนที่ = เรื่องเดียวกันแต่เป็นข้อมูลเสริม หรือคนละบริบท "
        "(ชอบกาแฟตอนเช้า กับ ชอบชาตอนเย็น = คนละบริบท ไม่แทนที่กัน)\n"
        "- ไม่แทนที่ = พูดเรื่องเดิมด้วยคำต่างกัน (ทำงานสายไอที กับ เป็นโปรแกรมเมอร์)\n"
        "- ถ้าไม่แน่ใจ ให้ตอบ NOOP เสมอ (เก็บไว้ทั้งคู่ปลอดภัยกว่าลบผิด)\n"
        f"\nความทรงจำใหม่:\n{new_text}\n"
        f"\nความทรงจำเก่าที่มีอยู่:\n{listing}\n"
        '\nตอบ JSON อย่างเดียว: {"action": "UPDATE"|"NOOP", "replaces": [<เลขข้อ>]}\n'
    )


def parse_conflict_json(raw: str) -> dict:
    """แปลงผลจากโมเดล — fail-safe: parse ไม่ได้ = NOOP (ไม่แทนที่อะไร)

    ⚠️ ต้อง fail ไปทาง NOOP เสมอ ตามแบบ rerank_with_llm (vectormemory.py:120-126)
       ที่เลือก "ไม่ inject รอบนี้" เมื่อ parse ไม่ได้ — เดาผิดแล้วลบความทรงจำจริงทิ้ง
       แย่กว่าเก็บของซ้ำไว้
    """
    import json as _json
    import re as _re
    txt = (raw or "").strip()
    if "</think>" in txt:
        txt = txt.rsplit("</think>", 1)[-1]
    m = _re.search(r"\{.*?\}", txt, _re.DOTALL)
    if not m:
        return {"action": "NOOP", "replaces": []}
    try:
        d = _json.loads(m.group(0))
    except Exception:
        return {"action": "NOOP", "replaces": []}
    if not isinstance(d, dict) or d.get("action") != "UPDATE":
        return {"action": "NOOP", "replaces": []}
    rep = d.get("replaces")
    if not isinstance(rep, list):
        return {"action": "NOOP", "replaces": []}
    return {"action": "UPDATE", "replaces": [r for r in rep if isinstance(r, int)]}
