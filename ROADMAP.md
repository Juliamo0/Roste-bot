# 🗺️ ROADMAP — โปรเจกต์รอสเต้ (Roste)

วิสัยทัศน์: ผู้ช่วย AI ที่มีบุคลิก คุยกับเราได้ (พิมพ์และเสียง)
ควบคุมอุปกรณ์ IoT ในบ้านได้ ตัดสินใจบางอย่างได้ และทำงานในโลกจริงได้
โดยใช้ LLM ที่รันในเครื่องตัวเอง (local)

> อัปเดตล่าสุด: 2 กรกฎาคม 2569

---

## ✅ เสร็จแล้ว (ใช้งานได้จริง)

### 🧠 แกนหลัก — แชต + บุคลิก
- [x] เชื่อม Discord + Ollama (LLM รันในเครื่อง)
- [x] บุคลิกตัวละคร "รอสเต้" (พูดไทย เป็นผู้หญิง มีน้ำเสียง/อารมณ์)
- [x] ระบบ Mood + Author's Note (ฉีดกฎติดคำตอบ กันหลุดคาแร็กเตอร์)
- [x] ความจำรายคน (จำชื่อ/เรื่องที่คุย, คำสั่ง "จำไว้ว่า"/"ลืมทุกอย่าง")
- [x] เลือกขนาดโมเดลได้ (qwen3:8b สมดุล / 14b ฉลาดขึ้นแต่ช้า)
- [x] **`fix_persona_slips()`** ใน `persona.py` — validation layer รอบสอง ดักคำหลุดคาแร็กเตอร์แบบ
  rule-based (เจอจริง: สรุปผลค้นเว็บยาวๆ จบด้วย "นะครับ!") กฎ "ห้ามครับ" มีใน SYSTEM_PROMPT + author note
  อยู่แล้วแต่โมเดลยังหลุดในคำตอบยาว จึงต้องมี validation layer แทนการเพิ่ม prompt ซ้ำ (บทเรียนเดียวกับ
  `_strip_ungrounded_optional_args`) ลำดับ replace สำคัญ: "นะครับ"→"นะคะ" ต้องมาก่อน "ครับ"→"ค่ะ"
- [x] **คุมความยาวคำตอบ** — เพิ่มกฎใน `build_author_note()`: คำถามข้อเท็จจริงสั้นๆ (เวลา/อากาศ/ราคา/ไฟดับ)
  ตอบ 2-4 ประโยค เข้าเรื่องเลย ไม่เกริ่นยาว ไม่สรุปเรื่องอื่นที่ไม่ได้ถาม ไม่ปิดท้ายแนะนำให้ไปเช็คแหล่งอื่นเอง
  (เจอจริง: ถามฝนวันนี้ ได้คำตอบเป็นเรียงความปนเฮอริเคนเดือนอื่น + ปิดท้าย "ไปเช็ค TMD เอง" ทั้งที่ดึงข้อมูลมาให้แล้ว)

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
  - RVC (โมเดลเสียงส่วนตัว) แปลงเสียงร้องเป็นเสียงรอสเต้ (~15s บน GPU)
  - วางไฟล์ที่ได้ใน `karaoke/` ตั้งชื่อ `[ชื่อเพลง]_[ศิลปิน].wav`
  - สั่ง `@รอสเต้ ร้องเพลง monster` หรือ `ร้องเพลงให้ฟัง` (สุ่ม) ในห้อง voice
  - sequence: TTS เกริ่น "จะร้องเพลง X ให้ฟัง" → เล่นเพลง → disconnect

### 🎙️ ระบบเสียงรอสเต้ — pipeline + integrate (เฟส 1–3)
- [x] ยืนยันว่า qwen3:8b + RVC อยู่บน 4GB VRAM พร้อมกันได้ (qwen ~2.4GB + RVC peak ~0.9GB)
- [x] RVC รันในเครื่อง (GPU, warm ~1–2s/ประโยค) — รัน inference ผ่าน rvc_venv (Python 3.10) แยก
- [x] **F5-TTS-THAI v2** — แทนที่ edge-tts ด้วย flow matching TTS ภาษาไทย local ล้วน (clone เสียงต้นแบบส่วนตัวด้วย ref audio)
  - pipeline: `f5_preprocess.py` (ตัวเลข/°C/fuel codes → ไทย) → F5-TTS-THAI v2 → RVC (โมเดลส่วนตัว) → .wav
  - cold load: F5 ~18s / RVC ~9s — warm inference ~3–5s/ประโยค รวม F5+RVC
  - ๆ expansion, number reading, degree symbols จัดการถูกต้อง
