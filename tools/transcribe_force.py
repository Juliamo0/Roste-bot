"""
Force transcribe ทุก chunk — ปิด no_speech filter และ logprob filter
"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

AUDIO_PATH = r"C:\Users\julia\OneDrive\Desktop\1_Lai_ref_(Vocals).mp3"

import whisper
print("โหลด model (cache)...", flush=True)
model = whisper.load_model("medium")
print("โหลดเสร็จ", flush=True)

result = model.transcribe(
    AUDIO_PATH,
    language="th",
    verbose=True,
    fp16=True,
    no_speech_threshold=1.0,   # ไม่ skip chunk ใดเลย
    logprob_threshold=None,    # ปิด logprob filter
    compression_ratio_threshold=None,  # ปิด compression filter
)

segs = result["segments"]
print(f"\n{'='*60}")
print(f"รวม {len(segs)} segments")
print(f"{'='*60}")
for seg in segs:
    ns = seg.get("no_speech_prob", 0)
    lp = seg.get("avg_logprob", 0)
    print(f"[{seg['start']:5.0f}s-{seg['end']:5.0f}s] ns={ns:.2f} lp={lp:.2f}  {seg['text'].strip()}")

out = r"C:\Users\julia\OneDrive\Desktop\mybot\f5_out\laibaht_force_transcript.txt"
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(f"รวม {len(segs)} segments\n\n")
    for seg in segs:
        ns = seg.get("no_speech_prob", 0)
        f.write(f"[{seg['start']:5.0f}s-{seg['end']:5.0f}s] ns={ns:.2f}  {seg['text'].strip()}\n")
print(f"\nบันทึกที่: {out}")
