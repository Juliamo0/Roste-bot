"""
บันทึก transcript ทั้งหมดจาก Whisper (ใช้ค่าเดียวกับที่ได้ผล)
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

AUDIO_PATH = r"C:\Users\julia\OneDrive\Desktop\1_Lai_ref_(Vocals).mp3"

import whisper
print("โหลด model medium (cache)...", flush=True)
model = whisper.load_model("medium")
print("โหลดเสร็จ", flush=True)

result = model.transcribe(
    AUDIO_PATH,
    language="th",
    verbose=True,
    fp16=True,
)

segs = result["segments"]
print(f"\n{'='*60}")
print(f"รวม {len(segs)} segments")
print(f"{'='*60}")
for seg in segs:
    print(f"[{seg['start']:6.1f}s - {seg['end']:6.1f}s]  {seg['text'].strip()}")

out = r"C:\Users\julia\OneDrive\Desktop\mybot\f5_out\laibaht_full_transcript.txt"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(f"รวม {len(segs)} segments\n\n")
    for seg in segs:
        f.write(f"[{seg['start']:6.1f}s - {seg['end']:6.1f}s]  {seg['text'].strip()}\n")
print(f"\nบันทึกที่: {out}")