- [x] `voice.py` + `voice_rvc_worker.py` + `f5_worker.py` + `f5_preprocess.py` — warm worker subprocess (JSON stdin/stdout)
- [x] ทดสอบ standalone ครบ (`tools/test_voice_pipeline.py`) — warm ~1–2s/ประโยค หลัง cold load ~8s
- [x] **เฟส 3a** — wire `RvcWorker` เข้า bot.py, gen TTS file หลังตอบ, โหลด worker เบื้องหลังตอน startup
- [x] **เฟส 3b** — join ห้อง voice, ทักทายเมื่อเข้าครั้งแรก (cache), เล่นคำตอบ, ค้างห้อง
- [x] **เฟส 3c** — leave timer: ออกห้องอัตโนมัติเมื่อว่าง 15s, cancel ได้ถ้าคนกลับมา
- [x] เล่นทักทาย + ทำ TTS คำตอบ **concurrent** (ทักทายไม่รอ TTS คำตอบ — ลด latency)
- [x] upgrade `discord.py` → 2.7.1 + `davey` (แก้ WebSocket close code 4017 จาก DAVE protocol)
- [x] **เฟส 3d — move logic** — ตรวจโค้ดพบว่าทำงานอยู่แล้วตั้งแต่ commit `dd23daa` (เฟส 3): `_speak_in_voice` และ `_play_karaoke` เทียบห้อง voice ของคนที่ @mention กับห้องที่บอทอยู่ ถ้าไม่ตรงกันจะ `move_to(new_channel)` ทุกครั้งที่มีคนคุยจากห้องอื่น (เพราะบอทตอบเฉพาะตอนถูก @mention อยู่แล้ว จึงเทียบเท่า "ย้ายเมื่อถูกเรียกจากห้องอื่น" ตามที่ตั้งใจ) — ไม่ต้องเขียนโค้ดเพิ่ม แค่ยังไม่เคยเช็คให้ชัวร์/ทำเครื่องหมายว่าเสร็จ
- [x] **เฟส 5 — sentence streaming** — เดิมรอทั้งคำตอบเจนเสร็จ+concat ก่อนเล่น (~15-20s สำหรับคำตอบยาว)
  เปลี่ยนเป็น `text_to_roste_voice_segments()` generator yield ไฟล์ `.wav` ทีละ segment (ตัดด้วย crfcut)
  ทันทีที่เจนเสร็จ — เล่น segment แรกได้เร็วขึ้น (~6.7s วัดจริงบน GPU เทียบ ~12.8-20.7s แบบเดิม)
  `text_to_roste_voice()` เดิม refactor ให้ consume generator + concat แทน (API/ผลลัพธ์ภายนอกเท่าเดิม
  ไม่กระทบ greeting cache/karaoke intro/tools อื่น)
  - **per-segment fail-safe** (จำเป็นเพราะ streaming ทำให้ fallback ทั้งก้อนแบบเดิมใช้ไม่ได้ — ถ้า segment
    แรกเล่นด้วยเสียง F5 ไปแล้ว แล้ว fallback ทั้งข้อความไป edge-tts จะทำให้เสียงเปลี่ยนกลางคันแล้วเล่นซ้ำจากต้น):
    F5 (retry 1 ครั้ง, ข้าม retry ทันทีถ้า worker ตายแล้ว) → edge-tts→adjust→RVC เฉพาะ segment นั้น → ข้าม segment
  - ทดสอบจริงบน GPU (kill F5 worker กลาง stream): segment ที่เหลือสลับไป edge-tts ต่อเนื่องถูกต้อง
    ไม่เงียบ ไม่เล่นซ้ำจากต้น
  - **เจอบั๊กแฝงระหว่างทดสอบ:** `python-crfsuite` ไม่เคยถูกติดตั้งจริงใน venv ที่บอทรัน ทำให้ `crfcut`
    import พังและถูก `try/except` ใน `_split_thai_text` กลืนเงียบมาตลอด (การตัดประโยคไทยไม่เคยทำงานจริง
    บนเครื่องนี้เลย) แก้แล้ว + เพิ่มเข้า `setup.bat` กันเงียบซ้ำตอน clone ใหม่
  - `test_voice.py` ใหม่ 11 tests ครอบ: ลำดับ segment, retry, fallback เฉพาะ segment, worker ตายกลางคัน,
    regression API เดิม
  - `tools/test_voice_stream.py` — สคริปต์ทดสอบ streaming จริงบน GPU (วัด time-to-first-segment +
    จำลอง F5 ตายกลางคัน) ใช้ซ้ำได้ทุกครั้งที่แตะ pipeline เสียง
