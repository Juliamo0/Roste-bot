"""
สร้างชุดเสียงทดสอบสำหรับ bench STT (ไทย / ไทยปนอังกฤษ / ชื่อเฉพาะ)

ใช้ edge-tts (th-TH-PremwadeeNeural — ตัวเดียวกับ fallback ใน voice.py)
เจนเสียงจากประโยคที่คล้ายกับที่ผู้ใช้พูดกับรอสเต้จริงในห้อง voice
แล้วเก็บคู่ (wav, ground truth) ลง JSON ให้ bench_stt_thai_en.py อ่านต่อ

ทำไมไม่ใช้ F5: F5 อ่านอังกฤษไม่ได้ ต้องทับศัพท์ก่อน (good morning → กู้ตมอนิ่ง)
ถ้าใช้ F5 เสียงกลุ่ม th_en จะกลายเป็นไทยทับศัพท์ ทำให้ ground truth ที่เป็น
อังกฤษไม่ตรงกับเสียง → วัด "ความสามารถถอดอังกฤษ" ไม่ได้เลย ซึ่งเป็นข้อเดียว
ที่ bench นี้ตั้งใจตอบ edge-tts พูดอังกฤษปนไทยได้จริงจึงเป็นทางเดียวที่วัดได้
โดยไม่ต้องอัดเสียงเอง

รันด้วย: venv\\Scripts\\python.exe tools\\gen_stt_cases.py
         (edge_tts อยู่ใน venv หลัก ไม่ใช่ f5_venv)

ข้อจำกัดที่ต้องรู้ตอนอ่านผล: เสียงนี้เป็นเสียงสังเคราะห์ ไม่มี noise ห้อง
ไม่มีสำเนียงหลากหลาย ไม่มีการพูดทับ/ตะกุกตะกัก ตัวเลข WER ที่ได้จึงเป็น
"พื้นบน" (optimistic) — ใช้ *เรียงลำดับ* โมเดลได้ แต่ใช้ทำนาย WER ในห้อง
voice จริงไม่ได้ อีกข้อ: edge-tts ออกเสียงอังกฤษแบบเจ้าของภาษา ขณะที่คนไทย
มักออกเสียงแบบไทย ๆ ("ดิสคอร์ด") ผลกลุ่ม th_en จึงเอนเข้าข้างโมเดลที่เก่ง
อังกฤษมากกว่าที่จะเจอจริง
"""
import sys, os, json, asyncio, subprocess, shutil

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "stt_cases")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

# เสียงเดียวกับ fallback ใน voice.py (VOICE)
VOICE = "th-TH-PremwadeeNeural"

# ── ชุดทดสอบ ────────────────────────────────────────────────────────────
# แบ่ง 3 กลุ่มตามสิ่งที่ต้องการวัด กลุ่ม th_en คือหัวใจ — ไม่มี benchmark
# สาธารณะตัวไหนวัดให้ (CommonVoice/FLEURS เป็นไทยล้วน)
CASES = [
    # ── ไทยล้วน — เทียบกับที่ Thonburian/Typhoon ประกาศไว้ได้ ──
    ("th", "วันนี้อากาศเป็นยังไงบ้าง"),
    ("th", "ช่วยเปิดเพลงให้หน่อยสิ"),
    ("th", "ตอนนี้กี่โมงแล้ว"),
    ("th", "พรุ่งนี้ฝนจะตกไหม"),
    ("th", "ราคาน้ำมันวันนี้เท่าไหร่"),
    ("th", "ช่วยจำไว้ว่าพรุ่งนี้ฉันต้องไปหาหมอ"),
    ("th", "แถวนี้มีร้านอาหารอร่อยๆ แนะนำไหม"),
    ("th", "ร้องเพลงให้ฟังหน่อยได้ไหม"),

    # ── ไทยปนอังกฤษ — จุดตัดสินของ bench นี้ ──
    ("th_en", "เปิดเพลง despacito หน่อย"),
    ("th_en", "ช่วยเช็ค weather วันนี้ให้หน่อย"),
    ("th_en", "ตอนนี้ GPU ใช้ไปเท่าไหร่แล้ว"),
    ("th_en", "ส่งไฟล์ PDF ไปที่ printer ให้หน่อย"),
    ("th_en", "ช่วย search google ว่าร้านนี้เปิดกี่โมง"),
    ("th_en", "เข้ามาใน voice channel หน่อยสิ"),
    ("th_en", "โมเดล whisper ตัวนี้ดีกว่าตัวเก่าไหม"),
    ("th_en", "ขอเพลง monster ของ imagine dragons"),

    # ── ชื่อเฉพาะ / ศัพท์เทคนิค — เคสที่ ASR มักพลาดที่สุด ──
    ("proper", "รอสเต้ช่วยเปิด discord ให้หน่อย"),
    ("proper", "ใช้ ollama รัน qwen อยู่"),
    ("proper", "ไปกินข้าวที่สยามพารากอนกัน"),
    ("proper", "เปิด youtube ดูหน่อย"),
]


async def _synth(text: str, out_mp3: str, retries: int = 3) -> None:
    """เจนเสียงผ่าน edge-tts พร้อม retry — network flake เกิดได้ (เหมือน voice.py)"""
    import edge_tts

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            comm = edge_tts.Communicate(text, VOICE)
            await comm.save(out_mp3)
            if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 0:
                return
            last_err = RuntimeError("ไฟล์ว่าง")
        except Exception as e:
            last_err = e
        if attempt < retries:
            await asyncio.sleep(1.0 * attempt)
    raise RuntimeError(f"edge-tts failed ({retries} attempts): {last_err}") from last_err


def _to_wav16k(mp3_path: str, wav_path: str) -> bool:
    """แปลงเป็น wav 16kHz mono — รูปแบบที่ Whisper ทุกตัวรับตรง ๆ ไม่ต้อง resample ซ้ำ"""
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path,
         "-ar", "16000", "-ac", "1", wav_path],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and os.path.exists(wav_path)


async def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ERR: ไม่พบ ffmpeg ใน PATH — ต้องใช้แปลง mp3 → wav 16k")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)

    manifest = []
    for i, (group, text) in enumerate(CASES, 1):
        stem = os.path.join(OUT_DIR, f"{i:02d}_{group}")
        mp3, wav = stem + ".mp3", stem + ".wav"

        try:
            await _synth(text, mp3)
        except Exception as e:
            print(f"[{i:2d}/{len(CASES)}] ERR [{group:6s}] {text}\n         -> {e}")
            continue

        if not _to_wav16k(mp3, wav):
            print(f"[{i:2d}/{len(CASES)}] ERR [{group:6s}] แปลง wav ไม่สำเร็จ")
            continue
        os.remove(mp3)

        print(f"[{i:2d}/{len(CASES)}] OK  [{group:6s}] {text}")
        manifest.append({"wav": wav, "text": text, "group": group})

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nสร้างเสร็จ {len(manifest)}/{len(CASES)} ไฟล์")
    print(f"manifest: {MANIFEST}")
    return 0 if manifest else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
