"""
Integration test — ยิง HTTP จริง 1 เคสต่อระบบ (Level 2)
วิธีรัน: python test_all_systems.py

รายงานผลเป็นตาราง:
  ✅  ทำงานปกติ
  ⚠️  ได้รับสัญญาณแต่แหล่งข้อมูลมีปัญหา (โควต้าหมด / ไม่มี token / ผลว่าง)
  ❌  พัง (exception หรือ parse error)

หมายเหตุ SerpApi: ใช้โควต้าสูงสุด 2 ครั้ง (web + maps)
"""
import sys
import os
import asyncio
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── ให้ import bot.py จากโฟลเดอร์เดียวกัน ────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot

ROWS = []  # [(ระบบ, สถานะ, รายละเอียด)]


def _row(name: str, status: str, detail: str = ""):
    ROWS.append((name, status, detail[:90]))
    print(f"  {status} {name[:30]}")


def _run(coro):
    return asyncio.run(coro)


print("=" * 68)
print("   test_all_systems — Integration Test (ยิง HTTP จริง)")
print("=" * 68)
print()

# ── 1. เวลา/วันที่ ────────────────────────────────────────────────────────────
print("[1] เวลา/วันที่ ...", end=" ", flush=True)
try:
    result = bot.get_thai_datetime()
    if "พ.ศ." in result and "น." in result:
        _row("เวลา/วันที่", "✅", result)
    else:
        _row("เวลา/วันที่", "❌", f"ผลผิดรูปแบบ: {result[:60]}")
except Exception as e:
    _row("เวลา/วันที่", "❌", str(e)[:60])

# ── 2. น้ำมัน (Kapook scraping) ──────────────────────────────────────────────
print("[2] น้ำมัน (Kapook) ...", end=" ", flush=True)
try:
    result = _run(bot.get_oil_price("ptt"))
    if "บาท/ลิตร" in result:
        # แสดงบรรทัดแรกที่มีราคา
        price_line = next((l for l in result.split("\n") if "บาท" in l), result[:60])
        _row("น้ำมัน (Kapook)", "✅", price_line.strip())
    elif "ไม่สำเร็จ" in result or "เปลี่ยนไป" in result:
        _row("น้ำมัน (Kapook)", "⚠️", result[:60])
    else:
        _row("น้ำมัน (Kapook)", "❌", result[:60])
except Exception as e:
    _row("น้ำมัน (Kapook)", "❌", str(e)[:60])

# ── 3. อากาศ (Open-Meteo — ไม่ต้องใช้ key) ──────────────────────────────────
print("[3] อากาศ Open-Meteo ...", end=" ", flush=True)
try:
    result = _run(bot.get_weather("Chumphon"))
    if "พยากรณ์อากาศ" in result and "วันนี้" in result:
        lines = [l for l in result.split("\n") if l.strip().startswith("-")]
        detail = lines[0].strip() if lines else result.split("\n")[0]
        _row("อากาศ (Open-Meteo)", "✅", detail[:80])
    elif "ดึงข้อมูลอากาศไม่สำเร็จ" in result or "หาตำแหน่ง" in result:
        _row("อากาศ (Open-Meteo)", "⚠️", result[:60])
    else:
        _row("อากาศ (Open-Meteo)", "❌", result[:60])
except Exception as e:
    _row("อากาศ (Open-Meteo)", "❌", str(e)[:60])

# ── 4. อากาศ (TMD — ถ้ามี token) ────────────────────────────────────────────
print("[4] อากาศ TMD ...", end=" ", flush=True)
if not bot.TMD_TOKEN or bot.TMD_TOKEN.startswith("วาง_"):
    _row("อากาศ (TMD)", "⚠️", "ไม่มี TMD_TOKEN ใน config.py — ข้าม")
else:
    try:
        result = _run(bot.get_weather_tmd("ชุมพร"))
        if result and "พยากรณ์อากาศ" in result:
            lines = result.split("\n")
            detail = lines[1].strip() if len(lines) > 1 else result[:60]
            _row("อากาศ (TMD)", "✅", detail[:80])
        elif result is None:
            _row("อากาศ (TMD)", "⚠️", "ดึงไม่ได้ — ตรวจสอบ TMD_TOKEN อาจหมดอายุ")
        else:
            _row("อากาศ (TMD)", "❌", str(result)[:60])
    except Exception as e:
        _row("อากาศ (TMD)", "❌", str(e)[:60])

# ── 5. ตัดไฟ (PEA) ─────────────────────────────────────────────────────────
print("[5] ตัดไฟ PEA ...", end=" ", flush=True)
try:
    result = _run(bot.get_power_outage())
    if "ชุมพร" in result or "ยังไม่มีประกาศ" in result or "กำลังจะถึง" in result:
        _row("ตัดไฟ (PEA)", "✅", result.split("\n")[0][:80])
    elif "เชื่อมต่อ" in result or "ดึงข้อมูล" in result:
        _row("ตัดไฟ (PEA)", "⚠️", result[:60])
    else:
        _row("ตัดไฟ (PEA)", "❌", result[:60])
except Exception as e:
    _row("ตัดไฟ (PEA)", "❌", str(e)[:60])