- [x] **แก้การอ่านปี พ.ศ./ค.ศ.** — `years_to_thai()` ใน `f5_preprocess.py`: เดิมอ่านปีแบบจำนวนเต็ม
  ("พ.ศ. 2569" → "สองพันห้าร้อยหกสิบเก้า" ยาวและ F5 อ่านตะกุกตะกัก) เปลี่ยนเป็นอ่านทีละหลักตามภาษาพูดจริง
  ("พอศอ สองห้าหกเก้า") — ทำงานเฉพาะบริบทที่เป็นปีชัดเจน (ตามหลังชื่อเดือน/"ปี"/พ.ศ./ค.ศ.) กันชน
  "2500 บาท" ที่ต้องอ่านแบบจำนวนเหมือนเดิม และดักเคส "พ.ค." (พฤษภาคม) ไม่ให้สับสนกับ "พ.ศ."
- [x] **แก้หน่วยจากข้อมูล TMD ที่ F5 อ่านผิด** — "มม." เดิมถูกอ่านสะกดตัวอักษร "มอมอ" (เพราะ TMD คืน
  ปริมาณฝนเป็น "0.2 มม." ตรงๆ) แก้ให้ขยายเป็น "มิลลิเมตร" + "%" (ความชื้น) ขยายเป็น "เปอร์เซ็นต์" ก่อนส่งเข้า F5
  - ลองสะกดแบบ "มิลลิเมด" (phonetic ตามเสียงพูดจริง) เพื่อแก้ปัญหาเสียงวรรณยุกต์เพี้ยนที่ F5 อ่าน "ตร"
    เป็นเสียงสูงผิด แต่ user ทดสอบแล้วอยากให้กลับไปใช้ตัวสะกดมาตรฐาน "มิลลิเมตร" ตามเดิม — ปัญหาเสียง
    วรรณยุกต์ยังไม่แก้ (ทราบแล้วแต่ user เลือกยอมรับ ไม่ใช่บั๊กที่ต้องรีบแก้)
- [x] **ทดลอง cap จำนวน segment เสียงสำหรับคำตอบยาว แล้วถอนออก** — เคยเพิ่ม `max_segments` ตัดเสียงเหลือ
  segment แรกๆ (ที่เหลืออ่านในแชตแทน) เพื่อกันคำตอบยาวเกินฟัง แต่พบว่าตัดจบกลางประโยคที่สมบูรณ์อยู่แล้ว
  (เช่น ตัดประโยคปิดท้าย "อ้างอิงข้อมูลจากกรมอุตุนิยมวิทยาค่ะ" ทิ้ง) ฟังดูเหมือนพูดไม่จบ — ถอนออกทั้งหมด
  เพราะปัญหา "คำตอบยาวเกิน" แก้ที่ต้นตอแล้วด้วย author note (ดูหัวข้อ Tool calling ด้านล่าง) และการนับ
  segment หลังขยายตัวเลขเป็นคำอ่านไทยไม่ใช่ตัวชี้วัดความยาวที่แม่นยำ (ตัวเลขขยายเป็นคำยาวกว่าอักษรเดิมมาก)

### 🛠️ Tool calling — LLM เลือกเครื่องมือเอง (แทน keyword dispatch)
- [x] แทนที่ `get_realtime_context()` (keyword matching เดิม) ด้วย native Ollama tool calling —
  ขยาย `TOOLS` จาก 1 (search_web) เป็น 6 เครื่องมือ: `get_current_time`, `get_weather`,
  `get_power_outage`, `get_oil_price`, `search_places`, `search_web`
- [x] ยืนยันแล้วว่าแก้เคสที่ keyword พลาดจริง เช่น "พรุ่งนี้ต้องพกร่มไหม" (ไม่มีคำว่า
  อากาศ/ฝนเลย) — โมเดลเลือก `get_weather` ถูกต้อง
- [x] ลบ `_pending_place` two-turn state ทิ้ง — ใช้ conversation history แทน (โมเดลเรียก
  `search_places` ซ้ำเองได้จาก context เมื่อผู้ใช้บอกจังหวัดในข้อความถัดไป) ทดสอบแล้วว่าทำงานจริง
- [x] `_validate_tool_args` + `TOOL_HANDLERS` dispatch table + try/except ครอบทุก handler —
  กันโมเดลเรียกเครื่องมือไม่มีจริง/ขาด param/handler error ไม่ให้ crash `ask_ollama`
- [x] `test_bot.py` เพิ่ม 27 tests (validate args, handler ต่อตัว, fail-safe ผ่าน `ask_ollama` เต็ม,
  grounding check)
