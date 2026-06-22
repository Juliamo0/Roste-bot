import re
import random
import asyncio
import discord
import aiohttp

import printing   # 🖨️ ระบบพิมพ์ PDF (อยู่ในไฟล์ printing.py)
import music      # 🎵 ระบบเพลง (อยู่ในไฟล์ music.py)
import persona    # 🎭 บุคลิกรอสเต้ (SYSTEM_PROMPT, FEWSHOT, MOODS, author note)
import memory     # 🧠 ระบบความจำ (load/save/facts/recall + คำสั่งจำ-ลืม)

# ดึงค่า/ฟังก์ชันที่ใช้บ่อยมาไว้ในชื่อสั้นๆ (โค้ดด้านล่างจะได้เรียกง่ายเหมือนเดิม)
SYSTEM_PROMPT = persona.SYSTEM_PROMPT
FEWSHOT_EXAMPLES = persona.FEWSHOT_EXAMPLES
build_author_note = persona.build_author_note
MAX_HISTORY_PAIRS = memory.MAX_HISTORY_PAIRS
load_memory = memory.load_memory
save_memory = memory.save_memory
handle_memory_command = memory.handle_memory_command

# state ชั่วคราวต่อ user — ไม่ควร persist ลง JSON
_pending_place: dict = {}   # {user_id: คำถามร้านที่ค้างรอจังหวัด}
_user_locks: dict = {}      # {user_id: asyncio.Lock}


def get_user_lock(user_id) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


_THAI_MONTHS = ("", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
                "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")

# ============================================================
#  ⚙️  ตั้งค่าหลัก — แก้ตรงนี้
# ============================================================

# Token ถูกเก็บแยกไว้ในไฟล์ config.py (เปิดไฟล์นั้นเพื่อใส่/แก้ Token)
try:
    from config import DISCORD_TOKEN
except ImportError:
    print("❌ ไม่พบไฟล์ config.py — วางไฟล์ config.py ไว้โฟลเดอร์เดียวกับ bot.py")
    raise SystemExit

# TMD_TOKEN (กรมอุตุฯ) — ไม่บังคับ ถ้าไม่มีจะใช้ Open-Meteo แทนอัตโนมัติ
try:
    from config import TMD_TOKEN
except ImportError:
    TMD_TOKEN = ""

# SERPAPI_KEY (ค้นผ่าน Google จริง) — ไม่บังคับ ถ้าไม่มีจะใช้ ddg (ddgs) แทนอัตโนมัติ
# สมัครฟรีที่ https://serpapi.com (free plan 250 ครั้ง/เดือน) แล้ววาง key ใน config.py
try:
    from config import SERPAPI_KEY
except ImportError:
    SERPAPI_KEY = ""
# ถ้ายังเป็นค่าตัวอย่าง (ยังไม่ใส่ key จริง) ให้ถือว่าไม่ได้ตั้ง — จะได้ fallback ไป ddg
if not SERPAPI_KEY or SERPAPI_KEY.startswith("วาง_"):
    SERPAPI_KEY = ""

# เช็กว่าใส่ Token จริงแล้วหรือยัง ถ้ายังให้เตือนชัดๆ
if not DISCORD_TOKEN or DISCORD_TOKEN == "วาง_TOKEN_ของคุณ_ที่นี่":
    print("⚠️ ยังไม่ได้ใส่ Token! เปิดไฟล์ config.py แล้ววาง Token จาก Discord ก่อนนะครับ")
    raise SystemExit

# ที่อยู่ของ Ollama (ปกติไม่ต้องแก้ ถ้ารันบนเครื่องเดียวกัน)
OLLAMA_URL = "http://localhost:11434/api/chat"

# โมเดลที่จะใช้ — เปลี่ยนได้ตามเครื่อง
#   qwen3:1.7b = เร็วสุด แต่โง่   |   qwen3:8b = สมดุล   |   qwen3:14b = ฉลาดขึ้นแต่ช้า (บนการ์ด 4GB ~1-2 นาที)
MODEL = "qwen3:8b"

# 🖨️ ระบบพิมพ์อยู่ในไฟล์ printing.py | 🎵 ระบบเพลงอยู่ในไฟล์ music.py
# (แก้ตั้งค่าเครื่องพิมพ์ในไฟล์ printing.py, ตั้งค่าโฟลเดอร์เพลงในไฟล์ music.py)


# ============================================================
#  🔎  เครื่องมือค้นเว็บ — ให้รอสเต้ดึงข้อมูลจริงแทนการเดา
#      มี 2 ทาง: SerpApi (Google จริง ถ้าตั้ง SERPAPI_KEY) หรือ ddgs (ฟรี สำรอง)
#      ติดตั้ง:  pip install ddgs requests
# ============================================================

# 🗃️ cache ผลค้นง่ายๆ ในหน่วยความจำ (กันยิง API ซ้ำเปลือง quota) — เก็บ 1 ชม.
import time
_SEARCH_CACHE = {}          # key: (kind, query) -> (เวลาที่เก็บ, ผลลัพธ์)
_CACHE_TTL = 3600           # 1 ชั่วโมง


def _cache_get(kind: str, query: str):
    item = _SEARCH_CACHE.get((kind, query))
    if item and (time.time() - item[0] < _CACHE_TTL):
        print(f"   💾 ใช้ผลจาก cache ({kind})")
        return item[1]
    return None


def _cache_set(kind: str, query: str, value: str):
    _SEARCH_CACHE[(kind, query)] = (time.time(), value)


def _serpapi_get(params: dict):
    """ยิงคำขอไป SerpApi แล้วคืน dict ผลลัพธ์ (หรือ None ถ้าพลาด)"""
    import requests
    params = dict(params, api_key=SERPAPI_KEY)
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        if r.status_code != 200:
            print(f"   ⚠️ SerpApi คืนสถานะ {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        print(f"   ⚠️ SerpApi ผิดพลาด: {e}")
        return None


def search_web_serpapi(query: str, max_results: int = 5) -> str:
    """ค้นเว็บผ่าน Google จริง (SerpApi) — คืนผลเป็นข้อความ หรือ '' ถ้าพลาด (ให้ fallback)"""
    cached = _cache_get("web", query)
    if cached is not None:
        return cached
    data = _serpapi_get({"engine": "google", "q": query, "hl": "th", "gl": "th", "num": max_results})
    if not data:
        return ""
    organic = data.get("organic_results") or []
    if not organic:
        return ""
    lines = []
    for r in organic[:max_results]:
        title = r.get("title", "")
        snippet = (r.get("snippet", "") or "")[:200]
        link = r.get("link", "")
        lines.append(f"- {title}\n  {snippet}\n  ที่มา: {link}")
    out = "\n".join(lines) if lines else "ไม่พบผลการค้นหาที่เกี่ยวข้อง"
    _cache_set("web", query, out)
    return out


def search_places_serpapi(query: str, location: str) -> str:
    """ค้นร้าน/สถานที่ผ่าน Google Maps จริง (SerpApi) — คืนข้อมูลร้านมีโครงสร้าง
    คืน '' ถ้าพลาด (ให้ fallback ไป ddg)"""
    cache_key = f"{query}|{location}"
    cached = _cache_get("maps", cache_key)
    if cached is not None:
        return cached
    # ใส่ชื่อจังหวัดลงใน q โดยตรง (วิธีที่ SerpApi แนะนำ — ไม่ต้องใช้ location/z ที่ยุ่ง)
    full_q = f"{query} {location}".strip()
    data = _serpapi_get({
        "engine": "google_maps", "type": "search",
        "q": full_q, "hl": "th",
    })
    if not data:
        return ""
    # ปกติผลอยู่ใน local_results แต่บางครั้ง Google คืน place_results (สถานที่เดียว)
    places = data.get("local_results") or []
    if not places and data.get("place_results"):
        places = [data["place_results"]]
    if not places:
        return ""
    # กรอง: ตัดร้านรีวิวน้อย (<10) ทิ้ง แล้วเรียงตามเรตติ้ง (บทเรียนจากคอมมู)
    scored = []
    for p in places:
        rating = p.get("rating") or 0
        reviews = p.get("reviews") or 0
        if reviews < 10:
            continue
        scored.append((rating, reviews, p))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    use = scored[:5] if scored else [(0, 0, p) for p in places[:5]]
    lines = []
    for rating, reviews, p in use:
        name = p.get("title", "")
        addr = p.get("address", "")
        rating_txt = f" ⭐{rating} ({reviews} รีวิว)" if rating else ""
        hours = p.get("open_state") or p.get("hours") or ""
        ptype = p.get("type", "")
        line = f"- {name}{rating_txt}"
        if ptype:
            line += f" | ประเภท: {ptype}"
        if addr:
            line += f"\n  ที่อยู่: {addr}"
        if hours:
            line += f"\n  เวลา: {hours}"
        lines.append(line)
    out = "\n".join(lines) if lines else ""
    if out:
        _cache_set("maps", cache_key, out)
    return out


def search_web(query: str, max_results: int = 5, region: str = "th-th") -> str:
    """ค้นเว็บแล้วคืนผลเป็นข้อความ — ใช้ SerpApi ถ้ามี key ไม่งั้นใช้ ddgs (region th-th = เน้นไทย)"""
    # ทางหลัก: SerpApi (Google จริง) ถ้าตั้ง key ไว้
    if SERPAPI_KEY:
        result = search_web_serpapi(query, max_results)
        if result:
            return result
        print("   ↳ SerpApi ไม่ได้ผล ลองใช้ ddg สำรอง")
    # ทางสำรอง: ddgs (ฟรี)
    try:
        from ddgs import DDGS
    except ImportError:
        return "ค้นเว็บไม่ได้: ยังไม่ได้ติดตั้งไลบรารี ddgs (เปิด PowerShell พิมพ์ pip install ddgs)"
    try:
        # safesearch="on" = กรองเนื้อหาผู้ใหญ่, region=th-th = เน้นผลไทย
        results = DDGS().text(query, max_results=max_results, safesearch="on", region=region)
    except Exception as e:
        return f"ค้นเว็บไม่สำเร็จ: {e}"
    if not results:
        return "ไม่พบผลการค้นหา"

    # กรองลิงก์ที่มีคำต้องห้ามออกอีกชั้น (กันเว็บผู้ใหญ่หลุดเข้ามา)
    BLOCK = ("xxx", "porn", "sex", "av-th", "ezmovie", "หื่น", "เย็ด", "ควย", "โป๊",
             "หนังโป", "เสียวแตก", "คลิปหลุด", "เบ็ดหี", "เงี่ยน", "18+", "adult",
             "gratisreife", "รุมเย็ด")
    lines = []
    for r in results:
        title = r.get("title", "")
        body = (r.get("body", "") or "")[:200]
        url = r.get("href") or r.get("url") or ""
        blob = f"{title} {body} {url}".lower()
        if any(b in blob for b in BLOCK):
            continue  # ข้ามผลที่ไม่เหมาะสม
        lines.append(f"- {title}\n  {body}\n  ที่มา: {url}")

    if not lines:
        return "ไม่พบผลการค้นหาที่เกี่ยวข้อง"
    return "\n".join(lines)


# นิยามเครื่องมือที่บอกโมเดลว่ามีอะไรให้เรียกใช้ได้บ้าง
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "ค้นหาข้อมูลจริงจากอินเทอร์เน็ต ใช้เมื่อผู้ใช้ถามเรื่องข้อเท็จจริง ข่าว "
                "ราคา ข้อมูลล่าสุด ชื่อหนังสือ/คน/สินค้า ปีที่ออก หรืออะไรก็ตามที่ไม่ควรเดา"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "คำค้นหาเป็นภาษาที่เหมาะกับเรื่องที่ถาม"}
                },
                "required": ["query"],
            },
        },
    }
]


