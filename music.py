# ============================================================
#  🎤  ระบบ Karaoke — รอสเต้ร้องเพลง cover ในห้อง voice ของ Discord
#  (แยกออกมาเป็นไฟล์ของตัวเอง เพื่อให้แก้/ดีบักง่าย)
# ============================================================
import os
import re
import json
import random
import asyncio
import discord

# โฟลเดอร์เพลง cover — ตั้งชื่อไฟล์ [ชื่อเพลง]_[ศิลปิน].wav เช่น monster_yoasobi.wav
KARAOKE_DIR = "karaoke"

# ไฟล์บันทึกว่าใครขอเพลงอะไรบ้าง (ไว้ดูว่าควรเตรียมเพลงไหนเพิ่ม)
SONG_REQUESTS_LOG = "song_requests.json"
MAX_SONG_REQUESTS = 200   # กันไฟล์โตไม่จำกัด — เกินแล้วตัดคำขอที่ถูกขอน้อยสุดทิ้งก่อน (เก็บเพลงยอดฮิตไว้)

# ---------- สถานะภายใน ----------
voice_lock = asyncio.Lock()   # เล่นได้ทีละเพลง

# guild_id ที่เพิ่งถูกสั่งหยุด — ให้ _play_karaoke รู้ว่า "ถูกสั่งหยุด" ไม่ใช่ "ร้องจบเอง"
# จะได้ไม่พูดปิดท้าย "ร้องจบแล้วค่ะ เพราะไหม~" ซึ่งฟังดูแปลกเมื่อผู้ใช้เพิ่งสั่งให้เงียบ
stopped_guilds: set = set()

# ธงจาก tool stop_voice — llm_tools ตั้ง, bot.py อ่านแล้วสั่งหยุดจริง
# (llm_tools ไม่มี voice client และไม่ควร import discord/bot = กัน circular import)
stop_requested: bool = False

SONG_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg")

# คำขึ้นต้น/คำเสริม ที่ตัดออกเพื่อให้เหลือ "ชื่อเพลง"
SONG_STRIP = ("ร้องเพลง", "เปิดเพลง", "เล่นเพลง", "ขอเพลง", "เปิดให้ฟัง",
              "ร้อง", "เปิด", "เล่น", "ขอ", "เพลง", "หน่อย", "ให้", "ที",
              "ด้วย", "นะ", "คะ", "ครับ", "ค่ะ", "ฟัง")

def _normalize_song(s):
    """ตัดช่องว่าง/ขีด/ตัวพิมพ์ เพื่อเทียบชื่อเพลงแบบหลวมๆ"""
    return re.sub(r"[\s_\-]", "", s.lower())


# ── คำสั่ง "หยุด" — ให้ผู้ใช้สั่งหยุดร้อง/หยุดพูดได้กลางคัน ──────────────────
#
# เดิมพอ voice_lock ถูกจอง ทุกอย่างเด้ง "รอแป๊บนึงแล้วลองใหม่นะคะ" อย่างเดียว
# ผู้ใช้จึงหยุดรอสเต้ไม่ได้เลย ต้องรอจนเพลงจบ (เพลงยาว 3-5 นาที)
#
# ⚠️ ต้องเช็ค *ก่อน* ด่าน voice_lock ไม่ใช่หลัง — ไม่งั้นคำสั่งหยุดจะโดนเด้งไปด้วย
#    ซึ่งเป็นตอนที่ผู้ใช้ต้องการใช้มันที่สุดพอดี
#
# ⚠️ จับที่ *กริยาหยุด + ประธานเสียง* ไม่ใช่คำเดี่ยว — "หยุด" คำเดียวกว้างเกินไป
#    ("หยุดงานวันไหน" / "รถหยุดตรงไหน" ไม่ใช่คำสั่งหยุดเสียง)
_STOP_VERBS = ("หยุด", "เงียบ", "พอ", "เลิก", "ปิด", "หุบปาก", "อย่า", "ไม่ต้อง",
               "ไม่เอา", "พัก", "ข้าม", "ยกเลิก", "จบ", "เบา",
               "stop", "shut up", "shutup", "quiet", "silence", "cancel", "skip",
               "pause", "mute", "enough")
# คำที่ยืนยันว่าหมายถึง "เสียงของรอสเต้" — ต้องมีอย่างน้อย 1 คำ
#
# ⚠️ ต้องเป็นคำที่ชี้ *เสียง/ตัวรอสเต้* เท่านั้น
# เคยใส่คำลงท้ายทั่วไป (หน่อย/แล้ว/ก่อน/เถอะ) แล้ววัดเจอ false positive ทันที:
#   "ผมเลิกงานแล้ว" -> เลิก + แล้ว = สั่งหยุด ❌
#   "ปิดไฟหน่อย"    -> ปิด + หน่อย = สั่งหยุด ❌
# คำลงท้ายไม่ได้บอกว่าพูดถึงอะไร จึงใช้เป็นตัวยืนยันไม่ได้
_STOP_TARGETS = ("ร้อง", "เพลง", "พูด", "เสียง", "รอสเต้", "singing", "song")
# สำนวนที่เป็นคำสั่งหยุดในตัวเอง ไม่ต้องมี target
_STOP_PHRASES = ("เงียบหน่อย", "เงียบก่อน", "เงียบๆ", "เงียบ ๆ", "พอแล้ว", "พอก่อน",
                 "หยุดก่อน", "หยุดเลย", "เลิกร้อง", "ไม่ต้องร้อง", "ไม่ต้องพูด",
                 "shutup", "shut up", "be quiet", "stop")


