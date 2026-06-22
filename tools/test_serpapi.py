# ============================================================
#  ทดสอบว่า SerpApi key ใช้ได้จริงไหม — รันแยกจากบอท
#  วิธีรัน: เปิด PowerShell ในโฟลเดอร์โปรเจกต์ แล้วพิมพ์  python test_serpapi.py
# ============================================================
import requests

# อ่าน key จาก config.py (ที่เดียวกับบอท)
try:
    from config import SERPAPI_KEY
except ImportError:
    print("❌ ไม่พบ config.py หรือไม่มี SERPAPI_KEY ในนั้น")
    raise SystemExit

if not SERPAPI_KEY or SERPAPI_KEY.startswith("วาง_"):
    print("❌ ยังไม่ได้ใส่ SERPAPI_KEY จริงใน config.py (ยังเป็นค่าตัวอย่างอยู่)")
    raise SystemExit

print(f"✅ อ่าน key ได้: {SERPAPI_KEY[:8]}...{SERPAPI_KEY[-4:]} (ซ่อนตรงกลางไว้)")
print("=" * 55)


def call(params, label):
    """ยิง SerpApi หนึ่งครั้ง แล้วรายงานผล"""
    params = dict(params, api_key=SERPAPI_KEY)
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
    except Exception as e:
        print(f"❌ {label}: ต่อเน็ตไม่ได้ — {e}")
        return None
    if r.status_code == 401:
        print(f"❌ {label}: key ผิดหรือหมดอายุ (401 Unauthorized)")
        return None
    if r.status_code == 429:
        print(f"❌ {label}: โควต้าหมด หรือยิงถี่เกินไป (429)")
        return None
    if r.status_code != 200:
        print(f"❌ {label}: สถานะ {r.status_code}")
        return None
    return r.json()


# ── เทสต์ 1: Google Maps (หาร้าน) ──
print("[1] ทดสอบ Google Maps — ค้น 'ร้านก๋วยเตี๋ยว ชุมพร'")
data = call({"engine": "google_maps", "type": "search",
             "q": "ร้านก๋วยเตี๋ยว ชุมพร", "hl": "th"}, "Maps")
if data:
    places = data.get("local_results") or []
    if not places and data.get("place_results"):
        places = [data["place_results"]]
    if places:
        print(f"    ✅ เจอ {len(places)} ร้าน — ตัวอย่าง 3 ร้านแรก:")
        for p in places[:3]:
            name = p.get("title", "?")
            rating = p.get("rating", "-")
            reviews = p.get("reviews", "-")
            print(f"       • {name} (⭐{rating}, {reviews} รีวิว)")
    else:
        print("    ⚠️ ยิงได้แต่ไม่เจอร้าน (ลองเปลี่ยนคำค้น/จังหวัด)")
print()

# ── เทสต์ 2: Google Search (ค้นเว็บทั่วไป) ──
print("[2] ทดสอบ Google Search — ค้น 'ข่าวเทคโนโลยี'")
data = call({"engine": "google", "q": "ข่าวเทคโนโลยี", "hl": "th", "gl": "th", "num": 3}, "Search")
if data:
    organic = data.get("organic_results") or []
    if organic:
        print(f"    ✅ เจอ {len(organic)} ผลลัพธ์ — ตัวอย่างหัวข้อแรก:")
        print(f"       • {organic[0].get('title', '?')}")
    else:
        print("    ⚠️ ยิงได้แต่ไม่มีผลลัพธ์")

    # เช็คโควต้าคงเหลือ (SerpApi ส่งมาใน search_metadata บางที)
    info = data.get("search_metadata", {})
    if info:
        print(f"    ℹ️ สถานะคำขอ: {info.get('status', '-')}")
print()
print("=" * 55)
print("เสร็จแล้ว — ถ้าเห็น ✅ ทั้งสองข้อ แปลว่า key ใช้ได้จริง พร้อมรันบอทได้เลย")
print("ดูโควต้าคงเหลือได้ที่ https://serpapi.com/dashboard (มุมขวาบน X/250)")
