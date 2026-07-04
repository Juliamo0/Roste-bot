# 🌙 รอสเต้ (Roste) — Discord AI Bot

บอท Discord ที่มีบุคลิกเป็นตัวละคร "รอสเต้" เด็กสาวดูแลห้องสมุดเวทมนตร์
ขับเคลื่อนด้วย LLM ที่รันในเครื่องตัวเอง (ผ่าน Ollama) — คุยภาษาไทย มีความจำ
ดึงข้อมูลจริงได้ สั่งพิมพ์ PDF ได้ และร้องเพลง cover ด้วยเสียงตัวเองในห้อง voice ได้

> โปรเจกต์งานอดิเรก รันในเครื่องตัวเอง (local) ทั้งหมด

## ✨ ความสามารถ

- 🎭 **บุคลิกตัวละคร** — รอสเต้ คุยไทย มีอารมณ์/น้ำเสียงเฉพาะตัว กันหลุดคาแร็กเตอร์ด้วย Author's Note
  (คุมความยาวคำตอบ 2-4 ประโยคสำหรับคำถามข้อเท็จจริง) + `fix_persona_slips()` ดักคำหลุด ("ครับ" → "ค่ะ")
  เป็น validation layer รอบสอง เผื่อโมเดลหลุดกฎใน prompt
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
- 🎤 **ร้องเพลง karaoke** — ร้องเพลง cover ด้วยเสียง RVC (ส่วนตัว ไม่แจกจ่ายโมเดล) จากโฟลเดอร์ `karaoke/`, ขอเพลงเจาะจงหรือสุ่มได้, TTS เกริ่นก่อนเล่น
- 🎙️ **รอสเต้พูดได้** — join ห้อง voice, ทักทายเมื่อเข้า, ตอบด้วยเสียง RVC จริง, ออกอัตโนมัติเมื่อห้องว่าง 15 วินาที
  - **Sentence streaming** — แบ่งคำตอบเป็นประโยค (crfcut) เล่นทีละ segment ทันทีที่เจนเสร็จ
    ไม่ต้องรอทั้งคำตอบ (latency ประโยคแรก ~6.7s แทน ~15-20s) พร้อม per-segment fail-safe
    (F5 พังกลาง stream → segment ที่เหลือสลับไป edge-tts อัตโนมัติ ไม่เงียบ ไม่เล่นซ้ำจากต้น)

## 🗂️ โครงสร้างไฟล์

### ไฟล์หลัก

| ไฟล์ | หน้าที่ |
|------|---------|
| `bot.py` | ตัวหลัก — เชื่อม Discord, LLM, เครื่องมือต่างๆ |
| `persona.py` | บุคลิกรอสเต้ — `SYSTEM_PROMPT`, few-shot examples, moods, author note |
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
| `test_bot.py` | pytest | 83 — lock, summarize, memory overflow, tool calling dispatch/validation/grounding, persona-slip filter, rate limiting, karaoke outro, fewshot ไม่มีข้อเท็จจริงตายตัว |
| `test_memory.py` | pytest | 56 — facts, recall, parse, summaries, supersede/consolidation |
| `test_realtime.py` | pytest | 51 — oil, weather, PEA, search, places (data-fetch functions ตรงๆ) |
| `test_vectormemory.py` | pytest | 15 — rerank fail-safe (output หลุดฟอร์แมต, temperature, edge case), PDF page cap |
| `test_voice.py` | pytest | 25 — streaming segment order/fail-safe, f5_preprocess (ปี/หน่วย), worker hang timeout |
| `test_printing.py` | pytest | 9 — print_jobs cleanup, pending_prints expiry |
| `test_music.py` | pytest | 9 — song_requests.json entry cap, extract_song_query tokenize |
| `test_all_systems.py` | integration script | 9 ระบบ — ยิง HTTP จริง รายงานตาราง ✅/⚠️/❌ |

