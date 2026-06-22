# 🌙 รอสเต้ (Roste) — Discord AI Bot

บอท Discord ที่มีบุคลิกเป็นตัวละคร "รอสเต้" เด็กสาวดูแลห้องสมุดเวทมนตร์
ขับเคลื่อนด้วย LLM ที่รันในเครื่องตัวเอง (ผ่าน Ollama) — คุยภาษาไทย มีความจำ
ดึงข้อมูลจริงได้ สั่งพิมพ์ PDF ได้ และเล่นเพลงในห้อง voice ได้

> โปรเจกต์งานอดิเรก รันในเครื่องตัวเอง (local) ทั้งหมด

## ✨ ความสามารถ

- 🎭 **บุคลิกตัวละคร** — รอสเต้ คุยไทย มีอารมณ์/น้ำเสียงเฉพาะตัว กันหลุดคาแร็กเตอร์ด้วย Author's Note
- 🧠 **ความจำหลายชั้น**
  - จำชื่อ/ข้อเท็จจริงถาวร (สั่งได้ + จำเองอัตโนมัติเบื้องหลัง)
  - สรุปบทสนทนาเก่าอัตโนมัติเมื่อ history ล้น (แทนที่จะทิ้ง)
  - Selective recall — ดึงเฉพาะ fact ที่เกี่ยวกับบทสนทนาตอนนั้น
  - คำสั่งความจำ: `จำไว้ว่า…` / `ลืมเรื่อง…` / `จำอะไรได้บ้าง`
- 🌐 **ข้อมูลจริง** — เวลา/วัน, พยากรณ์อากาศ, ราคาน้ำมัน, ค้นเว็บ, หาร้านอาหาร/สถานที่
- 🖨️ **สั่งพิมพ์ PDF** — แนบไฟล์ใน Discord แล้วให้รอสเต้สั่งเครื่องพิมพ์จริง
- 🎵 **เล่นเพลง** — เล่นไฟล์ mp3 ในห้อง voice ตามที่ขอ

## 🗂️ โครงสร้างไฟล์

### ไฟล์หลัก

| ไฟล์ | หน้าที่ |
|------|---------|
| `bot.py` | ตัวหลัก — เชื่อม Discord, LLM, เครื่องมือต่างๆ |
| `persona.py` | บุคลิกรอสเต้ — `SYSTEM_PROMPT`, few-shot examples, moods, author note |
| `memory.py` | ระบบความจำ — load/save/facts/recall/summaries + คำสั่งจำ-ลืม |
| `printing.py` | ระบบพิมพ์ PDF + ตั้งค่าเครื่องพิมพ์ |
| `music.py` | ระบบเล่นเพลงในห้อง voice + ตั้งค่าโฟลเดอร์เพลง |
| `config.py` | Discord Token (สร้างเองจาก `config.example.py` — ไม่อยู่ใน repo) |
| `start.bat` | ดับเบิลคลิกเพื่อรันบอท |
| `setup.bat` | ดับเบิลคลิกเพื่อติดตั้งไลบรารี |

### ไฟล์ทดสอบ / จำลอง

| ไฟล์ | หน้าที่ |
|------|---------|
| `test_memory.py` | Unit tests สำหรับ memory.py (35 tests) |
| `test_bot.py` | Unit tests สำหรับ bot.py — lock, summarize, overflow logic (18 tests) |
| `conftest.py` | pytest config — inject fake token ระหว่างทดสอบ |
| `simulate_chat.py` | จำลองการคุย 9 รอบ — ทดสอบ trigger สรุป history ครั้งแรก |
| `simulate_chat_long.py` | จำลองการคุย 18 รอบ — ดูว่า summaries สะสม 3 หัวข้อยังไง |

## 🚀 วิธีติดตั้ง

### สิ่งที่ต้องมีก่อน