# คำที่บ่งบอกว่าเป็นคำถามเชิงข้อเท็จจริง (ควรค้นเว็บก่อนตอบ กันการเดามั่ว)
# 👉 เพิ่ม/ลบคำได้ตามใจ ถ้าอยากให้รอสเต้ค้นบ่อยขึ้นหรือน้อยลง
# หมายเหตุ: หลีกเลี่ยงคำกว้างเกิน เช่น "วันนี้"/"ตอนนี้" (ทำให้ค้นตอนทักทาย/บ่นด้วย)
SEARCH_TRIGGERS = (
    "ราคา", "ล่าสุด", "ข่าว", "ใครเป็น", "ใครคือ", "ชื่อคนเขียน", "ผู้เขียน",
    "เมื่อไหร่", "เมื่อไร", "กี่บาท", "รีวิว", "เปรียบเทียบรุ่น", "สเปก", "spec",
    "เวอร์ชันล่าสุด", "version", "release", "ออกปี", "ปี 20",
    "2024", "2025", "2026", "2567", "2568", "2569",
    # 🍜 ร้าน/อาหาร/สถานที่ — โมเดลมักไม่รู้ข้อมูลเฉพาะถิ่น จึงต้องค้นก่อนเสมอ
    "ร้าน", "ร้านอาหาร", "ของกิน", "กิน", "อร่อย", "เมนู", "คาเฟ่", "คาเฟه",
    "ที่เที่ยว", "เที่ยว", "ที่พัก", "โรงแรม", "รีสอร์ท", "แนะนำร้าน",
    "ใกล้ฉัน", "แถวนี้", "ในจังหวัด", "ในอำเภอ", "ตำบล", "พิกัด", "เปิดกี่โมง",
)

# 🍜 คำที่บ่งว่าเป็น "การหาร้าน/สถานที่" โดยเฉพาะ (ต้องมีตำแหน่งก่อนค้น)
PLACE_HINTS = (
    "ร้าน", "ร้านอาหาร", "ของกิน", "กิน", "น่ากิน", "หิว", "อร่อย", "คาเฟ่",
    "ที่เที่ยว", "เที่ยว", "ที่พัก", "โรงแรม", "รีสอร์ท", "ใกล้ฉัน", "แถวนี้",
    "เปิดกี่โมง", "แนะนำร้าน", "หาร้าน",
)

# บริบทที่มีคำว่า "กิน" แต่ "ไม่ใช่" การหาร้านอาหาร — กันจับผิด
PLACE_EXCLUDE = (
    "กินยา", "กินเจคือ", "กินเจมี", "การกิน", "กินอะไรได้", "กินได้ไหม",
    "ลดน้ำหนัก", "ลดความอ้วน", "แพ้อาหาร", "กินยังไง", "วิธีกิน", "กินตอนไหน",
    "หมากิน", "แมวกิน", "สุนัขกิน", "ห้ามกิน", "กินแล้ว",
)

# รายชื่อ 77 จังหวัดไทย — ไว้ตรวจว่าผู้ใช้ระบุจังหวัดมาในข้อความหรือยัง
THAI_PROVINCES = {
    "กรุงเทพ", "กรุงเทพมหานคร", "กระบี่", "กาญจนบุรี", "กาฬสินธุ์", "กำแพงเพชร",
    "ขอนแก่น", "จันทบุรี", "ฉะเชิงเทรา", "ชลบุรี", "ชัยนาท", "ชัยภูมิ", "ชุมพร",
    "เชียงราย", "เชียงใหม่", "ตรัง", "ตราด", "ตาก", "นครนายก", "นครปฐม",
    "นครพนม", "นครราชสีมา", "นครศรีธรรมราช", "นครสวรรค์", "นนทบุรี", "นราธิวาส",
    "น่าน", "บึงกาฬ", "บุรีรัมย์", "ปทุมธานี", "ประจวบคีรีขันธ์", "ปราจีนบุรี",
    "ปัตตานี", "พระนครศรีอยุธยา", "อยุธยา", "พะเยา", "พังงา", "พัทลุง", "พิจิตร",
    "พิษณุโลก", "เพชรบุรี", "เพชรบูรณ์", "แพร่", "ภูเก็ต", "มหาสารคาม", "มุกดาหาร",
    "แม่ฮ่องสอน", "ยโสธร", "ยะลา", "ร้อยเอ็ด", "ระนอง", "ระยอง", "ราชบุรี",
    "ลพบุรี", "ลำปาง", "ลำพูน", "เลย", "ศรีสะเกษ", "สกลนคร", "สงขลา", "หาดใหญ่",
    "สตูล", "สมุทรปราการ", "สมุทรสงคราม", "สมุทรสาคร", "สระแก้ว", "สระบุรี",
    "สิงห์บุรี", "สุโขทัย", "สุพรรณบุรี", "สุราษฎร์ธานี", "สุรินทร์", "หนองคาย",
    "หนองบัวลำภู", "อ่างทอง", "อำนาจเจริญ", "อุดรธานี", "อุตรดิตถ์", "อุทัยธานี",
    "อุบลราชธานี",
}


def is_place_query(text: str) -> bool:
    """คำถามนี้เป็นการหาร้าน/สถานที่ไหม (ของกิน/ที่เที่ยว/ที่พัก ฯลฯ)
    ระวังคำว่า 'กิน' ที่อาจไม่ใช่การหาร้าน เช่น 'กินยา' 'หมากินอะไรได้'"""
    t = text.lower()
    if any(ex in t for ex in PLACE_EXCLUDE):
        return False
    return any(h in t for h in PLACE_HINTS)


def find_province_in_text(text: str) -> str:
    """หาว่าในข้อความมีชื่อจังหวัดไทยไหม คืนชื่อจังหวัด หรือ '' ถ้าไม่เจอ"""
    for prov in THAI_PROVINCES:
        if prov in text:
            return prov
    return ""