- [x] **`_strip_ungrounded_optional_args`** — แก้ปัญหา qwen3:8b เดา optional parameter เอง
  (พบจริง: ใส่ `province="กรุงเทพมหานคร"` ให้ `search_places`/`"บ้านที่ตั้งค่าไว้"` ให้ `get_weather`
  ทั้งที่ผู้ใช้ไม่เคยพูดถึง — ลองแก้ด้วย prompt description 2 รอบไม่หาย ต้องมี validation layer)
  เช็คว่าค่าที่โมเดลใส่มาปรากฏจริงใน user_message/history/saved facts ก่อนเชื่อ ถ้าไม่เจอที่มา
  → ตัดทิ้งให้ fallback เดิมของ handler ทำงานแทน (ใช้จังหวัดบ้าน/ถามกลับ) ใช้ได้กับทุก optional
  parameter ของทุกเครื่องมือ (ไม่ใช่แค่ province) — เผื่ออนาคต IoT/reminder เจอปัญหาเดิม
- [x] `tools/simulate_toolcalling.py` — เทสจริงกับ Ollama หลังแก้: เลือกเครื่องมือถูก 5/5,
  multi-turn place-search 2/2 (ยืนยันว่า grounding check ทำงานจริง ไม่ใช่แค่ mock)
- [x] **กัน `search_web` เรียกซ้อนหลัง `get_weather` สำเร็จ** — เจอจริง: TMD คืนพยากรณ์วันนี้มาแล้ว
  แต่โมเดล 8B ยังเรียก `search_web` ซ้ำ ได้หน้า climate-average (ค่าเฉลี่ยรายเดือน ไม่ใช่พยากรณ์วันนี้)
  มาปนกับข้อมูลจริง ทำให้ตอบไม่ตรงคำถาม ("วันนี้ฝนจะตกไหม" → ตอบความชื้นเดือนธันวาแทน) แก้โดยตัด
  `search_web` ออกจากรายการเครื่องมือของรอบถัดไปทันทีที่ `get_weather` สำเร็จ (ผ่าน `tools` param ใหม่ใน
  `_chat_once`) โมเดลจึงเรียกซ้ำไม่ได้อีกเลยในเทิร์นนั้น

### 🔎 ความจำเชิงความหมาย — RAG PDF + semantic recall
- [x] `vectormemory.py` — ChromaDB (persist ที่ `chroma_db/`) + Ollama `bge-m3` ทำ embedding, ไม่ต้องพึ่ง torch ใน venv หลัก
- [x] RAG PDF — แนบ PDF ที่ไม่ได้สั่งพิมพ์ = เก็บเนื้อหาไว้ถามได้ (persist ข้ามเซสชัน ต่อ user)
- [x] semantic recall — เสริม `recall_summaries` (keyword) ด้วยการค้นความหมาย ฉีดเข้า context อัตโนมัติ
- [x] **สถาปัตยกรรม 2 ด่าน: retrieve top-k (embedding) → rerank (LLM)** — เดิมใช้ cosine-distance threshold ตัดสินชั้นเดียว แต่เจอเคสก้ำกึ่งที่ distance ต่างกันแค่ ~0.005 แยกไม่ออก (คาลิเบรตยังไงก็ผิดได้) จึงเปลี่ยนให้ embedding แค่คัด 5 ผู้เข้ารอบ (`RETRIEVE_K`, relative ไม่ตัดสินขาด) แล้วให้ `qwen3:8b` (โมเดลเดิมที่ตอบแชตอยู่แล้ว ไม่กิน VRAM เพิ่ม) อ่าน query+candidate คู่กันจริงแล้วให้คะแนน 0-10 — threshold ย้ายไปอยู่บนคะแนน LLM แทน (`RERANK_SCORE_MIN`)
- [x] fail-safe: rerank พัง/parse ไม่ได้ → คืน `[]` (ไม่ inject) ไม่ใช่ปล่อย candidate ดิบผ่าน — "ยอมลืมดีกว่าจำผิดเรื่อง"
- [x] temperature=0 สำหรับ rerank (นิ่งสุด กันผลสลับข้ามรันสำหรับเคสก้ำกึ่ง)
- [x] `tools/simulate_vectormemory.py` — เทส end-to-end จริงกับ Ollama/ChromaDB, ปริ้น distance ดิบด่าน 1 คู่กับ verdict ด่าน 2 ให้เห็นว่า rerank แยกเคสก้ำกึ่งได้จริง (10/10 passed)
- [x] `test_vectormemory.py` — 13 unit tests mock Ollama เทส edge case ของ LLM-as-reranker โดยเฉพาะ (output หลุดฟอร์แมต, temperature, คะแนนต่ำหมดทั้ง 5 candidate)

### 🔒 ความปลอดภัย/คุณภาพโค้ด

