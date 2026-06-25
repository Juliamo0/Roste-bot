# ============================================================
#  🎵  ระบบเพลง — เล่นไฟล์ mp3 ในห้อง voice ของ Discord
#  (แยกออกมาเป็นไฟล์ของตัวเอง เพื่อให้แก้/ดีบักง่าย)
#  วิธีใช้จาก bot.py:  import music  แล้วเรียก music.play_song_in_voice(...)
# ============================================================
import os
import re
import json
import random
import asyncio
import discord

# ---------- ⚙️ ตั้งค่าระบบเพลง (แก้ตรงนี้) ----------
# โฟลเดอร์เก็บไฟล์เพลงที่รอสเต้ "ร้องได้" — หย่อนไฟล์ .mp3 ไว้ที่นี่
# ตั้งชื่อไฟล์ตามชื่อเพลง เช่น songs/วิมานดิน.mp3 แล้วสั่ง "@Roste ร้องเพลงวิมานดิน"
SONGS_DIR = "songs"
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

NOT_FOUND_LINES = [
    "เพลง \"{q}\" เหรอคะ... รอสเต้ยังไม่เคยได้ยินเพลงนี้เลย ยังร้องไม่ได้ค่ะ ขอไปหัดฟังก่อนนะคะ",
    "อืม... \"{q}\" รอสเต้ยังไม่เคยฟังเพลงนี้มาก่อนเลยค่ะ เลยยังร้องให้ไม่ได้ ขอเวลาทำความรู้จักก่อนนะคะ",
    "ขอโทษนะคะ เพลง \"{q}\" รอสเต้ยังร้องไม่เป็นเลย ไม่เคยได้ยินมาก่อนค่ะ ไว้หัดได้แล้วจะร้องให้นะคะ",
]


def _normalize_song(s):
    """ตัดช่องว่าง/ขีด/ตัวพิมพ์ เพื่อเทียบชื่อเพลงแบบหลวมๆ"""
    return re.sub(r"[\s_\-]", "", s.lower())


def extract_song_query(text):
    """ดึง 'ชื่อเพลง' ออกจากข้อความสั่ง"""
    q = text
    for w in SONG_STRIP:
        q = q.replace(w, " ")
    return re.sub(r"\s+", " ", q).strip()


def find_song(query):
    """หาไฟล์เพลงที่ตรงกับ query คืน (path, ชื่อเพลง) หรือ None"""
    if not query or not os.path.isdir(SONGS_DIR):
        return None
    qn = _normalize_song(query)
    if not qn:
        return None
    for f in os.listdir(SONGS_DIR):
        if not f.lower().endswith(SONG_EXTS):
            continue
        name = os.path.splitext(f)[0]
        nn = _normalize_song(name)
        if nn and (nn in qn or qn in nn):
            return os.path.join(SONGS_DIR, f), name
    return None


def find_karaoke(query: str):
    """หาไฟล์ใน karaoke/ ที่ match query (บางส่วน ไม่สนตัวพิมพ์) คืน (path, stem) หรือ None"""
    if not query or not os.path.isdir(KARAOKE_DIR):
        return None
    qn = _normalize_song(query)
    if not qn:
        return None
    for f in os.listdir(KARAOKE_DIR):
        if not f.lower().endswith(SONG_EXTS):
            continue
        stem = os.path.splitext(f)[0]
        sn = _normalize_song(stem)
        if sn and (qn in sn or sn in qn):
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


async def play_song_in_voice(message, song_path, song_name):
    """เข้าห้อง voice ที่ผู้สั่งอยู่ → เล่นเพลง → ออกจากห้อง"""
    channel = message.author.voice.channel
    async with voice_lock:
        # เชื่อมต่อห้อง voice
        try:
            vc = await channel.connect()
        except discord.ClientException:
            vc = message.guild.voice_client
            if vc and vc.channel != channel:
                await vc.move_to(channel)
        except Exception as e:
            await message.channel.send(
                f"{message.author.mention} เข้าห้องเสียงไม่ได้ค่ะ ({type(e).__name__}) ลองใหม่นะคะ")
            return

        await message.channel.send(
            f"🎵 รอสเต้เข้ามาร้องเพลง \"{song_name}\" ให้ {message.author.mention} แล้วนะคะ~")

        # เล่นเพลง แล้วรอจนจบ (ใช้ Event เชื่อม callback ที่ทำงานคนละเธรด)
        loop = asyncio.get_running_loop()
        done = asyncio.Event()

        def after_play(err):
            loop.call_soon_threadsafe(done.set)

        try:
            source = discord.FFmpegPCMAudio(song_path)
            vc.play(source, after=after_play)
        except Exception as e:
            await vc.disconnect()
            await message.channel.send(
                f"{message.author.mention} เล่นเพลงไม่สำเร็จค่ะ ({type(e).__name__}) "
                "ไฟล์อาจมีปัญหา ลองเพลงอื่นนะคะ")
            return

        try:
            await asyncio.wait_for(done.wait(), timeout=900)  # กันค้าง (สูงสุด 15 นาที)
        except asyncio.TimeoutError:
            pass

        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        await message.channel.send(
            f"{message.author.mention} ร้องจบแล้วค่ะ เป็นไงบ้างคะ เพราะไหม~ 🎶")
