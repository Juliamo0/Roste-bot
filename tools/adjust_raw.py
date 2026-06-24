"""
ปรับ pitch + tempo ของไฟล์ wav ก่อนส่งเข้า RVC
แก้ 3 บรรทัดบนสุดแล้วรันใหม่เพื่อลองค่าต่างๆ

วิธีใช้:
  python tools/adjust_raw.py                          → ปรับทุกไฟล์ใน tts_raw/
  python tools/adjust_raw.py tts_raw/raw_greeting.wav → ปรับไฟล์เดียว

ผลลัพธ์: tts_adjusted/  (ชื่อเดิม + _adj.wav)

backend ที่ใช้ (เลือกอัตโนมัติ):
  pyrubberband — คุณภาพสูงสุด ไม่เกิด echo แต่ต้องมี rubberband-cli:
                 Windows: winget install Breakfastquay.Rubberband
                 แล้วรีสตาร์ท terminal
  ffmpeg       — fallback อัตโนมัติ ถ้าไม่มี rubberband-cli
                 ใช้ asetrate+atempo (WSOLA) ไม่เกิด echo เหมือนกัน
"""

# ── ปรับค่าตรงนี้ ──────────────────────────────────────────────────────────────
SPEED           = 0.90    # tempo: < 1 = ช้าลง, > 1 = เร็วขึ้น (pitch ไม่เปลี่ยน)
PITCH_SEMITONES = 5.292   # semitone: + = สูงขึ้น, - = ต่ำลง (tempo ไม่เปลี่ยน)
                 #         ตั้ง 0 ถ้าไม่ต้องการปรับ pitch ที่นี่ (ไปตั้งใน RVC แทน)
OUT_SR          = 40000   # sample rate output — RVC มาตรฐานใช้ 40000 Hz
                 #         ถ้า RVC ของคุณ train ที่ 16000 Hz ให้เปลี่ยนเป็น 16000
# ──────────────────────────────────────────────────────────────────────────────

import os
import sys
import time
import glob

import librosa
import soundfile as sf
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "..")
IN_DIR      = os.path.join(PROJECT_DIR, "tts_raw")
OUT_DIR     = os.path.join(PROJECT_DIR, "tts_adjusted")


# ── backend detection ──────────────────────────────────────────────────────────

def _has_rubberband_bin() -> bool:
    """ตรวจว่า rubberband binary อยู่ใน PATH"""
    import shutil
    return shutil.which("rubberband") is not None


def _use_pyrubberband(y: np.ndarray, sr: int) -> np.ndarray:
    import pyrubberband as pyrb
    if PITCH_SEMITONES != 0:
        y = pyrb.pitch_shift(y, sr, PITCH_SEMITONES)
    if SPEED != 1.0:
        y = pyrb.time_stretch(y, sr, SPEED)
    return y


# ── ffmpeg backend ─────────────────────────────────────────────────────────────

def _atempo_chain(rate: float) -> list[str]:
    """atempo รับได้ 0.5–2.0 ต่อตัว chain หลายตัวถ้าเกินช่วง"""
    filters, r = [], rate
    while r < 0.5:
        filters.append("atempo=0.5")
        r /= 0.5
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    filters.append(f"atempo={r:.8f}")
    return filters


def _use_ffmpeg(in_path: str, out_path: str, sr: int) -> None:
    """
    pitch: asetrate + aresample — ไม่ใช้ phase vocoder ไม่เกิด echo
    speed: atempo (WSOLA) — ไม่เกิด echo

    เมื่อทำ pitch shift ด้วย asetrate audio จะสั้น/ยาวกว่าต้นฉบับ
    atempo ต้องชดเชยส่วนนั้นด้วย → effective_tempo = SPEED / pitch_factor
    """
    filters: list[str] = []

    pitch_factor = 2 ** (PITCH_SEMITONES / 12) if PITCH_SEMITONES != 0 else 1.0

    if PITCH_SEMITONES != 0:
        filters.append(f"asetrate={int(sr * pitch_factor)}")
        filters.append(f"aresample={sr}")

    # ชดเชย tempo ที่เปลี่ยนไปพร้อมกับ pitch + ปรับ SPEED
    effective_tempo = SPEED / pitch_factor
    if abs(effective_tempo - 1.0) > 1e-9:
        filters += _atempo_chain(effective_tempo)

    filter_str = ",".join(filters) if filters else "anull"
    cmd = (
        f'ffmpeg -y -loglevel error -i "{in_path}" '
        f'-af "{filter_str}" -ar {OUT_SR} -ac 1 -sample_fmt s16 "{out_path}"'
    )
    if os.system(cmd) != 0:
        raise RuntimeError(f"ffmpeg failed — คำสั่ง: {cmd}")


# ── main process ───────────────────────────────────────────────────────────────

def adjust(in_path: str) -> tuple[str, float, str]:
    """คืน (out_path, วินาทีที่ใช้, ชื่อ backend)"""
    t0 = time.perf_counter()
    os.makedirs(OUT_DIR, exist_ok=True)
    base     = os.path.splitext(os.path.basename(in_path))[0]
    out_path = os.path.join(OUT_DIR, f"{base}_adj.wav")

    if _has_rubberband_bin():
        y, sr = librosa.load(in_path, sr=None, mono=True)
        y = _use_pyrubberband(y, sr)
        if sr != OUT_SR:
            y = librosa.resample(y, orig_sr=sr, target_sr=OUT_SR)
        sf.write(out_path, y, OUT_SR, subtype="PCM_16")
        backend = "pyrubberband"
    else:
        info = sf.info(in_path)
        _use_ffmpeg(in_path, out_path, info.samplerate)
        backend = "ffmpeg"

    return out_path, time.perf_counter() - t0, backend


def main():
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = sorted(glob.glob(os.path.join(IN_DIR, "*.wav")))
        if not files:
            print(f"ไม่พบไฟล์ .wav ใน {IN_DIR}")
            print("ลองรัน  python tools/make_tts_raw.py  ก่อน")
            sys.exit(1)

    print(f"SPEED={SPEED}  PITCH={PITCH_SEMITONES:+.3f} semitones  OUT_SR={OUT_SR} Hz")
    print(f"บันทึกลง: {os.path.abspath(OUT_DIR)}\n")

    total = 0.0
    for f in files:
        name = os.path.basename(f)
        print(f"  {name} ...", end=" ", flush=True)
        out, elapsed, backend = adjust(f)
        total += elapsed
        print(f"{elapsed:.1f}s  [{backend}]  →  {os.path.basename(out)}")

    print(f"\n✅ เสร็จ {len(files)} ไฟล์  รวม {total:.1f}s")
    print(f"\nเช็คค่าที่ใช้แล้วผิด → แก้ SPEED / PITCH_SEMITONES / OUT_SR บนสุดแล้วรันใหม่")
    if not _has_rubberband_bin():
        print(f"ติดตั้ง rubberband เพื่อใช้ backend คุณภาพสูงกว่า:")
        print(f"  winget install Breakfastquay.Rubberband  (แล้วรีสตาร์ท terminal)")


if __name__ == "__main__":
    main()
