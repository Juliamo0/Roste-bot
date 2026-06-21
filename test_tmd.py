# ทดสอบ TMD API (กรมอุตุนิยมวิทยา) — ดูว่าดึงข้อมูลได้ไหม + มี field อะไรบ้าง
# วิธีใช้: python test_tmd.py
# ต้องมี TMD_TOKEN ใน config.py ก่อน
import json
import urllib.parse
import urllib.request

try:
    from config import TMD_TOKEN
except Exception:
    print("❌ ไม่พบ TMD_TOKEN ใน config.py — เพิ่มบรรทัด TMD_TOKEN = \"...\" ก่อน")
    raise SystemExit

PROVINCE = "ชุมพร"      # เปลี่ยนเป็นจังหวัดที่อยากเช็กได้
DURATION = 3            # ขอพยากรณ์กี่วัน

# ขอหลาย field เพื่อดูว่ามีอะไรให้บ้าง (tc=อุณหภูมิ, rh=ความชื้น, cond=สภาพอากาศ, rain=ฝน)
FIELDS = "tc_max,tc_min,rh,cond,rain"

base = "https://data.tmd.go.th/nwpapi/v1/forecast/location/daily/place"
params = urllib.parse.urlencode({
    "province": PROVINCE,
    "fields": FIELDS,
    "duration": DURATION,
})
url = f"{base}?{params}"

print(f"=== ทดสอบ TMD API: {PROVINCE} (ขอ {DURATION} วัน) ===\n")
print(f"URL: {url}\n")

req = urllib.request.Request(url)
req.add_header("accept", "application/json")
req.add_header("authorization", f"Bearer {TMD_TOKEN}")

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error {e.code}: {e.reason}")
    print("รายละเอียด:", e.read().decode("utf-8", "ignore")[:500])
    print("\nถ้า 401/403 = token ผิด/หมดอายุ | 400 = field หรือ parameter ผิด")
    raise SystemExit
except Exception as e:
    print(f"❌ เชื่อมต่อไม่สำเร็จ: {type(e).__name__}: {e}")
    raise SystemExit

print("✅ ดึงข้อมูลสำเร็จ! ข้อมูลดิบที่ได้:\n")
try:
    data = json.loads(raw)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
    print("\n--- เอาผลทั้งหมดนี้ไปให้ผู้ช่วยดู เพื่อเขียนโค้ดให้ตรง field ---")
except Exception:
    print(raw[:3000])
