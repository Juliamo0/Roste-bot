# ทดสอบดึงข้อมูลตัดไฟจาก PEA แล้วกรองเฉพาะชุมพร
# วิธีใช้: python test_outage.py
import json
import urllib.request

URL = "https://eservice.pea.co.th/PowerOutage/Home/GetOutages"
PROVINCE_ID = 69          # ชุมพร
PROVINCE_NAME = "ชุมพร"

# DataTables มักส่ง POST แบบ form — ลองส่งพารามิเตอร์พื้นฐาน
post_data = "draw=1&start=0&length=500".encode("utf-8")

req = urllib.request.Request(URL, data=post_data, method="POST")
req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
req.add_header("X-Requested-With", "XMLHttpRequest")
req.add_header("User-Agent", "Mozilla/5.0")
req.add_header("Accept", "application/json")

print(f"=== ทดสอบดึงตัดไฟ PEA (กรองเฉพาะ {PROVINCE_NAME}) ===\n")
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error {e.code}: {e.reason}")
    print(e.read().decode("utf-8", "ignore")[:500])
    raise SystemExit
except Exception as e:
    print(f"❌ เชื่อมต่อไม่สำเร็จ: {type(e).__name__}: {e}")
    raise SystemExit

try:
    data = json.loads(raw)
except Exception:
    print("❌ แปลง JSON ไม่ได้ ข้อมูลดิบ 500 ตัวแรก:")
    print(raw[:500])
    raise SystemExit

items = data.get("data", [])
print(f"✅ ดึงสำเร็จ! ได้ทั้งหมด {len(items)} รายการทั่วประเทศ\n")

# กรองเฉพาะชุมพร
chumphon = [x for x in items if x.get("PROVINCE_ID") == PROVINCE_ID
            or x.get("PROVINCE") == PROVINCE_NAME]
print(f"🔌 พบตัดไฟใน{PROVINCE_NAME}: {len(chumphon)} รายการ\n")

for i, x in enumerate(chumphon, 1):
    print(f"[{i}] {x.get('PROVINCE')} - {x.get('PEA_OFFICE','')}")
    print(f"    พื้นที่: {x.get('AREA','')}")
    print(f"    เริ่ม: {x.get('START_DATE_DISPLAY','?')}  ถึง  {x.get('END_DATE_DISPLAY','?')}")
    detail = (x.get('DETAIL','') or '').replace('\r\n', ' ').replace('\n', ' ')
    print(f"    รายละเอียด: {detail[:120]}")
    print()

print("--- เอาผลนี้ไปให้ผู้ช่วยดู เพื่อเขียนลง bot.py ---")
