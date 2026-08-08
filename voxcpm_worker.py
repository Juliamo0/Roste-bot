"""
voxcpm_worker.py — VoxCPM2 subprocess worker (รันด้วย voxcpm_venv)

โครงเดียวกับ f5_worker.py: โหลดโมเดลครั้งเดียว รับ job ผ่าน stdin/stdout
Protocol:
  stdin  line: JSON {"text": "...", "ref_audio": "...", "out_path": "...",
                     "cfg": 2.0, "steps": 10}
  stdout line: "OK:<path>|time=Xs|dur=Ys"  หรือ  "ERR:<msg บรรทัดเดียว>"

ทำไมต้องเป็น subprocess: VoxCPM2 ต้องใช้ voxcpm_venv (torch 2.11+cu128 สำหรับ
Blackwell + deps ชุดใหญ่) ซึ่งแยกจาก venv หลักของบอท

⚠️ sample rate อยู่ที่ model.tts_model.sample_rate (48000) ไม่ใช่ model.sample_rate
   ห้ามใช้ getattr(model, "sample_rate", <default>) — attr นั้นไม่มีจริง จะตกไปใช้
   ค่า default เงียบๆ แล้วเขียนไฟล์ผิด sample rate = เสียงช้าลงครึ่งหนึ่ง ทุ้มลง
   1 อ็อกเทฟ (บั๊กที่เคยเจอมาแล้ว เสียเวลาไล่หลายรอบ)
"""
import sys, os, time, json, traceback

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

MODEL_ID = "openbmb/VoxCPM2"

print("VOXCPM_WORKER_START", flush=True)
t0 = time.perf_counter()

# import ช้า (~หลายวินาที) ทำครั้งเดียวตอน start
from voxcpm import VoxCPM
import soundfile as sf

model = VoxCPM.from_pretrained(MODEL_ID)
SAMPLE_RATE = model.tts_model.sample_rate     # 48000 — อย่าใส่ default
load_time = time.perf_counter() - t0

try:
    import torch
    vram = torch.cuda.memory_allocated() / 1024**2 if torch.cuda.is_available() else 0
except Exception:
    vram = 0

print(f"VOXCPM_LOAD_TIME={load_time:.1f}|sr={SAMPLE_RATE}|vram={vram:.0f}MB", flush=True)
# ชื่อ marker ตาม pattern เดียวกับ f5_worker.py (F5_WORKER_READY) เพื่อให้ฝั่ง
# voice.py อ่านแบบเดียวกันได้
print("VOXCPM_WORKER_READY", flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    if line in ("QUIT", "EXIT"):   # EXIT = คำที่ voice.py ใช้กับ worker ตัวอื่น
        break
    try:
        job = json.loads(line)
        text = job["text"]
        ref_audio = job["ref_audio"]
        out_path = job["out_path"]
        cfg = job.get("cfg", 2.0)
        steps = job.get("steps", 10)

        t1 = time.perf_counter()
        # โหมด reference_wav_path = โคลนเสียงล้วน (ไม่ต้องมี transcript)
        # ห้ามใช้ prompt_wav_path — นั่นคือโหมด continuation ซึ่งเลียนจังหวะ/โทน
        # ของคลิป ref มาด้วย ทำให้เสียงยืดและผิดจังหวะ (ทดสอบแล้ว ref ชนะชัดเจน)
        wav = model.generate(
            text=text,
            reference_wav_path=ref_audio,
            cfg_value=cfg,
            inference_timesteps=steps,
        )
        elapsed = time.perf_counter() - t1

        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        sf.write(out_path, wav, SAMPLE_RATE)
        duration = len(wav) / SAMPLE_RATE

        print(f"OK:{out_path}|time={elapsed:.1f}s|dur={duration:.1f}s", flush=True)
    except Exception as e:
        # traceback หลายบรรทัด → รีดเหลือบรรทัดเดียวตาม protocol (ผู้เรียกอ่านทีละบรรทัด)
        msg = f"{type(e).__name__}: {e}".replace("\n", " ")[:400]
        print(f"ERR:{msg}", flush=True)
        print(traceback.format_exc(), file=sys.stderr)
