"""
test_crossfade.py — ทดสอบ cross_fade_duration ของ f5_tts_th.utils_infer.infer_batch_process
เทียบกับวิธีปัจจุบัน (ต่อ segment แบบตัดสนิท ไม่ crossfade)

พบว่า f5_tts_th (แพ็กเดียวกับที่ f5_worker.py ใช้) มี cross_fade_duration ให้ใช้อยู่แล้วผ่าน
infer_batch_process — แต่ TTS.infer() (wrapper ที่ f5_worker.py เรียก) ไม่เปิดพารามิเตอร์นี้ให้
สคริปต์นี้เลี่ยง wrapper ไปเรียก infer_batch_process ตรงๆ เพื่อฟังเทียบก่อนตัดสินใจว่าจะเอาเข้า
pipeline จริงไหม (ยังไม่แตะ voice.py/f5_worker.py เลย — สคริปต์แยกต่างหาก)

⚠️ crossfade เป็นแค่ linear fade คลื่นเสียงตรงรอยต่อ ~150ms ไม่ใช่การเปลี่ยน ref/tone ข้าม
segment (ที่เคยลองแล้วเสียงเสื่อมสะสม) ทุก segment ยัง generate จาก F5_REF_AUDIO/F5_REF_TEXT
คงที่เหมือนเดิม — คาดว่าช่วยลบ "รอยต่อ/click" ได้ แต่อาจไม่ช่วยเรื่องโทนกระโดดเต็มที่

รัน: f5_venv\\Scripts\\python.exe tools\\test_crossfade.py
     ⚠️ ปิดบอทก่อนรัน กัน VRAM ชนกัน (บอทถือ F5 worker ค้างไว้)
"""
import sys, os, time

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "crossfade_test")
os.makedirs(OUT_DIR, exist_ok=True)
sys.path.insert(0, BOT_DIR)

# torchaudio I/O patch เหมือน f5_worker.py — กัน TorchCodec error บน torch 2.11/cu128
import torchaudio as _ta
import soundfile as _sf
import torch as _torch


def _ta_load(filepath, frame_offset=0, num_frames=-1, normalize=True,
             channels_first=True, format=None, buffer_size=4096, backend=None):
    data, sr = _sf.read(str(filepath), dtype="float32", always_2d=True)
    if frame_offset or num_frames != -1:
        end = None if num_frames == -1 else frame_offset + num_frames
        data = data[frame_offset:end]
    tensor = _torch.from_numpy(data.T.copy())
    return (tensor, sr) if channels_first else (tensor.t(), sr)


def _ta_save(filepath, src, sample_rate, channels_first=True, **_kw):
    arr = src.detach().cpu().numpy()
    if channels_first and arr.ndim == 2:
        arr = arr.T
    _sf.write(str(filepath), arr, sample_rate)


class _TAInfo:
    def __init__(self, sr, frames, ch):
        self.sample_rate, self.num_frames, self.num_channels = sr, frames, ch


def _ta_info(filepath, *_a, **_k):
    i = _sf.info(str(filepath))
    return _TAInfo(i.samplerate, i.frames, i.channels)


_ta.load, _ta.save, _ta.info = _ta_load, _ta_save, _ta_info

print("โหลด F5 model...")
t0 = time.perf_counter()
from f5_tts_th.tts import TTS
from f5_tts_th.utils_infer import infer_batch_process, preprocess_ref_audio_text

tts = TTS(model="v2")
print(f"✅ โหลดเสร็จใน {time.perf_counter() - t0:.1f}s")

import voice
from voice import F5_REF_AUDIO, F5_REF_TEXT, F5_SPEED, F5_STEPS, _split_thai_text, _pitch_shift, _rvc_oneshot

TEST_TEXT = (
    "ง่วงง่วง นะคะ แต่ยังจำได้ว่าตอนที่แดดออกมักจะร้อนจนอยากไปอยู่ในห้องเย็นเย็น "
    "หรือดื่มน้ำเย็นเย็น ส่วนฝนตกก็เหมือนการได้พักจากความร้อน แล้วลมช่วงนั้นอากาศสดชื่น "
    "แต่ถ้าฝนตกหนักๆ ก็ไม่อยากออกไปไหนเลยค่ะ ชอบแบบที่แดดออกน้อยน้อย ผสมกับฝนตกเบาเบา นะ "
    "แบบว่าได้พักจากความร้อน แล้วมีลมเย็นเย็น เย็นใจ ค่ะ"
)

