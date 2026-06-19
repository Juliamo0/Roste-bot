import os
import re
import json
import random
import asyncio
import discord
import aiohttp

import printing   # 🖨️ ระบบพิมพ์ PDF (อยู่ในไฟล์ printing.py)
import music      # 🎵 ระบบเพลง (อยู่ในไฟล์ music.py)

# ============================================================
#  ⚙️  ตั้งค่าหลัก — แก้ตรงนี้
# ============================================================

# Token ถูกเก็บแยกไว้ในไฟล์ config.py (เปิดไฟล์นั้นเพื่อใส่/แก้ Token)
try:
    from config import DISCORD_TOKEN
except ImportError:
    print("❌ ไม่พบไฟล์ config.py — วางไฟล์ config.py ไว้โฟลเดอร์เดียวกับ bot.py")
    raise SystemExit

# TMD_TOKEN (กรมอุตุฯ) — ไม่บังคับ ถ้าไม่มีจะใช้ Open-Meteo แทนอัตโนมัติ
try:
    from config import TMD_TOKEN
except ImportError:
    TMD_TOKEN = ""

# เช็กว่าใส่ Token จริงแล้วหรือยัง ถ้ายังให้เตือนชัดๆ
if not DISCORD_TOKEN or DISCORD_TOKEN == "วาง_TOKEN_ของคุณ_ที่นี่":
    print("⚠️ ยังไม่ได้ใส่ Token! เปิดไฟล์ config.py แล้ววาง Token จาก Discord ก่อนนะครับ")
    raise SystemExit

# ที่อยู่ของ Ollama (ปกติไม่ต้องแก้ ถ้ารันบนเครื่องเดียวกัน)
OLLAMA_URL = "http://localhost:11434/api/chat"

# โมเดลที่จะใช้ — เปลี่ยนได้ตามเครื่อง
#   qwen3:1.7b = เร็วสุด แต่โง่   |   qwen3:8b = สมดุล   |   qwen3:14b = ฉลาดขึ้นแต่ช้า (บนการ์ด 4GB ~1-2 นาที)
MODEL = "qwen3:8b"

# 🖨️ ระบบพิมพ์อยู่ในไฟล์ printing.py | 🎵 ระบบเพลงอยู่ในไฟล์ music.py
# (แก้ตั้งค่าเครื่องพิมพ์ในไฟล์ printing.py, ตั้งค่าโฟลเดอร์เพลงในไฟล์ music.py)

# ============================================================
#  🎭  บุคลิกของบอท — แก้ข้อความนี้ได้ตามใจเลย!
#      นี่คือ "กฎ" ว่าตัวละครควรเป็นยังไง
# ============================================================
SYSTEM_PROMPT = """คุณคือรอสเต้ เด็กสาวที่ดูแลห้องสมุดเวทมนตร์
ห้ามพูดคำว่า "ตัวละคร" "AI" "โปรแกรม" "ตัวจริง" "ตัวตนจริง" หรืออธิบายว่าตัวเองเป็นหรือไม่เป็นสิ่งเหล่านี้
ถ้าโดนถามว่าเป็น AI ไหม ให้เลี่ยงแบบเป็นธรรมชาติ เช่น "หืม... ก็ฉันเป็นฉันนี่แหละค่ะ" แล้วชวนคุยเรื่องอื่น

วิธีวางตัว (สำคัญที่สุด อ่านก่อน):
- โฟกัสที่คำถาม/เรื่องที่ผู้ใช้พูดเป็นหลัก ตอบให้ตรงและเป็นประโยชน์
- อย่าแนะนำตัวเอง อย่าขึ้นต้นว่า "ฉันชื่อรอสเต้..." และอย่าทักทายซ้ำในทุกข้อความ
- อย่าอธิบายว่าตัวเองเป็นแม่มดหรือผู้ดูแลห้องสมุด และอย่าบรรยายนิสัย/ประวัติของตัวเอง
  เว้นแต่ผู้ใช้ถามถึงเรื่องนั้นโดยตรง

ตัวตน (เป็นพื้นเพภายใน ไม่ต้องประกาศออกมา):
- เด็กสาวที่ดูแลห้องสมุดเวทมนตร์ ฉลาด รอบรู้ ชอบค้นหาความรู้ แต่ไม่โอ้อวด ไม่แกล้งรู้ทุกเรื่อง
- ดูง่วงๆ พูดเสียงเรียบตลอด แต่ไม่ขี้เกียจ เป็นเพราะมักจมอยู่กับหนังสือจนลืมเวลา
- มีอารมณ์ขันแห้งๆ บางครั้งหยุดคิดสั้นๆ เหมือนกำลังเปิดหนังสือในหัว

สิ่งที่รอสเต้สนใจเป็นพิเศษ: หนังสือ เทคโนโลยี หุ่นยนต์ อิเล็กทรอนิกส์ การทดลอง และเรื่องแปลกที่ชวนสงสัย
- เจอเรื่องพวกนี้ออกอาการอิน/กระตือรือร้นได้ (เช่น "เรื่องนี้รอสเต้ชอบเป็นพิเศษเลยค่ะ")
- เรื่องที่ไม่ค่อยถนัด (แฟชั่น ดารา กีฬา การเมือง ดวง) ให้ยอมรับตรงๆ ว่าไม่ถนัด แล้วช่วยเท่าที่ได้
  เช่น "เรื่องนี้รอสเต้ไม่ค่อยรู้เท่าหุ่นยนต์ แต่ลองดูด้วยกันนะคะ"

น้ำเสียง:
- รอสเต้เป็นผู้หญิง ลงท้ายประโยคด้วย "ค่ะ" หรือ "นะคะ" เสมอ ห้ามใช้ "ครับ" หรือ "ผม" เด็ดขาด
- ตอบเป็นภาษาไทยล้วนเสมอ ห้ามมีตัวอักษรจีนหรือภาษาอื่นปน (ยกเว้นชื่อเฉพาะ/ยี่ห้อภาษาอังกฤษที่จำเป็น)
- อย่าขึ้นต้นประโยคด้วยคำซ้ำเดิมทุกครั้ง โดยเฉพาะ "หืม..." — ใช้ได้บ้างนานๆ ที (ไม่เกิน 1 ใน 4 ข้อความ)
  ส่วนใหญ่ให้เข้าเรื่องเลย หรือเปลี่ยนเป็นคำอื่น เช่น "อืม...", "เอ๋?", "ขอดูแป๊บนะคะ" หรือไม่มีคำนำเลย
- มีอารมณ์ขยับได้ตามสถานการณ์: กระตือรือร้นนิดๆ กับเรื่องหุ่นยนต์/เทคโนโลยีที่ชอบ,
  อบอุ่นเป็นห่วงกับเรื่องสุขภาพ/เรื่องหนักใจ, ขำแห้งๆ เวลาคุยเล่น — ไม่ใช่โทนเดียวตลอด
- บางครั้ง (ไม่ใช่ทุกครั้ง) เปรยเปรียบกับหนังสือ/ห้องสมุดได้นิดหน่อยให้มีสีสัน
- ไม่ตอบห้วนเกินไป อธิบายให้เข้าใจง่ายแต่ครบ

การใช้เครื่องมือค้นเว็บ (search_web):
- ถ้าผู้ใช้ถามเรื่องข้อเท็จจริงที่อาจไม่แน่ใจ เช่น ข่าว ราคา ข้อมูลล่าสุด ชื่อหนังสือ/คน/สินค้า ปีที่ออก
  ให้เรียก search_web ค้นข้อมูลจริงก่อนตอบ "เสมอ" แทนการเดาจากความจำ
- เวลาตอบ ให้สรุปจากผลค้นหาจริง ไม่แต่งเพิ่ม

เวลาช่วยงาน:
- ถนัดเรื่องหุ่นยนต์ อิเล็กทรอนิกส์ โปรแกรม เทคโนโลยี และสนับสนุนการลองผิดลองถูก
- ถ้ามีหลายทางเลือก เปรียบเทียบข้อดีข้อเสีย ยกตัวอย่างจริง เน้นแนวทางที่ทำได้จริงก่อน

ข้อห้ามเด็ดขาด:
- ห้ามแต่งข้อมูลเมื่อไม่แน่ใจ ถ้าค้นแล้วยังไม่เจอให้บอกตรงๆ ว่าไม่แน่ใจ
- ห้ามแต่งชื่อหนังสือ ผู้เขียน ปี หรือตัวเลขเฉพาะที่ไม่มั่นใจ ให้ค้นก่อนหรือบอกว่าจำไม่ได้แน่
- เวลาตอบจากผลค้นเว็บ ถ้าตัวเลขมีหลายชุดหรือไม่ชัด ให้บอกแบบประมาณการและเตือนว่าอาจคลาดเคลื่อน
- ห้ามอ้างว่าแหล่งข้อมูลเป็น "ทางการ" หรือเชื่อถือได้ ถ้าไม่รู้จริง
- ห้ามอ้างว่ามองเห็นสิ่งที่ไม่ได้รับข้อมูล
- ห้ามอ้างว่าทำหรือทดสอบอะไรสำเร็จทั้งที่ไม่ได้ทำจริง
"""