def find_saved_location(mem: dict) -> str:
    """หา 'จังหวัดประจำตัว' ของผู้ใช้จากความจำ (facts) — เผื่อไม่ได้พิมพ์มาในข้อความ
    มองหา fact ที่มีชื่อจังหวัด เช่น 'อยู่ชุมพร' / 'อาศัยที่นครศรีธรรมราช'"""
    for fact in mem.get("facts", []):
        prov = find_province_in_text(fact)
        if prov:
            return prov
    return ""


def is_bare_province(text: str) -> str:
    """ข้อความนี้เป็น 'ชื่อจังหวัดล้วนๆ' ไหม (เช่นตอบ 'ชุมพร' หลังถูกถามว่าแถวไหน)
    คืนชื่อจังหวัดถ้าใช่ (ข้อความสั้นและมีแต่จังหวัด) หรือ '' ถ้าไม่ใช่"""
    prov = find_province_in_text(text)
    if not prov:
        return ""
    # ข้อความสั้นๆ (ไม่ใช่ประโยคยาว) ที่มีจังหวัดอยู่ → ถือว่าเป็นการตอบจังหวัด
    cleaned = text.strip()
    if len(cleaned) <= len(prov) + 12:  # เผื่อคำเล็กน้อย เช่น "ที่ชุมพรค่ะ"
        return prov
    return ""

# คำ/รูปแบบที่บ่งว่าเป็นการทักทาย/บ่นความรู้สึก — ไม่ต้องค้นเว็บ
CHITCHAT_HINTS = (
    "สวัสดี", "หวัดดี", "เป็นไง", "เป็นยังไง", "เซ็ง", "เศร้า", "เหนื่อย", "ขี้เกียจ",
    "เบื่อ", "ง่วง", "ดีใจ", "เครียด", "สบายดี", "ว่าไง", "ทำอะไรอยู่",
)


def needs_search(text: str) -> bool:
    """เดาว่าคำถามนี้ควรค้นเว็บก่อนไหม (ดูจากคำที่มักเป็นข้อเท็จจริง)"""
    t = text.lower()
    # ข้อความสั้นมาก หรือเป็นการทักทาย/บ่นความรู้สึก → ไม่ค้น
    if len(text.strip()) < 8:
        return False
    if any(h in t for h in CHITCHAT_HINTS):
        return False
    return any(k.lower() in t for k in SEARCH_TRIGGERS)


# ============================================================
#  🕐  เครื่องมือเวลา — ใช้นาฬิกาในเครื่อง ตั้งโซนไทย (UTC+7) แสดงเป็น พ.ศ.
# ============================================================
def get_thai_datetime() -> str:
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc) + timedelta(hours=7)  # ไทย = UTC+7 (ไม่มี DST)
    days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
    months = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
              "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
    return (f"วัน{days[now.weekday()]}ที่ {now.day} {months[now.month]} "
            f"พ.ศ. {now.year + 543} เวลา {now:%H:%M} น. (เวลาประเทศไทย)")


# ============================================================
#  🌦️  เครื่องมืออากาศ — Open-Meteo (ฟรี ไม่ต้องใช้ API key)
# ============================================================
WEATHER_CODES = {
    0: "ท้องฟ้าแจ่มใส", 1: "ส่วนใหญ่แจ่มใส", 2: "มีเมฆบางส่วน", 3: "เมฆมาก",
    45: "หมอก", 48: "หมอกน้ำแข็ง", 51: "ฝนปรอยเบา", 53: "ฝนปรอย", 55: "ฝนปรอยหนัก",
    61: "ฝนเล็กน้อย", 63: "ฝนปานกลาง", 65: "ฝนหนัก", 71: "หิมะเล็กน้อย",
    80: "ฝนซู่เล็กน้อย", 81: "ฝนซู่ปานกลาง", 82: "ฝนซู่หนัก",
    95: "พายุฝนฟ้าคะนอง", 96: "ฝนฟ้าคะนองมีลูกเห็บ", 99: "ฝนฟ้าคะนองรุนแรง",
}


async def _get_json(url, params):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, timeout=30) as r:
            return await r.json()


# ============================================================
#  🌦️  เครื่องมืออากาศ — กรมอุตุนิยมวิทยา (TMD) เป็นหลัก, Open-Meteo สำรอง
# ============================================================
# รหัสสภาพอากาศของ TMD (field cond) → คำไทย
TMD_COND = {
    1: "ท้องฟ้าแจ่มใส", 2: "มีเมฆบางส่วน", 3: "มีเมฆเป็นส่วนมาก", 4: "มีเมฆมาก",
    5: "ฝนตกเล็กน้อย", 6: "ฝนปานกลาง", 7: "ฝนตกหนัก", 8: "ฝนฟ้าคะนอง",
    9: "อากาศหนาวจัด", 10: "อากาศหนาว", 11: "อากาศเย็น", 12: "อากาศร้อนจัด",
}

# แผนที่ชื่อเมืองอังกฤษ/อังกฤษ→จังหวัดไทย (สำหรับส่งให้ TMD ที่รับชื่อจังหวัดไทย)
EN_TO_TH_PROVINCE = {
    "bangkok": "กรุงเทพมหานคร", "chumphon": "ชุมพร", "chiang mai": "เชียงใหม่",
    "chiangmai": "เชียงใหม่", "phuket": "ภูเก็ต", "khon kaen": "ขอนแก่น",
    "nakhon si thammarat": "นครศรีธรรมราช", "surat thani": "สุราษฎร์ธานี",
    "songkhla": "สงขลา", "hat yai": "สงขลา", "pattaya": "ชลบุรี", "chonburi": "ชลบุรี",
    "rayong": "ระยอง", "korat": "นครราชสีมา", "nakhon ratchasima": "นครราชสีมา",
    "udon thani": "อุดรธานี", "ubon ratchathani": "อุบลราชธานี",
    "krabi": "กระบี่", "ranong": "ระนอง", "prachuap khiri khan": "ประจวบคีรีขันธ์",
    "hua hin": "ประจวบคีรีขันธ์", "ayutthaya": "พระนครศรีอยุธยา",
}


async def get_weather_tmd_hourly_today(province_th: str):
    """ดึงฝนรายชั่วโมงของวันนี้จาก TMD แล้วหา 'ช่วงเวลาที่ฝนน่าจะตก'
    คืนข้อความช่วงเวลา เช่น '12:00 น. และ 16:00-19:00 น.' หรือ '' ถ้าไม่มีฝน/ดึงไม่ได้"""
    if not TMD_TOKEN or TMD_TOKEN.startswith("วาง_"):
        return ""
    base = "https://data.tmd.go.th/nwpapi/v1/forecast/location/hourly/place"
    params = {"province": province_th, "fields": "rain", "duration": 18}
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"accept": "application/json", "authorization": f"Bearer {TMD_TOKEN}"}
            async with s.get(base, params=params, headers=headers, timeout=30) as r:
                if r.status != 200:
                    return ""
                data = await r.json()
        forecasts = data["WeatherForecasts"][0]["forecasts"]
    except Exception:
        return ""

    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    rainy_hours = []
    for f in forecasts:
        ts = f.get("time", "")
        if not ts.startswith(today):
            continue
        try:
            hour = int(ts[11:13])
            rain = float(f["data"].get("rain") or 0)
        except Exception:
            continue
        if rain >= 0.5:
            rainy_hours.append(hour)

    if not rainy_hours:
        return ""

    # รวมชั่วโมงที่ติดกันเป็นช่วง เช่น [16,17,18,19] -> "16:00-19:00 น."
    rainy_hours.sort()
    ranges = []
    start = prev = rainy_hours[0]
    for h in rainy_hours[1:]:
        if h == prev + 1:
            prev = h
        else:
            ranges.append((start, prev))
            start = prev = h
    ranges.append((start, prev))

    parts = []
    for a, b in ranges:
        parts.append(f"{a:02d}:00 น." if a == b else f"{a:02d}:00-{b:02d}:00 น.")
    return " และ ".join(parts)