**เสร็จแล้ว:**
- [x] จำกัดสิทธิ์คำสั่งพิมพ์ — เพิ่ม `PRINT_ALLOWED_USER_IDS` กัน user ใดๆ ก็สั่งพิมพ์ได้ (เดิมไม่มีการเช็คสิทธิ์เลย)
- [x] รวมโค้ด Ollama-call ที่ซ้ำ 6-7 จุดใน bot.py เป็น `_get_json_post`/`_strip_think` เดียว
- [x] เจอ+แก้บั๊กแฝง: `pypdf` ไม่เคยถูกติดตั้งจริงในเครื่อง ทั้งที่ `printing.py` อ้างอิงไว้ (lazy import ตอนพิมพ์จริงเท่านั้นเลยไม่เคยโดนจับ)
- [x] แก้ `tools/simulate_chat.py` / `simulate_chat_long.py` / `simulate_recall.py` — เดิม `import bot` พังเพราะ chdir ไปที่ `tools/` เอง ไม่ใช่ root ของโปรเจกต์ ทำให้รันตามที่ README บอกไม่ได้เลยมาตั้งแต่ต้น
- [x] ย้ายทั้งโปรเจกต์ออกจาก OneDrive → `d:\mybot` — ปิดความเสี่ยง secrets/ความจำผู้ใช้ (`memory/`, `chroma_db/`)
  ถูก sync ขึ้น cloud โดยไม่ตั้งใจ
- [x] เช็ค git history เต็ม (`git log --all --full-history -- config.py` + pickaxe `-S` ค้นเศษของ token/key
  จริงทั้ง 4 ตัวในทุก commit ทุก ref) → **สะอาด 100%** — `config.py` ไม่เคยถูก commit แม้แต่ครั้งเดียว
  และ secrets ไม่เคยหลุดไปอยู่ไฟล์อื่นด้วย ปลอดภัยสำหรับ push ขึ้น public repo
- [x] ตรวจ subprocess ทั้งหมด (printing.py, voice.py) — ใช้ list args ไม่มี `shell=True`/`eval`/`pickle` ที่เสี่ยง
- [x] ชื่อไฟล์ที่มาจาก user (PDF สั่งพิมพ์) sanitize ด้วย regex ก่อนสร้าง path — กัน path traversal
- [x] **ย้าย secrets จาก `config.py` (plaintext) ไป `.env`** — `config.py` ตอนนี้เป็นแค่ตัวโหลดผ่าน
  `python-dotenv` (`load_dotenv()` + `os.getenv(...)`) ไม่มีค่าลับในไฟล์เอง **commit เข้า git ได้ปกติแล้ว**
  ปิด failure mode "เผลอลบบรรทัดใน `.gitignore` แล้วหลุด" ถาวร (เดิมพึ่ง `.gitignore` เส้นเดียว)
  `.env.example` (placeholder, commit ได้) แทนที่ `config.example.py` เดิม — ทำก่อน push ตามที่วางแผนไว้

**ยังไม่ทำ (พบระหว่างตรวจสอบ 2 ก.ค. 2569 — ยืนยันด้วยการอ่านโค้ดจริง ไม่ใช่จากความจำ):**