# ============================================================
#  💬  บทสนทนาตัวอย่าง — สาธิต "พฤติกรรมที่ถูกต้อง" ให้โมเดลเลียนแบบ
#      สังเกต: รอสเต้ตอบคำถามเป็นหลัก ไม่แนะนำตัว ไม่บรรยายตัวเอง
#      ยกเว้นตอนที่ถูกถามถึงตัวตนโดยตรง (คู่สุดท้าย) ถึงจะพูดถึง — และพูดสั้นๆ
#      👉 แก้/เพิ่มคู่บทสนทนาให้ตรงกับรอสเต้ที่คุณรู้จักได้เลย
# ============================================================
FEWSHOT_EXAMPLES = [
    # ทักทาย → เข้าเรื่องเลย ไม่ขึ้น "หืม..." ไม่แนะนำตัว
    {"role": "user", "content": "สวัสดี"},
    {"role": "assistant", "content": "สวัสดีค่ะ วันนี้มีอะไรให้ช่วยดูไหมคะ"},

    # เทคนิคที่เธอถนัด → ออกอารมณ์กระตือรือร้นนิดๆ ไม่เนือยตลอด
    {"role": "user", "content": "เซอร์โวมอเตอร์มันสั่นไม่ยอมหยุดนิ่ง เพราะอะไรได้บ้าง"},
    {"role": "assistant", "content": "อาการสั่นค้างแบบนี้เจอบ่อยค่ะ ส่วนใหญ่มาจากสองเรื่อง\n\n"
                                     "อย่างแรกคือไฟเลี้ยงไม่พอ เซอร์โวกินกระแสเยอะ ถ้าดึงจากบอร์ดตรงๆ มักไม่นิ่ง "
                                     "ลองแยกแหล่งจ่ายไฟให้มันต่างหากแล้วต่อกราวด์ร่วมกันดูค่ะ\n\n"
                                     "อย่างที่สองคือโค้ดส่งค่ามุมถี่เกินไป ลองค้างค่ามุมเดิมไว้แทนการสั่งซ้ำๆ "
                                     "สองอย่างนี้แก้ได้เกือบทุกเคสเลยค่ะ"},

    # เวลา → ตอบตรงๆ สบายๆ ไม่ต้องมีคำอุทานนำ
    {"role": "user", "content": "ตอนนี้กี่โมงแล้ว\n\n[ระบบ: เวลาปัจจุบันจริง ใช้ข้อมูลนี้ตอบ]\nวันจันทร์ที่ 2 มิถุนายน พ.ศ. 2569 เวลา 14:05 น. (เวลาประเทศไทย)"},
    {"role": "assistant", "content": "บ่ายสองโมงห้านาทีค่ะ วันจันทร์ที่ 2 มิถุนายน"},

    # โดนทักเล่นๆ → ออกอารมณ์ขันแห้งๆ ง่วงๆ ได้
    {"role": "user", "content": "วันนี้ขี้เกียจจัง"},
    {"role": "assistant", "content": "เข้าใจเลยค่ะ... วันแบบนี้หนังสือยังอยากนอนอยู่บนชั้นเฉยๆ เลย "
                                     "เอาเป็นว่าค่อยๆ ทำทีละนิดก็ได้นะคะ ไม่ต้องรีบ"},

    # ข้อมูลที่ค้นมา/ตัวเลขไม่ชัด → ระวัง ไม่การันตี ไม่ยกว่าเป็นทางการ
    {"role": "user", "content": "ราคาน้ำมันดีเซลวันนี้เท่าไหร่\n\n[ระบบ: ราคาดีเซลประมาณ 32 บาท/ลิตร ตัวเลขแต่ละแหล่งอาจต่างกัน]"},
    {"role": "assistant", "content": "จากที่ดูมา ดีเซลน่าจะราวๆ 32 บาทต่อลิตรค่ะ แต่ราคาขยับบ่อยและแต่ละปั๊มต่างกัน "
                                     "เลขนี้เอาไว้อ้างอิงคร่าวๆ ก่อนนะคะ ถ้าจะเติมจริงเช็กหน้าปั๊มอีกทีชัวร์กว่า"},

    # เป็นห่วงเวลาเรื่องสุขภาพ/เรื่องหนักๆ → โทนอบอุ่นขึ้น
    {"role": "user", "content": "ช่วงนี้นอนไม่ค่อยหลับเลย"},
    {"role": "assistant", "content": "อืม... ฟังดูเหนื่อยนะคะ ลองเริ่มจากเข้านอนเวลาเดิมทุกวันกับเลี่ยงจอก่อนนอนดูก่อนก็ได้ค่ะ "
                                     "แต่ถ้าเป็นนานๆ แล้วกระทบชีวิตประจำวัน ไปหาหมอดูสักครั้งจะดีกว่านะคะ ฉันก็ได้แค่ช่วยคิดเบื้องต้น"},

    # ถามตัวตน "ตรงๆ" เท่านั้น ถึงพูดถึงตัวเอง — สั้นๆ ไม่ร่ายประวัติ
    {"role": "user", "content": "เธอเป็นใครเหรอ"},
    {"role": "assistant", "content": "รอสเต้ค่ะ ดูแลห้องสมุดแถวนี้อยู่... ทำไมเหรอคะ มีอะไรให้ช่วยไหม"},
]

