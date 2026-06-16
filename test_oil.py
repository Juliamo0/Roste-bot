# ทดสอบดึงราคาน้ำมันจาก Kapook (รันแยกจากบอท)
# วิธีใช้: python test_oil.py
import re
import urllib.request

URL = "https://gasprice.kapook.com/gasprice.php"
OIL_BRANDS = {
    "ptt": "ปตท.", "bcp": "บางจาก", "shell": "เชลล์", "caltex": "คาลเท็กซ์",
    "irpc": "ไออาร์พีซี", "pt": "พีที", "susco": "ซัสโก้", "pure": "เพียว",
    "suscodealers": "ซัสโก้ ดีลเลอร์",
}


def parse_oil_html(html):
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
        return "❌ parse ไม่ได้: โครงสร้างหน้าเว็บอาจเปลี่ยน"
    lines = [date or "ราคาน้ำมันวันนี้"]
    for code in order:
        rows = brands.get(code) or []
        if not rows:
            continue
        lines.append(f"\n[{OIL_BRANDS.get(code, code)}]")
        for fuel, price in rows:
            lines.append(f"  {fuel}: {price} บาท/ลิตร")
    return "\n".join(lines)


print("กำลังดึงราคาน้ำมันจาก Kapook...\n")
try:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
except Exception as e:
    print("❌ ดึงหน้าเว็บไม่สำเร็จ:", type(e).__name__, e)
    raise SystemExit

print(parse_oil_html(html))
print("\n--- ถ้าตัวเลขตรงกับหน้าเว็บ Kapook = scraper ใช้ได้ ---")
