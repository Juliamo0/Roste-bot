# 🗺️ ROADMAP — โปรเจกต์รอสเต้ (Roste)

วิสัยทัศน์: ผู้ช่วย AI ที่มีบุคลิก คุยกับเราได้ (พิมพ์และเสียง)
ควบคุมอุปกรณ์ IoT ในบ้านได้ ตัดสินใจบางอย่างได้ และทำงานในโลกจริงได้
โดยใช้ LLM ที่รันในเครื่องตัวเอง (local)

> อัปเดตล่าสุด: 29 มิถุนายน 2569

---

## ✅ เสร็จแล้ว (ใช้งานได้จริง)

### 🧠 แกนหลัก — แชต + บุคลิก
- [x] เชื่อม Discord + Ollama (LLM รันในเครื่อง)
- [x] บุคลิกตัวละคร "รอสเต้" (พูดไทย เป็นผู้หญิง มีน้ำเสียง/อารมณ์)
- [x] ระบบ Mood + Author's Note (ฉีดกฎติดคำตอบ กันหลุดคาแร็กเตอร์)
- [x] ความจำรายคน (จำชื่อ/เรื่องที่คุย, คำสั่ง "จำไว้ว่า"/"ลืมทุกอย่าง")
- [x] เลือกขนาดโมเดลได้ (qwen3:8b สมดุล / 14b ฉลาดขึ้นแต่ช้า)

### 🌐 ดึงข้อมูลจริง
- [x] เวลา/วันที่ (เขตไทย, พ.ศ.)
- [x] พยากรณ์อากาศ — TMD กรมอุตุฯ (รายวัน + รายชั่วโมง) + Open-Meteo สำรอง
- [x] ราคาน้ำมัน (ดึงจาก Kapook ทุกยี่ห้อ ทุกชนิด)
- [x] ประกาศตัดไฟ (การไฟฟ้าส่วนภูมิภาค PEA — กรองเฉพาะจังหวัดที่ตั้ง)
- [x] ค้นเว็บ (Google ผ่าน SerpApi + DuckDuckGo สำรอง, กรองเนื้อหาไม่เหมาะสม)
- [x] หาร้าน/สถานที่ (Google Maps ผ่าน SerpApi — เรตติ้ง/ที่อยู่/เวลาเปิด)

### 🖨️ IoT จริงชิ้นแรก — สั่งพิมพ์ PDF
- [x] รับไฟล์ PDF จาก Discord แล้วสั่งเครื่องพิมพ์จริง (Canon E3300)
- [x] พิมพ์เงียบด้วย SumatraPDF (ไม่เด้งหน้าต่าง)
- [x] ยืนยันก่อนพิมพ์งานใหญ่ (เกิน 5 ชุด / 20 หน้า)
- [x] ล็อกระหว่างพิมพ์ + แจ้งสถานะ + @ คนสั่ง
- [x] เช็คเครื่องออนไลน์ + จับงานค้างคิว (รู้เมื่อพิมพ์ไม่ออก)
- [ ] ~~อ่านสถานะหมึก/กระดาษเจาะจง~~ → ทำไม่ได้ (Canon USB ไม่ส่งให้ Windows)

### 🎵 ระบบเพลง + Karaoke (เฟส 4)
- [x] เล่นไฟล์ mp3/wav ในห้อง voice ของ Discord
- [x] ตอบเป็นธรรมชาติเมื่อไม่มีเพลงที่ขอ
- [x] บันทึกประวัติการขอเพลง (รู้ว่าควรเตรียมเพลงไหนเพิ่ม)
- [x] **เฟส 4 — karaoke: รอสเต้ร้องเพลง cover ด้วยเสียงตัวเอง**
  - UVR (Ultimate Vocal Remover) แยกเสียงร้องออกจากเพลงต้นฉบับ
  - RVC Laibaht แปลงเสียงร้องเป็นเสียงรอสเต้ (~15s บน GPU)
  - วางไฟล์ที่ได้ใน `karaoke/` ตั้งชื่อ `[ชื่อเพลง]_[ศิลปิน].wav`
  - สั่ง `@รอสเต้ ร้องเพลง monster` หรือ `ร้องเพลงให้ฟัง` (สุ่ม) ในห้อง voice
  - sequence: TTS เกริ่น "จะร้องเพลง X ให้ฟัง" → เล่นเพลง → disconnect