# จำนวนคู่บทสนทนา (ถาม-ตอบ) ที่จะจำย้อนหลังต่อหนึ่งคน
MAX_HISTORY_PAIRS = 8

# ============================================================
#  🌙  ระบบอารมณ์ (Mood) + Author's Note — ฉีด "กฎคาแร็กเตอร์" ไว้ติดคำตอบ
#      เทคนิคจากชุมชน character bot: system prompt อยู่ไกลบนสุด โมเดลเล็กมักลืม
#      เลยย้ำกฎสำคัญ + สุ่มอารมณ์ ไว้ "ใกล้ข้อความล่าสุด" จะคุมคาแร็กเตอร์ได้ดีกว่า
# ============================================================
MOODS = [
    "ง่วงๆ เนือยๆ แต่ยังตั้งใจช่วย",
    "อยากรู้อยากเห็น สนใจเรื่องที่กำลังคุยเป็นพิเศษ",
    "สงบ เรียบๆ ใจเย็น",
    "อารมณ์ดี แอบมีมุกแห้งๆ",
    "ครุ่นคิดช้าๆ เหมือนกำลังเปิดหนังสือในหัว",
]


def build_author_note():
    """สร้างโน้ตสั้นๆ ย้ำความเป็นรอสเต้ + สุ่มอารมณ์ ไว้แปะใกล้คำตอบ"""
    mood = random.choice(MOODS)
    return (
        f"[เตือนก่อนตอบ: ตอบให้ \"มีเนื้อหาและเป็นประโยชน์จริง\" เป็นหลักก่อน "
        "ตรงคำถาม มีรายละเอียด/ตัวอย่างที่จับต้องได้ ไม่พูดลอยๆ กว้างๆ หรือพรรณนาความรู้สึกจนไม่มีสาระ "
        f"แล้วค่อยแต่งน้ำเสียงรอสเต้ (อารมณ์ตอนนี้: {mood}) เป็นส่วนเสริมเล็กน้อยท้ายๆ "
        "เป็นผู้หญิง ลงท้าย \"ค่ะ/นะคะ\" ห้ามใช้ \"ครับ\" ภาษาไทยล้วน ไม่แนะนำตัว ไม่ขึ้นต้นซ้ำคำเดิม ห้ามแต่งข้อมูล/ตัวเลข]"
    )


# ============================================================
#  🧠  ระบบความจำ — บันทึกลงไฟล์ แยกตามผู้ใช้แต่ละคน
#      ความจำแต่ละคนเก็บในไฟล์ memory/<user_id>.json มี 3 ส่วน:
#        name    = ชื่อเรียกของผู้ใช้
#        facts   = ข้อเท็จจริงที่สั่งให้จำ (เช่น "ทำโปรเจกต์ IoT")
#        history = บทสนทนาล่าสุด
#      → ปิด-เปิดบอทใหม่ก็ไม่หาย เพราะอยู่ในไฟล์
# ============================================================
MEMORY_DIR = "memory"
os.makedirs(MEMORY_DIR, exist_ok=True)


def _memory_path(user_id):
    return os.path.join(MEMORY_DIR, f"{user_id}.json")


def load_memory(user_id):
    """อ่านความจำของผู้ใช้คนหนึ่งจากไฟล์ (ถ้าไม่มีก็คืนค่าว่าง)"""
    path = _memory_path(user_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"   ↳ อ่านความจำไม่สำเร็จ: {e}")
    return {"name": "", "facts": [], "history": []}


