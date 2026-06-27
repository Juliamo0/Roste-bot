"""
Whisper transcription of Laibaht ref vocal
รันด้วย: f5_venv\Scripts\python.exe tools\transcribe_ref.py
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

AUDIO_PATH = r"C:\Users\julia\OneDrive\Desktop\1_Lai_ref_(Vocals).mp3"
MODEL_NAME = "medium"

if not os.path.exists(AUDIO_PATH):
    # ลอง path อื่น
    alt = r"C:\Users\julia\OneDrive\Desktop\ref_laibath (vocal).mp3"
    if os.path.exists(alt):
        AUDIO_PATH = alt
    else:
        print("ERROR: ไม่พบไฟล์เสียง")
        print(f"  ลอง: {AUDIO_PATH}")
        print(f"  ลอง: {alt}")
        sys.exit(1)

print(f"ไฟล์: {AUDIO_PATH}")
print(f"โหลด Whisper model={MODEL_NAME}...", flush=True)

import whisper
t0 = time.perf_counter()
model = whisper.load_model(MODEL_NAME)
print(f"โหลดเสร็จใน {time.perf_counter()-t0:.1f}s", flush=True)

print("กำลัง transcribe...", flush=True)
t1 = time.perf_counter()
result = model.transcribe(AUDIO_PATH, language="th", verbose=False)
elapsed = time.perf_counter() - t1

print(f"\n{'='*60}")
print(f"Transcribe เสร็จใน {elapsed:.1f}s")
print(f"{'='*60}")
print(f"\nFULL TEXT:\n{result['text']}")

print(f"\n{'='*60}")
print("SEGMENTS (สำหรับเลือก ref_text):")
print(f"{'='*60}")
for seg in result["segments"]:
    start = seg["start"]
    end   = seg["end"]
    text  = seg["text"].strip()
    print(f"[{start:5.1f}s - {end:5.1f}s]  {text}")

# บันทึกไฟล์
out_txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "f5_out", "laibaht_ref_transcript.txt")
os.makedirs(os.path.dirname(out_txt), exist_ok=True)
with open(out_txt, "w", encoding="utf-8") as f:
    f.write(f"FILE: {AUDIO_PATH}\n")
    f.write(f"FULL TEXT:\n{result['text']}\n\n")
    f.write("SEGMENTS:\n")
    for seg in result["segments"]:
        f.write(f"[{seg['start']:5.1f}s - {seg['end']:5.1f}s]  {seg['text'].strip()}\n")

print(f"\nบันทึกที่: {out_txt}")
