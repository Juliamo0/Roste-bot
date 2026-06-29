"""
F5-TTS warm worker — โหลดโมเดลครั้งเดียว รับ job ผ่าน stdin (JSON)
รันด้วย: f5_venv\Scripts\python.exe f5_worker.py

Protocol (เหมือน voice_rvc_worker.py):
  stdin  line: JSON {"ref_audio": "...", "ref_text": "...", "gen_text": "...",
                     "out_path": "...", "speed": 1.0, "steps": 16}
  stdout line: "OK: <out_path>"  หรือ  "ERR: <message>"
  stdin  line: "EXIT" → ปิด worker
"""
import sys, os, time, json, traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

MODEL_VERSION = "v2"

print(f"F5_WORKER_START", flush=True)
t0 = time.perf_counter()
from f5_tts_th.tts import TTS
tts = TTS(model=MODEL_VERSION)
load_time = time.perf_counter() - t0

try:
    import torch
    if torch.cuda.is_available():
        vram = torch.cuda.memory_allocated() / 1024**2
        print(f"F5_WORKER_READY load={load_time:.1f}s vram={vram:.0f}MiB", flush=True)
    else:
        print(f"F5_WORKER_READY load={load_time:.1f}s (CPU)", flush=True)
except Exception:
    print(f"F5_WORKER_READY load={load_time:.1f}s", flush=True)

import soundfile as sf

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    if line == "EXIT":
        print("F5_WORKER_EXIT", flush=True)
        break
    try:
        job = json.loads(line)
        ref_audio  = job["ref_audio"]
        ref_text   = job["ref_text"]
        gen_text   = job["gen_text"]
        out_path   = job["out_path"]
        speed      = job.get("speed", 1.0)
        steps      = job.get("steps", 16)
        max_chars  = job.get("max_chars", 200)


        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        t1 = time.perf_counter()
        # redirect noisy stdout จาก f5_tts_th (tqdm/print) ไปที่ stderr
        # เพื่อกัน progress bar ปน OK:/ERR: protocol
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            wav = tts.infer(
                ref_audio=ref_audio,
                ref_text=ref_text,
                gen_text=gen_text,
                step=steps,
                cfg=2.0,
                speed=speed,
                max_chars=max_chars,
            )
        elapsed = time.perf_counter() - t1
        duration = len(wav) / 24000
        sf.write(out_path, wav, 24000)

        print(f"OK:{out_path}|time={elapsed:.1f}s|dur={duration:.1f}s", flush=True)
    except Exception as e:
        print(f"ERR:{traceback.format_exc()[-200:]}", flush=True)