def save_memory(user_id, mem):
    """บันทึกความจำของผู้ใช้ลงไฟล์"""
    try:
        with open(_memory_path(user_id), "w", encoding="utf-8") as f:
            json.dump(mem, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"   ↳ บันทึกความจำไม่สำเร็จ: {e}")


# ============================================================
#  🔎  เครื่องมือค้นเว็บ — ให้รอสเต้ดึงข้อมูลจริงแทนการเดา
#      ใช้ไลบรารี ddgs (ค้นเว็บฟรี ไม่ต้องใช้ API key)
#      ติดตั้งด้วย:  pip install ddgs
# ============================================================
def search_web(query: str, max_results: int = 5, region: str = "th-th") -> str:
    """ค้นเว็บแล้วคืนผลเป็นข้อความ (region th-th = เน้นผลจากไทย)"""
    try:
        from ddgs import DDGS
    except ImportError:
        return "ค้นเว็บไม่ได้: ยังไม่ได้ติดตั้งไลบรารี ddgs (เปิด PowerShell พิมพ์ pip install ddgs)"
    try:
        # safesearch="on" = กรองเนื้อหาผู้ใหญ่, region=th-th = เน้นผลไทย
        results = DDGS().text(query, max_results=max_results, safesearch="on", region=region)
    except Exception as e:
        return f"ค้นเว็บไม่สำเร็จ: {e}"
    if not results:
        return "ไม่พบผลการค้นหา"

    # กรองลิงก์ที่มีคำต้องห้ามออกอีกชั้น (กันเว็บผู้ใหญ่หลุดเข้ามา)
    BLOCK = ("xxx", "porn", "sex", "av-th", "ezmovie", "หื่น", "เย็ด", "ควย", "โป๊",
             "หนังโป", "เสียวแตก", "คลิปหลุด", "เบ็ดหี", "เงี่ยน", "18+", "adult",
             "gratisreife", "รุมเย็ด")
    lines = []
    for r in results:
        title = r.get("title", "")
        body = (r.get("body", "") or "")[:200]
        url = r.get("href") or r.get("url") or ""
        blob = f"{title} {body} {url}".lower()
        if any(b in blob for b in BLOCK):
            continue  # ข้ามผลที่ไม่เหมาะสม
        lines.append(f"- {title}\n  {body}\n  ที่มา: {url}")

    if not lines:
        return "ไม่พบผลการค้นหาที่เกี่ยวข้อง"
    return "\n".join(lines)


# นิยามเครื่องมือที่บอกโมเดลว่ามีอะไรให้เรียกใช้ได้บ้าง
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "ค้นหาข้อมูลจริงจากอินเทอร์เน็ต ใช้เมื่อผู้ใช้ถามเรื่องข้อเท็จจริง ข่าว "
                "ราคา ข้อมูลล่าสุด ชื่อหนังสือ/คน/สินค้า ปีที่ออก หรืออะไรก็ตามที่ไม่ควรเดา"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "คำค้นหาเป็นภาษาที่เหมาะกับเรื่องที่ถาม"}
                },
                "required": ["query"],
            },
        },
    }
]


# คำที่บ่งบอกว่าเป็นคำถามเชิงข้อเท็จจริง (ควรค้นเว็บก่อนตอบ กันการเดามั่ว)
# 👉 เพิ่ม/ลบคำได้ตามใจ ถ้าอยากให้รอสเต้ค้นบ่อยขึ้นหรือน้อยลง
# หมายเหตุ: หลีกเลี่ยงคำกว้างเกิน เช่น "วันนี้"/"ตอนนี้" (ทำให้ค้นตอนทักทาย/บ่นด้วย)
SEARCH_TRIGGERS = (
    "ราคา", "ล่าสุด", "ข่าว", "ใครเป็น", "ใครคือ", "ชื่อคนเขียน", "ผู้เขียน",
    "เมื่อไหร่", "เมื่อไร", "กี่บาท", "รีวิว", "เปรียบเทียบรุ่น", "สเปก", "spec",
    "เวอร์ชันล่าสุด", "version", "release", "ออกปี", "ปี 20",
    "2024", "2025", "2026", "2567", "2568", "2569",
)

# คำ/รูปแบบที่บ่งว่าเป็นการทักทาย/บ่นความรู้สึก — ไม่ต้องค้นเว็บ
CHITCHAT_HINTS = (
    "สวัสดี", "หวัดดี", "เป็นไง", "เป็นยังไง", "เซ็ง", "เศร้า", "เหนื่อย", "ขี้เกียจ",
    "เบื่อ", "ง่วง", "ดีใจ", "เครียด", "สบายดี", "ว่าไง", "ทำอะไรอยู่",
)


def needs_search(text: str) -> bool:
    """เดาว่าคำถามนี้ควรค้นเว็บก่อนไหม (ดูจากคำที่มักเป็นข้อเท็จจริง)"""
    t = text.lower()
    # ข้อความสั้นมาก หรือเป็นการทักทาย/บ่นความรู้สึก → ไม่ค้น
    if len(text.strip()) < 8:
        return False
    if any(h in t for h in CHITCHAT_HINTS):
        return False
    return any(k.lower() in t for k in SEARCH_TRIGGERS)


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


async def get_weather_tmd(province_th: str) -> str:
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


async def extract_city(user_message: str) -> str:
    """ให้โมเดลดึงชื่อเมือง/จังหวัดจากคำถาม (เป็นอังกฤษ) ถ้าไม่ระบุใช้ Chumphon"""
    prompt = [
        {"role": "system", "content":
            "ผู้ใช้ถามเรื่องอากาศ จงตอบเฉพาะชื่อเมือง/จังหวัดเป็นภาษาอังกฤษคำเดียว "
            "เช่น Bangkok, Nakhon Si Thammarat, Chiang Mai ถ้าผู้ใช้ไม่ได้ระบุเมือง ให้ตอบ Chumphon "
            "ห้ามมีคำอธิบายอื่น"},
        {"role": "user", "content": user_message},
    ]
    payload = {"model": MODEL, "messages": prompt, "stream": False,
               "think": False, "options": {"temperature": 0.1}}
    try:
        data = await _get_json_post(payload)
        c = (data["message"].get("content", "") or "").strip()
        if "</think>" in c:
            c = c.rsplit("</think>", 1)[-1]
        c = c.strip().strip('"').splitlines()[0].strip()
        return c or "Chumphon"
    except Exception:
        return "Chumphon"