# ── 6. ค้นเว็บ — ทดสอบทั้ง DDG และ SerpApi แยกกัน ──────────────────────────

# 6a. DDG (forced — ปิด SerpApi ชั่วคราว)
print("[6a] ค้นเว็บ DDG ...", end=" ", flush=True)
_orig_key = bot.SERPAPI_KEY
try:
    bot.SERPAPI_KEY = ""            # force DDG
    bot._SEARCH_CACHE.clear()
    result = bot.search_web("ข่าวเทคโนโลยี", max_results=3)
    if result and not result.startswith(("ค้นเว็บไม่", "ยังไม่ได้ติดตั้ง", "ไม่พบ")):
        first = result.split("\n")[0]
        _row("ค้นเว็บ (DDG)", "✅", first[:80])
    elif "ยังไม่ได้ติดตั้ง" in result:
        _row("ค้นเว็บ (DDG)", "❌", "ddgs ไม่ได้ติดตั้ง — pip install ddgs")
    else:
        _row("ค้นเว็บ (DDG)", "⚠️", result[:60])
except Exception as e:
    _row("ค้นเว็บ (DDG)", "❌", str(e)[:60])
finally:
    bot.SERPAPI_KEY = _orig_key     # คืนค่า

# 6b. SerpApi (ถ้ามี key)
print("[6b] ค้นเว็บ SerpApi ...", end=" ", flush=True)
if not bot.SERPAPI_KEY:
    _row("ค้นเว็บ (SerpApi)", "⚠️", "ไม่มี SERPAPI_KEY ใน config.py — ข้าม")
else:
    try:
        bot._SEARCH_CACHE.clear()
        result = bot.search_web_serpapi("ข่าวเทคโนโลยี", max_results=3)
        if result and "ที่มา:" in result:
            first = result.split("\n")[0]
            _row("ค้นเว็บ (SerpApi)", "✅", first[:80])
        elif result == "":
            _row("ค้นเว็บ (SerpApi)", "⚠️", "SerpApi คืนผลว่าง — โควต้าอาจหมดหรือ key ผิด")
        else:
            _row("ค้นเว็บ (SerpApi)", "❌", result[:60])
    except Exception as e:
        _row("ค้นเว็บ (SerpApi)", "❌", str(e)[:60])

# ── 7. หาร้าน (SerpApi Google Maps — ถ้ามี key) ──────────────────────────────
print("[7] หาร้าน Google Maps ...", end=" ", flush=True)
if not bot.SERPAPI_KEY:
    _row("หาร้าน (Google Maps)", "⚠️", "ไม่มี SERPAPI_KEY ใน config.py — ข้าม")
else:
    try:
        bot._SEARCH_CACHE.clear()
        result = bot.search_places_serpapi("ร้านก๋วยเตี๋ยว", "ชุมพร")
        if result and "- " in result:
            first = result.split("\n")[0]
            _row("หาร้าน (Google Maps)", "✅", first[:80])
        elif result == "":
            _row("หาร้าน (Google Maps)", "⚠️", "Google Maps คืนผลว่าง (ไม่เจอร้าน หรือรีวิวน้อย)")
        else:
            _row("หาร้าน (Google Maps)", "❌", result[:60])
    except Exception as e:
        _row("หาร้าน (Google Maps)", "❌", str(e)[:60])

# ── 8. parse_pea_date ─────────────────────────────────────────────────────────
print("[8] _parse_pea_date ...", end=" ", flush=True)
try:
    dt = bot._parse_pea_date("/Date(1751302800000)/")
    if dt and dt.year == 2025 and dt.month == 7:
        _row("_parse_pea_date", "✅", f"epoch → {dt.strftime('%Y-%m-%d %H:%M %z')}")
    else:
        _row("_parse_pea_date", "❌", f"ผิดพลาด: {dt}")
except Exception as e:
    _row("_parse_pea_date", "❌", str(e)[:60])

# ── รายงานผลสรุป ──────────────────────────────────────────────────────────────
print()
print("=" * 68)
print(f"{'ระบบ':<28} {'สถานะ':^5}  {'รายละเอียด'}")
print("-" * 68)

pass_count = fail_count = warn_count = 0
for name, status, detail in ROWS:
    # จัดให้ status กว้าง 2 columns เพราะ emoji กว้างกว่าตัวอักษรปกติ
    print(f"  {name:<26} {status}  {detail}")
    if status == "✅":
        pass_count += 1
    elif status == "❌":
        fail_count += 1
    else:
        warn_count += 1

print("-" * 68)
total = len(ROWS)
print(f"  สรุป: ✅ {pass_count}  ⚠️  {warn_count}  ❌ {fail_count}   (รวม {total} ระบบ)")
print("=" * 68)

if fail_count > 0:
    print("\n❌ มีระบบพัง — ตรวจสอบ error ด้านบน")
    sys.exit(1)
elif warn_count > 0:
    print("\n⚠️  มีระบบที่ข้ามหรือมีปัญหาแหล่งข้อมูล — อ่านรายละเอียดด้านบน")
else:
    print("\n✅ ทุกระบบทำงานปกติ")
