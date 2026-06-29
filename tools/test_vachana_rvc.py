"""
test_vachana_rvc.py — ทดสอบ VachanaTTS → RVC Laibaht
เทียบกับ F5 → RVC

รัน: f5_venv\Scripts\python.exe tools\test_vachana_rvc.py
     (บอทรันอยู่ก็ได้ — Vachana ใช้ CPU, RVC เพิ่มแค่ ~291MiB VRAM)
"""
import sys, os, time, json, subprocess, tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_DIR    = os.path.join(BOT_DIR, "f5_out", "pythaitts_test")   # vachana raw อยู่ที่นี่
OUT_DIR   = os.path.join(BOT_DIR, "f5_out", "vachana_rvc_test")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, BOT_DIR)

MODEL_DIR   = r"D:\LaibahtMaLaew"
RVC_VENV_PY = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")

# ── test sentences ────────────────────────────────────────────────────────────

TESTS = [
    ("short",   "สวัสดีค่ะ วันนี้ง่วงจังเลย"),
    ("numbers", "ราคาน้ำมันแก๊สโซฮอล์ 95 อยู่ที่ 38.85 บาทค่ะ"),
    ("yamok",   "ค่อยๆ ทำไปนะคะ"),
    ("long",    "ฉันชอบนั่งอ่านหนังสือในห้องสมุดมากเลยค่ะ เงียบสงบดี แต่บางทีก็มีคนมาคุยด้วย "
                "ซึ่งก็น่ารักดีเหมือนกันนะคะ ถ้าอยากได้ข้อมูลหรือหนังสือดีๆ บอกฉันได้เลยนะคะ"),
]

PITCH_VALUES = [-4, -2, 0, 2, 4]   # ทดสอบ pitch บน short sentence
PITCH_TEST_NAME = "short"

# ── VRAM ──────────────────────────────────────────────────────────────────────

def vram_used_mib() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return f"{torch.cuda.memory_allocated() // (1024**2)}MiB"
    except Exception:
        pass
    return "N/A"

# ── RVC helpers ────────────────────────────────────────────────────────────────

def _find_model_files():
    if not os.path.isdir(MODEL_DIR):
        return None, None
    files = os.listdir(MODEL_DIR)
    pth   = next((f for f in files if f.endswith(".pth")),   None)
    idx   = next((f for f in files if f.endswith(".index")), None)
    return (os.path.join(MODEL_DIR, pth) if pth else None,
            os.path.join(MODEL_DIR, idx) if idx else None)