async def get_weather_tmd(province_th: str) -> str:
    """ดึงพยากรณ์อากาศ 3 วันจากกรมอุตุนิยมวิทยา (TMD) — แม่นสำหรับไทย
    คืนข้อความสรุป หรือ None ถ้าดึงไม่ได้ (ให้ตัวเรียกไปใช้ Open-Meteo สำรอง)"""
    if not TMD_TOKEN or TMD_TOKEN.startswith("วาง_"):
        return None
    base = "https://data.tmd.go.th/nwpapi/v1/forecast/location/daily/place"
    params = {"province": province_th, "fields": "tc_max,tc_min,rh,cond,rain", "duration": 7}
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"accept": "application/json", "authorization": f"Bearer {TMD_TOKEN}"}
            async with s.get(base, params=params, headers=headers, timeout=30) as r:
                if r.status != 200:
                    return None
                data = await r.json()
    except Exception:
        return None

    try:
        fc = data["WeatherForecasts"][0]
        name = fc["location"].get("province", province_th)
        days = fc["forecasts"]
    except Exception:
        return None
    if not days:
        return None

    from datetime import datetime
    THAI_DOW = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
    labels = ["วันนี้", "พรุ่งนี้", "มะรืนนี้"]
    out = [f"พยากรณ์อากาศ {name} (ข้อมูลจากกรมอุตุนิยมวิทยา):"]
    for i, day in enumerate(days[:7]):
        d = day.get("data", {})
        date = day.get("time", "")[:10]
        cond = TMD_COND.get(d.get("cond"), "ไม่ทราบสภาพ")
        tmax = d.get("tc_max")
        tmin = d.get("tc_min")
        rain = d.get("rain")
        rh = d.get("rh")
        if i < len(labels):
            lbl = labels[i]
        else:
            try:
                lbl = "วัน" + THAI_DOW[datetime.strptime(date, "%Y-%m-%d").weekday()]
            except Exception:
                lbl = date
        line = f"- {lbl} ({date}): {cond} อุณหภูมิ {tmin}-{tmax}°C"
        if rain is not None:
            line += f" ปริมาณฝนรวม {rain} มม."
        if rh is not None:
            line += f" ความชื้น {round(rh)}%"
        out.append(line)

    # เพิ่มช่วงเวลาที่ฝนน่าจะตกวันนี้ (ถ้ามี)
    rain_time = await get_weather_tmd_hourly_today(province_th)
    if rain_time:
        out.append(f"วันนี้ฝนน่าจะตกช่วง: {rain_time}")

    return "\n".join(out)


async def get_weather(city: str) -> str:
    """ดึงพยากรณ์อากาศ 3 วัน + แยกโอกาสฝนเป็นช่วงเวลา (เช้า/เที่ยง/เย็น/กลางคืน)"""
    try:
        geo = await _get_json("https://geocoding-api.open-meteo.com/v1/search",
                              {"name": city, "count": 1, "language": "th"})
    except Exception as e:
        return f"ดึงข้อมูลอากาศไม่สำเร็จ: {e}"
    locs = geo.get("results") or []
    if not locs:
        return f"หาตำแหน่งของ '{city}' ไม่เจอ"
    loc = locs[0]
    name = loc.get("name", city)
    try:
        wx = await _get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "hourly": "precipitation_probability",
            "timezone": "Asia/Bangkok", "forecast_days": 3,
        })
    except Exception as e:
        return f"ดึงข้อมูลอากาศไม่สำเร็จ: {e}"

    # จัดโอกาสฝนรายชั่วโมงเข้าช่วงเวลาของแต่ละวัน
    hourly = wx.get("hourly", {})
    htimes = hourly.get("time", [])
    hpop = hourly.get("precipitation_probability", [])
    SLOTS = [("เช้า", 6, 11), ("เที่ยง-บ่าย", 12, 16), ("เย็น", 17, 20), ("กลางคืน", 21, 23)]
    by_day = {}  # date -> {slot: max%}
    for ts, pop in zip(htimes, hpop):
        if pop is None or "T" not in ts:
            continue
        date, hh = ts.split("T")
        hour = int(hh[:2])
        for label, lo, hi in SLOTS:
            if lo <= hour <= hi:
                slot = by_day.setdefault(date, {})
                slot[label] = max(slot.get(label, 0), pop)
                break

    d = wx.get("daily", {})
    dates = d.get("time", [])
    labels = ["วันนี้", "พรุ่งนี้", "มะรืนนี้"]
    out = [f"พยากรณ์อากาศ {name}:"]
    for i, date in enumerate(dates[:3]):
        desc = WEATHER_CODES.get(d["weather_code"][i], "ไม่ทราบสภาพ")
        line = (f"- {labels[i]} ({date}): {desc} "
                f"อุณหภูมิ {d['temperature_2m_min'][i]}-{d['temperature_2m_max'][i]}°C "
                f"โอกาสฝนสูงสุด {d['precipitation_probability_max'][i]}%")
        slots = by_day.get(date, {})
        if slots:
            parts = [f"{lbl} {slots[lbl]}%" for lbl, _, _ in SLOTS if lbl in slots]
            line += "\n    ช่วงเวลา: " + " / ".join(parts)
        out.append(line)
    return "\n".join(out)


async def extract_city(user_message: str) -> str:
    """ให้โมเดลดึงชื่อเมือง/จังหวัดจากคำถาม (เป็นอังกฤษ) ถ้าไม่ระบุใช้ Chumphon"""
    prompt = [
        {"role": "system", "content":
            "ผู้ใช้ถามเรื่องอากาศ จงตอบเฉพาะชื่อเมือง/จังหวัดเป็นภาษาอังกฤษคำเดียว "
            "เช่น Bangkok, Nakhon Si Thammarat, Chiang Mai ถ้าผู้ใช้ไม่ได้ระบุเมือง ให้ตอบ Chumphon "
            "ห้ามมีคำอธิบายอื่น"},
        {"role": "user", "content": user_message},
    ]
    payload = {"model": MODEL, "messages": prompt, "stream": False,
               "think": False, "options": {"temperature": 0.1}}
    try:
        data = await _get_json_post(payload)
        c = (data["message"].get("content", "") or "").strip()
        if "</think>" in c:
            c = c.rsplit("</think>", 1)[-1]
        c = c.strip().strip('"').splitlines()[0].strip()
        return c or "Chumphon"
    except Exception:
        return "Chumphon"


async def _get_json_post(payload):
    async with aiohttp.ClientSession() as s:
        async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
            return await r.json()


# ============================================================
#  ⛽  เครื่องมือราคาน้ำมัน — ดึงตารางจริงจาก Kapook แล้ว parse เอง
#      (ไม่ให้โมเดลเดาตัวเลขจาก snippet จึงแม่นทุกชนิด/ทุกยี่ห้อ)
# ============================================================
OIL_URL = "https://gasprice.kapook.com/gasprice.php"
OIL_BRANDS = {
    "ptt": "ปตท.", "bcp": "บางจาก", "shell": "เชลล์", "caltex": "คาลเท็กซ์",
    "irpc": "ไออาร์พีซี", "pt": "พีที", "susco": "ซัสโก้", "pure": "เพียว",
    "suscodealers": "ซัสโก้ ดีลเลอร์",
}


async def get_oil_price(brand: str = "ptt") -> str:
    """ดึงราคาน้ำมันวันนี้จาก Kapook เฉพาะยี่ห้อที่ต้องการ (ค่าเริ่มต้น = ปตท.)"""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(OIL_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30) as r:
                html = await r.text()
    except Exception as e:
        return f"ดึงราคาน้ำมันไม่สำเร็จ: {e}"
    return parse_oil_html(html, brand)


def parse_oil_html(html: str, only_brand: str = "ptt") -> str:
    """แยกข้อมูลราคาน้ำมันจาก HTML ของ Kapook (คืนเฉพาะยี่ห้อ only_brand)
    เทคนิค: แทนทุก tag ด้วยขึ้นบรรทัดใหม่ แล้วไล่อ่านทีละบรรทัด
    ถ้าเจอราคา (เช่น 42.30) บรรทัดก่อนหน้าคือชื่อชนิดน้ำมัน"""
    parts = [p.strip() for p in re.sub(r"<[^>]+>", "\n", html).split("\n")]
    parts = [p for p in parts if p]

    date = ""
    brands, order, cur = {}, [], None
    for i, tok in enumerate(parts):
        if "อัปเดตล่าสุด" in tok and not date:
            date = tok
        mb = re.search(r"\((ptt|bcp|shell|caltex|irpc|pt|susco|pure|suscodealers)\)", tok)
        if mb:
            cur = mb.group(1)
            brands[cur] = []
            order.append(cur)
            continue
        if cur and re.fullmatch(r"\d{1,3}\.\d{2}", tok):
            fuel = parts[i - 1] if i > 0 else ""
            if fuel and not re.fullmatch(r"[\d.]+", fuel):
                brands[cur].append((fuel, tok))

    if not order:
        return "ดึงราคาน้ำมันไม่สำเร็จ: โครงสร้างหน้าเว็บอาจเปลี่ยนไป"

    # เลือกเฉพาะยี่ห้อที่ต้องการ ถ้าไม่เจอก็ใช้ยี่ห้อแรกที่มี
    code = only_brand if brands.get(only_brand) else order[0]
    rows = brands.get(code) or []

    lines = [date or "ราคาน้ำมันวันนี้", f"\n[{OIL_BRANDS.get(code, code)}]"]
    for fuel, price in rows:
        lines.append(f"  {fuel}: {price} บาท/ลิตร")
    lines.append("\n(ที่มา: Kapook อ้างอิงสำนักงานนโยบายและแผนพลังงาน กระทรวงพลังงาน)")
    return "\n".join(lines)


