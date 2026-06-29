"""
test_pythaitts.py — ทดสอบ PyThaiTTS เทียบ F5
รัน: f5_venv\Scripts\python.exe tools\test_pythaitts.py

โมเดลที่ทดสอบ:
  lunarlist_onnx — ONNX lightweight, CPU only
  vachana        — VachanaTTS2, CPU only
  khanomtan      — ต้องการ coqui-tts (ลอง install อัตโนมัติ)
"""
import sys, os, time, subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "pythaitts_test")
os.makedirs(OUT_DIR, exist_ok=True)

# ── preprocess check ───────────────────────────────────────────────────────────

print("=== เทียบ preprocess_text ===")
from pythaitts import preprocess_text, num_to_thai, expand_maiyamok
cases = [
    "ราคาน้ำมันแก๊สโซฮอล์ 95 อยู่ที่ 38.85 บาทค่ะ",
    "ค่อยๆ ทำไปนะคะ",
    "สวัสดีค่ะ วันนี้ง่วงจังเลย",
    "ดีเซลอยู่ที่ 37.50 บาท/ลิตร แก๊สโซฮอล์ E20 อยู่ที่ 33.05 บาทค่ะ",
]
for c in cases:
    out = preprocess_text(c)
    print(f"  in:  {c}")
    print(f"  out: {out}")
    print()

# ── test sentences ─────────────────────────────────────────────────────────────

TESTS = [
    ("short",   "สวัสดีค่ะ วันนี้ง่วงจังเลย"),
    ("numbers", "ราคาน้ำมันแก๊สโซฮอล์ 95 อยู่ที่ 38.85 บาทค่ะ"),
    ("yamok",   "ค่อยๆ ทำไปนะคะ"),
    ("long",    "ฉันชอบนั่งอ่านหนังสือในห้องสมุดมากเลยค่ะ เงียบสงบดี แต่บางทีก็มีคนมาคุยด้วย "
                "ซึ่งก็น่ารักดีเหมือนกันนะคะ ถ้าอยากได้ข้อมูลหรือหนังสือดีๆ บอกฉันได้เลยนะคะ"),
]

# ── VRAM helper ────────────────────────────────────────────────────────────────

def vram_used_mib() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return f"{torch.cuda.memory_allocated() // (1024**2)}MiB"
    except Exception:
        pass
    return "N/A"

# ── model test helper ──────────────────────────────────────────────────────────

def test_model(model_name: str, speaker: str, extra_install: str = None):
    print(f"\n{'='*60}")
    print(f"โมเดล: {model_name}  speaker: {speaker}")
    print("="*60)

    if extra_install:
        print(f"  📦 ตรวจสอบ {extra_install}...")
        try:
            r = subprocess.run(
                [sys.executable, "-c", f"import {extra_install.split('[')[0].replace('-','_')}"],
                capture_output=True
            )
            if r.returncode != 0:
                print(f"  ติดตั้ง {extra_install}...")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", extra_install, "-q"]
                )
        except Exception as e:
            print(f"  ⚠️ ติดตั้งไม่ได้: {e} — ข้ามโมเดลนี้")
            return

    print(f"  โหลดโมเดล...")
    t0 = time.perf_counter()
    try:
        from pythaitts import TTS
        tts = TTS(pretrained=model_name)
        load_time = time.perf_counter() - t0
        print(f"  ✅ โหลดเสร็จใน {load_time:.1f}s | VRAM: {vram_used_mib()}")
    except Exception as e:
        print(f"  ❌ โหลดไม่ได้: {e}")
        return

    results = []
    for name, text in TESTS:
        out_path = os.path.join(OUT_DIR, f"{name}_{model_name}.wav")
        print(f"\n  [{name}] {text[:60]}")
        preprocessed = preprocess_text(text)
        print(f"  preprocess: {preprocessed[:80]}")
        try:
            t0 = time.perf_counter()
            tts.tts(
                text=text,
                speaker_idx=speaker,
                language_idx="th-th",
                return_type="file",
                filename=out_path,
                preprocess=True,
            )
            elapsed = time.perf_counter() - t0
            # check output file exists and get duration
            dur = "?"
            if os.path.exists(out_path):
                try:
                    import soundfile as sf
                    dur = f"{sf.info(out_path).duration:.1f}s"
                except Exception:
                    dur = f"{os.path.getsize(out_path)//1000}KB"
            print(f"  ✅ gen={elapsed:.1f}s  audio={dur}  → {os.path.basename(out_path)}")
            results.append({"name": name, "gen": elapsed, "dur": dur, "ok": True})
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
            results.append({"name": name, "ok": False})

    return results

# ── main ────────────────────────────────────────────────────────────────────────

print("\n" + "="*60)
print("PyThaiTTS — ทดสอบ 3 โมเดล")
print("="*60)

# 1. lunarlist_onnx — CPU, ไม่ต้องติดตั้งเพิ่ม
test_model("lunarlist_onnx", speaker="Linda")

# 2. vachana — CPU, ไม่ต้องติดตั้งเพิ่ม, ลอง speaker th_f_1 (หญิง)
test_model("vachana", speaker="th_f_1")

# 3. khanomtan — ต้องการ coqui-tts
#    (comment out ถ้าไม่ต้องการ install coqui-tts ~500MB)
test_model("khanomtan", speaker="Linda", extra_install="coqui-tts")

print(f"\n{'='*60}")
print(f"ไฟล์ทั้งหมดอยู่ที่: {OUT_DIR}")
print("\nฟัง:")
for name, _ in TESTS:
    for m in ["lunarlist_onnx", "vachana", "khanomtan"]:
        f = f"{name}_{m}.wav"
        if os.path.exists(os.path.join(OUT_DIR, f)):
            print(f"  {f}")