segments = _split_thai_text(TEST_TEXT, max_chars=300)
print(f"\n🔤 แบ่งได้ {len(segments)} segment:")
for i, s in enumerate(segments):
    print(f"  [{i}] ({len(s)}c) {s!r}")

ref_audio, ref_text = preprocess_ref_audio_text(F5_REF_AUDIO, F5_REF_TEXT)

# ── วิธีปัจจุบัน: เจนทีละ segment แยกกัน แล้วต่อสนิท (ไม่ crossfade) ──
print("\n" + "=" * 60)
print("วิธีปัจจุบัน: เจนแยก segment ต่อสนิท (baseline)")
print("=" * 60)
import numpy as np

waveform, sr = _ta.load(ref_audio)
current_waves = []
for i, seg in enumerate(segments):
    t0 = time.perf_counter()
    result = next(infer_batch_process(
        (waveform, sr), ref_text, [seg], tts.f5_model, tts.vocoder,
        mel_spec_type=tts.vocoder_name, cross_fade_duration=0.0,
        nfe_step=F5_STEPS, speed=F5_SPEED, device="cuda", use_ipa=True,
    ))
    wav, out_sr, _ = result
    current_waves.append(wav)
    print(f"  [{i}] gen={time.perf_counter()-t0:.1f}s dur={len(wav)/out_sr:.1f}s")
current_concat = np.concatenate(current_waves)
current_f5_path = os.path.join(OUT_DIR, "a_current_no_crossfade_f5raw.wav")
_sf.write(current_f5_path, current_concat, out_sr)
print(f"✅ F5 ล้วน → {current_f5_path}")

print("  → pitch108 + RVC (เหมือน pipeline จริง)...")
current_pitched = _pitch_shift(current_f5_path, os.path.join(OUT_DIR, "a_pitch.wav"))
current_path = os.path.join(OUT_DIR, "a_current_no_crossfade_ROSTE.wav")
_rvc_oneshot(current_pitched, current_path)
print(f"✅ เสียงรอสเต้ → {current_path}")

# ── วิธีใหม่: เจนทุก segment ในคำขอเดียว ให้ infer_batch_process crossfade ให้ ──
print("\n" + "=" * 60)
print("วิธีใหม่: infer_batch_process cross_fade_duration=0.15")
print("=" * 60)
t0 = time.perf_counter()
result = next(infer_batch_process(
    (waveform, sr), ref_text, segments, tts.f5_model, tts.vocoder,
    mel_spec_type=tts.vocoder_name, cross_fade_duration=0.15,
    nfe_step=F5_STEPS, speed=F5_SPEED, device="cuda", use_ipa=True,
))
wav_cf, out_sr_cf, _ = result
crossfade_f5_path = os.path.join(OUT_DIR, "b_crossfade_015_f5raw.wav")
_sf.write(crossfade_f5_path, wav_cf, out_sr_cf)
print(f"✅ F5 ล้วน gen={time.perf_counter()-t0:.1f}s dur={len(wav_cf)/out_sr_cf:.1f}s → {crossfade_f5_path}")

print("  → pitch108 + RVC (เหมือน pipeline จริง)...")
crossfade_pitched = _pitch_shift(crossfade_f5_path, os.path.join(OUT_DIR, "b_pitch.wav"))
crossfade_path = os.path.join(OUT_DIR, "b_crossfade_015_ROSTE.wav")
_rvc_oneshot(crossfade_pitched, crossfade_path)
print(f"✅ เสียงรอสเต้ → {crossfade_path}")

print("\n" + "=" * 60)
print("สรุป — ฟังเทียบ (เสียงรอสเต้จริง ผ่าน RVC + pitch108 แล้ว):")
print("=" * 60)
print(f"  a) {current_path}")
print(f"     (baseline — เหมือนที่บอทเล่นจริงตอนนี้ ตัดสนิทไม่ crossfade)")
print(f"  b) {crossfade_path}")
print(f"     (crossfade 150ms ตรงรอยต่อทุก segment)")