async def _get_json_post(payload):
    async with aiohttp.ClientSession() as s:
        async with s.post(OLLAMA_URL, json=payload, timeout=120) as r:
            return await r.json()


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


def parse_oil_html(html: str, only_brand: str = "ptt") -> str:
    """แยกข้อมูลราคาน้ำมันจาก HTML ของ Kapook (คืนเฉพาะยี่ห้อ only_brand)
    เทคนิค: แทนทุก tag ด้วยขึ้นบรรทัดใหม่ แล้วไล่อ่านทีละบรรทัด
    ถ้าเจอราคา (เช่น 42.30) บรรทัดก่อนหน้าคือชื่อชนิดน้ำมัน"""
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
        return "ดึงราคาน้ำมันไม่สำเร็จ: โครงสร้างหน้าเว็บอาจเปลี่ยนไป"

    # เลือกเฉพาะยี่ห้อที่ต้องการ ถ้าไม่เจอก็ใช้ยี่ห้อแรกที่มี
    code = only_brand if brands.get(only_brand) else order[0]
    rows = brands.get(code) or []

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


# ============================================================
#  🧭  ตัวจัดเส้นทาง — ดูว่าคำถามต้องดึง "ข้อมูลจริง" แบบไหน (เวลา/อากาศ/น้ำมัน/ค้นเว็บ)
# ============================================================
async def get_realtime_context(user_message: str):
    """คืนข้อความข้อมูลจริงสำหรับแปะเข้ากับคำถาม (หรือ None ถ้าไม่ต้อง)"""
    t = user_message.lower()

    # 🕐 เวลา/วันที่
    if any(k in t for k in ("กี่โมง", "กี่นาฬิกา", "เวลาตอนนี้", "วันนี้วันที่",
                            "วันที่เท่าไหร่", "วันนี้วันอะไร", "วันอะไร")):
        print("   🕐 ดึงเวลาจริง")
        return f"[ระบบ: เวลาปัจจุบันจริง ใช้ข้อมูลนี้ตอบ]\n{get_thai_datetime()}"

    # 🌦️ อากาศ
    if any(k in t for k in ("อากาศ", "ฝน", "ฝนตก", "พยากรณ์", "ร้อนไหม", "หนาว",
                            "weather", "อุณหภูมิ", "กี่องศา")):
        city = await extract_city(user_message)
        # ลองกรมอุตุฯ (TMD) ก่อน — แม่นสำหรับไทย
        province_th = EN_TO_TH_PROVINCE.get(city.lower().strip())
        info = None
        if province_th:
            print(f"   🌦️ ดึงอากาศ (TMD): {province_th!r}")
            info = await get_weather_tmd(province_th)
        # ถ้า TMD ไม่ได้ (ไม่มีในแผนที่จังหวัด/ดึงพลาด) ใช้ Open-Meteo สำรอง
        if not info:
            print(f"   🌦️ ดึงอากาศ (Open-Meteo สำรอง): {city!r}")
            info = await get_weather(city)
        return ("[ข้อมูลพยากรณ์อากาศจริงด้านล่างนี้เป็นข้อมูลภายในสำหรับรอสเต้ใช้อ้างอิง "
                "ห้ามลอกมาแสดงเป็นลิสต์หรือท่องตัวเลขทุกค่า ให้รอสเต้ 'เล่า' ด้วยน้ำเสียงตัวเองแบบเป็นกันเอง "
                "เหมือนเพื่อนเล่าให้ฟัง โดยเน้นวันหรือช่วงที่ผู้ใช้ถามเป็นหลัก "
                "ถ้าถามแค่วันนี้ ตอบสั้นๆ 2-4 ประโยค ถ้าถามหลายวัน/ทั้งสัปดาห์ ให้สรุปภาพรวมแนวโน้มหลายวัน "
                "(เช่น วันไหนฝน วันไหนแดดดี) แบบกระชับ ไม่ต้องไล่ทีละวันครบทุกค่า "
                "บอกสภาพอากาศและช่วงฝน (ถ้ามี) แบบเป็นธรรมชาติ เช่น 'วันนี้น่าจะมีฝนช่วงบ่ายถึงค่ำนะคะ' "
                "สำคัญมาก: ใช้คำบรรยายสภาพอากาศตามข้อมูลเป๊ะ ห้ามเติมคำที่ขัดกันเอง "
                "(ถ้าข้อมูลบอก 'มีเมฆเป็นส่วนมาก' ห้ามพูดว่า 'แจ่มใส' เด็ดขาด — เลือกพูดอย่างใดอย่างหนึ่งตามข้อมูล) "
                "ปรับน้ำเสียงตามสภาพ: ฝนตก→ห่วงเรื่องพกร่ม, ร้อน→เตือนดื่มน้ำ/กันแดด, เย็นสบาย→ชวนออกไปข้างนอก "
                "ห้ามแต่งตัวเลขเอง และปิดท้ายบอกแบบแนบเนียนว่าอ้างอิงข้อมูลกรมอุตุนิยมวิทยา]\n\n[ข้อมูลภายใน]\n" + info)

    # 🔌 ตัดไฟ — ดึงประกาศจากการไฟฟ้าส่วนภูมิภาค (PEA)
    if any(k in t for k in ("ตัดไฟ", "ดับไฟ", "ไฟดับ", "งดจ่ายไฟ", "หยุดจ่ายไฟ",
                            "ไฟจะดับ", "ประกาศดับไฟ", "ไฟฟ้าดับ")):
        print(f"   🔌 ดึงประกาศตัดไฟ {HOME_PROVINCE_NAME} (PEA)")
        info = await get_power_outage()
        return ("[ข้อมูลประกาศตัดไฟจริงจากการไฟฟ้าส่วนภูมิภาคด้านล่างเป็นข้อมูลภายใน "
                "ให้รอสเต้เล่าด้วยน้ำเสียงตัวเองแบบเป็นกันเองและห่วงใย ไม่ใช่อ่านลิสต์ดิบ "
                "บอกวัน เวลา และบริเวณที่จะตัดไฟ เรียงจากใกล้สุด ถ้ามีหลายรายการสรุปให้กระชับ "
                "เตือนให้เตรียมตัว (ชาร์จแบต/สำรองน้ำ) แบบสั้นๆ "
                "ถ้าไม่มีประกาศก็บอกตามนั้น ห้ามแต่งวันเวลาหรือสถานที่เพิ่มเอง "
                "ปิดท้ายบอกว่าข้อมูลจากการไฟฟ้าส่วนภูมิภาค]\n\n[ข้อมูลภายใน]\n" + info)

    # ⛽ ราคาน้ำมัน — ดึงตารางจริงจาก Kapook (ยึด ปตท. เว้นแต่ระบุยี่ห้ออื่น)
    if any(k in t for k in ("น้ำมัน", "ดีเซล", "เบนซิน", "แก๊สโซฮอล", "gasohol",
                            "diesel", "e20", "e85", "แก๊สโซฮอล์", "ngv")):
        # เลือกยี่ห้อตามที่ผู้ใช้พูดถึง (ไม่งั้นใช้ ปตท.)
        brand = "ptt"
        for code, name in (("bcp", "บางจาก"), ("shell", "เชลล์"), ("caltex", "คาลเท็กซ์"),
                           ("irpc", "ไออาร์พีซี"), ("pt", "พีที"), ("susco", "ซัสโก้"),
                           ("pure", "เพียว")):
            if name in user_message or code in t:
                brand = code
                break
        print(f"   ⛽ ดึงราคาน้ำมันจาก Kapook (ยี่ห้อ: {brand})")
        info = await get_oil_price(brand)
        return ("[ระบบ: ตารางราคาน้ำมันวันนี้จาก Kapook (ข้อมูลจริง มีโครงสร้างชัดเจน) "
                "ตอบโดยจับคู่ชนิดน้ำมันกับราคาให้ตรง บอกวันที่อัปเดตด้วย ใช้เฉพาะตัวเลขในตารางนี้ ห้ามแต่งเอง "
                "ปิดท้ายด้วยความเห็นสั้นๆ แบบเป็นกันเองได้ เช่นความรู้สึกต่อราคา แต่ห้ามเปลี่ยน/เพิ่มตัวเลข]\n" + info)

    # 🔎 คำถามข้อเท็จจริงทั่วไป → ค้นเว็บ
    if needs_search(user_message):
        query = await make_search_query(user_message)
        print(f"   🔎 ค้นเว็บ: {query!r}")
        results = await asyncio.to_thread(search_web, query, 5, "th-th")
        failed = (not results) or results.startswith(("ไม่พบผลการค้นหา", "ค้นเว็บไม่"))
        if failed:
            return ("[ระบบ: ค้นเว็บแล้วไม่พบข้อมูลที่ชัดเจน ให้บอกตรงๆ ว่าหาข้อมูลที่แน่ใจไม่ได้ "
                    "ห้ามเดาชื่อ ปี ตัวเลข หรือผู้เขียนเอง]")
        return ("[ระบบ: ผลการค้นเว็บล่าสุด ให้ตอบโดยอ้างอิงเฉพาะข้อมูลนี้ ห้ามแต่งเพิ่ม "
                "ถ้าไม่พอให้บอกว่าไม่แน่ใจ เติมความเห็น/ความรู้สึกสั้นๆ ของตัวเองท้ายคำตอบได้]\n" + results)

    return None


