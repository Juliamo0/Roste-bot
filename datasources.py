"""
🌦️⛽🔌🕐 ตัวดึงข้อมูลจริงดิบๆ — weather (TMD + Open-Meteo), ราคาน้ำมัน (Kapook),
ประกาศตัดไฟ (PEA), เวลาไทย, แผนที่ชื่อจังหวัด

แยกออกมาจาก bot.py เพราะไม่พึ่งอะไรในนั้นเลยนอกจาก config (TMD_TOKEN) — แต่ละฟังก์ชัน
คืนข้อความดิบล้วนๆ ไม่รู้เรื่อง tool-calling/persona (ส่วนนั้นอยู่ใน _tool_* wrapper ใน bot.py)
"""
import re
import aiohttp

# TMD_TOKEN (กรมอุตุฯ) — ไม่บังคับ ถ้าไม่มีจะใช้ Open-Meteo แทนอัตโนมัติ
try:
    from config import TMD_TOKEN
except ImportError:
    TMD_TOKEN = ""


# ============================================================
#  🗺️  แผนที่จังหวัดไทย
# ============================================================
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


async def get_weather_tmd(province_th: str) -> str | None:
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


_OIL_SECTION_RE = re.compile(
    r'id="brand-(ptt|bcp|shell|caltex|irpc|pt|susco|pure|suscodealers)"\s+class="scroll-mt-28"')


def parse_oil_html(html: str, only_brand: str = "ptt") -> str:
    """แยกข้อมูลราคาน้ำมันจาก HTML ของ Kapook (คืนเฉพาะยี่ห้อ only_brand)

    เว็บเปลี่ยนมาเรนเดอร์เป็น Next.js (ก.ค. 2569) — ไม่มี "(ptt)" ห้อยท้ายชื่อแบบเดิมแล้ว
    แต่ละยี่ห้อกลายเป็น <section id="brand-XXX" class="scroll-mt-28"> ต้องอิงจาก id แทน
    (หาตำแหน่งจาก HTML ดิบก่อนแทน tag ด้วยขึ้นบรรทัดใหม่ เพราะ attribute จะหายไปพร้อม tag)

    ในแต่ละ section: แทนทุก tag ด้วยขึ้นบรรทัดใหม่ แล้วไล่อ่านทีละบรรทัด แถวนึงคือ
    [ชื่อชนิดน้ำมัน, ป้ายหมวด (badge), ราคา, หน่วย] วนซ้ำ — ราคาอยู่ 2 บรรทัดหลังชื่อจริง
    (ไม่ใช่บรรทัดก่อนหน้าตรงๆ เพราะมี badge คั่นกลางเสมอ)"""
    matches = list(_OIL_SECTION_RE.finditer(html))
    if not matches:
        return "ดึงราคาน้ำมันไม่สำเร็จ: โครงสร้างหน้าเว็บอาจเปลี่ยนไป"

    order = [m.group(1) for m in matches]
    code = only_brand if only_brand in order else order[0]
    idx = order.index(code)
    start = matches[idx].start()
    end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
    section_html = html[start:end]

    # วันที่ "อัปเดตล่าสุด" อยู่นอก section (ก่อนตาราง) — คั่นจากตัววันที่จริงด้วย HTML
    # comment (React hydration marker) กลายเป็นคนละบรรทัดกันหลังแทน tag ด้วยขึ้นบรรทัดใหม่
    date = ""
    page_parts = [p.strip() for p in re.sub(r"<[^>]+>", "\n", html).split("\n")]
    page_parts = [p for p in page_parts if p]
    for i, tok in enumerate(page_parts):
        if "อัปเดตล่าสุด" in tok:
            nxt = page_parts[i + 1] if i + 1 < len(page_parts) else ""
            date = tok if re.search(r"\d", tok) else f"{tok} {nxt}".strip()
            break

    parts = [p.strip() for p in re.sub(r"<[^>]+>", "\n", section_html).split("\n")]
    parts = [p for p in parts if p]

    rows = []
    for i, tok in enumerate(parts):
        if re.fullmatch(r"\d{1,3}\.\d{2}", tok):
            fuel = parts[i - 2] if i >= 2 else ""
            if fuel and not re.fullmatch(r"[\d.]+", fuel):
                rows.append((fuel, tok))

    if not rows:
        return "ดึงราคาน้ำมันไม่สำเร็จ: โครงสร้างหน้าเว็บอาจเปลี่ยนไป"

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
