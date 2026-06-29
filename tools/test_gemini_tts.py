"""
test_gemini_tts.py — ทดสอบ Gemini TTS → RVC Laibaht
เทียบ 4 voices + pitch

ต้องการ: GEMINI_API_KEY env variable หรือ --api-key flag
รัน:     python tools\\test_gemini_tts.py --api-key AIza...
         python tools\\test_gemini_tts.py --skip-rvc   (แค่ Gemini raw)
         python tools\\test_gemini_tts.py --pitch-test  (ทดสอบ pitch ด้วย)
"""
import sys, os, time, wave, json, subprocess, tempfile, argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "gemini_test")
os.makedirs(OUT_DIR, exist_ok=True)

sys.path.insert(0, BOT_DIR)

# ── config ────────────────────────────────────────────────────────────────────────

STYLE = (
    "พูดด้วยน้ำเสียงนุ่มนวล ง่วงนิดๆ น่ารัก แบบบรรณารักษ์สาวอายุยี่สิบปี "
    "ไม่เร่งรีบ สงบเงียบ ใจดี ฟังดูอบอุ่น"
)

TESTS = [
    ("short",   "สวัสดีค่ะ วันนี้ง่วงจังเลยนะคะ"),
    ("numbers", "ราคาน้ำมันแก๊สโซฮอล์ 95 อยู่ที่ 38.85 บาท ดีเซลอยู่ที่ 37.50 บาทค่ะ"),
    ("long",
     "ฉันชอบนั่งอ่านหนังสือในห้องสมุดมากเลยค่ะ เงียบสงบดี แต่บางทีก็มีคนมาคุยด้วย "
     "ซึ่งก็น่ารักดีเหมือนกันนะคะ ถ้าอยากได้ข้อมูลหรือหนังสือดีๆ บอกฉันได้เลยนะคะ"),
]

VOICES = ["Kore", "Leda", "Aoede", "Zephyr"]

PITCH_TEST_VOICE  = "Kore"
PITCH_TEST_TEXT   = "สวัสดีค่ะ วันนี้ง่วงจังเลยนะคะ"
PITCH_TEST_VALUES = [-4, -2, 0, 2, 4]

# ลอง model name ตามลำดับ จนเจอตัวที่ใช้ได้
GEMINI_MODELS = [
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-flash-tts",
    "gemini-3.1-flash-tts-preview",
]

MODEL_DIR   = r"D:\LaibahtMaLaew"
RVC_VENV_PY = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")

# ── audio helpers ────────────────────────────────────────────────────────────────

def pcm_to_wav(pcm_bytes: bytes, path: str, sample_rate: int = 24000) -> None:
    """บันทึก raw PCM 16-bit mono เป็น WAV"""
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


# ── Gemini TTS ────────────────────────────────────────────────────────────────────

def detect_model(client) -> str:
    from google.genai import types
    for m in GEMINI_MODELS:
        try:
            client.models.generate_content(
                model=m,
                contents=types.Content(parts=[types.Part(text="สวัสดี")]),
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                        )
                    ),
                ),
            )
            print(f"  ✅ model: {m}")
            return m
        except Exception as e:
            print(f"  ❌ {m}: {e}")
    raise RuntimeError("ไม่มี Gemini TTS model ที่ใช้ได้ — ตรวจสอบ API key หรือ quota")


_last_gemini_call = 0.0
RATE_LIMIT_INTERVAL = 22  # free tier: 3 req/min → รอ 22s ระหว่าง request