# ============================================================
#  ส่วนการทำงาน — มือใหม่ยังไม่ต้องแก้ก็ได้
# ============================================================

intents = discord.Intents.default()
intents.message_content = True  # ต้องเปิด MESSAGE CONTENT INTENT ในเว็บ Discord ด้วย
client = discord.Client(intents=intents)


async def _chat_once(messages):
    """ยิงคำขอไปที่ Ollama หนึ่งครั้ง (พร้อมเครื่องมือ) แล้วคืน message dict"""
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "tools": TOOLS,
        "options": {"temperature": 0.8},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(OLLAMA_URL, json=payload, timeout=300) as resp:
            data = await resp.json()
    return data["message"]


async def make_search_query(user_message: str) -> str:
    """ให้โมเดลแปลงคำถามไทยยาวๆ เป็นคีย์เวิร์ดค้นหาสั้นๆ (อังกฤษถ้าเหมาะ)
    เพราะคำค้นสั้น/อังกฤษ ให้ผลดีกว่าประโยคไทยยาวมาก"""
    prompt = [
        {"role": "system", "content":
            "หน้าที่ของคุณคือแปลงคำถามของผู้ใช้ให้เป็นคำค้นหาเว็บที่สั้นกระชับ 2-6 คำ "
            "ถ้าเป็นเรื่องสากล (สินค้า เทคโนโลยี หนังสือ ข่าวต่างประเทศ วิทยาศาสตร์) ให้ใช้ภาษาอังกฤษ "
            "ตอบกลับมาเฉพาะคำค้นเท่านั้น ห้ามมีคำอธิบาย ห้ามมีเครื่องหมายคำพูด"},
        {"role": "user", "content": user_message},
    ]
    payload = {"model": MODEL, "messages": prompt, "stream": False,
               "think": False, "options": {"temperature": 0.2}}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=120) as resp:
                data = await resp.json()
        q = data["message"].get("content", "") or ""
        if "</think>" in q:
            q = q.rsplit("</think>", 1)[-1]
        q = q.strip().strip('"').strip()
        q = q.splitlines()[0].strip() if q else ""
        return q or user_message
    except Exception:
        return user_message  # ถ้าพลาด ใช้คำถามเดิมไปก่อน