| ระดับ | ปัญหา | รายละเอียด | แนวทางแก้ |
|-------|-------|-----------|-----------|
| 🔴 วิกฤต | ไม่มี rate limiting / guild allowlist | `on_message` ตอบทุกคนที่ DM หรือ @mention ได้ไม่จำกัด ไม่มี cooldown ต่อ user ไม่มี allowlist server/channel — ใครแกล้งสแปมเผา GPU (F5+RVC ~3-5s/ประโยค), เผาโควตา SerpApi (250 ครั้ง/เดือน) หมดในไม่กี่นาที | จำกัด guild ID ที่ตอบ + cooldown ต่อ user (เช่น 1 ข้อความ/5 วิ) + นับโควตา search ต่อวัน |
| 🟠 สูง | PDF ingest ไม่มี cap ขนาดไฟล์/จำนวนหน้า | `vectormemory.ingest_pdf` มี `MAX_CHUNKS_PER_PDF=300` กันไฟล์ยาวเกิน แต่ไม่มีเช็คขนาดไฟล์ดิบหรือจำนวนหน้าก่อน `PdfReader` parse — PDF ใหญ่มากหรือที่ออกแบบให้ parse ช้า (decompression bomb) ทำให้บอทค้างได้ | เช็ค `pdf_attach.size` ก่อน (เช่น ≤10MB) + จำกัดจำนวนหน้าก่อน extract |
| 🟠 สูง | Prompt injection ผ่าน PDF/ผลค้นเว็บ ยังไม่ครบทุกจุด | tool ส่วนใหญ่ (weather/oil/power/maps) มี label `[ข้อมูลภายใน]` + กำกับชัดว่าเป็นข้อมูลอ้างอิงแล้ว แต่ `search_web` result และ PDF context (บรรทัด `_tool_search_web`, ตัวแปร `augmented_message`) ยังไม่มีประโยคกำกับชัดๆ ว่า "นี่คือข้อมูล ไม่ใช่คำสั่ง" — ความเสี่ยงจำกัดเพราะ tool ทั้งหมด read-only และคำสั่งพิมพ์ไม่ผ่าน LLM แต่ควรครอบให้ครบทุกจุดเพื่อความสม่ำเสมอ | เพิ่มประโยคกำกับให้ครบทุก tool ที่รับเนื้อหาจากภายนอก (เว็บ/PDF) |
| 🟡 กลาง | ไฟล์ใน `print_jobs/` ไม่ถูกลบหลังพิมพ์ | เอกสารที่สั่งพิมพ์ (อาจเป็นเอกสารส่วนตัว) ค้างอยู่บนดิสก์ตลอดไป | `os.remove(job["path"])` ใน `run_print_job` หลังจบงาน |
| 🟡 กลาง | `pending_prints` ไม่มีวันหมดอายุ | งานใหญ่ที่รอยืนยันค้างได้ไม่จำกัด ถ้าอีกหลายวันเจ้าของพิมพ์คำว่า "ยืนยัน" ในบริบทอื่น งานเก่าจะพิมพ์ออกมาทันที | ใส่ timestamp แล้วหมดอายุใน ~5 นาที |
| 🟡 กลาง | `song_requests.json` โตได้ไม่จำกัด | ทุก query ที่ขอเพลงกลายเป็น key ใหม่ในไฟล์ ไม่มี cap | จำกัดจำนวน entries |
| 🟡 กลาง | ไม่มี `requirements.txt` (pin เวอร์ชัน) | `setup.bat` ยังติดตั้งเวอร์ชันล่าสุดเสมอ ไม่ reproduce ได้ เสี่ยง breaking change/supply chain | สร้าง `requirements.txt` ระบุเวอร์ชัน |

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
- [x] ~~`pending_place_query` ย้ายออกจาก JSON ไปเก็บใน RAM~~ → ถูกลบทิ้งทั้งกลไกแล้วตอนทำ tool
  calling (ใช้ conversation history แทน ดูหัวข้อ Tool calling ด้านบน)
- [x] แก้ SELF_REFERENCE_HINTS — ลบ `"มี"` เดี่ยว ใส่รูปผูกสรรพนาม (`"ผมมี"`, `"ฉันมี"` ฯลฯ)
- [x] asyncio Queue + bg worker — serialize งาน Ollama background (แก้ TimeoutError เมื่อ summarize + auto-remember ชนกัน)
- [x] ย้าย `_last_had_summary_notice` state เข้า `_maybe_append_summary_notice` (แก้ notice ไม่แสดง)
- [x] **Fact supersede/consolidation** — หลักการ "supersede ไม่ delete" ให้ตรงกับ fail-conservative
  ของโปรเจกต์: `build_extract_prompt` เปลี่ยนให้โมเดล emit `{category, text}` ต่อ fact แทนสตริงล้วน
  (ฟรี เพราะโมเดลจัดหมวดอยู่แล้วตอนตัดสินใจสกัด ไม่เพิ่ม LLM call) — category บังคับจาก closed set
  (`FACT_CATEGORIES`), หลุด set = category=None (ไม่ auto-supersede แต่ไม่ทิ้ง fact)
  - single-value category (ชื่อ/ที่อยู่/งาน) — fact ใหม่หมวดเดียวกัน mark fact เก่าเป็น
    `superseded=True` + timestamp + `superseded_by` ทันที (rule-based ล้วน ไม่เรียก LLM)
  - multi-value category (ความชอบ/ของที่มี/เรื่องที่สนใจ/หัวข้อสนทนา) — สะสมได้ ไม่ supersede
  - `recall_facts` กรอง superseded ออกก่อนเสมอ (ทั้ง path facts น้อย/เกิน cap) — กันโมเดลเห็น
    ค่าเก่า+ใหม่พร้อมกันแล้วสับสน ของเก่ายังอยู่ใน `mem["facts"]` จริง แค่ไม่ถูกเสนอเป็นค่าปัจจุบัน
  - fact แบบเก่า (บันทึกไว้ก่อน schema นี้ เป็น str ล้วน) ไม่ถูกแตะเลย ยกเว้นจาก consolidation ถาวร
    self-heal ผ่าน MAX_FACTS eviction ปกติ
  - ทดสอบจริงกับ Ollama (`tools/simulate_fact_consolidation.py`, 4/4 passed): บอกที่อยู่ →
    เปลี่ยนที่อยู่ → โมเดลจัดหมวด "ที่อยู่" ถูกทั้งสองครั้ง → supersede อัตโนมัติถูกต้อง →
    recall คืนเฉพาะที่อยู่ปัจจุบัน
  - `test_memory.py` เพิ่ม 21 tests ครอบ: category หลุด set, single vs multi แยกถูก, recall
    เลือกอันล่าสุด, fact เก่าไม่โดนแตะ, เคส supersede ผิดต้องกู้คืนได้ (56 tests รวม)
  - **ยังไม่ทำ:** LLM-as-judge fallback สำหรับเคสที่ rule แยกไม่ออกว่าขัดกันจริงไหม (เช่น category
    ไม่ตรงกันเป๊ะแต่น่าจะเป็นเรื่องเดียวกัน) — ต้อง clarify เงื่อนไข trigger ที่ชัดเจนก่อนสร้าง

