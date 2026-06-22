# ทดสอบว่า ddgs ค้นเว็บได้จริงไหมบนเครื่องนี้ (รันแยกจากบอท)
# วิธีใช้: เปิด PowerShell ในโฟลเดอร์ mybot แล้วพิมพ์   python test_search.py

from ddgs import DDGS


def show(query):
    print("=" * 60)
    print("คำค้น:", repr(query))
    print("-" * 60)
    try:
        results = DDGS().text(query, max_results=5)
    except Exception as e:
        print("❌ ค้นไม่สำเร็จ:", type(e).__name__, e)
        print()
        return
    if not results:
        print("⚠️ คืนค่าว่าง (ไม่เจอผล)")
        print()
        return
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.get('title', '')}")
        print(f"   {(r.get('body', '') or '')[:150]}")
        print(f"   {r.get('href') or r.get('url') or ''}")
    print()


# ลองหลายแบบ: ไทยยาว, อังกฤษกระชับ, คำถามทั่วไป
show("แนะนำหนังสือหุ่นยนต์ที่ออกปี 2024 พร้อมชื่อคนเขียน")
show("robotics books 2024")
show("Raspberry Pi 5 price")
show("ข่าว AI ล่าสุด")

# ลองคำค้นราคาน้ำมัน หลายแบบ เพื่อดูว่าแบบไหนได้ข้อมูลใหม่/ถูก
print("\n\n########## ทดสอบราคาน้ำมัน ##########\n")
show("ราคาน้ำมันวันนี้ ปตท ล่าสุด")
show("ราคาน้ำมันวันนี้")
show("ราคาดีเซลวันนี้ 2569")

print("ทดสอบเสร็จแล้ว — ดูว่ามีหัวข้อ/ลิงก์จริงขึ้นมาไหม")