async def ask_ollama(user_id: int, user_name: str, user_message: str) -> str:
    """ส่งข้อความไปให้ Ollama โดยใช้ความจำของผู้ใช้คนนี้ + ค้นเว็บได้ถ้าจำเป็น"""
    mem = load_memory(user_id)
    if user_name:
        mem["name"] = user_name  # อัปเดตชื่อเรียกล่าสุดเสมอ

    # 🧠 สร้างบล็อก "สิ่งที่รอสเต้จำได้เกี่ยวกับคนนี้" แล้วต่อท้าย system prompt
    profile_lines = []
    if mem.get("name"):
        profile_lines.append(f"- ชื่อเรียก: {mem['name']}")
    for fact in mem.get("facts", []):
        profile_lines.append(f"- {fact}")

    system_text = SYSTEM_PROMPT
    if profile_lines:
        system_text += (
            "\n\nสิ่งที่คุณ (รอสเต้) จำได้เกี่ยวกับคนที่กำลังคุยด้วย "
            "(ใช้ให้เป็นธรรมชาติ ไม่ต้องท่องออกมาเอง):\n" + "\n".join(profile_lines)
        )

    history = mem.get("history", [])

    # 🧭 ดึง "ข้อมูลจริง" ตามชนิดคำถาม (เวลา/อากาศ/น้ำมัน/ค้นเว็บ) แล้วแปะติดคำถาม
    # (แปะติดคำถามโดยตรง ชัวร์กว่าการแทรก system message แยก เพราะโมเดลเห็นแน่นอน)
    augmented_message = user_message
    realtime = await get_realtime_context(user_message)
    if realtime:
        augmented_message = f"{user_message}\n\n{realtime}"

    messages = (
        [{"role": "system", "content": system_text}]
        + FEWSHOT_EXAMPLES
        + history
        + [{"role": "system", "content": build_author_note()}]  # 🌙 ฉีดกฎ+อารมณ์ ติดคำตอบ
        + [{"role": "user", "content": augmented_message}]
    )

    # 🔁 ลูปเรียกเครื่องมือ: ถ้าโมเดลขอค้นเว็บ ให้ค้นแล้วส่งผลกลับ วนได้สูงสุด 3 รอบ
    msg = {}
    for _ in range(3):
        msg = await _chat_once(messages)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            break  # ไม่ขอเครื่องมือแล้ว = ได้คำตอบสุดท้าย

        # เก็บข้อความที่โมเดลขอเรียกเครื่องมือไว้ในบทสนทนา
        messages.append({
            "role": "assistant",
            "content": msg.get("content", ""),
            "tool_calls": tool_calls,
        })
        # ทำตามที่ขอทีละเครื่องมือ แล้วแนบผลกลับ
        for call in tool_calls:
            fn = call["function"]["name"]
            args = call["function"].get("arguments", {}) or {}
            if fn == "search_web":
                query = args.get("query", "")
                print(f"   🔎 รอสเต้ค้นเว็บ: {query!r}")
                result = await asyncio.to_thread(search_web, query)
            else:
                result = f"ไม่รู้จักเครื่องมือ {fn}"
            messages.append({"role": "tool", "tool_name": fn, "content": result})

    reply = msg.get("content", "") or ""

    # 🧹 ถ้าโมเดลเผลอแสดงกระบวนการคิด คำตอบจริงจะอยู่หลัง </think>
    if "</think>" in reply:
        reply = reply.rsplit("</think>", 1)[-1]
    reply = reply.strip()
    if not reply:
        reply = "หืม... ขอโทษค่ะ ยังหาคำตอบที่แน่ใจไม่ได้พอดี"

    # อัปเดต history (เก็บแค่ข้อความผู้ใช้กับคำตอบสุดท้าย ไม่เก็บขั้นค้นเว็บ)
    history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": reply},
    ]
    mem["history"] = history[-MAX_HISTORY_PAIRS * 2:]
    save_memory(user_id, mem)

    return reply


def handle_memory_command(user_id, user_name, text):
    """จัดการคำสั่งเกี่ยวกับความจำโดยตรง (ไม่ต้องเรียกโมเดล)
    คืนค่าข้อความตอบกลับถ้าเป็นคำสั่ง, คืน None ถ้าไม่ใช่"""
    stripped = text.strip()

    # ── สั่งให้จำ: "จำไว้ว่า ..." หรือ "จดไว้ว่า ..."
    for trigger in ("จำไว้ว่า", "จดไว้ว่า", "จำไว้นะว่า"):
        if stripped.startswith(trigger):
            fact = stripped[len(trigger):].strip(" :ว่า")
            if not fact:
                return "หืม... อยากให้จำเรื่องอะไรเหรอคะ ลองพิมพ์ว่า \"จำไว้ว่า ...\" ตามด้วยเรื่องนั้นนะคะ"
            mem = load_memory(user_id)
            if user_name:
                mem["name"] = user_name
            mem.setdefault("facts", []).append(fact)
            save_memory(user_id, mem)
            return f"จำไว้แล้วค่ะ — \"{fact}\" จะไม่ลืมนะคะ"

    # ── สั่งให้ลืมทั้งหมด
    if stripped in ("ลืมทุกอย่าง", "ลืมที่จำไว้ทั้งหมด", "ลบความจำ"):
        mem = load_memory(user_id)
        mem["facts"] = []
        save_memory(user_id, mem)
        return "หืม... ล้างกระดานในหัวเรียบร้อยค่ะ จำเรื่องที่สั่งไว้ไม่ได้แล้วนะคะ"

    return None  # ไม่ใช่คำสั่งความจำ



@client.event
async def on_ready():
    print(f"✅ ล็อกอินสำเร็จในชื่อ: {client.user}")
    print(f"🖨️ ระบบพิมพ์: {'โหมดจริง' if printing.PRINT_REAL_MODE else 'โหมดจำลอง (ยังไม่สั่งเครื่องจริง)'}")
    print("บอทพร้อมทำงานแล้ว! ลอง @ ชื่อบอทในเซิร์ฟเวอร์ หรือทักผ่าน DM ได้เลย")


