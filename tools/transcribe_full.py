"""
Whisper transcribe แบบ aggressive — no_speech_threshold ต่ำ เพื่อจับทุก segment
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

AUDIO_PATH = r"C:\Users\julia\OneDrive\Desktop\1_Lai_ref_(Vocals).mp3"

import whisper
print("โหลด model medium (cache)...", flush=True)
model = whisper.load_model("medium")
print("โหลดเสร็จ", flush=True)

print("transcribe (no_speech_threshold=0.1)...\n", flush=True)
result = model.transcribe(
    AUDIO_PATH,
    language="th",
    verbose=True,
    fp16=True,
    no_speech_threshold=0.1,      # ปกติ 0.6 — ลดเพื่อจับเสียงพูดเบาๆ
    condition_on_previous_text=False,
)

print(f"\n{'='*60}")
print(f"FULL TEXT ({len(result['segments'])} segments):")
print(f"{'='*60}")
print(result['text'])

out = r"C:\Users\julia\OneDrive\Desktop\mybot\f5_out\laibaht_full_transcript.txt"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(f"FULL TEXT:\n{result['text']}\n\nSEGMENTS:\n")
    for seg in result["segments"]:
        f.write(f"[{seg['start']:6.1f}s - {seg['end']:6.1f}s]  {seg['text'].strip()}\n")
print(f"\nบันทึกที่: {out}")
