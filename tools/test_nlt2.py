# ทดสอบดึง NLT แบบเก็บ cookie session ก่อน (เลียนแบบเบราว์เซอร์)
# วิธีใช้: python test_nlt2.py
import urllib.request
import urllib.parse
import http.cookiejar
import re
import html

KEYWORD = ""          # ว่าง = ดึงทั้งหมด (ตาม URL ที่ผู้ใช้ให้)
KEYWORD_TYPE = 1      # 1=ชื่อเรื่อง

# สร้างตัวจัดการ cookie (เก็บ session อัตโนมัติ)
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
opener.addheaders = [
    ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    ("Accept-Language", "th,en;q=0.9"),
]

print("=== NLT ทดสอบแบบเก็บ cookie ===\n")

# ขั้น 1: เข้าหน้าแรกเพื่อรับ cookie session
try:
    print("[1] เข้าหน้าแรกเพื่อรับ cookie...")
    opener.open("https://e-service.nlt.go.th/home", timeout=30).read()
    print("    cookie ที่ได้:", [c.name for c in cj])
except Exception as e:
    print(f"    ❌ {type(e).__name__}: {e}")

# ขั้น 2: เข้าหน้าค้นหา ISBN (เผื่อมันตั้ง cookie เพิ่ม)
try:
    print("[2] เข้าหน้า ISBNReq...")
    opener.open("https://e-service.nlt.go.th/ISBNReq", timeout=30).read()
except Exception as e:
    print(f"    (ข้าม: {type(e).__name__})")

# ขั้น 3: เรียกหน้าค้นหาจริง
base = "https://e-service.nlt.go.th/ISBNReq/ListSearchPub"
params = urllib.parse.urlencode({
    "KeywordTypeKey": KEYWORD_TYPE,
    "Keyword": KEYWORD,
    "ISBNReqTypeKey": "",
})
url = f"{base}?{params}"
print(f"[3] เรียกหน้าค้นหา: {url}")

try:
    resp = opener.open(url, timeout=30)
    raw = resp.read().decode("utf-8", "ignore")
    final_url = resp.geturl()
except Exception as e:
    print(f"    ❌ {type(e).__name__}: {e}")
    raise SystemExit

print(f"    final URL: {final_url}\n")

if "home/index" in final_url.lower() or ("ชื่อหนังสือ" not in raw and "ชื่อผู้แต่ง" not in raw):
    print("⚠️ ยังโดนเด้ง login / ไม่เจอตารางหนังสือ")
    print("HTML 400 ตัวแรก:\n", raw[:400])
    raise SystemExit

# แกะตาราง
rows = re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S)
def clean(c):
    c = re.sub(r"<[^>]+>", " ", c)
    return re.sub(r"\s+", " ", html.unescape(c)).strip()
books = []
for row in rows:
    cells = [clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
    if len(cells) >= 4:
        books.append(cells)

print(f"✅ สำเร็จ! เจอ {len(books)} แถว\n")
for b in books[:8]:
    title = b[2] if len(b) > 2 else "?"
    author = b[3] if len(b) > 3 else "?"
    pub = b[4] if len(b) > 4 else "?"
    isbn = b[1] if len(b) > 1 else "?"
    print(f"- {title}\n    ผู้แต่ง: {author} | สนพ.: {pub} | ISBN: {isbn}\n")
print("--- เอาผลนี้ไปให้ผู้ช่วยดู ---")