### 🎙️ ระบบเสียงรอสเต้ — pipeline + integrate (เฟส 1–3)
- [x] ยืนยันว่า qwen3:8b + RVC อยู่บน 4GB VRAM พร้อมกันได้ (qwen ~2.4GB + RVC peak ~0.9GB)
- [x] RVC รันในเครื่อง (GPU, warm ~1–2s/ประโยค) — รัน inference ผ่าน rvc_venv (Python 3.10) แยก
- [x] **F5-TTS-THAI v2** — แทนที่ edge-tts ด้วย flow matching TTS ภาษาไทย local ล้วน (clone เสียง Laibaht ด้วย ref audio)
  - pipeline: `f5_preprocess.py` (ตัวเลข/°C/fuel codes → ไทย) → F5-TTS-THAI v2 → RVC (Laibaht) → .wav
  - cold load: F5 ~18s / RVC ~9s — warm inference ~3–5s/ประโยค รวม F5+RVC
  - ๆ expansion, number reading, degree symbols จัดการถูกต้อง
- [x] `voice.py` + `voice_rvc_worker.py` + `f5_worker.py` + `f5_preprocess.py` — warm worker subprocess (JSON stdin/stdout)
- [x] ทดสอบ standalone ครบ (`tools/test_voice_pipeline.py`) — warm ~1–2s/ประโยค หลัง cold load ~8s
- [x] **เฟส 3a** — wire `RvcWorker` เข้า bot.py, gen TTS file หลังตอบ, โหลด worker เบื้องหลังตอน startup
- [x] **เฟส 3b** — join ห้อง voice, ทักทายเมื่อเข้าครั้งแรก (cache), เล่นคำตอบ, ค้างห้อง
- [x] **เฟส 3c** — leave timer: ออกห้องอัตโนมัติเมื่อว่าง 15s, cancel ได้ถ้าคนกลับมา
- [x] เล่นทักทาย + ทำ TTS คำตอบ **concurrent** (ทักทายไม่รอ TTS คำตอบ — ลด latency)
- [x] upgrade `discord.py` → 2.7.1 + `davey` (แก้ WebSocket close code 4017 จาก DAVE protocol)

### 🛠️ โครงสร้าง/เครื่องมือ
- [x] แยกโค้ดเป็นไฟล์ (bot.py / printing.py / music.py)
- [x] start.bat + setup.bat (ดับเบิลคลิกรัน/ติดตั้ง)
- [x] อัปขึ้น GitHub อย่างปลอดภัย (กัน Token หลุดด้วย .gitignore)

---

## 🔧 ปรับปรุงโค้ดภายใน (ไม่ได้อยู่ใน roadmap หลัก)

งานต่อไปนี้ทำเพื่อให้โค้ดสะอาด แข็งแกร่ง และต่อยอดได้ง่ายขึ้น
ไม่ใช่ feature ใหม่ตามวิสัยทัศน์ แต่เป็นพื้นฐานที่จำเป็น

### 🗂️ Refactor โครงสร้าง
- [x] แยก `persona.py` — SYSTEM_PROMPT, few-shot, moods, author note ออกจาก bot.py
- [x] แยก `memory.py` — load/save/facts/recall + คำสั่งจำ-ลืม ออกจาก bot.py

### 🧠 ระบบความจำ (ปรับปรุงจากของเดิม)
- [x] Selective recall — ดึงเฉพาะ fact ที่เกี่ยวกับข้อความปัจจุบัน (กัน context ล้น)
- [x] Auto-remember — สกัดข้อเท็จจริงจากบทสนทนาเบื้องหลังอัตโนมัติ (ไม่บล็อกการตอบ)
- [x] Conversation summaries — บทสนทนาที่ล้น history แทนที่จะทิ้ง สรุปเป็น 1 บรรทัดเก็บไว้
- [x] แก้ race condition — `asyncio.Lock` ต่อ user_id ครอบ critical section load→save
- [x] `pending_place_query` ย้ายออกจาก JSON ไปเก็บใน RAM (`_pending_place` dict)
- [x] แก้ SELF_REFERENCE_HINTS — ลบ `"มี"` เดี่ยว ใส่รูปผูกสรรพนาม (`"ผมมี"`, `"ฉันมี"` ฯลฯ)
- [x] asyncio Queue + bg worker — serialize งาน Ollama background (แก้ TimeoutError เมื่อ summarize + auto-remember ชนกัน)
- [x] ย้าย `_last_had_summary_notice` state เข้า `_maybe_append_summary_notice` (แก้ notice ไม่แสดง)