- [Python](https://www.python.org/downloads/) 3.10 ขึ้นไป (ตอนติดตั้งติ๊ก "Add Python to PATH")
- [Ollama](https://ollama.com) — สำหรับรันโมเดล LLM
- (ถ้าจะใช้พิมพ์) [SumatraPDF](https://www.sumatrapdfreader.org)
- (ถ้าจะเล่นเพลง) FFmpeg — `winget install ffmpeg`

### ขั้นตอน

1. โคลนโปรเจกต์นี้ หรือดาวน์โหลด ZIP
2. ติดตั้งไลบรารี — ดับเบิลคลิก `setup.bat`
   ```
   pip install discord.py aiohttp ddgs pypdf pywin32 PyNaCl
   ```
3. โหลดโมเดล
   ```
   ollama pull qwen3:8b
   ```
   (หรือ `qwen3:14b` ถ้าการ์ดแรงพอ, `qwen3:1.7b` ถ้าการ์ดเล็ก)
4. ตั้งค่า Token:
   - คัดลอก `config.example.py` → `config.py`
   - ใส่ Token จาก [Discord Developer Portal](https://discord.com/developers/applications)
   - เปิด **MESSAGE CONTENT INTENT** ใน Bot settings
5. รันบอท — ดับเบิลคลิก `start.bat`

### API keys เสริม (ไม่บังคับ)

| ไฟล์ | ค่า | ใช้ทำอะไร |
|------|-----|-----------|
| `config.py` | `TMD_TOKEN` | พยากรณ์อากาศจากกรมอุตุฯ (ถ้าไม่มีใช้ Open-Meteo แทนอัตโนมัติ) |
| `config.py` | `SERPAPI_KEY` | ค้นเว็บผ่าน Google จริง (ถ้าไม่มีใช้ DuckDuckGo แทนอัตโนมัติ) |

## ⚙️ การปรับแต่ง

| ต้องการแก้อะไร | แก้ที่ไหน |
|---------------|----------|
| บุคลิก/น้ำเสียงรอสเต้ | `persona.py` → `SYSTEM_PROMPT` |
| ตัวอย่างบทสนทนา (few-shot) | `persona.py` → `FEWSHOT_EXAMPLES` |
| โมเดล LLM | `bot.py` → `MODEL` |
| จำนวน history ที่เก็บ | `memory.py` → `MAX_HISTORY_PAIRS` |
| จำนวน facts สูงสุดต่อคน | `memory.py` → `MAX_FACTS` |
| จำนวน summaries สูงสุดต่อคน | `memory.py` → `MAX_SUMMARIES` |
| ตั้งค่าเครื่องพิมพ์ | `printing.py` → `PRINTER_NAME` |
| เพิ่มเพลง | วางไฟล์ `.mp3` ในโฟลเดอร์ `songs/` |

## 🧠 ระบบความจำ

ความจำแบ่งเป็น 3 ชั้น เก็บแยกต่อ user แต่ละคนใน `memory/<user_id>.json`

```
facts      → ข้อเท็จจริงถาวร (ชื่อ, ที่อยู่, ความชอบ ...)
history    → บทสนทนาล่าสุด 8 คู่
summaries  → สรุปบทสนทนาเก่า 1 บรรทัดต่อคู่ที่ล้นออกจาก history
```

**คำสั่งที่ใช้ใน Discord:**

| พิมพ์ | ผล |
|------|----|
| `จำไว้ว่า [เรื่อง]` | สั่งให้จำ fact นั้น |
| `ลืมเรื่อง [คำ]` | ลบ fact ที่มีคำนั้น |
| `จำอะไรได้บ้าง` | ดูรายการ facts ทั้งหมด |
| `ลืมทุกอย่าง` | ล้าง facts ทั้งหมด |

นอกจากนั้น รอสเต้จะ **จำเองอัตโนมัติ** (auto-remember) ในเบื้องหลัง — ถ้าข้อความมีสัญญาณว่าพูดถึงตัวเอง (เช่น "ฉันทำงาน..." "ผมมี..." "ชื่อ...") โมเดลจะสกัดเป็น fact และบันทึกโดยไม่รบกวนการตอบ

## 🧪 ทดสอบ

รัน unit tests (ไม่ต้องเปิด Ollama):

```bash
pytest test_memory.py test_bot.py -v
```

รันสคริปต์จำลองการคุยต่อ Ollama จริง:

```bash
python simulate_chat.py       # 9 รอบ — ดู trigger สรุปครั้งแรก
python simulate_chat_long.py  # 18 รอบ — ดู summaries สะสม 3 หัวข้อ
```

## 📝 หมายเหตุ

- บอทรันในเครื่องตัวเองทั้งหมด ข้อมูลไม่ออกไปไหน (ยกเว้นการค้นเว็บ)
- เหมาะกับการใช้ในเซิร์ฟเวอร์ส่วนตัว/วงเพื่อน
- การเล่นเพลงที่มีลิขสิทธิ์ในที่สาธารณะอาจผิดกฎ — ใช้ในวงเพื่อนเท่านั้น

## 📜 License

โปรเจกต์ส่วนตัว ใช้/ดัดแปลงได้ตามสะดวก