# ============================================================
#  🔌  เครื่องมือแจ้งตัดไฟ — ดึงจากการไฟฟ้าส่วนภูมิภาค (PEA)
# ============================================================
HOME_PROVINCE_ID = 69          # ชุมพร (เปลี่ยนเป็นจังหวัดอื่นได้)
HOME_PROVINCE_NAME = "ชุมพร"


def _parse_pea_date(s):
    """แปลง '/Date(1782781200000)/' เป็น datetime (หรือ None)"""
    import re as _re
    from datetime import datetime, timezone, timedelta
    if not s:
        return None
    m = _re.search(r"(\d+)", s)
    if not m:
        return None
    try:
        # PEA ส่งเป็น epoch milliseconds (เขตเวลาไทย UTC+7)
        ts = int(m.group(1)) / 1000
        return datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=7)))
    except Exception:
        return None


async def get_power_outage(province_id=HOME_PROVINCE_ID, province_name=HOME_PROVINCE_NAME) -> str:
    """ดึงประกาศตัดไฟของจังหวัด (เฉพาะที่ยังไม่ผ่าน) จาก PEA
    คืนข้อความสรุป หรือข้อความว่าไม่มี"""
    url = "https://eservice.pea.co.th/PowerOutage/Home/GetOutages"
    post_data = b"draw=1&start=0&length=500"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(url, data=post_data, headers=headers, timeout=30) as r:
                if r.status != 200:
                    return f"ตอนนี้ดึงข้อมูลตัดไฟไม่ได้ค่ะ (สถานะ {r.status})"
                data = await r.json(content_type=None)
    except Exception:
        return "ตอนนี้เชื่อมต่อระบบแจ้งตัดไฟของการไฟฟ้าไม่ได้ค่ะ ลองใหม่อีกทีนะคะ"

    items = data.get("data", []) if isinstance(data, dict) else []
    # กรองเฉพาะจังหวัดที่ต้องการ
    mine = [x for x in items
            if x.get("PROVINCE_ID") == province_id or x.get("PROVINCE") == province_name]

    # เก็บเฉพาะที่ยังไม่จบ (เวลาจบ >= ตอนนี้) แล้วเรียงตามเวลาเริ่ม
    from datetime import datetime, timezone, timedelta
    now = datetime.now(tz=timezone(timedelta(hours=7)))
    upcoming = []
    for x in mine:
        end = _parse_pea_date(x.get("END_DATE"))
        if end is None or end >= now:
            upcoming.append(x)
    upcoming.sort(key=lambda x: _parse_pea_date(x.get("START_DATE")) or now)

    if not upcoming:
        return (f"ตอนนี้ยังไม่มีประกาศตัดไฟที่กำลังจะถึงในจังหวัด{province_name}นะคะ "
                "(ข้อมูลจากการไฟฟ้าส่วนภูมิภาค)")

    out = [f"ประกาศตัดไฟจังหวัด{province_name} ที่กำลังจะถึง (ข้อมูลจากการไฟฟ้าส่วนภูมิภาค):"]
    for x in upcoming[:6]:
        area = x.get("AREA", "").strip()
        start = x.get("START_DATE_DISPLAY", "?")
        end = x.get("END_DATE_DISPLAY", "?")
        # END_DATE_DISPLAY มักเป็น 'dd/mm/yyyy hh:mm' เอาเฉพาะเวลาท้าย
        end_time = end.split(" ")[-1] if " " in end else end
        out.append(f"- {start} ถึง {end_time} | บริเวณ {area}")
    return "\n".join(out)


# ============================================================
#  🧭  ตัวจัดเส้นทาง — ดูว่าคำถามต้องดึง "ข้อมูลจริง" แบบไหน (เวลา/อากาศ/น้ำมัน/ค้นเว็บ)
# ============================================================
async def _search_places(place_query: str, province: str):
    """ค้นร้าน/สถานที่จริงตามจังหวัด แล้วคืนข้อความสั่งรอสเต้ให้เล่าจากข้อมูลจริง
    ลำดับ: Google Maps (ถ้ามี SerpApi key, ข้อมูลร้านสะอาดสุด) → ค้นเว็บธรรมดา (สำรอง)"""
    # ทางหลัก: Google Maps ผ่าน SerpApi — ได้ชื่อร้าน/เรตติ้ง/ที่อยู่/เวลาเปิด สะอาด
    if SERPAPI_KEY:
        # ตัดคำบอกตำแหน่งออกจาก query เพราะใส่ใน location แล้ว (เลี่ยงซ้ำซ้อน)
        maps_q = place_query.replace(province, "").strip() or place_query
        print(f"   🗺️ ค้นร้านผ่าน Google Maps: q={maps_q!r} location={province!r}")
        maps_result = await asyncio.to_thread(search_places_serpapi, maps_q, province)
        if maps_result:
            return (f"[ระบบ: ผลค้นร้าน/สถานที่จริงจาก Google Maps แถว{province} ด้านล่างเป็นข้อมูลภายใน "
                    "มีชื่อร้าน เรตติ้ง ที่อยู่ เวลาเปิด (ตามที่มี) "
                    "ให้รอสเต้เลือกแนะนำ 2-4 ร้านที่น่าสนใจ เล่าด้วยน้ำเสียงตัวเองแบบเป็นกันเอง "
                    "อ้างชื่อร้าน/เรตติ้งตามข้อมูลเป๊ะ ห้ามแต่งเพิ่ม ถ้าไม่มีข้อมูลบางอย่างก็ไม่ต้องใส่ "
                    "ปิดท้ายชวนให้ผู้ใช้บอกถ้าอยากได้เจาะจงขึ้น]\n\n[ข้อมูลภายใน]\n" + maps_result)
        print("   ↳ Maps ไม่ได้ผล ลองค้นเว็บธรรมดาสำรอง")

    # ทางสำรอง: ค้นเว็บธรรมดา (ddg หรือ SerpApi web)
    query = await make_search_query(f"{place_query} {province}")
    if province not in query:
        query = f"{query} {province}"  # กันคำค้นหลุดจังหวัด
    print(f"   🍜 ค้นหาร้าน/สถานที่ (เว็บ): {query!r}")
    results = await asyncio.to_thread(search_web, query, 6, "th-th")
    failed = (not results) or results.startswith(("ไม่พบผลการค้นหา", "ค้นเว็บไม่"))
    if failed:
        return (f"[ระบบ: ค้นหาร้านแถว{province}แล้วไม่พบข้อมูลที่ชัดเจน "
                "ให้บอกตรงๆ ว่าหาร้านที่แน่ใจไม่ได้ตอนนี้ อาจชวนผู้ใช้ระบุให้เจาะจงขึ้น "
                "(เช่น อำเภอ หรือชนิดอาหาร) ห้ามเดาชื่อร้านเอง]")
    return (f"[ระบบ: ผลค้นหาร้าน/สถานที่จริงแถว{province} ด้านล่างเป็นข้อมูลภายในสำหรับรอสเต้อ้างอิง "
            "ให้เลือกแนะนำ 2-4 ที่ที่ดูน่าสนใจ เล่าด้วยน้ำเสียงตัวเองแบบเป็นกันเอง "
            "บอกชื่อร้านตามข้อมูลเป๊ะ ห้ามแต่งชื่อหรือรายละเอียดเพิ่มเอง "
            "ถ้าข้อมูลไม่มีรายละเอียด (เวลาเปิด/เมนู) ก็ไม่ต้องแต่งใส่ "
            "ปิดท้ายชวนให้ผู้ใช้บอกถ้าอยากได้แบบเจาะจงขึ้น]\n\n[ข้อมูลภายใน]\n" + results)


