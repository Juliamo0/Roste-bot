"""test_isolate.py — เทียบ TTS.infer() (ทางที่รู้ว่าใช้งานได้จริง) กับ infer_batch_process ตรงๆ"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "f5_out", "crossfade_test")
os.makedirs(OUT_DIR, exist_ok=True)

from f5_tts_th.tts import TTS
tts = TTS(model="v2")
print("model loaded")

from voice import F5_REF_AUDIO, F5_REF_TEXT

GEN_TEXT = "สวัสดีค่ะ วันนี้อากาศดีมากเลย"

from f5_tts_th.utils_infer import infer_batch_process, preprocess_ref_audio_text, chunk_text
from f5_tts_th.normalize import normalize_text

# พารามิเตอร์ให้ตรงกับที่ TTS.infer() → infer_process ใช้จริง ไม่งั้นเทียบไม่ได้
COMMON = dict(
    mel_spec_type=tts.vocoder_name, cross_fade_duration=0.15,
    nfe_step=32, cfg_strength=2.0, sway_sampling_coef=-1.0,
    target_rms=0.1, speed=1.0, device="cuda", use_ipa=True,
)

# ── ทาง A: TTS.infer() — ทางที่ f5_worker.py ใช้จริง รู้ว่าใช้งานได้ ──
# NOTE: ชื่อพารามิเตอร์คือ step= ไม่ใช่ steps=
wav = tts.infer(ref_audio=F5_REF_AUDIO, ref_text=F5_REF_TEXT, gen_text=GEN_TEXT, speed=1.0, step=32)
path_a = os.path.join(OUT_DIR, "c_via_TTSinfer.wav")
_sf.write(path_a, wav, 24000)
print("A) TTS.infer() →", path_a)

ref_audio, ref_text = preprocess_ref_audio_text(F5_REF_AUDIO, F5_REF_TEXT)
waveform, sr = _ta.load(ref_audio)

# ── ทาง B: infer_batch_process ตรงๆ ข้าม normalize_text + ข้าม chunk_text ──
wav_b, sr_b, _ = next(infer_batch_process(
    (waveform, sr), ref_text, [GEN_TEXT], tts.f5_model, tts.vocoder, **COMMON))
path_b = os.path.join(OUT_DIR, "d_via_infer_batch_direct.wav")
_sf.write(path_b, wav_b, sr_b)
print("B) infer_batch_process direct →", path_b)

# ── ทาง C: ใส่ normalize_text + chunk_text(100) กลับเข้าไป ──
# ถ้า C ดีแต่ B พัง = ต้นเหตุอยู่ที่สองขั้นนี้ ไม่ใช่ที่ตัวโมเดล
batches = chunk_text(normalize_text(GEN_TEXT), max_chars=100)
print("C) batches =", batches)
wav_c, sr_c, _ = next(infer_batch_process(
    (waveform, sr), ref_text, batches, tts.f5_model, tts.vocoder, **COMMON))
path_c = os.path.join(OUT_DIR, "e_via_infer_batch_normalized.wav")
_sf.write(path_c, wav_c, sr_c)
print("C) infer_batch_process + normalize + chunk →", path_c)