def gemini_tts(client, model: str, text: str, voice: str, out_path: str,
               retries: int = 4) -> float:
    global _last_gemini_call
    from google.genai import types

    # embed style prompt ใน text (system_instruction ไม่รองรับใน TTS model)
    styled_text = f"({STYLE})\n{text}"

    last_err = None
    for attempt in range(retries):
        # rate limit: รอให้ครบ interval ก่อนยิง request ใหม่
        elapsed_since = time.perf_counter() - _last_gemini_call
        if elapsed_since < RATE_LIMIT_INTERVAL:
            wait = RATE_LIMIT_INTERVAL - elapsed_since
            print(f"    rate limit: รอ {wait:.0f}s...")
            time.sleep(wait)

        if attempt > 0:
            print(f"    retry {attempt+1}...")

        try:
            t0 = time.perf_counter()
            _last_gemini_call = t0
            resp = client.models.generate_content(
                model=model,
                contents=types.Content(parts=[types.Part(text=styled_text)]),
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                        )
                    ),
                ),
            )
            elapsed = time.perf_counter() - t0
            part = resp.candidates[0].content.parts[0]
            audio_bytes = part.inline_data.data
            mime        = part.inline_data.mime_type
            sr = 24000
            if "rate=" in mime:
                try:
                    sr = int(mime.split("rate=")[1].split(";")[0].split(",")[0])
                except Exception:
                    pass
            pcm_to_wav(audio_bytes, out_path, sr)
            return elapsed
        except Exception as e:
            last_err = e
            err_str = str(e)
            # extract retryDelay จาก error message ถ้ามี
            retry_wait = RATE_LIMIT_INTERVAL
            if "retryDelay" in err_str or "retry in" in err_str.lower():
                import re as _re
                m = _re.search(r'retry in (\d+)', err_str)
                if m:
                    retry_wait = int(m.group(1)) + 2
            print(f"    ⚠️ attempt {attempt+1}: {type(e).__name__}: {str(e)[:120]}")
            if "429" in err_str:
                print(f"    rate limited — รอ {retry_wait}s...")
                _last_gemini_call = time.perf_counter() + retry_wait - RATE_LIMIT_INTERVAL
                time.sleep(retry_wait)
    raise RuntimeError(f"Gemini TTS failed after {retries} attempts: {last_err}")


# ── RVC ───────────────────────────────────────────────────────────────────────────

def rvc_oneshot(in_wav: str, out_wav: str, pitch: int = 0) -> float:
    """Cold-load RVC สำหรับ pitch test (ช้า ~8s ต่อไฟล์)"""
    if not os.path.isdir(MODEL_DIR):
        raise RuntimeError(f"ไม่พบ MODEL_DIR: {MODEL_DIR}")
    files     = os.listdir(MODEL_DIR)
    pth       = next((f for f in files if f.endswith(".pth")), None)
    idx       = next((f for f in files if f.endswith(".index")), None)
    model_pth = os.path.join(MODEL_DIR, pth) if pth else None
    if not model_pth:
        raise RuntimeError(f"ไม่พบ .pth ใน {MODEL_DIR}")
    model_idx = os.path.join(MODEL_DIR, idx) if idx else ""

    cfg = {
        "model_path": model_pth, "index_path": model_idx,
        "device": "cuda:0", "index_rate": 0.5,
        "protect": 0.33, "f0up_key": pitch,
        "in_wav": in_wav, "out_wav": out_wav,
    }
    tmp_cfg = os.path.join(tempfile.gettempdir(), "gemini_rvc_pitch.json")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    code = f"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rvc_python.infer import RVCInference
with open({repr(tmp_cfg)}, encoding='utf-8') as f:
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
    elapsed = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(f"RVC failed:\n{r.stderr[-500:]}")
    return elapsed


# ── main ─────────────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser()
_cfg_key = ""
try:
    import importlib.util, types as _types
    _spec = importlib.util.spec_from_file_location("config", os.path.join(BOT_DIR, "config.py"))
    _cfg  = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_cfg)
    _cfg_key = getattr(_cfg, "GEMINI_API_KEY", "") or ""
except Exception:
    pass

parser.add_argument("--api-key",    default=os.environ.get("GEMINI_API_KEY", "") or _cfg_key)
parser.add_argument("--skip-rvc",  action="store_true", help="ข้าม RVC ทั้งหมด")
parser.add_argument("--pitch-test", action="store_true", help="ทดสอบ pitch หลัง main")
args = parser.parse_args()

if not args.api_key:
    print("❌ ต้องการ API key — ใช้ --api-key หรือ set GEMINI_API_KEY")
    sys.exit(1)

from google import genai
client = genai.Client(api_key=args.api_key)

print("🔍 ตรวจสอบ Gemini TTS model...")
model = detect_model(client)

