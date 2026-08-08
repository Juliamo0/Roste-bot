"""
ab_voice_compare.py — สร้างเสียง F5(+RVC) ด้วยประโยคเดียวกับ test_voxcpm2.py
เพื่อฟังเทียบแบบ A/B ว่าเสียงไหนดีกว่ากันจริง

รันด้วย: f5_venv\Scripts\python.exe tools\ab_voice_compare.py

ออกไฟล์ที่ f5_out/ab_compare/ ตั้งชื่อคู่กับของ VoxCPM2 ให้ฟังสลับกันได้ทันที:
    f5_<ชื่อ>.wav      ← F5 ล้วน (ยังไม่ผ่าน RVC)
    f5rvc_<ชื่อ>.wav   ← F5 → RVC (เสียงรอสเต้จริงที่บอทใช้ตอนนี้)

เทียบกับ f5_out/voxcpm2/t1_<ชื่อ>.wav และ t2_<ชื่อ>.wav
"""
import sys, os, time, json, subprocess
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ── torchaudio shim (ลอกจาก f5_worker.py) ───────────────────────────
# torchaudio 2.11 ทิ้ง backend ในตัว แล้วส่งงาน I/O ไป torchcodec ซึ่งต้องมี FFmpeg
# shared DLL ที่เราไม่ได้ลง → f5_tts_th เรียก torchaudio.load(ref_audio) แล้วพัง
# ต้องรัน "ก่อน" import f5_tts_th. จำเป็นบน Blackwell (torch 2.11/cu128)
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
# ────────────────────────────────────────────────────────────────────

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "ab_compare")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, BOT_DIR)

# ── ค่าเดียวกับที่บอทใช้จริง (voice.py) ─────────────────────────────
REF_AUDIO = os.path.join(BOT_DIR, "ref_audio", "lai_seg4_160s.wav")
REF_TEXT = ("ตีสอง ตีสาม ตีสี่ อะไรทรงเนี้ยแบบก่อนเช้าอ่ะ มันจะเป็นช่วงผีออกอะไรสักอย่างนึง "
            "แหลมบาดก็แบบว่า")
F5_SPEED = 1.0
F5_STEPS = 32

# ── ประโยคเดียวกับ test_voxcpm2.py เป๊ะ ─────────────────────────────
# ชุด 1: ข้อความปกติ (VoxCPM2 = t1_*)
TESTS = {
    "short":  "สวัสดีค่ะ วันนี้อากาศดีนะคะ",
    "number": "สวัสดีค่ะ วันนี้อากาศดีนะคะ ราคาน้ำมัน 38.85 บาทต่อลิตรค่ะ",
    "medium": "รอสเต้เข้ามาแล้ว อากาศวันนี้ร้อนมากเลย อย่าลืมดื่มน้ำด้วยนะคะ",
    "or_mid": "วันนี้อากาศร้อนมากค่ะ อยากแนะนำให้ดื่มน้ำเยอะนะคะ",
}
# ชุด 2: ข้อความดิบที่ต้องพึ่ง f5_preprocess (VoxCPM2 = t2_*)
TESTS_RAW = {
    "unit":   "ฝนตก 0.2 มม. ความชื้น 75% ค่ะ",
    "year":   "วันนี้วันที่ 7 สิงหาคม พ.ศ. 2569 ค่ะ",
    "codesw": "เดี๋ยวรอสเต้ generate ไฟล์ให้นะคะ รอสักครู่",
}
# ประโยคเดียวกับชุดสไตล์ของ VoxCPM2 (t3_style_none) — F5 ทำสไตล์ไม่ได้
# ใส่ไว้เพื่อให้เทียบ "โทนกลาง" ของสองโมเดลตรงๆ
STYLE_TEXT = "รอสเต้เข้ามาแล้วค่ะ วันนี้เป็นยังไงบ้างคะ"


def main():
    from f5_tts_th.tts import TTS
    from f5_preprocess import preprocess_for_f5
    import soundfile as sf

    print("โหลด F5-TTS-THAI v2 ...")
    t0 = time.perf_counter()
    tts = TTS(model="v2")
    print(f"  โหลดเสร็จใน {time.perf_counter()-t0:.1f}s")

    results = []

    def gen(name, text, preprocess: bool):
        """สร้างเสียง F5 1 ประโยค — preprocess=True คือเส้นทางจริงที่บอทใช้"""
        if preprocess:
            sent, warns = preprocess_for_f5(text)   # คืน (text, warnings)
            if sent != text:
                print(f"    preprocess: {text!r}\n             → {sent!r}")
            if warns:
                print(f"    ⚠️  {warns}")
        else:
            sent = text
        t1 = time.perf_counter()
        try:
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                wav = tts.infer(
                    ref_audio=REF_AUDIO, ref_text=REF_TEXT, gen_text=sent,
                    step=F5_STEPS, cfg=2.0, speed=F5_SPEED, max_chars=150,
                )
            elapsed = time.perf_counter() - t1
            path = os.path.join(OUT_DIR, f"f5_{name}.wav")
            sf.write(path, wav, 24000)
            dur = len(wav) / 24000
            print(f"    {name:<8} → {dur:5.1f}s audio  gen={elapsed:5.1f}s  RTF={elapsed/dur:.2f}")
            results.append({"engine": "f5", "tag": name, "duration": round(dur, 2),
                            "gen_time": round(elapsed, 2), "rtf": round(elapsed/dur, 3),
                            "file": f"f5_{name}.wav", "ok": True})
            return path
        except Exception as e:
            print(f"    {name:<8} → ❌ {type(e).__name__}: {e}")
            results.append({"engine": "f5", "tag": name, "ok": False,
                            "error": f"{type(e).__name__}: {e}"})
            return None

    print("\n" + "=" * 62)
    print("ชุด 1 — ข้อความปกติ (เทียบกับ voxcpm2/t1_*.wav)")
    print("=" * 62)
    for name, text in TESTS.items():
        gen(name, text, preprocess=True)

    print("\n" + "=" * 62)
    print("ชุด 2 — ข้อความดิบ ผ่าน f5_preprocess (เทียบกับ voxcpm2/t2_*.wav)")
    print("=" * 62)
    for name, text in TESTS_RAW.items():
        gen(name, text, preprocess=True)

    print("\n" + "=" * 62)
    print("ชุด 3 — โทนกลาง ประโยคเดียวกับ voxcpm2/t3_style_none.wav")
    print("=" * 62)
    gen("style_none", STYLE_TEXT, preprocess=True)

    ok = [r for r in results if r.get("ok")]
    print("\n" + "=" * 62)
    print(f"สำเร็จ {len(ok)}/{len(results)}")
    if ok:
        print(f"RTF เฉลี่ย (F5 ล้วน ยังไม่รวม RVC) {sum(r['rtf'] for r in ok)/len(ok):.3f}")
    print(f"\nไฟล์อยู่ที่: {OUT_DIR}")
    print("ขั้นต่อไป: รัน RVC ต่อท้ายด้วย tools/ab_run_rvc.py เพื่อได้เสียงรอสเต้จริง")

    with open(os.path.join(OUT_DIR, "f5_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
