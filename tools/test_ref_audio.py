"""
test_ref_audio.py — ทดสอบสมมติฐาน: ref audio ที่ชัดกว่าทำให้ F5 อ่านดีขึ้น

Phase 1: ตัด 6 segments จาก 1_Lai_ref_(Vocals).mp3 + Whisper transcribe
Phase 2: สร้าง Vachana ref (เสียงชัด synthetic)
Phase 3: ทดสอบ F5 กับ 4 refs — current + best_laibaht + vachana
Phase 4: สรุปไฟล์ให้ฟัง

รัน: f5_venv\Scripts\python.exe tools\test_ref_audio.py
     ⚠️ บอทรันอยู่ก็ได้ — แต่ถ้า F5 ทำงาน error ให้ปิดบอทก่อน
"""
import sys, os, time, json

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_MP3 = os.path.join(BOT_DIR, "1_Lai_ref_(Vocals).mp3")
OUT_DIR    = os.path.join(BOT_DIR, "f5_out", "ref_test")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, BOT_DIR)

# ── gen_text ที่ F5 เคยอ่านผิด ─────────────────────────────────────────────────
TESTS = [
    ("numbers", "ราคาน้ำมันแก๊สโซฮอล์ เก้าสิบห้า อยู่ที่ สามสิบแปดจุดแปดห้า บาทค่ะ"),
    ("long",    "ฉันชอบนั่งอ่านหนังสือในห้องสมุดมากเลยค่ะ เงียบสงบดี แต่บางทีก็มีคนมาคุยด้วย "
                "ซึ่งก็น่ารักดีเหมือนกันนะคะ ถ้าอยากได้ข้อมูลหรือหนังสือดีๆ บอกฉันได้เลยนะคะ"),
    ("short",   "สวัสดีค่ะ วันนี้ง่วงจังเลย"),
]

# ── audio helpers ─────────────────────────────────────────────────────────────