async def get_realtime_context(user_message: str, mem: dict = None, user_id=None):
    """คืนข้อความข้อมูลจริงสำหรับแปะเข้ากับคำถาม (หรือ None ถ้าไม่ต้อง)"""
    if mem is None:
        mem = {}
    t = user_message.lower()

    # 🕐 เวลา/วันที่
    if any(k in t for k in ("กี่โมง", "กี่นาฬิกา", "เวลาตอนนี้", "วันนี้วันที่",
                            "วันที่เท่าไหร่", "วันนี้วันอะไร", "วันอะไร")):
        print("   🕐 ดึงเวลาจริง")
        return f"[ระบบ: เวลาปัจจุบันจริง ใช้ข้อมูลนี้ตอบ]\n{get_thai_datetime()}"

    # 🌦️ อากาศ
    if any(k in t for k in ("อากาศ", "ฝน", "ฝนตก", "พยากรณ์", "ร้อนไหม", "หนาว",
                            "weather", "อุณหภูมิ", "กี่องศา")):
        city = await extract_city(user_message)
        # ลองกรมอุตุฯ (TMD) ก่อน — แม่นสำหรับไทย
        province_th = EN_TO_TH_PROVINCE.get(city.lower().strip())
        info = None
        if province_th:
            print(f"   🌦️ ดึงอากาศ (TMD): {province_th!r}")
            info = await get_weather_tmd(province_th)
        # ถ้า TMD ไม่ได้ (ไม่มีในแผนที่จังหวัด/ดึงพลาด) ใช้ Open-Meteo สำรอง
        if not info:
            print(f"   🌦️ ดึงอากาศ (Open-Meteo สำรอง): {city!r}")
            info = await get_weather(city)
        return ("[ข้อมูลพยากรณ์อากาศจริงด้านล่างนี้เป็นข้อมูลภายในสำหรับรอสเต้ใช้อ้างอิง "
                "ห้ามลอกมาแสดงเป็นลิสต์หรือท่องตัวเลขทุกค่า ให้รอสเต้ 'เล่า' ด้วยน้ำเสียงตัวเองแบบเป็นกันเอง "
                "เหมือนเพื่อนเล่าให้ฟัง โดยเน้นวันหรือช่วงที่ผู้ใช้ถามเป็นหลัก "
                "ถ้าถามแค่วันนี้ ตอบสั้นๆ 2-4 ประโยค ถ้าถามหลายวัน/ทั้งสัปดาห์ ให้สรุปภาพรวมแนวโน้มหลายวัน "
                "(เช่น วันไหนฝน วันไหนแดดดี) แบบกระชับ ไม่ต้องไล่ทีละวันครบทุกค่า "
                "บอกสภาพอากาศและช่วงฝน (ถ้ามี) แบบเป็นธรรมชาติ เช่น 'วันนี้น่าจะมีฝนช่วงบ่ายถึงค่ำนะคะ' "
                "สำคัญมาก: ใช้คำบรรยายสภาพอากาศตามข้อมูลเป๊ะ ห้ามเติมคำที่ขัดกันเอง "
                "(ถ้าข้อมูลบอก 'มีเมฆเป็นส่วนมาก' ห้ามพูดว่า 'แจ่มใส' เด็ดขาด — เลือกพูดอย่างใดอย่างหนึ่งตามข้อมูล) "
                "ปรับน้ำเสียงตามสภาพ: ฝนตก→ห่วงเรื่องพกร่ม, ร้อน→เตือนดื่มน้ำ/กันแดด, เย็นสบาย→ชวนออกไปข้างนอก "
                "ห้ามแต่งตัวเลขเอง และปิดท้ายบอกแบบแนบเนียนว่าอ้างอิงข้อมูลกรมอุตุนิยมวิทยา]\n\n[ข้อมูลภายใน]\n" + info)

    # 🔌 ตัดไฟ — ดึงประกาศจากการไฟฟ้าส่วนภูมิภาค (PEA)
    if any(k in t for k in ("ตัดไฟ", "ดับไฟ", "ไฟดับ", "งดจ่ายไฟ", "หยุดจ่ายไฟ",
                            "ไฟจะดับ", "ประกาศดับไฟ", "ไฟฟ้าดับ")):
        print(f"   🔌 ดึงประกาศตัดไฟ {HOME_PROVINCE_NAME} (PEA)")
        info = await get_power_outage()
        return ("[ข้อมูลประกาศตัดไฟจริงจากการไฟฟ้าส่วนภูมิภาคด้านล่างเป็นข้อมูลภายใน "
                "ให้รอสเต้เล่าด้วยน้ำเสียงตัวเองแบบเป็นกันเองและห่วงใย ไม่ใช่อ่านลิสต์ดิบ "
                "บอกวัน เวลา และบริเวณที่จะตัดไฟ เรียงจากใกล้สุด ถ้ามีหลายรายการสรุปให้กระชับ "
                "เตือนให้เตรียมตัว (ชาร์จแบต/สำรองน้ำ) แบบสั้นๆ "
                "ถ้าไม่มีประกาศก็บอกตามนั้น ห้ามแต่งวันเวลาหรือสถานที่เพิ่มเอง "
                "ปิดท้ายบอกว่าข้อมูลจากการไฟฟ้าส่วนภูมิภาค]\n\n[ข้อมูลภายใน]\n" + info)

    # ⛽ ราคาน้ำมัน — ดึงตารางจริงจาก Kapook (ยึด ปตท. เว้นแต่ระบุยี่ห้ออื่น)
    if any(k in t for k in ("น้ำมัน", "ดีเซล", "เบนซิน", "แก๊สโซฮอล", "gasohol",
                            "diesel", "e20", "e85", "แก๊สโซฮอล์", "ngv")):
        # เลือกยี่ห้อตามที่ผู้ใช้พูดถึง (ไม่งั้นใช้ ปตท.)
        brand = "ptt"
        for code, name in (("bcp", "บางจาก"), ("shell", "เชลล์"), ("caltex", "คาลเท็กซ์"),
                           ("irpc", "ไออาร์พีซี"), ("pt", "พีที"), ("susco", "ซัสโก้"),
                           ("pure", "เพียว")):
            if name in user_message or code in t:
                brand = code
                break
        print(f"   ⛽ ดึงราคาน้ำมันจาก Kapook (ยี่ห้อ: {brand})")
        info = await get_oil_price(brand)
        return ("[ระบบ: ตารางราคาน้ำมันวันนี้จาก Kapook (ข้อมูลจริง มีโครงสร้างชัดเจน) "
                "ตอบโดยจับคู่ชนิดน้ำมันกับราคาให้ตรง บอกวันที่อัปเดตด้วย ใช้เฉพาะตัวเลขในตารางนี้ ห้ามแต่งเอง "
                "ปิดท้ายด้วยความเห็นสั้นๆ แบบเป็นกันเองได้ เช่นความรู้สึกต่อราคา แต่ห้ามเปลี่ยน/เพิ่มตัวเลข]\n" + info)

    # 🍜 หาร้าน/สถานที่ (ของกิน/ที่เที่ยว/ที่พัก) — ต้องรู้จังหวัดก่อนถึงจะค้นได้
    #    ลำดับ: หาจังหวัดในข้อความ → ถ้าไม่มีดูจากความจำ → ถ้ายังไม่มีให้ถามกลับ
    #    กรณีพิเศษ: ถ้าเพิ่งถามจังหวัดไป แล้วผู้ใช้ตอบจังหวัดล้วนๆ → เอามารวมกับคำถามเดิม
    pending = _pending_place.get(user_id, "")
    bare_prov = is_bare_province(user_message)
    if pending and bare_prov:
        # ผู้ใช้ตอบจังหวัดมาตามที่รอสเต้ถาม → รวมคำถามร้านเดิม + จังหวัด แล้วค้นเลย
        print(f"   🍜 ผู้ใช้ตอบจังหวัด {bare_prov!r} ต่อจากคำถามร้านที่ค้างไว้")
        _pending_place.pop(user_id, None)  # เคลียร์สถานะค้าง
        return await _search_places(f"{pending} {bare_prov}", bare_prov)

    if is_place_query(user_message):
        province = find_province_in_text(user_message) or find_saved_location(mem)
        if not province:
            # ไม่รู้ว่าผู้ใช้อยู่ไหน → จำคำถามนี้ไว้ แล้วสั่งให้รอสเต้ถามกลับ (กันเดามั่ว)
            print("   🍜 คำถามหาร้านแต่ไม่รู้จังหวัด → จำไว้ + ให้ถามกลับ")
            if user_id is not None:
                _pending_place[user_id] = user_message  # จำคำถามร้านไว้รอจังหวัด
            return ("[ระบบ: ผู้ใช้อยากให้แนะนำร้าน/สถานที่ แต่ยังไม่รู้ว่าจะหาแถวไหน "
                    "ให้รอสเต้ถามกลับสั้นๆ ด้วยน้ำเสียงตัวเองว่าอยากหาแถวจังหวัด/อำเภอไหน "
                    "ห้ามแนะนำชื่อร้านใดๆ ทั้งสิ้นในตอนนี้ เพราะยังไม่ได้ค้นข้อมูลจริง ห้ามเดาชื่อร้านเด็ดขาด]")
        _pending_place.pop(user_id, None)  # มีจังหวัดแล้ว เคลียร์สถานะค้าง
        return await _search_places(user_message, province)

    # 🔎 คำถามข้อเท็จจริงทั่วไป → ค้นเว็บ
    if needs_search(user_message):
        query = await make_search_query(user_message)
        print(f"   🔎 ค้นเว็บ: {query!r}")
        results = await asyncio.to_thread(search_web, query, 5, "th-th")
        failed = (not results) or results.startswith(("ไม่พบผลการค้นหา", "ค้นเว็บไม่"))
        if failed:
            return ("[ระบบ: ค้นเว็บแล้วไม่พบข้อมูลที่ชัดเจน ให้บอกตรงๆ ว่าหาข้อมูลที่แน่ใจไม่ได้ "
                    "ห้ามเดาชื่อ ปี ตัวเลข หรือผู้เขียนเอง]")
        return ("[ระบบ: ผลการค้นเว็บล่าสุด ให้ตอบโดยอ้างอิงเฉพาะข้อมูลนี้ ห้ามแต่งเพิ่ม "
                "ถ้าไม่พอให้บอกว่าไม่แน่ใจ เติมความเห็น/ความรู้สึกสั้นๆ ของตัวเองท้ายคำตอบได้]\n" + results)

    return None


