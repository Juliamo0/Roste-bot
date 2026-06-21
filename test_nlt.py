# ทดสอบดึงข้อมูลหนังสือจากระบบ ISBN หอสมุดแห่งชาติ (NLT)
# วิธีใช้: python test_nlt.py
import urllib.request
import urllib.parse
import re
import html

# ค้นหาตามคำ (keywordTypeKey: 1=ชื่อเรื่อง, 2=ชื่อผู้แต่ง, 3=สำนักพิมพ์, 4=ISBN)
KEYWORD = "Hiro"
KEYWORD_TYPE = 2
PAGE = 1

base = "https://e-service.nlt.go.th/ISBNReq/ListSearchPub"
params = urllib.parse.urlencode({
    "keyword": KEYWORD,
    "keywordTypeKey": KEYWORD_TYPE,
    "RegTypeKey": "JuristicPerson",
    "fromRangeCode": "00000",
    "toRangeCode": "00000",
    "pageNo": PAGE,
})
url = f"{base}?{params}"

print(f"=== ทดสอบดึงหนังสือจาก NLT: คำค้น '{KEYWORD}' ===\n{url}\n")

req = urllib.request.Request(url)
# เลียนแบบเบราว์เซอร์ กันโดนเด้ง login
req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
req.add_header("Accept", "text/html,application/xhtml+xml")
req.add_header("Accept-Language", "th,en;q=0.9")

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode("utf-8", "ignore")
        final_url = resp.geturl()
except Exception as e:
    print(f"❌ ดึงไม่สำเร็จ: {type(e).__name__}: {e}")
    raise SystemExit

# เช็คว่าโดนเด้งไป login ไหม
if "ListSearchPub" not in final_url or "ชื่อผู้ใช้งาน" in raw and "ชื่อหนังสือ" not in raw:
    print(f"⚠️ ดูเหมือนโดนเด้งไปหน้าอื่น (final URL: {final_url})")
    print("อาจต้องล็อกอิน — ดึงอัตโนมัติไม่ได้")
    print("ตัวอย่าง HTML 500 ตัวแรก:\n", raw[:500])
    raise SystemExit

# แกะตาราง: หาแถว <tr> ที่มี <td> หลายช่อง
rows = re.findall(r"<tr[^>]*>(.*?)</tr>", raw, re.S)
books = []
for row in rows:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    if len(cells) >= 4:
        # ทำความสะอาด: ตัด tag, แปลง entity, ตัดช่องว่าง
        def clean(c):
            c = re.sub(r"<[^>]+>", " ", c)
            c = html.unescape(c)
            return re.sub(r"\s+", " ", c).strip()
        cleaned = [clean(c) for c in cells]
        # คอลัมน์: ลำดับ, ISBN, ชื่อหนังสือ, ผู้แต่ง, สำนักพิมพ์, (ปุ่มดูข้อมูล)
        books.append(cleaned)

print(f"✅ ดึงสำเร็จ! เจอ {len(books)} แถวข้อมูล\n")
for b in books[:8]:
    # b[1]=ISBN, b[2]=ชื่อ, b[3]=ผู้แต่ง, b[4]=สำนักพิมพ์ (ถ้ามีครบ)
    isbn = b[1] if len(b) > 1 else "?"
    title = b[2] if len(b) > 2 else "?"
    author = b[3] if len(b) > 3 else "?"
    pub = b[4] if len(b) > 4 else "?"
    print(f"- {title}\n    ผู้แต่ง: {author} | สนพ.: {pub} | ISBN: {isbn}\n")

print("--- เอาผลนี้ไปให้ผู้ช่วยดู ---")
