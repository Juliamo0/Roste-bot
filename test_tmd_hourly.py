# ทดสอบ TMD API รายชั่วโมง (hourly) — ดูว่าได้ข้อมูลฝนแยกตามชั่วโมงไหม
# วิธีใช้: python test_tmd_hourly.py
import json
import urllib.parse
import urllib.request

try:
    from config import TMD_TOKEN
except Exception:
    print("❌ ไม่พบ TMD_TOKEN ใน config.py")
    raise SystemExit

PROVINCE = "ชุมพร"
DURATION = 24          # ขอ 24 ชั่วโมงข้างหน้า
FIELDS = "tc,rh,cond,rain"   # รายชั่วโมงใช้ tc (ไม่ใช่ tc_max/min)

base = "https://data.tmd.go.th/nwpapi/v1/forecast/location/hourly/place"
params = urllib.parse.urlencode({
    "province": PROVINCE,
    "fields": FIELDS,
    "duration": DURATION,
})
url = f"{base}?{params}"

print(f"=== ทดสอบ TMD รายชั่วโมง: {PROVINCE} ({DURATION} ชม.) ===\n")
req = urllib.request.Request(url)
req.add_header("accept", "application/json")
req.add_header("authorization", f"Bearer {TMD_TOKEN}")

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error {e.code}: {e.reason}")
    print("รายละเอียด:", e.read().decode("utf-8", "ignore")[:500])
    raise SystemExit
except Exception as e:
    print(f"❌ เชื่อมต่อไม่สำเร็จ: {type(e).__name__}: {e}")
    raise SystemExit

print("✅ สำเร็จ! ข้อมูลดิบ (ตัด 4000 ตัวอักษรแรก):\n")
try:
    data = json.loads(raw)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
except Exception:
    print(raw[:4000])
print("\n--- เอาผลนี้ไปให้ผู้ช่วยดู เพื่อทำ 'ฝนตอนไหนของวัน' ---")