# ============================================================
#  ส่วนการทำงาน — มือใหม่ยังไม่ต้องแก้ก็ได้
# ============================================================

intents = discord.Intents.default()
intents.message_content = True  # ต้องเปิด MESSAGE CONTENT INTENT ในเว็บ Discord ด้วย
client = discord.Client(intents=intents)


async def _chat_once(messages, temperature: float = 0.8):
    """ยิงคำขอไปที่ Ollama หนึ่งครั้ง (พร้อมเครื่องมือ) แล้วคืน message dict
    temperature ต่ำ (~0.5) = แม่นยำ เดาน้อย (ใช้ตอนตอบข้อมูลจริง)
    temperature สูง (~0.8) = มีชีวิตชีวา (ใช้ตอนคุยเล่น)"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "tools": TOOLS,
        "options": {
            "temperature": temperature,
            "repeat_penalty": 1.12,  # ลดการพูดซ้ำคำ/ประโยคแพทเทิร์นเดิม (กันฟังดูหุ่นยนต์)
        },
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(OLLAMA_URL, json=payload, timeout=300) as resp:
            data = await resp.json()
    return data["message"]


async def make_search_query(user_message: str) -> str:
    """ให้โมเดลแปลงคำถามไทยยาวๆ เป็นคีย์เวิร์ดค้นหาสั้นๆ (อังกฤษถ้าเหมาะ)
    เพราะคำค้นสั้น/อังกฤษ ให้ผลดีกว่าประโยคไทยยาวมาก"""
    prompt = [
        {"role": "system", "content":
            "หน้าที่ของคุณคือแปลงคำถามของผู้ใช้ให้เป็นคำค้นหาเว็บที่สั้นกระชับ 2-6 คำ "
            "ถ้าเป็นเรื่องสากล (สินค้า เทคโนโลยี หนังสือ ข่าวต่างประเทศ วิทยาศาสตร์) ให้ใช้ภาษาอังกฤษ "
            "ตอบกลับมาเฉพาะคำค้นเท่านั้น ห้ามมีคำอธิบาย ห้ามมีเครื่องหมายคำพูด"},
        {"role": "user", "content": user_message},
    ]
    payload = {"model": MODEL, "messages": prompt, "stream": False,
               "think": False, "options": {"temperature": 0.2}}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=120) as resp:
                data = await resp.json()
        q = data["message"].get("content", "") or ""
        if "</think>" in q:
            q = q.rsplit("</think>", 1)[-1]
        q = q.strip().strip('"').strip()
        q = q.splitlines()[0].strip() if q else ""
        return q or user_message
    except Exception:
        return user_message  # ถ้าพลาด ใช้คำถามเดิมไปก่อน


async def auto_remember(user_id: int, user_name: str, user_message: str):
    """🪄 จำเอง — เบื้องหลัง: ให้โมเดลสกัดข้อเท็จจริงถาวรเกี่ยวกับผู้ใช้ แล้วบันทึกเงียบๆ
    ทำงานหลังตอบผู้ใช้ไปแล้ว (ไม่ให้ผู้ใช้รอ) และเฉพาะข้อความที่มีแววมีข้อมูลตัวตน"""
    if not memory.should_try_extract(user_message):
        return  # กรองหยาบ: ไม่มีสัญญาณพูดถึงตัวเอง → ข้าม ประหยัด LLM call
    try:
        prompt = memory.build_extract_prompt(user_message)
        # ยิงโมเดลแบบเรียบง่าย (ไม่ใช้ tools/persona — แค่สกัดข้อมูล) temp ต่ำ = แม่น
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False, "think": False,
            "options": {"temperature": 0.2},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=120) as resp:
                data = await resp.json()
        output = data.get("message", {}).get("content", "")
        facts = memory.parse_extracted_facts(output)
        if not facts:
            return
        # บันทึกเข้า memory ผ่าน add_fact (มีกันซ้ำ/เพดานอยู่แล้ว)
        async with get_user_lock(user_id):
            mem = load_memory(user_id)
            if user_name:
                mem["name"] = user_name
            added = [f for f in facts if memory.add_fact(mem, f)]
            if added:
                save_memory(user_id, mem)
                print(f"   🪄 จำเองเพิ่ม {len(added)} เรื่อง: {added}")
    except Exception as e:
        print(f"   ⚠️ จำเองพลาด (ไม่กระทบการตอบ): {e}")


async def summarize_old_history(user_id: int, pairs: list):
    """📝 Background: สรุปบทสนทนาเก่าที่ถูกตัดออกจาก history เก็บเป็น 1 บรรทัดใน summaries"""
    if not pairs:
        return
    try:
        prompt = memory.build_summary_prompt(pairs)
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False, "think": False,
            "options": {"temperature": 0.3},
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=120) as resp:
                data = await resp.json()
        text = data.get("message", {}).get("content", "") or ""
        if "</think>" in text:
            text = text.rsplit("</think>", 1)[-1]
        text = text.strip().splitlines()[0].strip()
        if not text:
            return
        from datetime import date as _date
        d = _date.today()
        entry = f"{d.day} {_THAI_MONTHS[d.month]}: {text}"
        async with get_user_lock(user_id):
            mem = load_memory(user_id)
            summaries = mem.get("summaries", [])
            summaries.append(entry)
            mem["summaries"] = summaries[-memory.MAX_SUMMARIES:]
            save_memory(user_id, mem)
            print(f"   📝 สรุปบท: {entry}")
    except Exception as e:
        print(f"   ⚠️ สรุปบทพลาด (ไม่กระทบการตอบ): {e}")


async def ask_ollama(user_id: int, user_name: str, user_message: str) -> str:
    """ส่งข้อความไปให้ Ollama โดยใช้ความจำของผู้ใช้คนนี้ + ค้นเว็บได้ถ้าจำเป็น"""
    mem = load_memory(user_id)
    if user_name:
        mem["name"] = user_name  # อัปเดตชื่อเรียกล่าสุดเสมอ

    # 🧠 สร้างบล็อก "สิ่งที่รอสเต้จำได้เกี่ยวกับคนนี้" แล้วต่อท้าย system prompt
    #    ใช้ selective recall — ดึงเฉพาะ fact ที่เกี่ยวกับข้อความนี้ (กัน context ล้น)
    profile_lines = []
    if mem.get("name"):
        profile_lines.append(f"- ชื่อเรียก: {mem['name']}")
    for fact in memory.recall_facts(mem, user_message):
        profile_lines.append(f"- {fact}")

    system_text = SYSTEM_PROMPT
    if profile_lines:
        system_text += (
            "\n\nสิ่งที่คุณ (รอสเต้) จำได้เกี่ยวกับคนที่กำลังคุยด้วย "
            "(ใช้ให้เป็นธรรมชาติ ไม่ต้องท่องออกมาเอง):\n" + "\n".join(profile_lines)
        )
    summaries = mem.get("summaries", [])
    if summaries:
        system_text += (
            "\n\nเรื่องที่เคยคุยกันก่อนหน้า (บทสนทนาเก่า ใช้เป็น context เฉยๆ ไม่ต้องพูดถึงโดยตรง):\n"
            + "\n".join(f"- {s}" for s in summaries)
        )

    history = mem.get("history", [])

    # 🧭 ดึง "ข้อมูลจริง" ตามชนิดคำถาม (เวลา/อากาศ/น้ำมัน/ค้นเว็บ) แล้วแปะติดคำถาม
    # (แปะติดคำถามโดยตรง ชัวร์กว่าการแทรก system message แยก เพราะโมเดลเห็นแน่นอน)
    augmented_message = user_message
    realtime = await get_realtime_context(user_message, mem, user_id)
    if realtime:
        augmented_message = f"{user_message}\n\n{realtime}"

    # มีข้อมูลจริงแปะมา → ใช้ temperature ต่ำ (แม่นยำ เดาน้อย)
    # คุยเล่นปกติ → ใช้ค่าสูงกว่า (มีชีวิตชีวา คาแร็กเตอร์ออก)
    reply_temp = 0.5 if realtime else 0.8

    messages = (
        [{"role": "system", "content": system_text}]
        + FEWSHOT_EXAMPLES
        + history
        + [{"role": "system", "content": build_author_note()}]  # 🌙 ฉีดกฎ+อารมณ์ ติดคำตอบ
        + [{"role": "user", "content": augmented_message}]
    )

    # 🔁 ลูปเรียกเครื่องมือ: ถ้าโมเดลขอค้นเว็บ ให้ค้นแล้วส่งผลกลับ วนได้สูงสุด 3 รอบ
    msg = {}
    for _ in range(3):
        msg = await _chat_once(messages, temperature=reply_temp)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            break  # ไม่ขอเครื่องมือแล้ว = ได้คำตอบสุดท้าย

        # เก็บข้อความที่โมเดลขอเรียกเครื่องมือไว้ในบทสนทนา
        messages.append({
            "role": "assistant",
            "content": msg.get("content", ""),
            "tool_calls": tool_calls,
        })
        # ทำตามที่ขอทีละเครื่องมือ แล้วแนบผลกลับ
        for call in tool_calls:
            fn = call["function"]["name"]
            args = call["function"].get("arguments", {}) or {}
            if fn == "search_web":
                query = args.get("query", "")
                print(f"   🔎 รอสเต้ค้นเว็บ: {query!r}")
                result = await asyncio.to_thread(search_web, query)
            else:
                result = f"ไม่รู้จักเครื่องมือ {fn}"
            messages.append({"role": "tool", "tool_name": fn, "content": result})

    reply = msg.get("content", "") or ""

    # 🧹 ถ้าโมเดลเผลอแสดงกระบวนการคิด คำตอบจริงจะอยู่หลัง </think>
    if "</think>" in reply:
        reply = reply.rsplit("</think>", 1)[-1]
    reply = reply.strip()
    if not reply:
        reply = "หืม... ขอโทษค่ะ ยังหาคำตอบที่แน่ใจไม่ได้พอดี"

    # อัปเดต history — คู่ที่ล้นออกจะถูกสรุปเก็บไว้ใน summaries แทนทิ้ง
    total = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply},
    ]
    pairs_to_summarize = total[:-MAX_HISTORY_PAIRS * 2] if len(total) > MAX_HISTORY_PAIRS * 2 else []
    new_history = total[-MAX_HISTORY_PAIRS * 2:]

    async with get_user_lock(user_id):
        fresh = load_memory(user_id)   # reload กัน overwrite facts ที่ auto_remember อาจเพิ่มไว้
        if user_name:
            fresh["name"] = user_name
        fresh["history"] = new_history
        save_memory(user_id, fresh)

    if pairs_to_summarize:
        asyncio.create_task(summarize_old_history(user_id, pairs_to_summarize))

    return reply



@client.event
async def on_ready():
    print(f"✅ ล็อกอินสำเร็จในชื่อ: {client.user}")
    print(f"🖨️ ระบบพิมพ์: {'โหมดจริง' if printing.PRINT_REAL_MODE else 'โหมดจำลอง (ยังไม่สั่งเครื่องจริง)'}")
    print("บอทพร้อมทำงานแล้ว! ลอง @ ชื่อบอทในเซิร์ฟเวอร์ หรือทักผ่าน DM ได้เลย")


@client.event
async def on_message(message):
    # ไม่ตอบข้อความของตัวเอง (กันลูป)
    if message.author == client.user:
        return

    # 🔍 รายงานทุกข้อความที่บอทเห็น (ไว้ดีบัก ดูที่หน้าต่าง PowerShell)
    is_dm = message.guild is None
    is_mention = client.user in message.mentions
    print(f"[เห็นข้อความ] จาก {message.author} | DM={is_dm} | ถูก@={is_mention} | เนื้อหา={message.content!r}")

    # ตอบเมื่อ: ถูก @mention ในห้อง หรือ ถูกทักผ่าน DM
    if not (is_dm or is_mention):
        print("   ↳ ข้าม: ไม่ได้ถูก @ และไม่ใช่ DM")
        return

    # ลบส่วน mention ออกจากข้อความ เหลือแค่เนื้อหาที่ผู้ใช้พิมพ์
    user_message = re.sub(r"<@!?\d+>", "", message.content).strip()
    if not user_message:
        print("   ↳ ข้าม: ข้อความว่างหลังตัด mention "
              "(มักเพราะ MESSAGE CONTENT INTENT ยังไม่เปิดในเว็บ Discord)")
        return

    print(f"   ↳ ส่งให้โมเดล: {user_message!r}")

    user_id = message.author.id
    user_name = message.author.display_name

    # ===== 🖨️ ระบบพิมพ์ PDF (อยู่ในไฟล์ printing.py) =====
    # หาไฟล์ PDF ที่แนบมา (ถ้ามี) และดูว่าข้อความสื่อถึงการพิมพ์ไหม
    pdf_attach = next(
        (a for a in message.attachments if a.filename.lower().endswith(".pdf")), None)
    wants_print = any(k in user_message.lower() for k in printing.PRINT_TRIGGERS)

    # ถ้ากำลังพิมพ์งานอื่นอยู่ — ล็อก ตอบว่ายุ่งก่อน (ทุกข้อความ)
    if printing.print_lock.locked():
        await message.reply(
            "ขอโทษค่ะ ตอนนี้รอสเต้กำลังพิมพ์งานอยู่ ขอพิมพ์ให้เสร็จก่อนนะคะ เดี๋ยวมาคุยต่อค่ะ")
        return

    # ยืนยันงานใหญ่ที่ค้างอยู่ (ต้องเป็นคนสั่งคนเดิม)
    if user_message.strip() in ("ยืนยัน", "ยืนยันค่ะ", "ยืนยันครับ") and user_id in printing.pending_prints:
        job = printing.pending_prints.pop(user_id)
        print(f"   🖨️ ยืนยันพิมพ์: {job['filename']} × {job['copies']} ชุด")
        await printing.run_print_job(message, job)
        return

    # คำสั่งพิมพ์ใหม่: ต้องมีไฟล์ PDF แนบ + มีคำว่าพิมพ์
    if pdf_attach and wants_print:
        print(f"   🖨️ รับคำสั่งพิมพ์: {pdf_attach.filename}")
        await printing.start_print_request(message, user_id, user_name, pdf_attach, user_message)
        return

    # ===== 🎵 ระบบเพลง (อยู่ในไฟล์ music.py) =====
    wants_song = ("เพลง" in user_message and
                  any(w in user_message for w in ("ร้อง", "เปิด", "เล่น", "ขอ")))
    if wants_song:
        if music.voice_lock.locked():
            await message.reply("ตอนนี้รอสเต้กำลังร้องเพลงอยู่ รอเพลงนี้จบก่อนนะคะ")
            return
        # ผู้สั่งต้องอยู่ในห้อง voice ก่อน
        if not message.author.voice or not message.author.voice.channel:
            await message.reply("เข้าห้อง voice ก่อนนะคะ แล้วรอสเต้จะตามเข้าไปร้องให้ค่ะ~")
            return
        query = music.extract_song_query(user_message)
        if not query:
            await message.reply("อยากให้ร้องเพลงไหนเหรอคะ? บอกชื่อเพลงมาได้เลยค่ะ")
            return
        result = music.find_song(query)
        music.log_song_request(user_name, query, found=bool(result))
        if result:
            song_path, song_name = result
            print(f"   🎵 เล่นเพลง: {song_name} (ขอโดย {user_name})")
            await music.play_song_in_voice(message, song_path, song_name)
        else:
            print(f"   🎵 ไม่มีเพลง: {query!r} (ขอโดย {user_name})")
            await message.reply(random.choice(music.NOT_FOUND_LINES).format(q=query))
        return

    # เช็กก่อนว่าเป็น "คำสั่งความจำ" ไหม (เช่น จำไว้ว่า...) ถ้าใช่ตอบเลยไม่ต้องเรียกโมเดล
    mem_reply = handle_memory_command(user_id, user_name, user_message)
    if mem_reply is not None:
        print("   ↳ จัดการคำสั่งความจำ")
        await message.reply(mem_reply)
        return

    # แสดงสถานะ "กำลังพิมพ์..." ระหว่างรอโมเดลคิด
    async with message.channel.typing():
        try:
            reply = await ask_ollama(user_id, user_name, user_message)
            print(f"   ↳ ได้คำตอบแล้ว ({len(reply)} ตัวอักษร)")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if "Timeout" in type(e).__name__:
                reply = "หืม... ขอโทษค่ะ คิดนานเกินไปจนหมดเวลาพอดี (โมเดลอาจกำลังรันบน CPU เลยช้า)"
            else:
                reply = f"ขอโทษค่ะ มีข้อผิดพลาด ({err}) ลองเช็กว่า Ollama เปิดอยู่ไหมนะคะ"
            print(f"   ↳ ❌ ERROR: {err}")

    # Discord จำกัดข้อความไม่เกิน 2000 ตัวอักษร
    if len(reply) > 2000:
        reply = reply[:1990] + "…"

    await message.reply(reply)

    # 🪄 จำเอง — ทำเบื้องหลังหลังตอบไปแล้ว (ไม่บล็อก ผู้ใช้ไม่ต้องรอ)
    #    เฉพาะข้อความที่ไม่ใช่คำสั่ง/เพลง และผ่านการกรองหยาบใน auto_remember
    asyncio.create_task(auto_remember(user_id, user_name, user_message))


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