### 🧪 Testing
- [x] Unit tests สำหรับ memory.py — 56 tests (pytest)
- [x] Unit tests สำหรับ bot.py — 67 tests (mock Ollama; รวม tool calling, persona-slip filter)
- [x] Unit tests สำหรับ realtime functions — 51 tests (mock HTTP ทุกระบบ)
- [x] Unit tests สำหรับ vectormemory.py — 13 tests (rerank fail-safe)
- [x] Unit tests สำหรับ voice.py + f5_preprocess.py — 20 tests (streaming segment order/fail-safe, ปี/หน่วย)
- [x] Integration test `test_all_systems.py` — ยิง HTTP จริง 9 ระบบ รายงานตาราง ✅/⚠️/❌
- [x] จัดไฟล์ทดสอบ — pytest ไว้ root, diagnostic scripts ย้ายไป `tools/`
- [x] `tools/simulate_chat_long.py` — จำลอง 18 รอบ 3 หัวข้อ ดู summaries สะสม
- [x] `tools/simulate_recall.py` — จำลองดึง fact + recall หลัง auto-remember

**รวม 207 unit tests** (`pytest test_bot.py test_memory.py test_realtime.py test_vectormemory.py test_voice.py`)
หมายเหตุ: `pytest` เปล่าไม่มี argument จะพังเพราะ `tools/test_gemini_tts.py` เป็นสคริปต์ (ใช้ `argparse`)
ไม่ใช่ไฟล์เทสจริง ทำให้ pytest collect ทั้งโฟลเดอร์พัง — ต้องระบุไฟล์ตรงๆ เสมอ

---

## ⏳ กำลังค้างอยู่ (เริ่มแล้ว ยังไม่จบ)

_(ไม่มีตอนนี้ — เฟส 3d ย้ายไปอยู่ในหมวด ✅ เสร็จแล้วด้านบนแล้ว)_

---

## ⚠️ Known Issues

### เสียงพูด — ข้อจำกัด F5-TTS-THAI
- **cold load ~18s** — บอทรอ F5 worker พร้อมก่อนตอบด้วยเสียงได้ (ตอบแชตได้ก่อน warm เสร็จ)
- **F5 ออกเสียงผิด** กรณีข้อความมีตัวเลข/หน่วย/โค้ดพิเศษที่ `f5_preprocess.py` ยังไม่ครอบคลุม — แก้ได้โดยเพิ่ม regex ใน `preprocess_for_f5()`
- **เสียงวรรณยุกต์ "มิลลิเมตร" เพี้ยน** — F5 อ่านคำนี้เป็นเสียงสูงผิด (ปกติควรเป็นเสียงเอก/ต่ำ) ลองสะกดใหม่เป็น
  "มิลลิเมด" แล้วแต่ user เลือกกลับไปใช้ตัวสะกดมาตรฐาน "มิลลิเมตร" ตามเดิม — ยังไม่แก้ ยอมรับไว้ก่อน
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

### 🔔 ทักก่อนได้ (proactive / เริ่มบทสนทนาเอง)
แนวคิด: LLM ต้องมี prompt เข้าเสมอ — "ทักเอง" คือมี scheduler ยิง prompt ปลอมให้อัตโนมัติ
(เหมือน Neuro-sama ที่มี loop ซ่อนอยู่ ไม่ใช่โมเดลตัดสินใจพูดเองจริงๆ) ต่อยอดจาก pipeline แชตเดิม
+ vector memory ที่ทำเสร็จแล้ว (ใช้ `query_conversation_memory`/summaries ดึง "เรื่องล่าสุดที่คุยกัน"
มาสร้าง prompt แบบ "เมื่อวานคุยเรื่อง X ไปเป็นไงบ้าง")

**ตัดสินใจแล้ว:**
- [x] **ช่องทาง: DM** (ไม่ใช่ห้องเจาะจง) — เพราะเห็นเฉพาะคนเดียว ไม่มีทางน่ารำคาญคนอื่นใน server,
  ไม่ต้อง config channel ID ต่อ server, และ DM เป็นช่องทางที่บอทรองรับอยู่แล้ว (`is_dm` ใน `on_message`)