### 🧪 Testing
- [x] Unit tests สำหรับ memory.py — 35 tests (pytest)
- [x] Unit tests สำหรับ bot.py — 34 tests (mock Ollama)
- [x] Unit tests สำหรับ realtime functions — 61 tests (mock HTTP ทุกระบบ)
- [x] Integration test `test_all_systems.py` — ยิง HTTP จริง 9 ระบบ รายงานตาราง ✅/⚠️/❌
- [x] จัดไฟล์ทดสอบ — pytest ไว้ root, diagnostic scripts ย้ายไป `tools/`
- [x] `tools/simulate_chat_long.py` — จำลอง 18 รอบ 3 หัวข้อ ดู summaries สะสม
- [x] `tools/simulate_recall.py` — จำลองดึง fact + recall หลัง auto-remember

---

## ⏳ กำลังค้างอยู่ (เริ่มแล้ว ยังไม่จบ)

### 🔊 เฟส 3d — move logic
- [ ] รอสเต้ย้ายตามคน ถ้าถูก @mention จากห้อง voice อื่น → `move_to(new_channel)`

---

## ⚠️ Known Issues

### เสียงพูด — ข้อจำกัด F5-TTS-THAI
- **cold load ~18s** — บอทรอ F5 worker พร้อมก่อนตอบด้วยเสียงได้ (ตอบแชตได้ก่อน warm เสร็จ)
- **F5 ออกเสียงผิด** กรณีข้อความมีตัวเลข/หน่วย/โค้ดพิเศษที่ `f5_preprocess.py` ยังไม่ครอบคลุม — แก้ได้โดยเพิ่ม regex ใน `preprocess_for_f5()`
- **อารมณ์เสียง** ขึ้นกับ ref audio — ปรับได้โดยเลือก ref audio ที่มีน้ำเสียงเหมาะสม

### เพลง cover — คุณภาพขึ้นกับต้นฉบับ
- ถ้าไฟล์ต้นฉบับคุณภาพต่ำหรือ UVR แยกไม่สะอาด เสียงร้องที่ได้จะ flat/mono
- แนะนำ: หาไฟล์คุณภาพสูง + ฟัง vocals หลัง UVR ก่อน ถ้าผ่าน ค่อย RVC

---

## 🔧 เทคนิคที่เจอระหว่างพัฒนา (จดไว้กัน debug ซ้ำ)

| ปัญหา | สาเหตุ | วิธีแก้ |
|--------|--------|---------|
| WebSocket close code **4017** (loop reconnect) | Discord เปิดใช้ DAVE protocol (E2EE audio) แต่ discord.py 2.6.x ยังไม่รองรับ | upgrade เป็น `discord.py[voice]>=2.7.1` (มี `davey` bundled) |
| `RuntimeError: PyNaCl library needed` | PyNaCl ไม่ได้ติดตั้งใน venv ที่บอทรัน (testomise myenv) | `pip install PyNaCl` ใน venv ที่รันบอทจริง ไม่ใช่ System Python |
| RVC worker ไม่โหลด / CUDA error | Python version หรือ torch CUDA mismatch | RVC ต้องรันใน `rvc_venv` (Python 3.10 + torch CUDA 12.1) แยกจาก main env |
| `.gitignore` ไม่ ignore ไฟล์ | git ไม่รองรับ inline comment (`pattern  # comment`) | ย้าย comment ขึ้นบรรทัดก่อน pattern แยกต่างหาก |

---

## 🔮 อนาคต (ยังไม่เริ่ม — เรียงตามความเป็นไปได้)

### 🔌 ควบคุม IoT ในบ้าน — เปิด-ปิดไฟ/ปลั๊ก (smart home)
เป้าหมายหลักถัดไป ใช้หลักการเดียวกับสั่งพิมพ์ (สั่งอุปกรณ์จริง + รายงานผล)
- [ ] เริ่มจาก "จำลอง" ใน Discord ก่อน (สั่งเปิด-ปิด → ตอบรับ โดยยังไม่มีอุปกรณ์)
- [ ] ต่ออุปกรณ์จริง — เช่น ESP32 + รีเลย์ หรือปลั๊ก WiFi (Tasmota/Tuya)
- [ ] รอสเต้สั่งผ่านคำพูด เช่น "เปิดไฟห้องนอน" → สั่งงาน → ยืนยันผล
- [ ] รายงานสถานะ (ไฟเปิด/ปิดอยู่)

