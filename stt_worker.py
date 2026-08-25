r"""
Typhoon ASR (NeMo) warm worker — โหลดโมเดลครั้งเดียว รับ job ผ่าน stdin (JSON)

รันด้วย venv แยกจาก f5_venv (ต้องใช้ dependency stack ของ NVIDIA NeMo toolkit):
  typhoon_asr_venv\Scripts\python.exe stt_worker.py

ใช้ scb10x/typhoon-asr-realtime (FastConformer-Transducer 114M) แทน faster-whisper
เพราะวัดแล้วแม่นกว่า (CER 9.84% vs 13.8%) และกิน VRAM น้อยกว่าครึ่ง (~740 vs ~2100 MiB)

⚠️ ห้ามใช้ typhoon_asr.transcribe() ของแพ็กเกจ — มันโหลดโมเดลใหม่ทุกครั้งที่เรียก
   (นิยาม load_typhoon_model() ใหม่ในตัวฟังก์ชันเอง) ใช้กับ warm worker ไม่ได้
   ต้องเรียก nemo_asr.models.ASRModel.from_pretrained() เองครั้งเดียวตอน start

⚠️ NEMO_REDIRECT_LOGS_TO_STDERR ต้องตั้ง *ก่อน* import nemo — ไม่งั้น NeMo สร้าง
   StreamHandler ชี้ stdout (ดู Logger.add_stream_handlers) แล้ว log ของมัน
   ("[NeMo I ...] Using RNNT Loss...") จะปนกับบรรทัด protocol ทำให้ฝั่งที่อ่าน
   stdout ทีละบรรทัดหลุด sync — เจอจริงตอนเทส: readline() ได้ log แทน READY

Protocol (เหมือน f5_worker.py):
  stdin  line: JSON {"wav": "<path to .wav>"}
  stdout line: "OK:<text>"  หรือ  "ERR:<message>"
  stdin  line: "EXIT" → ปิด worker
"""

import os
os.environ["NEMO_REDIRECT_LOGS_TO_STDERR"] = "1"   # ต้องมาก่อน import nemo

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import json
import time
import traceback

import nemo.collections.asr as nemo_asr

MODEL_NAME = "scb10x/typhoon-asr-realtime"
DEVICE = "cuda"

_load_start = time.perf_counter()
try:
    MODEL = nemo_asr.models.ASRModel.from_pretrained(
        model_name=MODEL_NAME,
        map_location=DEVICE,
    )
except Exception:
    # โหลดโมเดลพัง = ตายไปเลยพร้อม traceback ทาง stderr — ไม่พิมพ์ ERR: ที่นี่
    # เพราะ ERR: เป็น protocol ของ *งานราย job* บน stdout เท่านั้น
    traceback.print_exc()
    raise

print(f"STT_WORKER_READY load={time.perf_counter() - _load_start:.1f}s", flush=True)


def _one_line(message) -> str:
    """ยุบข้อความ error ให้เหลือบรรทัดเดียว (protocol = 1 บรรทัดต่อ 1 คำตอบ)"""
    return " ".join(str(message).split())


def _transcribe_wav(wav_path: str) -> str:
    # NeMo รับ list ของ path คืน list ของ Hypothesis (บางเวอร์ชันคืน str ตรงๆ)
    # ไม่มี/ไม่ต้องส่ง language — โมเดลนี้เป็นไทยเฉพาะทางอยู่แล้ว
    result = MODEL.transcribe([wav_path])
    if not result:
        raise RuntimeError(f"transcribe() คืนผลว่างสำหรับ {wav_path!r}")
    first = result[0]
    text = first.text if hasattr(first, "text") else first
    return str(text).strip()


while True:
    line = sys.stdin.readline()
    if not line:
        break                      # stdin ปิด (EOF) — ผู้เรียกเลิกใช้แล้ว

    raw = line.strip()
    if not raw:
        continue

    if raw == "EXIT":
        print("STT_WORKER_EXIT", flush=True)
        break

    try:
        payload = json.loads(raw)
        wav_path = payload.get("wav")
        if not wav_path or not isinstance(wav_path, str):
            raise ValueError('job JSON ต้องมีฟิลด์ "wav" เป็น string ที่ไม่ว่าง')
        text = _transcribe_wav(wav_path)
    except Exception as exc:
        print(f"ERR:{_one_line(exc)}", flush=True)
    else:
        print(f"OK:{text}", flush=True)
