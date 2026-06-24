"""
สร้างไฟล์เสียงดิบ (.wav) จาก edge-tts สำหรับเอาไปจูนใน WavePad
เสียง: th-TH-PremwadeeNeural — ค่าดิบไม่ปรับอะไร (rate/pitch/volume ศูนย์ทั้งหมด)

วิธีใช้:  python tools/make_tts_raw.py
ผลลัพธ์:  tts_raw/raw_*.wav
"""

import asyncio
import os
import sys
import time

import edge_tts

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VOICE = "th-TH-PremwadeeNeural"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tts_raw")

LINES = [
    ("raw_greeting",  "สวัสดีค่ะ วันนี้มีอะไรให้รอสเต้ช่วยไหมคะ"),
    ("raw_excited",   "อืม... เรื่องหุ่นยนต์นี่รอสเต้ชอบเป็นพิเศษเลยค่ะ"),
    ("raw_sleepy",    "วันแบบนี้หนังสือยังอยากนอนอยู่บนชั้นเฉยๆ เลยค่ะ"),
    ("raw_long",      "ถ้าชอบแนว sci-fi ที่มีโลกสมมติซับซ้อน ลองอ่าน Dune ของ Frank Herbert ดูนะคะ"),
    ("raw_english",   "ลองใช้ asyncio.Lock ต่อ user_id ดูค่ะ น่าจะช่วยได้"),
]


async def _make_wav(name: str, text: str) -> float:
    """สร้างไฟล์เดียว แล้วแปลง mp3→wav ด้วย ffmpeg — คืนเวลาที่ใช้ (วินาที)"""
    os.makedirs(OUT_DIR, exist_ok=True)
    mp3_path = os.path.join(OUT_DIR, f"{name}.mp3")
    wav_path = os.path.join(OUT_DIR, f"{name}.wav")

    t0 = time.perf_counter()

    # edge-tts สร้าง mp3 ก่อน (API ของมันไม่ส่ง wav โดยตรง)
    tts = edge_tts.Communicate(text, VOICE, rate="+0%", pitch="+0Hz", volume="+0%")
    await tts.save(mp3_path)

    # แปลงเป็น wav ด้วย ffmpeg (ไม่บีบอัด PCM 16-bit 24kHz)
    ret = os.system(
        f'ffmpeg -y -loglevel error -i "{mp3_path}" -ar 24000 -ac 1 -sample_fmt s16 "{wav_path}"'
    )
    os.remove(mp3_path)  # ลบ mp3 ชั่วคราว

    elapsed = time.perf_counter() - t0

    if ret != 0:
        print(f"  ⚠️  ffmpeg คืน exit code {ret} — ตรวจสอบว่า ffmpeg ติดตั้งแล้ว (winget install ffmpeg)")
    return elapsed


async def main():
    print(f"เสียง: {VOICE}  |  rate +0%  pitch +0Hz  volume +0%  (ดิบ ไม่ปรับ)")
    print(f"บันทึกลง: {os.path.abspath(OUT_DIR)}\n")

    total = 0.0
    for name, text in LINES:
        print(f"  สร้าง {name}.wav ...", end=" ", flush=True)
        elapsed = await _make_wav(name, text)
        total += elapsed
        print(f"{elapsed:.1f}s  — {text[:40]}{'…' if len(text) > 40 else ''}")

    print(f"\n✅ เสร็จ {len(LINES)} ไฟล์  รวม {total:.1f}s")
    print(f"เปิด WavePad แล้ว import จากโฟลเดอร์  tts_raw/")


if __name__ == "__main__":
    asyncio.run(main())