### 🎤 ฟังเสียงได้ (STT)
- [ ] รับเสียงจากห้อง voice (discord-ext-voice-recv)
- [ ] แปลงเสียง→ข้อความ (Whisper)
- หมายเหตุ: ยากสุดในสายเสียง + กิน VRAM (เครื่อง 4GB อาจไม่ไหวพร้อม LLM)

### 🎵 ร้องเพลงด้วยเสียงรอสเต้ (RVC singing) → ✅ เสร็จแล้ว (เฟส 4)
- [x] RVC infrastructure พร้อม (โมเดล Laibaht ใช้กับเสียงพูดได้)
- [x] Laibaht model ร้องเพลงได้โดยไม่ต้องเทรนแยก — ทดสอบกับ Monster (YOASOBI) สำเร็จ
- [x] pipeline: UVR แยกเสียงร้อง → RVC Laibaht → `karaoke/` → เล่นในห้อง voice
- [ ] **อนาคต: Synthesizer V Studio** — สร้างเสียงร้องสังเคราะห์ตรงๆ ด้วยโมเดลเสียงรอสเต้ ไม่ต้องพึ่งต้นฉบับ (UVR stage ไม่จำเป็น)

### 🎙️ อัปเกรด TTS — เสียงที่มีอารมณ์กว่า edge-tts
✅ **F5-TTS-THAI ใช้งานได้แล้ว** — ถ้าต้องการทดสอบตัวเลือกอื่นในอนาคต:

| ตัวเลือก | ประเภท | ข้อดี | ข้อเสีย |
|---------|--------|-------|---------|
| **Gemini TTS** (Google AI Studio) | cloud | audio tags ควบคุมอารมณ์/จังหวะ, ไทยดีมาก, ไม่กิน VRAM | พึ่งเน็ต/API key, clone เสียงไม่ได้, เสี่ยง preview ปิด |
| **MOSS-TTS** (local) | local | รองรับไทย v1.5, clone เสียงได้, อารมณ์ดี | โมเดล 4B — VRAM 4GB อาจไม่พอ, ตั้งยาก |
| ~~**F5-TTS-THAI**~~ | ✅ ใช้แล้ว | local ล้วน, ไทยโดยเฉพาะ, clone ref audio | — |

### 🧠 ตัดสินใจเองได้มากขึ้น
- [ ] ให้รอสเต้เลือกทำ action เองตามสถานการณ์ (เช่น เตือนเมื่อถึงเวลา)
- หมายเหตุ: ต้องระวังเรื่องความแม่นยำของโมเดลเล็ก

---

## 📌 ข้อจำกัดที่รู้แล้ว (เพดานฮาร์ดแวร์ปัจจุบัน)

- **การ์ดจอ 4GB VRAM** — รันโมเดลใหญ่กว่า 14B ไม่ไหว; qwen3:8b + RVC อยู่พร้อมกันได้ (~3.3GB peak), แต่ STT (Whisper) พร้อมกันอีกจะเต็ม
- **Canon E3300 (USB)** — ไม่รายงานสถานะหมึก/กระดาษให้โปรแกรมอ่าน
- **เสียงไทย TTS** — F5-TTS-THAI v2 ใช้งานได้แล้ว (local, clone ref audio); ถ้าต้องการอารมณ์กว่านี้ → Gemini TTS (cloud) หรือ MOSS-TTS (local, VRAM ตึง)

> ถ้าอัปเกรดการ์ดจอ (VRAM 8-12GB+) หรือใช้เครื่องพิมพ์/อุปกรณ์ WiFi
> หลายข้อจำกัดข้างบนจะเปิดทางได้มากขึ้น

---

## 🧭 ลำดับที่แนะนำต่อไป

1. **เฟส 3d — move logic** — รอสเต้ย้ายตามคนถ้าถูกเรียกจากห้องอื่น (เล็กน้อย)
2. **IoT เปิด-ปิดไฟ (จำลองก่อน)** — เป้าหมายหลักที่ตั้งใจ ทำได้จริงด้วยกลไกเดิม
3. **ทดสอบ Synthesizer V Studio** — สร้างเพลง karaoke ด้วยเสียงสังเคราะห์โดยตรง แทน UVR+RVC
4. ที่เหลือ (STT / ตัดสินใจเอง) — งานใหญ่ ค่อยทำทีละขั้น