def looks_like_pure_stop(text: str) -> bool:
    """เป็นคำสั่งหยุด *ล้วนๆ* ไหม (ไม่ได้มีเนื้อหาอื่นให้ตอบ)

    ใช้แยกว่า "หยุดแล้วจบ" หรือ "หยุดแล้วไปตอบข้อความนั้นต่อ"
        "เงียบหน่อย" / "พอแล้ว" -> ล้วน -> ตอบ "ค่ะ หยุดแล้วนะคะ" พอ
        "พอดีผมยุ่ง" / "จบยัง"  -> ไม่ล้วน -> หยุดเสียงแล้วไปตอบข้อความนั้นตามปกติ
    """
    t = re.sub(r"[\s]+", "", (text or "").lower())
    if not t:
        return False
    if any(re.sub(r"\s", "", p) in t for p in _STOP_PHRASES):
        return True
    has_verb = any(v.replace(" ", "") in t for v in _STOP_VERBS)
    if not has_verb:
        return False
    # มีคำถาม = ไม่ใช่คำสั่งล้วน ("รถหยุดตรงไหน" / "วันนี้หยุดงานไหม")
    if any(q in t for q in ("ไหน", "ไหม", "อะไร", "ทำไม", "ยังไง", "กี่", "?", "เมื่อไหร่")):
        return False
    # สั้นมาก + มีกริยาหยุด = คำสั่งล้วน ("หยุด" "พอ" "เงียบ" "หยุดเลย")
    # หรือมีคำชี้เสียงชัดเจน ("เลิกร้อง" "ไม่ต้องพูด")
    has_target = any(g.replace(" ", "") in t for g in _STOP_TARGETS)
    return len(t) <= 8 or has_target


def extract_song_query(text):
    """ดึง 'ชื่อเพลง' ออกจากข้อความสั่ง — tokenize คำไทยจริงก่อนกรองออกทีละคำ (ไม่ใช่ substring
    replace แบบเดิม) กัน SONG_STRIP กินตัวอักษรกลางชื่อเพลง เช่น เพลงชื่อ "ขอโทษ" ไม่ควรโดนตัดคำว่า
    "ขอ" ออกจากกลางคำ (บั๊กจริงที่เจอจาก code review — substring replace เดิมทำแบบนั้น)"""
    try:
        from pythainlp.tokenize import word_tokenize
        tokens = word_tokenize(text, engine="newmm")
    except Exception:
        # pythainlp มีปัญหา — fallback ไปวิธีเดิม (substring replace) ดีกว่าไม่ทำงานเลย
        q = text
        for w in SONG_STRIP:
            q = q.replace(w, " ")
        return re.sub(r"\s+", " ", q).strip()

    kept = [t for t in tokens if t.strip() and t not in SONG_STRIP]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def find_karaoke(query: str):
    """หาไฟล์ใน karaoke/ ที่ match query (บางส่วน ไม่สนตัวพิมพ์) คืน (path, stem) หรือ None"""
    if not query or not os.path.isdir(KARAOKE_DIR):
        return None
    # แยก query เป็นคำๆ ก่อน normalize — กัน "รอสเต้ monster" จับคำว่า "monster" ได้ถูก
    words = [_normalize_song(w) for w in query.split() if len(_normalize_song(w)) >= 2]
    if not words:
        return None
    for f in os.listdir(KARAOKE_DIR):
        if not f.lower().endswith(SONG_EXTS):
            continue
        stem = os.path.splitext(f)[0]
        sn = _normalize_song(stem)
        if sn and any(w in sn for w in words):
            return os.path.join(KARAOKE_DIR, f), stem
    return None


def get_random_karaoke():
    """สุ่ม 1 เพลงจาก karaoke/ คืน (path, stem) หรือ None"""
    if not os.path.isdir(KARAOKE_DIR):
        return None
    files = [f for f in os.listdir(KARAOKE_DIR) if f.lower().endswith(SONG_EXTS)]
    if not files:
        return None
    f = random.choice(files)
    return os.path.join(KARAOKE_DIR, f), os.path.splitext(f)[0]


def prettify_song_name(stem: str) -> str:
    """monster_yoasobi → 'Monster', blinding_lights_weeknd → 'Blinding Lights'"""
    parts = stem.split("_")
    if len(parts) > 1:
        parts = parts[:-1]  # ตัดส่วนสุดท้าย (ชื่อศิลปิน) ออก
    return " ".join(p.capitalize() for p in parts)


def log_song_request(user_name, query, found):
    """บันทึกว่าใครขอเพลงอะไร (นับจำนวนครั้ง) ลง song_requests.json"""
    data = {}
    try:
        if os.path.exists(SONG_REQUESTS_LOG):
            with open(SONG_REQUESTS_LOG, encoding="utf-8") as f:
                data = json.load(f)
    except Exception:
        data = {}
    key = query or "(ไม่ระบุชื่อ)"
    entry = data.get(key, {"count": 0, "found": found, "last_by": ""})
    entry["count"] += 1
    entry["found"] = found
    entry["last_by"] = user_name
    data[key] = entry
    if len(data) > MAX_SONG_REQUESTS:
        excess = len(data) - MAX_SONG_REQUESTS
        lowest = sorted(data, key=lambda k: data[k].get("count", 0))[:excess]
        for k in lowest:
            del data[k]
    try:
        with open(SONG_REQUESTS_LOG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


