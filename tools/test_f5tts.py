"""
ทดสอบ F5-TTS-THAI เบื้องต้น
รันด้วย: f5_venv\Scripts\python.exe tools\test_f5tts.py
"""
import sys, time, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REF_AUDIO = r"C:\Users\julia\OneDrive\Desktop\mybot\rvc_out\bot\55682969_rvc.wav"
REF_TEXT  = "รอสเต้เข้ามาแล้วนะคะ"
GEN_TEXT  = "สวัสดีค่ะ วันนี้อากาศดีมากเลยนะคะ เป็นยังไงบ้างคะ"
OUT_PATH  = r"C:\Users\julia\OneDrive\Desktop\mybot\f5_out\test_output.wav"

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)

print("โหลด F5-TTS model (V2)...")
t0 = time.perf_counter()
from f5_tts_th.tts import TTS
tts = TTS(model="v2")
print(f"โหลดเสร็จใน {time.perf_counter()-t0:.1f}s")

try:
    import torch
    if torch.cuda.is_available():
        used  = torch.cuda.memory_allocated() / 1024**2
        total = torch.cuda.get_device_properties(0).total_memory / 1024**2
        print(f"VRAM: {used:.0f}/{total:.0f} MiB ใช้อยู่หลังโหลดโมเดล")
except Exception:
    pass

print(f"\nสร้างเสียง: {GEN_TEXT!r}")
t1 = time.perf_counter()
import soundfile as sf
wav = tts.infer(
    ref_audio=REF_AUDIO,
    ref_text=REF_TEXT,
    gen_text=GEN_TEXT,
    step=32,
    cfg=2.0,
    speed=1.0,
)
elapsed = time.perf_counter() - t1
print(f"สร้างเสร็จใน {elapsed:.1f}s")

sf.write(OUT_PATH, wav, 24000)
duration = len(wav) / 24000
print(f"บันทึก {OUT_PATH}")
print(f"ความยาวเสียง: {duration:.1f}s | RTF: {elapsed/duration:.2f}x")

try:
    import torch
    if torch.cuda.is_available():
        used = torch.cuda.memory_reserved() / 1024**2
        print(f"VRAM reserved: {used:.0f} MiB")
except Exception:
    pass

print("\nเสร็จ — เปิดไฟล์ test_output.wav เพื่อฟัง")
