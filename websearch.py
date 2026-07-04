"""
🔎 เครื่องมือค้นเว็บ — ให้รอสเต้ดึงข้อมูลจริงแทนการเดา
มี 2 ทาง: SerpApi (Google จริง ถ้าตั้ง SERPAPI_KEY) หรือ ddgs (ฟรี สำรอง)
ติดตั้ง:  pip install ddgs requests

แยกออกมาจาก bot.py เพราะไม่พึ่งอะไรในนั้นเลยนอกจาก config (SERPAPI_KEY)
"""
import logging
import time

logger = logging.getLogger("roste.websearch")

# SERPAPI_KEY (ค้นผ่าน Google จริง) — ไม่บังคับ ถ้าไม่มีจะใช้ ddg (ddgs) แทนอัตโนมัติ
# สมัครฟรีที่ https://serpapi.com (free plan 250 ครั้ง/เดือน) แล้ววาง key ใน config.py
try:
    from config import SERPAPI_KEY
except ImportError:
    SERPAPI_KEY = ""
# ถ้ายังเป็นค่าตัวอย่าง (ยังไม่ใส่ key จริง) ให้ถือว่าไม่ได้ตั้ง — จะได้ fallback ไป ddg
if not SERPAPI_KEY or SERPAPI_KEY.startswith("วาง_"):
    SERPAPI_KEY = ""

# ── SerpApi daily quota guard — free plan 250 ครั้ง/เดือน ≈ 8/วัน ──────────
# กันสแปมเผาโควตาทั้งเดือนหมดในไม่กี่นาที — เกิน limit ต่อวัน fallback ไป ddg อัตโนมัติ
_SERPAPI_DAILY_LIMIT = 8
_serpapi_quota_date = None
_serpapi_quota_count = 0


def _serpapi_quota_ok() -> bool:
    global _serpapi_quota_date, _serpapi_quota_count
    from datetime import date as _date
    today = _date.today()
    if _serpapi_quota_date != today:
        _serpapi_quota_date = today
        _serpapi_quota_count = 0
    if _serpapi_quota_count >= _SERPAPI_DAILY_LIMIT:
        return False
    _serpapi_quota_count += 1
    return True


# 🗃️ cache ผลค้นง่ายๆ ในหน่วยความจำ (กันยิง API ซ้ำเปลือง quota) — เก็บ 1 ชม.
_SEARCH_CACHE = {}          # key: (kind, query) -> (เวลาที่เก็บ, ผลลัพธ์)
_CACHE_TTL = 3600           # 1 ชั่วโมง


def _cache_get(kind: str, query: str):
    item = _SEARCH_CACHE.get((kind, query))
    if item and (time.time() - item[0] < _CACHE_TTL):
        logger.info(f"   💾 ใช้ผลจาก cache ({kind})")
        return item[1]
    return None


def _purge_stale_cache_entries() -> None:
    now = time.time()
    stale = [k for k, (ts, _) in _SEARCH_CACHE.items() if now - ts > _CACHE_TTL]
    for k in stale:
        del _SEARCH_CACHE[k]


def _cache_set(kind: str, query: str, value: str):
    _SEARCH_CACHE[(kind, query)] = (time.time(), value)
    _purge_stale_cache_entries()


def _serpapi_get(params: dict):
    """ยิงคำขอไป SerpApi แล้วคืน dict ผลลัพธ์ (หรือ None ถ้าพลาด)"""
    import requests
    params = dict(params, api_key=SERPAPI_KEY)
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        if r.status_code != 200:
            logger.warning(f"   ⚠️ SerpApi คืนสถานะ {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        logger.warning(f"   ⚠️ SerpApi ผิดพลาด: {e}")
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
    # ทางหลัก: SerpApi (Google จริง) ถ้าตั้ง key ไว้ และยังไม่เกินโควตาวันนี้
    if SERPAPI_KEY and _serpapi_quota_ok():
        result = search_web_serpapi(query, max_results)
        if result:
            return result
        logger.info("   ↳ SerpApi ไม่ได้ผล ลองใช้ ddg สำรอง")
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
