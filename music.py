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

# ---------- สถานะภายใน ----------
voice_lock = asyncio.Lock()   # เล่นได้ทีละเพลง

SONG_EXTS = (".mp3", ".wav", ".m4a", ".flac", ".ogg")

# คำขึ้นต้น/คำเสริม ที่ตัดออกเพื่อให้เหลือ "ชื่อเพลง"
SONG_STRIP = ("ร้องเพลง", "เปิดเพลง", "เล่นเพลง", "ขอเพลง", "เปิดให้ฟัง",
              "ร้อง", "เปิด", "เล่น", "ขอ", "เพลง", "หน่อย", "ให้", "ที",
              "ด้วย", "นะ", "คะ", "ครับ", "ค่ะ", "ฟัง")

def _normalize_song(s):
    """ตัดช่องว่าง/ขีด/ตัวพิมพ์ เพื่อเทียบชื่อเพลงแบบหลวมๆ"""
    return re.sub(r"[\s_\-]", "", s.lower())


def extract_song_query(text):
    """ดึง 'ชื่อเพลง' ออกจากข้อความสั่ง"""
    q = text
    for w in SONG_STRIP:
        q = q.replace(w, " ")
    return re.sub(r"\s+", " ", q).strip()


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
    try:
        with open(SONG_REQUESTS_LOG, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


