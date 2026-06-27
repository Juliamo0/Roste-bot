"""
แยก audio เป็น chunk 30 วินาที แล้ว transcribe ทีละ chunk
เก็บทุกอย่างลง log รวมถึง no_speech_prob เพื่อแยกเสียงพูดจริง vs เงียบ
"""
import sys, os, subprocess, json, tempfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

AUDIO_PATH = r"C:\Users\julia\OneDrive\Desktop\1_Lai_ref_(Vocals).mp3"
CHUNK_SEC  = 30
OUT_LOG    = r"C:\Users\julia\OneDrive\Desktop\mybot\f5_out\laibaht_chunks_transcript.txt"
os.makedirs(os.path.dirname(OUT_LOG), exist_ok=True)

# หา duration
r = subprocess.run(
    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
     "-of", "csv=p=0", AUDIO_PATH],
    capture_output=True, text=True
)
total_sec = float(r.stdout.strip())
print(f"ไฟล์: {total_sec:.1f}s ({total_sec/60:.1f} นาที)")

import whisper
print("โหลด model medium (cache)...", flush=True)
model = whisper.load_model("medium")
print("โหลดเสร็จ\n", flush=True)

results = []
n_chunks = int(total_sec / CHUNK_SEC) + 1

with tempfile.TemporaryDirectory() as tmpdir:
    for i in range(n_chunks):
        start = i * CHUNK_SEC
        if start >= total_sec:
            break
        end = min(start + CHUNK_SEC, total_sec)
        chunk_path = os.path.join(tmpdir, f"chunk_{i:03d}.wav")

        # ตัด audio ด้วย ffmpeg
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", AUDIO_PATH,
            "-ss", str(start), "-to", str(end),
            "-ar", "16000", "-ac", "1",
            chunk_path
        ], check=True)

        # transcribe chunk นี้
        res = model.transcribe(
            chunk_path,
            language="th",
            fp16=True,
            verbose=False,
            no_speech_threshold=0.8,
        )

        segs = res["segments"]
        chunk_text = " ".join(s["text"].strip() for s in segs)
        avg_ns = sum(s.get("no_speech_prob", 1) for s in segs) / len(segs) if segs else 1.0

        label = "🗣" if avg_ns < 0.7 else ("❓" if avg_ns < 0.9 else "🔇")
        mm_s = int(start)//60
        ss_s = int(start)%60
        mm_e = int(end)//60
        ss_e = int(end)%60

        line = f"[{mm_s:02d}:{ss_s:02d}-{mm_e:02d}:{ss_e:02d}] ns={avg_ns:.2f} {label}  {chunk_text if chunk_text else '(เงียบ)'}"
        print(line, flush=True)
        results.append(line)

print(f"\nบันทึกที่: {OUT_LOG}")
with open(OUT_LOG, "w", encoding="utf-8") as f:
    f.write("ns < 0.7 = 🗣 เสียงพูด  |  0.7-0.9 = ❓ ไม่แน่ใจ  |  > 0.9 = 🔇 เงียบ\n")
    f.write("="*60 + "\n")
    for line in results:
        f.write(line + "\n")