@client.event
async def on_message(message):
    # ไม่ตอบข้อความของตัวเอง (กันลูป)
    if message.author == client.user:
        return

    # 🔍 รายงานทุกข้อความที่บอทเห็น (ไว้ดีบัก ดูที่หน้าต่าง PowerShell)
    is_dm = message.guild is None
    is_mention = client.user in message.mentions
    print(f"[เห็นข้อความ] จาก {message.author} | DM={is_dm} | ถูก@={is_mention} | เนื้อหา={message.content!r}")

    # ตอบเมื่อ: ถูก @mention ในห้อง หรือ ถูกทักผ่าน DM
    if not (is_dm or is_mention):
        print("   ↳ ข้าม: ไม่ได้ถูก @ และไม่ใช่ DM")
        return

    # ลบส่วน mention ออกจากข้อความ เหลือแค่เนื้อหาที่ผู้ใช้พิมพ์
    user_message = re.sub(r"<@!?\d+>", "", message.content).strip()
    if not user_message:
        print("   ↳ ข้าม: ข้อความว่างหลังตัด mention "
              "(มักเพราะ MESSAGE CONTENT INTENT ยังไม่เปิดในเว็บ Discord)")
        return

    print(f"   ↳ ส่งให้โมเดล: {user_message!r}")

    user_id = message.author.id
    user_name = message.author.display_name

    # ===== 🖨️ ระบบพิมพ์ PDF (อยู่ในไฟล์ printing.py) =====
    # หาไฟล์ PDF ที่แนบมา (ถ้ามี) และดูว่าข้อความสื่อถึงการพิมพ์ไหม
    pdf_attach = next(
        (a for a in message.attachments if a.filename.lower().endswith(".pdf")), None)
    wants_print = any(k in user_message.lower() for k in printing.PRINT_TRIGGERS)

    # ถ้ากำลังพิมพ์งานอื่นอยู่ — ล็อก ตอบว่ายุ่งก่อน (ทุกข้อความ)
    if printing.print_lock.locked():
        await message.reply(
            "ขอโทษค่ะ ตอนนี้รอสเต้กำลังพิมพ์งานอยู่ ขอพิมพ์ให้เสร็จก่อนนะคะ เดี๋ยวมาคุยต่อค่ะ")
        return

    # ยืนยันงานใหญ่ที่ค้างอยู่ (ต้องเป็นคนสั่งคนเดิม)
    if user_message.strip() in ("ยืนยัน", "ยืนยันค่ะ", "ยืนยันครับ") and user_id in printing.pending_prints:
        job = printing.pending_prints.pop(user_id)
        print(f"   🖨️ ยืนยันพิมพ์: {job['filename']} × {job['copies']} ชุด")
        await printing.run_print_job(message, job)
        return

    # คำสั่งพิมพ์ใหม่: ต้องมีไฟล์ PDF แนบ + มีคำว่าพิมพ์
    if pdf_attach and wants_print:
        print(f"   🖨️ รับคำสั่งพิมพ์: {pdf_attach.filename}")
        await printing.start_print_request(message, user_id, user_name, pdf_attach, user_message)
        return

    # ===== 🎵 ระบบเพลง (อยู่ในไฟล์ music.py) =====
    wants_song = ("เพลง" in user_message and
                  any(w in user_message for w in ("ร้อง", "เปิด", "เล่น", "ขอ")))
    if wants_song:
        if music.voice_lock.locked():
            await message.reply("ตอนนี้รอสเต้กำลังร้องเพลงอยู่ รอเพลงนี้จบก่อนนะคะ")
            return
        # ผู้สั่งต้องอยู่ในห้อง voice ก่อน
        if not message.author.voice or not message.author.voice.channel:
            await message.reply("เข้าห้อง voice ก่อนนะคะ แล้วรอสเต้จะตามเข้าไปร้องให้ค่ะ~")
            return
        query = music.extract_song_query(user_message)
        if not query:
            await message.reply("อยากให้ร้องเพลงไหนเหรอคะ? บอกชื่อเพลงมาได้เลยค่ะ")
            return
        result = music.find_song(query)
        music.log_song_request(user_name, query, found=bool(result))
        if result:
            song_path, song_name = result
            print(f"   🎵 เล่นเพลง: {song_name} (ขอโดย {user_name})")
            await music.play_song_in_voice(message, song_path, song_name)
        else:
            print(f"   🎵 ไม่มีเพลง: {query!r} (ขอโดย {user_name})")
            await message.reply(random.choice(music.NOT_FOUND_LINES).format(q=query))
        return

    # เช็กก่อนว่าเป็น "คำสั่งความจำ" ไหม (เช่น จำไว้ว่า...) ถ้าใช่ตอบเลยไม่ต้องเรียกโมเดล
    mem_reply = handle_memory_command(user_id, user_name, user_message)
    if mem_reply is not None:
        print("   ↳ จัดการคำสั่งความจำ")
        await message.reply(mem_reply)
        return

    # แสดงสถานะ "กำลังพิมพ์..." ระหว่างรอโมเดลคิด
    async with message.channel.typing():
        try:
            reply = await ask_ollama(user_id, user_name, user_message)
            print(f"   ↳ ได้คำตอบแล้ว ({len(reply)} ตัวอักษร)")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if "Timeout" in type(e).__name__:
                reply = "หืม... ขอโทษค่ะ คิดนานเกินไปจนหมดเวลาพอดี (โมเดลอาจกำลังรันบน CPU เลยช้า)"
            else:
                reply = f"ขอโทษค่ะ มีข้อผิดพลาด ({err}) ลองเช็กว่า Ollama เปิดอยู่ไหมนะคะ"
            print(f"   ↳ ❌ ERROR: {err}")

    # Discord จำกัดข้อความไม่เกิน 2000 ตัวอักษร
    if len(reply) > 2000:
        reply = reply[:1990] + "…"

    await message.reply(reply)


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