รัน unit tests ทั้งหมด: `pytest test_bot.py test_memory.py test_realtime.py test_vectormemory.py test_voice.py test_printing.py test_music.py`

### tools/ — สคริปต์เสริม (ไม่ใช่ regression test)

| ไฟล์ | ใช้ทำอะไร |
|------|-----------|
| `simulate_chat_long.py` | จำลองคุย 18 รอบกับ Ollama จริง — ดู summaries สะสม |
| `simulate_recall.py` | จำลองดึง fact + recall หลัง auto-remember |
| `simulate_chat.py` | จำลองคุย 9 รอบ — ดู trigger สรุปครั้งแรก |
| `simulate_vectormemory.py` | เทส RAG PDF + semantic recall แบบ end-to-end กับ Ollama/ChromaDB จริง |
| `simulate_toolcalling.py` | เทส LLM tool calling จริง — เลือกเครื่องมือถูกไหม + multi-turn place-search |
| `simulate_fact_consolidation.py` | เทส fact supersede จริงกับ Ollama — ย้ายที่อยู่ต้อง supersede ไม่ใช่เพิ่มซ้อน |
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
5. รันบอท — ดับเบิลคลิก `start.bat`

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
| บุคลิก/น้ำเสียงรอสเต้ | `persona.py` → `SYSTEM_PROMPT` |
| ตัวอย่างบทสนทนา (few-shot) | `persona.py` → `FEWSHOT_EXAMPLES` |
| โมเดล LLM | `bot.py` → `MODEL` |
| จังหวัดบ้านเกิด (ตัดไฟ/อากาศ default) | `bot.py` → `HOME_PROVINCE_ID`, `HOME_PROVINCE_NAME` |
| จำนวน history ที่เก็บ | `memory.py` → `MAX_HISTORY_PAIRS` |
| จำนวน facts สูงสุดต่อคน | `memory.py` → `MAX_FACTS` |
| จำนวน summaries สูงสุดต่อคน | `memory.py` → `MAX_SUMMARIES` |
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

## 🧪 ทดสอบ

รัน unit tests ทั้งหมด (ไม่ต้องเปิด Ollama หรือมี internet):

```bash
pytest test_bot.py test_memory.py test_realtime.py test_vectormemory.py test_voice.py test_printing.py test_music.py -v
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
        → F5-TTS-THAI v2 (ref audio ต้นแบบ, local) → RVC (โมเดลเสียงส่วนตัว) → .wav ทีละ segment
```

**Sentence streaming:** `text_to_roste_voice_segments()` เป็น generator yield ไฟล์ `.wav` ทีละ segment
ทันทีที่เจนเสร็จ (ไม่รอทั้งคำตอบ) — `bot.py` เล่นไฟล์แรกได้เร็วขึ้น (~6.7s แทน ~15-20s สำหรับคำตอบยาว)
**per-segment fail-safe:** แต่ละ segment มี chain ของตัวเอง — F5 (retry 1 ครั้ง) → edge-tts→adjust→RVC
(เฉพาะ segment ที่พัง) → ข้าม segment (เนื้อหาหายแต่เสียงไม่สะดุด) กันปัญหากรณี F5 worker ตายกลางคำตอบยาว
ที่ segment แรกๆ เล่นไปแล้วด้วยเสียง F5 — fallback ทั้งก้อนแบบเดิมใช้ไม่ได้เพราะจะทำให้เสียงเปลี่ยนกลางคันแล้วเล่นซ้ำจากต้น

F5-TTS-THAI และ RVC ทำงานใน subprocess แยก (`f5_venv`, `rvc_venv`) เพื่อไม่ให้ dependency ชนกับบอทหลัก
cold load: F5 ~18s / RVC ~9s — หลังจากนั้น inference ~3–5s/ประโยค (F5+RVC รวม)