- [x] **ไม่ทำ idle trigger บนห้อง Discord แชร์กัน** — ห้องส่วนตัวเงียบได้เป็นเรื่องปกติ ทักใส่ห้องว่าง
  จะน่ารำคาญ (ต่างจากบริบท live stream ที่มีคนดูตลอด)
- [x] **หยุดทักถ้าเงียบ 3 วันติด** — เงียบ 1 ครั้งยังไม่หยุด (กันเผลอพลาดจังหวะ), 3 วันติดถึงหยุด
  จนกว่า user จะกลับมาคุยเอง (reset counter ทันทีที่มี `on_message` ปกติจาก user คนนั้น)

**ยังไม่ตัดสินใจ (รอกำหนดตอน implement):**
- [ ] **ช่วงเวลาทักตอนเช้า** — ยังไม่ fix ตัวเลข ต้องปรับตามตารางชีวิตจริงตอนเริ่มเขียน (ตัวเลือกที่คุยไว้:
  7:00-9:00 / 8:00-10:00 / 9:00-11:00 — สุ่มเวลาในช่วงที่เลือกกันดูเป็น cron ตายตัวเกินไป)
- [ ] **quiet hours แบบ hard cutoff** — ห้ามทักดึกเด็ดขาดไม่ว่ากรณีใด (เช่น 22:00-08:00) เป็น safety net
  แยกจากช่วงเวลาทักหลัก เผื่อ logic อื่นพลาดไปยิงนอกช่วง
- [ ] **scope ผู้ใช้ที่จะทัก** — ควรทักเฉพาะ user ที่เคยคุยมาก่อน/มี summaries ใน memory (ไม่ทัก user
  ใหม่ที่ไม่เคยคุยเลย เพราะจะดูแปลก/creepy)
- [ ] กลไก scheduler — `asyncio` background task loop เช็คเวลาเป็นระยะ (เหมือน `_bg_worker`/`_leave_after_idle`
  ที่มีอยู่แล้ว) น่าจะพอ ไม่ต้องเพิ่ม dependency ใหม่ (เช่น APScheduler)
- [ ] เก็บ state ต่อ user: `last_proactive_greet_date`, `consecutive_silent_greets` — เข้า `memory/<user_id>.json`
  แบบเดียวกับ facts/summaries

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
- [x] RVC infrastructure พร้อม (โมเดลเสียงส่วนตัวที่ใช้กับเสียงพูดใช้ร้องเพลงได้ด้วย)
- [x] โมเดลร้องเพลงได้โดยไม่ต้องเทรนแยก — ทดสอบกับ Monster (YOASOBI) สำเร็จ
- [x] pipeline: UVR แยกเสียงร้อง → RVC (โมเดลส่วนตัว) → `karaoke/` → เล่นในห้อง voice
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

1. **เก็บงานความปลอดภัยที่เหลือ** (ดูตารางที่หัวข้อ "🔒 ความปลอดภัย/คุณภาพโค้ด" ด้านบน) — ย้าย secrets
   ไป `.env` ทำแล้ว ก่อนเพิ่มฟีเจอร์ใหม่ (โดยเฉพาะ IoT ที่จะเพิ่ม attack surface) ที่เหลือคือ
   rate limit/guild allowlist (วิกฤต) + PDF size cap
2. **IoT เปิด-ปิดไฟ (จำลองก่อน)** — เป้าหมายหลักที่ตั้งใจ ตอนนี้ง่ายขึ้นเพราะมี tool calling แล้ว
   (เพิ่ม tool ใหม่แค่ประกาศใน `TOOLS` + เขียน handler + เพิ่มเข้า `TOOL_HANDLERS`) แนะนำใช้
   Home Assistant เป็นตัวกลางแทนเขียน integration ทีละยี่ห้อ (ESP32/Tuya) เอง **สำคัญ:** คำสั่ง IoT ต้อง
   gate ด้วย user ID เหมือนคำสั่งพิมพ์ (`PRINT_ALLOWED_USER_IDS`) และห้ามให้ LLM ตัดสินใจสั่งอุปกรณ์เองโดยไม่มีคนขอ
3. **ทักก่อนได้ (proactive greeting)** — ออกแบบเสร็จแล้ว (ช่องทาง DM, หยุดถ้าเงียบ 3 วัน) เหลือแค่ fix
   ช่วงเวลาทัก + implement scheduler ต่อยอดจาก vector memory ที่ทำเสร็จแล้ว
4. **ทดสอบ Synthesizer V Studio** — สร้างเพลง karaoke ด้วยเสียงสังเคราะห์โดยตรง แทน UVR+RVC
5. ที่เหลือ (model orchestration / STT / ตัดสินใจเอง) — งานใหญ่ ค่อยทำทีละขั้น
