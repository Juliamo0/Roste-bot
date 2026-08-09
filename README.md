# 🌙 รอสเต้ (Roste) — Discord AI Bot

![version](https://img.shields.io/badge/version-0.1.1--alpha-orange)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows-lightgrey)

บอท Discord ที่มีบุคลิกเป็นตัวละคร ขับเคลื่อนด้วย LLM ที่รันในเครื่องตัวเอง
(ผ่าน Ollama) — คุยภาษาไทย มีความจำ ดึงข้อมูลจริงได้ พูดด้วยเสียงสังเคราะห์
สั่งพิมพ์ PDF ได้ และร้องเพลง cover ในห้อง voice ได้

> โปรเจกต์งานอดิเรก รันในเครื่องตัวเอง (local) ทั้งหมด
> ดูรายการความสามารถ/ข้อจำกัดทั้งหมดที่ [CHANGELOG.md](CHANGELOG.md)

> ⚠️ **สถานะ: alpha** — ยังเปลี่ยนโครงสร้าง/พฤติกรรมได้ตลอดโดยไม่ถือเป็น breaking change
> รันบน Windows เท่านั้น และต้องมี GPU + Ollama ในเครื่อง

### 🎭 ตัวละคร "รอสเต้" คือ template — แก้เป็นตัวละครของคุณได้เลย

`persona.py` มีตัวละครรอสเต้มาให้ครบ (บุคลิก บทสนทนาตัวอย่าง อารมณ์ กลไกกันหลุดคาแร็กเตอร์)
แต่ตั้งใจให้เป็น **แม่แบบ** ไม่ใช่ของตายตัว — เปิดไฟล์แล้วแก้ `SYSTEM_PROMPT`,
`FEWSHOT_EXAMPLES`, `MOODS` ให้เป็นตัวละครของคุณได้เลย โครงสร้างและคอมเมนต์ในไฟล์
อธิบายไว้ว่าแต่ละส่วนมีผลยังไง รวมถึงกับดักที่เจอมาแล้วจริง (เช่น few-shot ที่มีวันที่/ราคา
จะทำให้โมเดลก๊อปคำตอบมาใช้แทนการเรียก tool)

> **เสียงไม่ได้มาด้วย** — โมเดล RVC และ reference audio เป็นเสียงส่วนตัว ไม่แจกจ่าย
> ถ้าอยากให้บอทพูดต้องเตรียม ref audio ของคุณเอง (ดูหัวข้อ [ระบบเสียง](#-ระบบเสียงรอสเต้))

## ✨ ความสามารถ

- 🎭 **บุคลิกตัวละคร** — รอสเต้ คุยไทย มีอารมณ์/น้ำเสียงเฉพาะตัว กันหลุดคาแร็กเตอร์ด้วย Author's Note
  (คุมความยาวคำตอบ 2-4 ประโยคสำหรับคำถามข้อเท็จจริง) + `fix_persona_slips()` ดักคำหลุด ("ครับ" → "ค่ะ")
  เป็น validation layer รอบสอง เผื่อโมเดลหลุดกฎใน prompt
- 🧠 **ความจำหลายชั้น**
  - จำชื่อ/ข้อเท็จจริงถาวร (สั่งได้ + จำเองอัตโนมัติเบื้องหลัง)
  - สรุปบทสนทนาเก่าอัตโนมัติเมื่อ history ล้น (แทนที่จะทิ้ง)
  - **แยกความทรงจำตามเจ้าของ** — รอสเต้รู้ว่าเรื่องไหนของผู้ใช้ เรื่องไหนของตัวเอง
    (ดู [ระบบความจำแยกเจ้าของ](#-ระบบความจำแยกเจ้าของ))
  - Selective recall — ดึงเฉพาะ fact ที่เกี่ยวกับบทสนทนาตอนนั้น (ตัดคำไทยด้วย `newmm` +
    stopword + คำพ้อง — `str.split()` ใช้กับภาษาไทยไม่ได้เพราะไม่มีช่องว่างระหว่างคำ)
  - คำสั่งความจำ: `จำไว้ว่า…` / `ลืมเรื่อง…` / `จำอะไรได้บ้าง`
- 🌐 **ข้อมูลจริง**
  - 🕐 เวลา/วันที่ (UTC+7, พ.ศ.)
  - 🌦️ พยากรณ์อากาศ (กรมอุตุฯ TMD + Open-Meteo สำรอง)
  - ⛽ ราคาน้ำมัน (Kapook — ทุกยี่ห้อ ทุกชนิด)
  - 🔌 ประกาศตัดไฟ (การไฟฟ้าส่วนภูมิภาค PEA)
  - 🔎 ค้นเว็บ (Google ผ่าน SerpApi + DuckDuckGo สำรอง)
  - 🍜 หาร้าน/สถานที่ (Google Maps ผ่าน SerpApi)
  - 🎯 **Dynamic tool selection** — ยื่นเฉพาะเครื่องมือที่เกี่ยวกับคำถามนั้น ไม่ยื่นครบทุกตัว
    (ดู [ระบบเลือกเครื่องมือ](#-ระบบเลือกเครื่องมือ-dynamic-tool-selection))
- 🖨️ **สั่งพิมพ์ PDF** — แนบไฟล์ใน Discord แล้วให้รอสเต้สั่งเครื่องพิมพ์จริง
- 🎵 **เล่นเพลง** — เล่นไฟล์ mp3 ในห้อง voice ตามที่ขอ
- 🎤 **ร้องเพลง karaoke** — ร้องเพลง cover ด้วยเสียง RVC (ส่วนตัว ไม่แจกจ่ายโมเดล) จากโฟลเดอร์ `karaoke/`, ขอเพลงเจาะจงหรือสุ่มได้, TTS เกริ่นก่อนเล่น
- 🎙️ **รอสเต้พูดได้** — join ห้อง voice, ทักทายเมื่อเข้า, ตอบด้วยเสียงสังเคราะห์ (F5-TTS-THAI
  โคลนจาก ref audio), ออกอัตโนมัติเมื่อห้องว่าง 15 วินาที
  - **Sentence streaming** — แบ่งคำตอบเป็นประโยค (crfcut) เล่นทีละ segment ทันทีที่เจนเสร็จ
    ไม่ต้องรอทั้งคำตอบ (latency ประโยคแรก ~3s แทน ~15-20s) พร้อม per-segment fail-safe
    (F5 พังกลาง stream → segment ที่เหลือสลับไป edge-tts อัตโนมัติ ไม่เงียบ ไม่เล่นซ้ำจากต้น)

## 🗂️ โครงสร้างไฟล์

### ไฟล์หลัก

| ไฟล์ | หน้าที่ |
|------|---------|
| `bot.py` | ตัวหลัก — เชื่อม Discord, LLM, เครื่องมือต่างๆ |
| `persona.py` | ตัวละคร (`SYSTEM_PROMPT`, few-shot, moods) + กลไกกันหลุดคาแร็กเตอร์ — **แก้เป็นตัวละครของคุณได้** |
| `memory.py` | ระบบความจำ — load/save/facts/recall/summaries + คำสั่งจำ-ลืม |
| `printing.py` | ระบบพิมพ์ PDF + ตั้งค่าเครื่องพิมพ์ |
| `music.py` | ระบบเล่นเพลงในห้อง voice + ตั้งค่าโฟลเดอร์เพลง |
| `config.py` | โหลดค่าลับจาก `.env` ผ่าน `python-dotenv` — ไฟล์นี้เองไม่มีค่าลับ commit ได้ปกติ |
| `start.bat` | ดับเบิลคลิกเพื่อรันบอท |
| `setup.bat` | ดับเบิลคลิกเพื่อติดตั้งไลบรารี |
| `voice.py` | voice pipeline — `text_to_roste_voice_segments(text, worker=w)` (generator, yield ทีละ segment) + `text_to_roste_voice()` (concat ครบ ต่อยอดจากตัวแรก) |
| `voice_rvc_worker.py` | subprocess worker ที่รันใน rvc_venv — โหลด RVC ครั้งเดียว รับงานผ่าน JSON stdin |
| `f5_worker.py` | subprocess worker ที่รันใน f5_venv — โหลด F5-TTS-THAI v2 ครั้งเดียว รับงานผ่าน JSON stdin |
| `f5_preprocess.py` | แก้ข้อความก่อนส่ง F5 — ตัวเลข, ปี พ.ศ./ค.ศ. (อ่านทีละหลัก), °C, หน่วย (มม./%), fuel codes, markdown → ภาษาไทย |

### ไฟล์ทดสอบ (root)

| ไฟล์ | ประเภท | จำนวน tests |
|------|--------|-------------|
| `test_bot.py` | pytest | 260 — lock, summarize (JSON + tag เจ้าของ), memory overflow, tool calling dispatch/validation/grounding, **dynamic tool selection**, persona-slip filter, AI-claim guard, **บุคลิกกันเองเสมอ/สรรพนามทางการ**, rate limiting, karaoke outro |
| `test_memory.py` | pytest | 97 — facts, recall (ตัดคำไทย/คำพ้อง), **แยกความทรงจำตามเจ้าของ**, parse, summaries, supersede/consolidation |
| `test_realtime.py` | pytest | 63 — oil, weather, PEA, search, places (data-fetch functions ตรงๆ) |
| `test_voice.py` | pytest | 68 — streaming segment order/fail-safe, ตัวซอยข้อความไทย, f5_preprocess, worker hang timeout, crossfade/edge fade |
| `test_vectormemory.py` | pytest | 19 — rerank fail-safe (output หลุดฟอร์แมต, temperature, edge case), PDF page cap |
| `test_stats.py` | pytest | 17 — stage timing, concurrent message isolation |
| `test_monitor.py` | pytest | 16 — health check, resource sampling |
| `test_config.py` | pytest | 14 — โหลด `.env`, ค่า default |
| `test_printing.py` | pytest | 9 — print_jobs cleanup, pending_prints expiry |
| `test_music.py` | pytest | 9 — song_requests.json entry cap, extract_song_query tokenize |
| `test_tts_stream.py` | pytest | 10 — prefetch ไม่บล็อก, ลำดับ segment, เก็บกวาดไฟล์ตอนหยุดกลางคัน |
| `test_all_systems.py` | integration script | 9 ระบบ — ยิง HTTP จริง รายงานตาราง ✅/⚠️/❌ |

**รวม 582 unit tests** — รันทั้งหมดด้วย `pytest` (ไฟล์เทสอยู่ใน `tests/` — `pytest.ini` ตั้ง path ให้แล้ว)
ไม่ต้องเปิด Ollama หรือต่อเน็ต (mock ล้วน) ยกเว้น `test_all_systems.py` ที่ยิง HTTP จริง

### tools/ — สคริปต์เสริม (ไม่ใช่ regression test)

| ไฟล์ | ใช้ทำอะไร |
|------|-----------|
| `simulate_chat_long.py` | จำลองคุย 18 รอบกับ Ollama จริง — ดู summaries สะสม |
| `simulate_recall.py` | จำลองดึง fact + recall หลัง auto-remember |
| `simulate_chat.py` | จำลองคุย 9 รอบ — ดู trigger สรุปครั้งแรก |
| `simulate_vectormemory.py` | เทส RAG PDF + semantic recall แบบ end-to-end กับ Ollama/ChromaDB จริง |
| `simulate_toolcalling.py` | เทส LLM tool calling จริง — เลือกเครื่องมือถูกไหม + multi-turn place-search |
| `simulate_fact_consolidation.py` | เทส fact supersede จริงกับ Ollama — ย้ายที่อยู่ต้อง supersede ไม่ใช่เพิ่มซ้อน |
| `bench_attention.py` | เทียบ 4 ทางแก้ attention dilution — ตัวที่เผยว่าทุกทางแลกกันหมด (ได้ความจำเสียข้อมูลสด) |
| `bench_realistic_tools.py` | เทียบกลยุทธ์คัด tool ผ่าน `chat.ask_ollama` เส้นจริง วัด 5 เกณฑ์พร้อมกัน (ความจำ/ข้อมูลสด/คุยเล่น/ยั่วให้หลุดเป็น AI/สรรพนาม) |
| `bench_memory_full.py` | ทดสอบความจำครบวงจรผ่าน `ask_ollama` (ไม่ประกอบ prompt เอง) |
| `bench_memory_prompt.py` | วัดผลของถ้อยคำใน prompt — ตัวที่พิสูจน์ว่าถ้อยคำไม่ใช่ตัวแปรหลัก |
| `bench_recall.py` | วัด recall layer แยกจากโมเดล (แยกความผิดของ recall ออกจาก LLM) |
| `bench_model_upgrade.py` | เทียบโมเดล/พารามิเตอร์ด้วย pass^k — เผยความไม่แน่นอนที่ pass@1 ซ่อนไว้ |
| `memory_fixture.py` | ชุดข้อมูลทดสอบความจำ (แต่งเอง ไม่ใช้บทสนทนาจริง) — 27 เคสรวมชุดหิน/คำพ้อง |
| `bench_summary_compare.py` | เทียบ 6 วิธีทำ summary — วิธี F (แยกเจ้าของ) ชนะ |
| `bench_memory_read.py` | ทดสอบส่วน "ค้น" แบบไม่เรียกโมเดล (rule ล้วน ผลไม่แกว่ง) |
| `bench_memory_search.py` | เทียบ keyword vs vector + วัด latency |
| `bench_rerank_ablation.py` | ตัด LLM rerank ได้ไหม (ผล: เก็บไว้ — จำเป็นกับเคส "ไม่เคยคุย") |
| `bench_memory_e2e.py` | วัดความจำผ่าน `chat.ask_ollama` จริง + แยก latency ทีละขั้น |
| `bench_pronoun_rate.py` | วัดว่ารอสเต้เปลี่ยนเป็นโทนทางการบ่อยแค่ไหน (สรรพนาม + วลีทางการ) — ตัดส่วนที่ยกมาเป็นตัวอย่างออกก่อนนับ |

> `bench_*.py` อ่านความจำผู้ใช้จริงเป็นข้อมูลตั้งต้น — default หยิบไฟล์ที่ใหญ่ที่สุดใน `memory/`
> เจาะจงได้ด้วย `BENCH_MEMORY_UID=<discord_user_id>` (ดู `tools/_bench_target.py`)
| `test_oil.py` | ดึงราคาน้ำมัน Kapook แบบ print-and-check |
| `test_tmd.py` | ดึงพยากรณ์อากาศ TMD รายวัน |
| `test_tmd_hourly.py` | ดึงพยากรณ์อากาศ TMD รายชั่วโมง |
| `test_outage.py` | ดึงประกาศตัดไฟ PEA |
| `test_search.py` | ทดสอบ DuckDuckGo |
| `test_serpapi.py` | ทดสอบ SerpApi key (web + maps) |
| `test_printer.py` | อ่านสถานะเครื่องพิมพ์ Windows |
| `test_nlt.py` / `test_nlt2.py` | สำรวจ API หอสมุดแห่งชาติ (NLT) |
| `make_tts_raw.py` | สร้างไฟล์เสียง TTS ดิบ (edge-tts) → `tts_raw/` |
| `adjust_raw.py` | ปรับ pitch/speed ของไฟล์ wav ด้วย ffmpeg → `tts_adjusted/` |
| `test_rvc_local.py` | ทดสอบ RVC GPU — วัด warm timing + VRAM (รันใน rvc_venv) |
| `test_speech_tone.py` | ทดสอบโทนภาษาพูด Ollama + pipeline เสียง standalone |
| `test_voice_pipeline.py` | ทดสอบ `voice.py` pipeline เต็ม (edge-tts → adjust → RVC warm) |

## 🚀 วิธีติดตั้ง

### สิ่งที่ต้องมีก่อน

- [Python](https://www.python.org/downloads/) 3.10 ขึ้นไป (ตอนติดตั้งติ๊ก "Add Python to PATH")
- [Ollama](https://ollama.com) — สำหรับรันโมเดล LLM
- (ถ้าจะใช้พิมพ์) [SumatraPDF](https://www.sumatrapdfreader.org)
- (ถ้าจะเล่นเพลง) FFmpeg — `winget install ffmpeg`

### ขั้นตอน

1. โคลนโปรเจกต์นี้ หรือดาวน์โหลด ZIP
2. ติดตั้งไลบรารี — ดับเบิลคลิก `setup.bat` (รัน `pip install -r requirements.txt` ให้อัตโนมัติ
   เวอร์ชัน pin ไว้แล้วทุกตัว reproduce ได้ตรงกันทุกเครื่อง)
   (`pythainlp` + `python-crfsuite` ใช้ตัดประโยคไทยสำหรับ sentence-streaming TTS —
   ถ้าขาด `python-crfsuite` การตัดประโยคจะพังเงียบ ไม่มี error ให้เห็น)
3. โหลดโมเดล
   ```
   ollama pull qwen3:8b
   ollama pull bge-m3
   ```
   (`qwen3:8b` หรือ `qwen3:14b` ถ้าการ์ดแรงพอ / `qwen3:1.7b` ถ้าการ์ดเล็ก — `bge-m3` ใช้ทำ embedding สำหรับความจำเชิงความหมาย + RAG PDF)
4. ตั้งค่า Token:
   - คัดลอก `.env.example` → `.env`
   - ใส่ Token จาก [Discord Developer Portal](https://discord.com/developers/applications)
   - เปิด **MESSAGE CONTENT INTENT** ใน Bot settings
5. *(ไม่บังคับ)* **แก้ตัวละคร** — เปิด `persona.py` แล้วแก้ `SYSTEM_PROMPT`,
   `FEWSHOT_EXAMPLES`, `MOODS` ให้เป็นตัวละครของคุณเอง
   (ไม่แก้ก็รันได้ จะได้รอสเต้ตามค่าเริ่มต้น)
6. รันบอท — ดับเบิลคลิก `start.bat`

### API keys เสริม (ไม่บังคับ)

| ค่าใน `.env` | ใช้ทำอะไร | ไม่มีจะ fallback ไป |
|-------------------|-----------|-------------------|
| `TMD_TOKEN` | พยากรณ์อากาศจากกรมอุตุฯ (แม่นสำหรับไทย) | Open-Meteo (ฟรี ไม่ต้องใช้ key) |
| `SERPAPI_KEY` | ค้นเว็บ + หาร้านผ่าน Google จริง (250 ครั้ง/เดือน) | DuckDuckGo (ฟรี ไม่ต้องใช้ key) |
| `PRINTER_NAME` | ชื่อเครื่องพิมพ์ที่ตั้งค่าไว้ใน Windows | ค่า default ในโค้ด (`Canon E3300 series`) |

> `config.py` เป็นแค่ตัวโหลดค่าจาก `.env` (ไม่มีค่าลับในไฟล์เอง) ไม่ต้องแก้อะไรในนั้น

## ⚙️ การปรับแต่ง

| ต้องการแก้อะไร | แก้ที่ไหน |
|---------------|----------|
| บุคลิก/น้ำเสียงตัวละคร | `persona.py` → `SYSTEM_PROMPT` |
| ตัวอย่างบทสนทนา (few-shot) | `persona.py` → `FEWSHOT_EXAMPLES` |
| อารมณ์ที่สุ่มมาใช้ | `persona.py` → `MOODS` |
| โมเดล LLM | `ollama_client.py` → `MODEL` |
| จังหวัดบ้านเกิด (ตัดไฟ/อากาศ default) | `datasources.py` → `HOME_PROVINCE_ID`, `HOME_PROVINCE_NAME` |
| จำนวน history ที่เก็บ | `memory.py` → `MAX_HISTORY_PAIRS` |
| จำนวน facts สูงสุดต่อคน | `memory.py` → `MAX_FACTS` |
| จำนวน summaries สูงสุดต่อคน | `memory.py` → `MAX_SUMMARIES` |
| คำที่ชี้ว่าคำถามต้องใช้เครื่องมือไหน | `llm_tools.py` → `TOOL_HINTS` (ดู [ระบบเลือกเครื่องมือ](#-ระบบเลือกเครื่องมือ-dynamic-tool-selection)) |
| ยื่น `search_web` ไว้เสมอ | `llm_tools.py` → `ALWAYS_OFFER_SEARCH_WEB` |
| ตั้งค่าเครื่องพิมพ์ | `printing.py` → `PRINTER_NAME` |
| เพิ่มเพลงทั่วไป | วางไฟล์ `.mp3` ในโฟลเดอร์ `songs/` |
| เพิ่มเพลง karaoke | วางไฟล์ `.wav` ในโฟลเดอร์ `karaoke/` ตั้งชื่อ `[ชื่อเพลง]_[ศิลปิน].wav` |

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

## 🎯 ระบบเลือกเครื่องมือ (Dynamic tool selection)

รอสเต้มีเครื่องมือ 6 ตัว แต่**ไม่ได้ยื่นให้โมเดลครบทุกตัวทุกครั้ง** — คัดเฉพาะตัวที่เกี่ยวกับคำถามนั้น
ผ่าน `llm_tools.select_tools()`

### ทำไมต้องคัด

เจอปัญหาจริง: ผู้ใช้ถาม "เราเคยคุยเรื่องการอ่านไหม" แล้วรอสเต้ตอบว่าไม่เคย **ทั้งที่ summary
ของบทสนทนานั้นอยู่ใน context ครบถ้วนแล้ว**

ต้นเหตุไม่ใช่ระบบความจำ และไม่ใช่ถ้อยคำใน prompt — เป็น**ขนาดของ tool schema** เมื่อยื่นเครื่องมือ
เยอะเกินไป โมเดลจะละเลยข้อมูลส่วนอื่นใน context (attention dilution / *Over-Tooled Agent*)

วัดได้ว่าเกณฑ์อยู่ราว **3,700 ตัวอักษร** — และไม่เกี่ยวกับ*เนื้อหา*ของ tool เลย เพราะ tool ปลอมที่
description เป็นตัว `x` ล้วนก็ทำให้พังเท่ากับ tool จริง เครื่องมือทั้ง 6 ตัวรวมกัน = 4,292c จึงเกิน
เกณฑ์ทุกครั้ง

### ผลที่วัดได้

| | ความจำ | ข้อมูลสด | ขนาด tool |
|---|---|---|---|
| ยื่นครบ 6 ตัว | 30/120 (25%) | 100/100 | 4,292c |
| **คัดตามคำถาม** | **120/120 (100%)** | 100/100 | **725c** |

วัดด้วย pass^40 (n=120) ช่วงความเชื่อมั่น 95% ไม่ซ้อนทับกัน = ต่างจริง ไม่ใช่ noise
และความแม่นในการเลือกเครื่องมือ**ไม่ตกเลย** — ได้ทั้งสองฝั่งพร้อมกัน

### ข้อดีที่ตามมา

คำถามที่ไม่ต้องใช้เครื่องมือ (ความจำล้วน/คุยเล่น) จะได้ 0 tool **โดยอัตโนมัติ** เพราะไม่มีคำที่ชี้
เครื่องมือใดๆ — ไม่ต้องมีกฎเดาว่า "คำถามนี้เป็นเรื่องความจำหรือเปล่า" ซึ่งเปราะและผิดได้ง่าย
(เช่น "เมื่อวานอากาศเป็นไง" เป็นทั้งคำถามความจำและข้อมูลสดพร้อมกัน)

### ปรับแต่ง

| ต้องการ | ทำอย่างไร |
|---------|-----------|
| เพิ่มคำที่ชี้เครื่องมือ | `llm_tools.py` → `TOOL_HINTS` |
| ยื่น `search_web` ไว้เสมอ | `llm_tools.py` → `ALWAYS_OFFER_SEARCH_WEB = True` |

> ⚠️ **เพิ่มเครื่องมือใหม่ต้องเพิ่มคำใน `TOOL_HINTS` ด้วย** ไม่งั้นเครื่องมือนั้นจะไม่ถูกยื่นให้โมเดลเลย

เปิด `ALWAYS_OFFER_SEARCH_WEB` เมื่อเจอคำถามข้อมูลสดที่ `TOOL_HINTS` ครอบไม่ถึง (เช่น
"ใครชนะเลือกตั้ง") แล้วรอสเต้เดาคำตอบแทนการค้น — วัดแล้วว่าเปิดไม่ทำให้ด้านอื่นแย่ลง แค่ขนาดโตขึ้น
เป็น ~1,057c ซึ่งยังห่างเกณฑ์มาก

## 🧠 ระบบความจำแยกเจ้าของ

รอสเต้จำได้ว่า **เรื่องไหนของผู้ใช้ เรื่องไหนของตัวเอง** — ไม่ปนกัน

### ปัญหาที่แก้

summary เดิมเก็บแค่หัวข้อ ไม่เก็บเนื้อหา และเขียนรวมกันเป็นประโยคเดียว:
```
"23 ก.ค.: คุยเรื่องความแตกต่างระหว่างเจลาโต้และไอศกรีม"
```
ผู้ใช้ถาม "ผมชอบของหวานอะไร" → ตอบไม่ได้ เพราะ summary ไม่ได้เก็บว่าใครชอบอะไร

แย่กว่านั้น เมื่อ summary มีทั้งความชอบของผู้ใช้และของรอสเต้ปนกัน โมเดล**จำสลับเจ้าของ 29%**
(1 ใน 3 ครั้ง) — รอสเต้เชื่อว่าผู้ใช้ชอบสิ่งที่ตัวเองชอบ ซึ่งแย่กว่าการจำไม่ได้

### วิธีแก้ — ติดป้ายเจ้าของตั้งแต่ตอนบันทึก

```
"1 ส.ค.: คุยแนวนิยาย | user_pref:ชอบนิยายสืบสวน me_pref:ชอบแนวแฟนตาซี"
                       └── ของผู้ใช้ ──┘  └── ของรอสเต้ ──┘
```

| tag | เก็บอะไร |
|-----|----------|
| `user_pref:` | สิ่งที่ผู้ใช้ชอบ/ไม่ชอบ |
| `user_fact:` | ข้อเท็จจริงของผู้ใช้ |
| `me_pref:` | สิ่งที่รอสเต้เองชอบ/ไม่ชอบ |
| `me_fact:` | สิ่งที่รอสเต้ทำหรือเป็น |

แล้วตอนตอบ **กรองเหลือเฉพาะฝั่งที่ถูกถามก่อนส่งเข้า context**:
```
ถาม "ผมชอบอะไร"     → ส่งแค่ "— ผู้ใช้: ชอบนิยายสืบสวน"
ถาม "รอสเต้ชอบอะไร"  → ส่งแค่ "— รอสเต้: ชอบแนวแฟนตาซี"
```

### ผลที่วัดได้

| | เดิม | หลังแก้ |
|---|---|---|
| จำสลับเจ้าของ | 29% | **0%** |
| เก็บรายละเอียดผู้ใช้ | 0% | **100%** |
| ค้นเจอ (ชุดทดสอบ 17 เคส) | 5/17 | **17/17** |
| ผ่าน `ask_ollama` จริง | — | **89%** (n=100) |

### สิ่งที่ต้องรู้ถ้าจะแก้ต่อ

- **3 ส่วนต้องทำงานร่วมกัน** — บันทึก (tag) → ค้น (กรองฝั่ง) → ส่ง (กรองอีกชั้น)
  แก้อย่างเดียวไม่ได้ผล
- **summary เก่าที่ไม่มี tag ยังใช้ได้** — มีทางถอย: ถ้าไม่มี tag เลยจะไม่กรอง
  (ไม่งั้นผู้ใช้เดิมจะเจอบอทลืมทุกอย่างทันทีที่อัปเดต)
- **`vector search` ค้นแม่นกว่า keyword ในเคสคำพ้อง** (30/30 vs 21/30) เพราะ keyword
  ต้องมีคำตรง — "เลี้ยงสัตว์" ไม่แมตช์ "เลี้ยงแมว"

รายละเอียดการทดลองทั้งหมด (พร้อมตัวเลขทุกตัวและ bench script) อยู่ที่
**[docs/MEMORY_EXPERIMENTS.md](docs/MEMORY_EXPERIMENTS.md)**

## 🧪 ทดสอบ

รัน unit tests ทั้งหมด (ไม่ต้องเปิด Ollama หรือมี internet):

```bash
pytest
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

## 🎙️ ระบบเสียงรอสเต้

### สถานะ

| เฟส | รายละเอียด | สถานะ |
|-----|-----------|-------|
| เฟส 1 | RVC รันในเครื่องได้ (GPU, warm ~1–2s/ประโยค) | ✅ เสร็จ |
| เฟส 2 | pipeline เสียงทำงาน standalone (`voice.py`) | ✅ เสร็จ |
| เฟส 3 (3a–3c) | integrate เข้า bot.py — join, ทักทาย, พูดตอบ, leave timer | ✅ เสร็จ |
| เฟส 3 (3d) | move logic — ย้ายตามคนถ้าถูกเรียกจากห้องอื่น | ✅ เสร็จ (ทำงานอยู่แล้วผ่าน `_speak_in_voice`/`_play_karaoke`) |
| เฟส 4 | karaoke — ร้องเพลง cover ด้วยเสียงตัวเองในห้อง voice | ✅ เสร็จ |
| เฟส 5 | sentence streaming — เล่นทีละประโยคทันทีที่เจนเสร็จ + per-segment fail-safe | ✅ เสร็จ |

### pipeline

```
ข้อความ → crfcut (ตัดเป็นประโยค) → f5_preprocess.py (ตัวเลข/ปี/°C/หน่วย/fuel codes → ไทย)
        → F5-TTS-THAI v2 (ref audio ต้นแบบ, local) → pitch shift 108% → edge fade → .wav ทีละ segment
```

**ไม่ผ่าน RVC แล้วสำหรับ TTS ปกติ** (`F5_THEN_RVC = False` ใน `voice.py`) — ผู้ใช้ฟังเทียบแล้วเลือก
F5 + pitch 108% ล้วน ลดขั้นตอน/latency ลงหนึ่งขั้น RVC ยังเก็บโค้ด+worker ไว้ครบเพราะ **karaoke ยังใช้อยู่**

**รอยต่อระหว่าง segment:** เส้น streaming เล่นทีละไฟล์ผ่าน Discord จึง crossfade แท้ไม่ได้ (คลื่นสองก้อน
ไม่เคยเล่นซ้อนกัน) — ใช้ fade หัว/ท้าย 15ms ต่อ segment แทน (`SEG_EDGE_FADE_MS`) แก้เสียงคลิก/ป๊อปที่เกิด
จากคลื่นถูกตัดกลางคัน ส่วนเส้นไฟล์เดียว (`text_to_roste_voice` → `_concat_wavs`) รวมเป็น array เดียวได้
จึง crossfade แท้ 150ms (`SEG_CROSSFADE_MS`) ตั้ง 0 ทั้งคู่เพื่อกลับพฤติกรรมเดิม

> ⚠️ fade แก้ได้แค่เสียงคลิกตรงรอยต่อ **ไม่ได้แก้โทน/จังหวะที่กระโดด** ซึ่งมาจากการที่แต่ละ segment เจน
> แยกกันจาก ref เดียวโดยไม่รู้บริบทก้อนก่อนหน้า — เป็นข้อจำกัดของสถาปัตยกรรม ไม่ใช่ของ fade

**Sentence streaming:** `text_to_roste_voice_segments()` เป็น generator yield ไฟล์ `.wav` ทีละ segment
ทันทีที่เจนเสร็จ (ไม่รอทั้งคำตอบ) — `bot.py` เล่นไฟล์แรกได้เร็วขึ้น (~3s แทน ~15-20s สำหรับคำตอบยาว
วัดจาก log จริง: segment ทยอยออกทุก ~3-4 วินาทีสม่ำเสมอตลอดคำตอบ 15 segment)
**per-segment fail-safe:** แต่ละ segment มี chain ของตัวเอง — F5 (retry 1 ครั้ง) → edge-tts→adjust→RVC
(เฉพาะ segment ที่พัง) → ข้าม segment (เนื้อหาหายแต่เสียงไม่สะดุด) กันปัญหากรณี F5 worker ตายกลางคำตอบยาว
ที่ segment แรกๆ เล่นไปแล้วด้วยเสียง F5 — fallback ทั้งก้อนแบบเดิมใช้ไม่ได้เพราะจะทำให้เสียงเปลี่ยนกลางคันแล้วเล่นซ้ำจากต้น

F5-TTS-THAI และ RVC ทำงานใน subprocess แยก (`f5_venv`, `rvc_venv`) เพื่อไม่ให้ dependency ชนกับบอทหลัก
cold load (วัดจาก log จริง หลายรอบ): **F5 ~13–36s / RVC ~5–18s** — แกว่งตาม disk cache
ว่าอุ่นหรือเย็น (รีสตาร์ทติดๆ กันจะเร็วกว่ารอบแรกหลังเปิดเครื่องมาก)

หลัง warm แล้ว F5 เจนเร็วกว่าเวลาเล่นจริง (RTF ~0.65) — prefetch จึงกลบช่องว่างระหว่าง
segment ได้หมด เสียงออกต่อเนื่องไม่สะดุด

> RVC ยังโหลดค้างไว้ (~1GB VRAM) แม้ TTS ปกติจะไม่ผ่าน RVC แล้ว เพราะ **karaoke ยังใช้อยู่**
> — ถ้าไม่โหลดล่วงหน้า สั่งร้องเพลงครั้งแรกจะต้องรอ cold load

**Worker hang timeout:** ถ้า RVC/F5 subprocess ค้าง (GPU stall/driver hang) `RvcWorker.convert()`/
`F5Worker.generate()` จะ timeout ใน 60 วิ (`_WORKER_READ_TIMEOUT_SEC`) แล้ว kill process ทันที ให้
`.alive` กลาย False และ fail-safe chain สลับไป edge-tts ต่อได้ปกติ — เดิมไม่มี timeout เลย ทำให้
`music.voice_lock` ค้างตลอดไปถ้า worker แฮงก์แม้แต่ครั้งเดียว (บอทต้องรีสตาร์ทเองถึงจะกลับมาใช้เสียงได้)

### ติดตั้ง f5_venv (ต้องทำเอง — ไม่มีใน repo)

`f5_venv/` และ `f5_out/` อยู่ใน `.gitignore` — ต้องสร้างใหม่หลัง clone

```bash
# สร้าง venv — ใช้ Python 3.10 (เวอร์ชันเดียวกับ venv หลักและ rvc_venv)
py -3.10 -m venv f5_venv

# ติดตั้ง torch CUDA — เวอร์ชันที่ใช้จริงบนเครื่อง dev คือ torch 2.11.0+cu128
# เลือก index-url ให้ตรงกับ CUDA ของการ์ดตัวเอง (cu128 = CUDA 12.8)
f5_venv\Scripts\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

# ติดตั้ง F5-TTS-THAI
f5_venv\Scripts\pip install f5-tts-th
```

**ref audio (ต้องเตรียมเอง — ไม่มีใน repo):**

F5 โคลนเสียงจากไฟล์ต้นแบบ ซึ่งเป็นเสียงส่วนตัวจึงไม่ได้แจกมาด้วย ต้องเตรียมเอง:

1. เตรียมไฟล์ `.wav` เสียงพูดชัดๆ ยาว **10–160 วินาที** (ยิ่งชัด ไม่มีเสียงรบกวน ยิ่งโคลนได้ดี)
2. วางไว้ในโฟลเดอร์ `ref_audio/`
3. แก้ `voice.py` → `F5_REF_AUDIO` ให้ชี้ไฟล์นั้น
4. แก้ `voice.py` → `F5_REF_TEXT` ให้เป็นข้อความที่ตรงกับคำพูดในไฟล์ (ถอดเทปเอง)
   — ถ้าไม่ตรง เสียงที่ได้จะเพี้ยน

> ถ้าไม่มีไฟล์นี้ บอทจะยังรันได้ปกติ (แชตได้) แต่ตอนเรียกใช้เสียงจะขึ้น error
> พร้อมบอกขั้นตอนข้างบนซ้ำให้

### ติดตั้ง rvc_venv (ต้องทำเอง — ไม่มีใน repo)

`rvc_venv/` และ `rvc_out/` อยู่ใน `.gitignore` — ต้องสร้างใหม่หลัง clone

**ต้องการก่อน:** [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (สำหรับ fairseq)

```bash
# สร้าง venv Python 3.10
py -3.10 -m venv rvc_venv

# ติดตั้ง torch CUDA — เวอร์ชันที่ใช้จริงบนเครื่อง dev คือ torch 2.11.0+cu128
rvc_venv\Scripts\pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128

# ติดตั้ง RVC
rvc_venv\Scripts\pip install rvc-python==0.1.5
```

**โมเดล:** วาง `.pth` และ `.index` ที่ path ตั้งค่าใน `voice.py` → `MODEL_DIR` (โมเดลเสียงเป็นของส่วนตัว
ไม่ได้แจกจ่ายมากับ repo นี้ และไม่ควรนำไปใช้เชิงพาณิชย์ตามความประสงค์ของเจ้าของเสียงต้นทาง)

ทดสอบ pipeline:
```bash
python tools/test_voice_pipeline.py
```

## 🎤 ระบบ Karaoke

รอสเต้ร้องเพลง cover ด้วยเสียง RVC ส่วนตัวในห้อง voice

**sequence:** เกริ่นก่อนร้อง ("จะร้องเพลง X ให้ฟังนะคะ") → เล่นเพลง → พูดปิดท้าย ("ร้องเพลง X จบแล้วค่ะ
เป็นไงบ้างคะ เพราะไหม~") → disconnect (เดิม disconnect ทันทีไม่พูดอะไรเลยหลังร้องจบ รู้สึกห้วน — แก้แล้ว)

### วิธีใช้ใน Discord

| พิมพ์ | ผล |
|------|----|
| `@รอสเต้ ร้องเพลง monster` | ร้องเพลงที่ขอ |
| `@รอสเต้ ร้องเพลงให้ฟัง` | สุ่มเพลงจากคลัง |

### pipeline สร้างเพลง cover

```
เพลงต้นฉบับ
  └─▶ UVR (Ultimate Vocal Remover) — แยกเสียงร้องออกจากดนตรี → vocals.wav
        └─▶ RVC (GPU) — แปลงเสียงร้องเป็นเสียงรอสเต้ (~15s) → roste_vocals.wav
              └─▶ mix (Audacity/ffmpeg) — ผสม roste_vocals + instrumental (optional)
                    └─▶ karaoke/[ชื่อเพลง]_[ศิลปิน].wav
```

> mix กับ instrumental ทำให้เสียงอิ่มขึ้น แต่ถ้าใช้แค่ vocals ก็ฟังได้

> **อนาคต:** [Synthesizer V Studio](https://dreamtonics.com/synthv/) + โมเดลเสียงรอสเต้ → สร้างเสียงร้องสังเคราะห์ตรงๆ ไม่ต้องพึ่งต้นฉบับ (มีโอกาสสูงกว่า UVR+RVC ในคุณภาพระดับ studio)

### วิธีเพิ่มเพลงใหม่

1. แยกเสียงร้องด้วย UVR → ได้ไฟล์ vocals `.wav`
2. แปลงด้วย RVC โมเดลเสียงส่วนตัว (ผ่าน `rvc_venv`)
3. ตั้งชื่อไฟล์รูปแบบ **`[ชื่อเพลง]_[ศิลปิน].wav`**
   - `monster_yoasobi.wav` → รอสเต้เรียกชื่อ "Monster"
   - `blinding_lights_weeknd.wav` → "Blinding Lights"
4. วางไฟล์ในโฟลเดอร์ `karaoke/`
5. ไม่ต้อง restart บอท — ค้นหาไฟล์แบบ on-demand

### คลังเพลง

โฟลเดอร์ `karaoke/` ไม่ได้ commit ขึ้น repo (ลิขสิทธิ์เป็นของเจ้าของเพลง) — ต้องเตรียมเอง
บอทค้นไฟล์แบบ on-demand ทุกครั้งที่ถูกขอ จึงเพิ่ม/ลบเพลงได้โดยไม่ต้องรีสตาร์ท

## 🔧 Troubleshooting

| ปัญหา | สาเหตุ | วิธีแก้ |
|--------|--------|---------|
| WebSocket close 4017 / reconnect loop | Discord DAVE protocol (E2EE audio) — discord.py เก่าไม่รองรับ | `pip install "discord.py[voice]>=2.7.1"` |
| `RuntimeError: PyNaCl library needed` | PyNaCl ไม่ได้ติดตั้งใน venv ที่บอทรัน | `pip install PyNaCl` ใน venv ที่รันบอทจริง |
| RVC ไม่ทำงาน / CUDA error | Python version หรือ torch mismatch | ใช้ Python 3.10 + torch CUDA ตรงกับ GPU ใน `rvc_venv` แยก |
| `.gitignore` ไม่ทำงาน | git ไม่รองรับ inline comment ท้าย pattern line | ย้าย comment ขึ้นบรรทัดก่อน pattern แยกต่างหาก |

## 📝 หมายเหตุ

- บอทรันในเครื่องตัวเองทั้งหมด ข้อมูลไม่ออกไปไหน (ยกเว้นการค้นเว็บ/ดึงข้อมูลจริง)
- เหมาะกับการใช้ในเซิร์ฟเวอร์ส่วนตัว/วงเพื่อน
- การเล่นเพลงที่มีลิขสิทธิ์ในที่สาธารณะอาจผิดกฎ — ใช้ในวงเพื่อนเท่านั้น
- **โมเดลเสียง RVC ที่ใช้เป็นของส่วนตัว ไม่ได้แจกจ่ายมากับ repo นี้** และไม่ใช้เชิงพาณิชย์ตามความประสงค์ของ
  เจ้าของเสียงต้นทาง — ถ้าจะทำ voice cloning เอง ต้องหาข้อมูลเสียง/โมเดลของตัวเอง
- มี rate limiting พื้นฐานแล้ว (cooldown ต่อ user, guild allowlist ผ่าน `.env`, โควตา SerpApi ต่อวัน) —
  ดูรายละเอียด/ปรับค่าได้ที่ [ROADMAP.md](docs/ROADMAP.md) หัวข้อความปลอดภัย
- **ล็อกของบอทเก็บที่ `logs/bot.log`** (rotating file, 5MB × 3 backups) ดูย้อนหลังได้แม้ปิด console ไปแล้ว
  — เนื้อหาข้อความผู้ใช้ (PII) ไม่ถูกเขียนลงไฟล์โดย default (อยู่ระดับ DEBUG) เห็นแค่ผู้ส่ง/DM/mention
- ผ่าน code review ภายนอกมาแล้ว 3 รอบ (โครงสร้าง + ความปลอดภัย ×2) — เก็บครบทุกข้อความเสี่ยงต่ำ/กลางแล้ว
  (PDF ต่อ user มีเพดาน, DM มี allowlist แบบ opt-in, dict ใน memory ไม่โตไม่จำกัดแล้ว, `os.system` ใน
  dev scripts เปลี่ยนเป็น `subprocess.run`) จุดที่ยังเหลือเป็นเรื่องโครงสร้างระยะยาว (เช่น `bot.py`
  เริ่มยาวเกินไป, dispatch ด้วย keyword ยังเปราะ) บันทึกไว้ที่ [ROADMAP.md](docs/ROADMAP.md) หัวข้อ
  "ผลตรวจโค้ดจาก code review ภายนอก"

## 📜 License

[PolyForm Noncommercial License 1.0.0](LICENSE) — ดู/แก้/แจกจ่ายซอร์สได้ แต่ห้ามใช้เชิงพาณิชย์
(ใช้ส่วนตัว ศึกษา ทดลอง งานอดิเรก ทำได้เต็มที่)