def rvc_convert(in_wav: str, out_wav: str, pitch: int = 0) -> float:
    model_pth, model_idx = _find_model_files()
    if not model_pth:
        raise RuntimeError(f"ไม่พบ .pth ใน {MODEL_DIR}")

    cfg = {
        "model_path": model_pth, "index_path": model_idx or "",
        "device": "cuda:0", "index_rate": 0.5, "protect": 0.33,
        "f0up_key": pitch, "in_wav": in_wav, "out_wav": out_wav,
    }
    tmp = os.path.join(tempfile.gettempdir(), "vachana_rvc_test.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    code = f"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rvc_python.infer import RVCInference
with open({repr(tmp)}, encoding='utf-8') as f:
    c = json.load(f)
rvc = RVCInference(device=c['device'])
rvc.load_model(c['model_path'], index_path=c['index_path'] or None)
rvc.set_params(f0up_key=c['f0up_key'], f0method='rmvpe',
               index_rate=c['index_rate'], protect=c['protect'])
os.makedirs(os.path.dirname(os.path.abspath(c['out_wav'])), exist_ok=True)
rvc.infer_file(input_path=c['in_wav'], output_path=c['out_wav'])
print('done', flush=True)
"""
    t0 = time.perf_counter()
    r = subprocess.run(
        [RVC_VENV_PY, "-c", code],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise RuntimeError(f"RVC failed:\n{r.stderr[-500:]}")
    return time.perf_counter() - t0


# ── generate Vachana (fresh) ───────────────────────────────────────────────────

def gen_vachana(text: str, out_path: str) -> float:
    from pythaitts import TTS
    tts = TTS(pretrained="vachana")
    t0  = time.perf_counter()
    tts.tts(text=text, speaker_idx="th_f_1", language_idx="th-th",
            return_type="file", filename=out_path, preprocess=True)
    return time.perf_counter() - t0


# ── audio duration ─────────────────────────────────────────────────────────────

def dur(path: str) -> str:
    try:
        import soundfile as sf
        return f"{sf.info(path).duration:.1f}s"
    except Exception:
        return "?"

# ── Phase 1: Vachana raw (ตรวจ preprocess+อ่านถูก) ───────────────────────────

print("=" * 60)
print("Phase 1: VachanaTTS raw — ตรวจ preprocess + อ่าน")
print("=" * 60)

print("\nโหลด Vachana...")
from pythaitts import TTS, preprocess_text
tts_vachana = TTS(pretrained="vachana")
print("✅ Vachana พร้อม (CPU, 0 VRAM)")

vachana_raws = {}
for name, text in TESTS:
    raw_path = os.path.join(OUT_DIR, f"{name}_vachana_raw.wav")
    preprocessed = preprocess_text(text)
    print(f"\n[{name}] {text[:55]}")
    print(f"  preprocess → {preprocessed[:70]}")
    # copy จาก test ก่อน ถ้ามีอยู่แล้ว (เร็วกว่า re-gen)
    src = os.path.join(IN_DIR, f"{name}_vachana.wav")
    if os.path.exists(src):
        import shutil
        shutil.copy2(src, raw_path)
        print(f"  ✅ copy จาก previous test → {os.path.basename(raw_path)} ({dur(raw_path)})")
    else:
        t = gen_vachana(text, raw_path)
        print(f"  ✅ gen={t:.1f}s → {os.path.basename(raw_path)} ({dur(raw_path)})")
    vachana_raws[name] = raw_path

# ── Phase 2: Vachana → RVC pitch=0 ───────────────────────────────────────────

print("\n" + "=" * 60)
print("Phase 2: Vachana → RVC (pitch=0, Laibaht)")
print("=" * 60)
print("\n⚠️  โหลด RVC subprocess... (~8s ต่อไฟล์)")

vachana_rvcs = {}
for name, text in TESTS:
    raw  = vachana_raws[name]
    out  = os.path.join(OUT_DIR, f"{name}_vachana_rvc_p0.wav")
    print(f"\n[{name}] RVC pitch=0...")
    try:
        t = rvc_convert(raw, out, pitch=0)
        print(f"  ✅ {t:.1f}s → {os.path.basename(out)} ({dur(out)})")
        vachana_rvcs[name] = out
    except Exception as e:
        print(f"  ❌ {e}")

# ── Phase 3: Pitch test (short sentence) ─────────────────────────────────────

print("\n" + "=" * 60)
print(f"Phase 3: Pitch test — \"{TESTS[0][1]}\"")
print(f"  pitches: {PITCH_VALUES}")
print("=" * 60)

raw_pitch = vachana_raws.get(PITCH_TEST_NAME)
if raw_pitch and os.path.exists(raw_pitch):
    for pitch in PITCH_VALUES:
        out = os.path.join(OUT_DIR, f"{PITCH_TEST_NAME}_vachana_rvc_p{pitch:+d}.wav")
        if pitch == 0 and os.path.exists(out):
            print(f"  pitch {pitch:+d}: มีอยู่แล้ว → {os.path.basename(out)}")
            continue
        print(f"\n  pitch {pitch:+d}...")
        try:
            t = rvc_convert(raw_pitch, out, pitch=pitch)
            print(f"  ✅ {t:.1f}s → {os.path.basename(out)} ({dur(out)})")
        except Exception as e:
            print(f"  ❌ {e}")
else:
    print("  ❌ ไม่พบ raw file สำหรับ pitch test")

# ── สรุป ──────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("สรุป — ไฟล์ทั้งหมด")
print("=" * 60)
print(f"\nอยู่ที่: {OUT_DIR}")

print("\n📂 Phase 1 — Vachana raw (ฟังเช็คอ่านถูกไหม):")
for name, _ in TESTS:
    f = os.path.join(OUT_DIR, f"{name}_vachana_raw.wav")
    if os.path.exists(f):
        print(f"  {name}_vachana_raw.wav  ({dur(f)})")

print("\n📂 Phase 2 — Vachana → RVC pitch=0 (เทียบเสียง Laibaht):")
for name, _ in TESTS:
    f = os.path.join(OUT_DIR, f"{name}_vachana_rvc_p0.wav")
    if os.path.exists(f):
        print(f"  {name}_vachana_rvc_p0.wav  ({dur(f)})")

print("\n📂 Phase 3 — Pitch test (short sentence):")
for pitch in PITCH_VALUES:
    f = os.path.join(OUT_DIR, f"{PITCH_TEST_NAME}_vachana_rvc_p{pitch:+d}.wav")
    if os.path.exists(f):
        print(f"  {PITCH_TEST_NAME}_vachana_rvc_p{pitch:+d}.wav  ({dur(f)})")

print("\n📂 เปรียบเทียบกับ F5 (rvc_out/bot/):")
bot_out = os.path.join(BOT_DIR, "rvc_out", "bot")
if os.path.isdir(bot_out):
    recent = sorted(
        [f for f in os.listdir(bot_out) if f.endswith("_rvc.wav")],
        key=lambda x: os.path.getmtime(os.path.join(bot_out, x)),
        reverse=True
    )[:5]
    for f in recent:
        print(f"  rvc_out/bot/{f}  ({dur(os.path.join(bot_out, f))})")
