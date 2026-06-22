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
- 🌐 **ข้อมูลจริง**
  - 🕐 เวลา/วันที่ (UTC+7, พ.ศ.)
  - 🌦️ พยากรณ์อากาศ (กรมอุตุฯ TMD + Open-Meteo สำรอง)
  - ⛽ ราคาน้ำมัน (Kapook — ทุกยี่ห้อ ทุกชนิด)
  - 🔌 ประกาศตัดไฟ (การไฟฟ้าส่วนภูมิภาค PEA)
  - 🔎 ค้นเว็บ (Google ผ่าน SerpApi + DuckDuckGo สำรอง)
  - 🍜 หาร้าน/สถานที่ (Google Maps ผ่าน SerpApi)
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
| `config.py` | Discord Token + API keys (สร้างเองจาก `config.example.py` — ไม่อยู่ใน repo) |
| `start.bat` | ดับเบิลคลิกเพื่อรันบอท |
| `setup.bat` | ดับเบิลคลิกเพื่อติดตั้งไลบรารี |

### ไฟล์ทดสอบ (root)

| ไฟล์ | ประเภท | จำนวน tests |
|------|--------|-------------|
| `test_bot.py` | pytest | 34 — lock, summarize, memory overflow, routing |
| `test_memory.py` | pytest | 35 — facts, recall, parse, summaries |
| `test_realtime.py` | pytest | 61 — oil, weather, PEA, search, places, routing |
| `test_all_systems.py` | integration script | 9 ระบบ — ยิง HTTP จริง รายงานตาราง ✅/⚠️/❌ |

รัน unit tests ทั้งหมด: `pytest test_bot.py test_memory.py test_realtime.py`

### tools/ — สคริปต์เสริม (ไม่ใช่ regression test)

| ไฟล์ | ใช้ทำอะไร |
|------|-----------|
| `simulate_chat_long.py` | จำลองคุย 18 รอบกับ Ollama จริง — ดู summaries สะสม |
| `simulate_recall.py` | จำลองดึง fact + recall หลัง auto-remember |
| `simulate_chat.py` | จำลองคุย 9 รอบ — ดู trigger สรุปครั้งแรก |
| `test_oil.py` | ดึงราคาน้ำมัน Kapook แบบ print-and-check |
| `test_tmd.py` | ดึงพยากรณ์อากาศ TMD รายวัน |
| `test_tmd_hourly.py` | ดึงพยากรณ์อากาศ TMD รายชั่วโมง |
| `test_outage.py` | ดึงประกาศตัดไฟ PEA |
| `test_search.py` | ทดสอบ DuckDuckGo |
| `test_serpapi.py` | ทดสอบ SerpApi key (web + maps) |
| `test_printer.py` | อ่านสถานะเครื่องพิมพ์ Windows |
| `test_nlt.py` / `test_nlt2.py` | สำรวจ API หอสมุดแห่งชาติ (NLT) |

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
   pip install discord.py aiohttp ddgs requests pypdf pywin32 PyNaCl
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

| ค่าใน `config.py` | ใช้ทำอะไร | ไม่มีจะ fallback ไป |
|-------------------|-----------|-------------------|
| `TMD_TOKEN` | พยากรณ์อากาศจากกรมอุตุฯ (แม่นสำหรับไทย) | Open-Meteo (ฟรี ไม่ต้องใช้ key) |
| `SERPAPI_KEY` | ค้นเว็บ + หาร้านผ่าน Google จริง (250 ครั้ง/เดือน) | DuckDuckGo (ฟรี ไม่ต้องใช้ key) |

## ⚙️ การปรับแต่ง

| ต้องการแก้อะไร | แก้ที่ไหน |
|---------------|----------|
| บุคลิก/น้ำเสียงรอสเต้ | `persona.py` → `SYSTEM_PROMPT` |
| ตัวอย่างบทสนทนา (few-shot) | `persona.py` → `FEWSHOT_EXAMPLES` |
| โมเดล LLM | `bot.py` → `MODEL` |
| จังหวัดบ้านเกิด (ตัดไฟ/อากาศ default) | `bot.py` → `HOME_PROVINCE_ID`, `HOME_PROVINCE_NAME` |
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

รัน unit tests ทั้งหมด (ไม่ต้องเปิด Ollama หรือมี internet):

```bash
pytest test_bot.py test_memory.py test_realtime.py -v
```

รัน integration test (ยิง HTTP จริง — ต้องต่อ internet):

```bash
python test_all_systems.py
```

รันสคริปต์จำลองการคุยต่อ Ollama จริง (ต้องเปิด Ollama):

```bash
python tools/simulate_chat_long.py   # 18 รอบ — ดู summaries สะสม 3 หัวข้อ
python tools/simulate_recall.py      # ดู fact + recall หลัง auto-remember
```

## 📝 หมายเหตุ

- บอทรันในเครื่องตัวเองทั้งหมด ข้อมูลไม่ออกไปไหน (ยกเว้นการค้นเว็บ/ดึงข้อมูลจริง)
- เหมาะกับการใช้ในเซิร์ฟเวอร์ส่วนตัว/วงเพื่อน
- การเล่นเพลงที่มีลิขสิทธิ์ในที่สาธารณะอาจผิดกฎ — ใช้ในวงเพื่อนเท่านั้น

## 📜 License

โปรเจกต์ส่วนตัว ใช้/ดัดแปลงได้ตามสะดวก