**Worker hang timeout:** ถ้า RVC/F5 subprocess ค้าง (GPU stall/driver hang) `RvcWorker.convert()`/
`F5Worker.generate()` จะ timeout ใน 60 วิ (`_WORKER_READ_TIMEOUT_SEC`) แล้ว kill process ทันที ให้
`.alive` กลาย False และ fail-safe chain สลับไป edge-tts ต่อได้ปกติ — เดิมไม่มี timeout เลย ทำให้
`music.voice_lock` ค้างตลอดไปถ้า worker แฮงก์แม้แต่ครั้งเดียว (บอทต้องรีสตาร์ทเองถึงจะกลับมาใช้เสียงได้)

### ติดตั้ง f5_venv (ต้องทำเอง — ไม่มีใน repo)

`f5_venv/` และ `f5_out/` อยู่ใน `.gitignore` — ต้องสร้างใหม่หลัง clone

```bash
# สร้าง venv (Python 3.11 ขึ้นไป)
py -3.11 -m venv f5_venv

# ติดตั้ง torch CUDA (RTX 30xx — CUDA 12.1)
f5_venv\Scripts\pip install torch==2.4.0 torchaudio==2.4.0 --index-url https://download.pytorch.org/whl/cu121

# ติดตั้ง F5-TTS-THAI
f5_venv\Scripts\pip install f5-tts-th
```

**ref audio:** วางไฟล์ `lai_seg4_160s.wav` ใน `f5_out/ref_test/` (path ตั้งค่าใน `voice.py` → `F5_REF_AUDIO`)

### ติดตั้ง rvc_venv (ต้องทำเอง — ไม่มีใน repo)

`rvc_venv/` และ `rvc_out/` อยู่ใน `.gitignore` — ต้องสร้างใหม่หลัง clone

**ต้องการก่อน:** [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) (สำหรับ fairseq)

```bash
# สร้าง venv Python 3.10
py -3.10 -m venv rvc_venv

# ติดตั้ง torch CUDA (RTX 30xx — CUDA 12.1)
rvc_venv\Scripts\pip install torch==2.1.0 torchaudio==2.1.0 --index-url https://download.pytorch.org/whl/cu121

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

### เพลงที่มีตอนนี้

| ไฟล์ | ชื่อเพลง | ศิลปิน |
|------|---------|--------|
| `monster_yoasobi.wav` | Monster | YOASOBI |

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
  ดูรายละเอียด/ปรับค่าได้ที่ [ROADMAP.md](ROADMAP.md) หัวข้อความปลอดภัย
- **ล็อกของบอทเก็บที่ `logs/bot.log`** (rotating file, 5MB × 3 backups) ดูย้อนหลังได้แม้ปิด console ไปแล้ว
  — เนื้อหาข้อความผู้ใช้ (PII) ไม่ถูกเขียนลงไฟล์โดย default (อยู่ระดับ DEBUG) เห็นแค่ผู้ส่ง/DM/mention
- ผ่าน code review ภายนอกมาแล้ว 3 รอบ (โครงสร้าง + ความปลอดภัย ×2) — เก็บครบทุกข้อความเสี่ยงต่ำ/กลางแล้ว
  (PDF ต่อ user มีเพดาน, DM มี allowlist แบบ opt-in, dict ใน memory ไม่โตไม่จำกัดแล้ว, `os.system` ใน
  dev scripts เปลี่ยนเป็น `subprocess.run`) จุดที่ยังเหลือเป็นเรื่องโครงสร้างระยะยาว (เช่น `bot.py`
  เริ่มยาวเกินไป, dispatch ด้วย keyword ยังเปราะ) บันทึกไว้ที่ [ROADMAP.md](ROADMAP.md) หัวข้อ
  "ผลตรวจโค้ดจาก code review ภายนอก"

## 📜 License

[PolyForm Noncommercial License 1.0.0](LICENSE) — ดู/แก้/แจกจ่ายซอร์สได้ แต่ห้ามใช้เชิงพาณิชย์
(ใช้ส่วนตัว ศึกษา ทดลอง งานอดิเรก ทำได้เต็มที่)