def load_mono_24k(path: str, start: float = 0.0, end: float = None):
    """โหลดเสียง → mono → resample 24kHz"""
    import soundfile as sf
    import numpy as np
    from scipy.signal import resample_poly
    from math import gcd

    data, sr = sf.read(path, always_2d=True)
    data = data.mean(axis=1)  # stereo → mono

    s = int(start * sr)
    e = int(end   * sr) if end else len(data)
    data = data[s:e]

    if sr != 24000:
        g = gcd(sr, 24000)
        data = resample_poly(data, 24000 // g, sr // g).astype(np.float32)
    return data.astype(np.float32), 24000


def save_wav(data, sr: int, path: str) -> None:
    import soundfile as sf
    sf.write(path, data, sr)


def dur_str(path: str) -> str:
    try:
        import soundfile as sf
        return f"{sf.info(path).duration:.1f}s"
    except Exception:
        return "?"

# ── Phase 1: ตัด candidates + Whisper transcribe ─────────────────────────────

print("=" * 60)
print("Phase 1: ตัด segments จาก 1_Lai_ref_(Vocals).mp3 + Whisper")
print("=" * 60)

import soundfile as sf
src_info = sf.info(SOURCE_MP3)
total_dur = src_info.duration
print(f"\nต้นฉบับ: {total_dur:.1f}s ({total_dur/60:.1f} นาที)")

# timestamp candidates (start, end) — กระจายทั่วไฟล์
CANDIDATES = [
    (30,  38),
    (70,  78),
    (115, 123),
    (160, 168),
    (210, 218),
    (270, 278),
]

print("\nโหลด Whisper (small, CPU)...")
import whisper as whisper_mod
wmodel = whisper_mod.load_model("small", device="cpu")
print("✅ Whisper พร้อม")

candidate_refs = []
for i, (start, end) in enumerate(CANDIDATES):
    name   = f"lai_seg{i+1}_{start}s"
    path   = os.path.join(OUT_DIR, f"{name}.wav")
    print(f"\n  segment {i+1}: {start}-{end}s")
    try:
        data, sr = load_mono_24k(SOURCE_MP3, start, end)
        save_wav(data, sr, path)
        # Whisper transcribe
        result = wmodel.transcribe(path, language="th", fp16=False)
        text   = result["text"].strip()
        print(f"  ✅ {dur_str(path)} → {os.path.basename(path)}")
        print(f"  📝 Whisper: {text}")
        candidate_refs.append({"name": name, "path": path, "text": text,
                                "start": start, "end": end})
    except Exception as e:
        print(f"  ❌ {e}")

# ── Phase 2: Vachana ref ───────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("Phase 2: สร้าง Vachana ref (เสียงชัด synthetic)")
print("=" * 60)

VACHANA_REF_TEXT = "สวัสดีค่ะ วันนี้อยู่ที่ห้องสมุดนะคะ มีอะไรให้ช่วยก็บอกได้เลยค่ะ"
vachana_ref_path = os.path.join(OUT_DIR, "vachana_ref.wav")

print(f"\nข้อความ: \"{VACHANA_REF_TEXT}\"")
try:
    from pythaitts import TTS as VachTTS
    vtts = VachTTS(pretrained="vachana")
    vtts.tts(text=VACHANA_REF_TEXT, speaker_idx="th_f_1", language_idx="th-th",
             return_type="file", filename=vachana_ref_path, preprocess=True)
    print(f"✅ Vachana ref → {os.path.basename(vachana_ref_path)} ({dur_str(vachana_ref_path)})")
    # resample to 24kHz if needed (Vachana อาจ output 22kHz)
    data_v, sr_v = load_mono_24k(vachana_ref_path)
    save_wav(data_v, 24000, vachana_ref_path)
    print(f"   (resampled to 24kHz)")
except Exception as e:
    print(f"❌ Vachana ref failed: {e}")
    vachana_ref_path = None

# ── Phase 3: F5 test ───────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("Phase 3: ทดสอบ F5 กับแต่ละ ref")
print("=" * 60)

# กำหนด refs ที่จะทดสอบ
CURRENT_REF = {
    "name": "current_laibaht",
    "path": os.path.join(BOT_DIR, "f5_out", "ref_laibaht.wav"),
    "text": "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง",
}

test_refs = [CURRENT_REF]

# เพิ่ม Vachana ref
if vachana_ref_path and os.path.exists(vachana_ref_path):
    test_refs.append({
        "name": "vachana_ref",
        "path": vachana_ref_path,
        "text": VACHANA_REF_TEXT,
    })

# เพิ่ม Laibaht candidates (ทุกอัน — ผู้ใช้เลือกทีหลัง)
test_refs += candidate_refs

print(f"\nรวม {len(test_refs)} refs ที่จะทดสอบ")
print("โหลด F5 Worker...")

from voice import F5Worker
F5_REF_AUDIO_ORIG = os.path.join(BOT_DIR, "f5_out", "ref_laibaht.wav")
F5_REF_TEXT_ORIG  = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"

try:
    f5 = F5Worker()
    f5.start()
    print(f"✅ F5 Worker พร้อม ({f5.load_time:.1f}s)")
except Exception as e:
    print(f"❌ F5 Worker ไม่พร้อม: {e}")
    print("   → ปิดบอทก่อนแล้วรันใหม่")
    f5 = None

results = []

if f5:
    for ref in test_refs:
        ref_name = ref["name"]
        ref_path = ref["path"]
        ref_text = ref["text"]
        print(f"\n{'─'*50}")
        print(f"ref: {ref_name}")
        print(f"text: \"{ref_text[:60]}\"")

        for test_name, gen_text in TESTS:
            out_f5  = os.path.join(OUT_DIR, f"{test_name}_{ref_name}_f5.wav")
            print(f"\n  [{test_name}] {gen_text[:50]}...")
            try:
                t0  = time.perf_counter()
                dur = f5.generate(
                    ref_audio=ref_path,
                    ref_text=ref_text,
                    gen_text=gen_text,
                    out_path=out_f5,
                    speed=1.0,
                    steps=32,
                )
                elapsed = time.perf_counter() - t0
                print(f"  ✅ gen={elapsed:.1f}s  audio={dur:.1f}s → {os.path.basename(out_f5)}")
                results.append({"ref": ref_name, "test": test_name,
                                 "gen": round(elapsed, 1), "dur": round(dur, 1), "ok": True})
            except Exception as e:
                print(f"  ❌ {e}")
                results.append({"ref": ref_name, "test": test_name, "ok": False})

    f5.stop()

# ── สรุป ──────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("สรุป — ไฟล์ทั้งหมดอยู่ที่: " + OUT_DIR)
print("=" * 60)

print("\n📂 Laibaht source segments (ฟังเลือกอันที่ 'ชัด-ช้า' สุด):")
for c in candidate_refs:
    p = c["path"]
    if os.path.exists(p):
        print(f"  {os.path.basename(p)} ({dur_str(p)})  → \"{c['text'][:50]}\"")

print("\n📂 Vachana ref (เสียงชัด synthetic):")
if vachana_ref_path and os.path.exists(vachana_ref_path):
    print(f"  {os.path.basename(vachana_ref_path)} ({dur_str(vachana_ref_path)})")

if results:
    print("\n📂 F5 outputs — เปรียบเทียบแต่ละ ref:")
    print(f"  {'ref':<22} {'test':<10} {'gen':>7} {'audio':>7}")
    print("  " + "-"*50)
    for r in results:
        if r["ok"]:
            print(f"  {r['ref']:<22} {r['test']:<10} {r['gen']:>6.1f}s {r['dur']:>6.1f}s")
        else:
            print(f"  {r['ref']:<22} {r['test']:<10}   ❌")

    print("\nฟัง (เปรียบ ref ต่างๆ บน gen_text เดียวกัน):")
    for test_name, _ in TESTS:
        print(f"\n  [{test_name}]:")
        print(f"    {test_name}_current_laibaht_f5.wav  ← current")
        if vachana_ref_path:
            print(f"    {test_name}_vachana_ref_f5.wav     ← Vachana ref")
        for c in candidate_refs:
            f = f"{test_name}_{c['name']}_f5.wav"
            if os.path.exists(os.path.join(OUT_DIR, f)):
                print(f"    {f}")
