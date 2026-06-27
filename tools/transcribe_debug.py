"""
Debug Whisper — ไม่ล็อก language เพื่อดูว่า detect ได้อะไร
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

AUDIO_PATH = r"C:\Users\julia\OneDrive\Desktop\1_Lai_ref_(Vocals).mp3"

import whisper, torch
print(f"CUDA: {torch.cuda.is_available()}")

# โหลดจาก cache (ไม่ต้องดาวน์โหลดใหม่)
print("โหลด model medium...", flush=True)
model = whisper.load_model("medium")
print("โหลดเสร็จ", flush=True)

# ขั้น 1: detect ว่าเสียงเป็นภาษาอะไร
print("\n--- Language Detection ---", flush=True)
audio = whisper.load_audio(AUDIO_PATH)
audio_30s = whisper.pad_or_trim(audio)  # ตัด 30 วิแรก
mel = whisper.log_mel_spectrogram(audio_30s).to(model.device)
_, probs = model.detect_language(mel)
top5 = sorted(probs.items(), key=lambda x: x[1], reverse=True)[:5]
for lang, prob in top5:
    print(f"  {lang}: {prob:.3f}")

detected_lang = top5[0][0]
print(f"\nDetected: {detected_lang}", flush=True)

# ขั้น 2: transcribe แบบ verbose=True ดู segment
print("\n--- Transcribe (verbose) ---", flush=True)
result = model.transcribe(AUDIO_PATH, language="th", verbose=True, fp16=True)

print(f"\n--- RESULT ---")
print(f"text: {result['text']!r}")
print(f"segments: {len(result['segments'])}")
for seg in result["segments"][:10]:
    print(f"  [{seg['start']:.1f}s] {seg['text']!r}  avg_logprob={seg.get('avg_logprob',0):.2f}")