# โหลด RVC Worker (warm) สำหรับ main test
rvc_worker = None
if not args.skip_rvc:
    print("\n🎙️ โหลด RVC worker...")
    try:
        from voice import RvcWorker
        rvc_worker = RvcWorker()
        rvc_worker.start()
        print(f"  ✅ RVC worker พร้อม ({rvc_worker.load_time:.1f}s)")
    except Exception as e:
        print(f"  ⚠️ RVC ไม่พร้อม ({e}) — จะข้าม RVC")

# ── Phase 1: voices × sentences ──────────────────────────────────────────────────
print("\n" + "="*60)
print("Phase 1: Gemini TTS — 4 voices × 3 sentences")
print("="*60)

results = []
for voice in VOICES:
    for name, text in TESTS:
        raw_path = os.path.join(OUT_DIR, f"{name}_{voice}_raw.wav")
        rvc_path = os.path.join(OUT_DIR, f"{name}_{voice}_rvc.wav")

        print(f"\n[{voice}] {name} ({len(text)}c): {text[:50]}...")
        t_api = t_rvc = None

        try:
            t_api = gemini_tts(client, model, text, voice, raw_path)
            print(f"  Gemini: {t_api:.1f}s → {os.path.basename(raw_path)}")
        except Exception as e:
            print(f"  ❌ Gemini: {e}")
            continue

        if rvc_worker:
            try:
                t_rvc = rvc_worker.convert(raw_path, rvc_path)
                print(f"  RVC:    {t_rvc:.1f}s → {os.path.basename(rvc_path)}")
            except Exception as e:
                print(f"  ⚠️ RVC: {e}")

        results.append({"voice": voice, "test": name,
                         "t_api": t_api, "t_rvc": t_rvc})

# ── Phase 2: pitch test ──────────────────────────────────────────────────────────
if args.pitch_test:
    print("\n" + "="*60)
    print(f"Phase 2: Pitch test — voice={PITCH_TEST_VOICE}")
    print(f"  text: \"{PITCH_TEST_TEXT}\"")
    print("="*60)

    raw_pitch = os.path.join(OUT_DIR, f"pitch_{PITCH_TEST_VOICE}_raw.wav")
    try:
        gemini_tts(client, model, PITCH_TEST_TEXT, PITCH_TEST_VOICE, raw_pitch)
        print(f"  raw saved → {os.path.basename(raw_pitch)}")
    except Exception as e:
        print(f"  ❌ Gemini raw: {e}")
        raw_pitch = None

    if raw_pitch and os.path.exists(raw_pitch) and not args.skip_rvc:
        for pitch in PITCH_TEST_VALUES:
            out = os.path.join(OUT_DIR, f"pitch_{PITCH_TEST_VOICE}_p{pitch:+d}_rvc.wav")
            print(f"\n  pitch {pitch:+d}...")
            try:
                t = rvc_oneshot(raw_pitch, out, pitch=pitch)
                print(f"    ✅ {t:.1f}s → {os.path.basename(out)}")
            except Exception as e:
                print(f"    ❌ {e}")

# ── cleanup + summary ─────────────────────────────────────────────────────────────
if rvc_worker:
    rvc_worker.stop()

print("\n" + "="*60)
print("สรุป:")
print(f"  {'voice':<8} {'test':<10} {'Gemini(s)':>10} {'RVC(s)':>8} {'total':>8}")
print("  " + "-"*48)
for r in results:
    ta = f"{r['t_api']:.1f}" if r["t_api"] else "-"
    tr = f"{r['t_rvc']:.1f}" if r["t_rvc"] else "-"
    tot = f"{r['t_api'] + (r['t_rvc'] or 0):.1f}" if r["t_api"] else "-"
    print(f"  {r['voice']:<8} {r['test']:<10} {ta:>10} {tr:>8} {tot:>8}")

print(f"\nไฟล์ทั้งหมดอยู่ที่: {OUT_DIR}")
print("\nฟัง (raw ก่อน → rvc หลัง):")
for voice in VOICES:
    for name, _ in TESTS:
        print(f"  {name}_{voice}_raw.wav  →  {name}_{voice}_rvc.wav")

if args.pitch_test:
    print(f"\nPitch test files (Kore voice):")
    for p in PITCH_TEST_VALUES:
        print(f"  pitch_{PITCH_TEST_VOICE}_p{p:+d}_rvc.wav")
