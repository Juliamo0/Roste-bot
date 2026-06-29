"""
tune_f5_params.py — เทียบ F5 model/speed/steps
รันด้วย: f5_venv\Scripts\python.exe tools\tune_f5_params.py
"""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR  = os.path.join(BOT_DIR, "f5_out", "tuning")
os.makedirs(OUT_DIR, exist_ok=True)

REF_AUDIO = os.path.join(BOT_DIR, "f5_out", "ref_laibaht.wav")
REF_TEXT  = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"

# ── ประโยคทดสอบ (preprocessed แล้ว) ──────────────────────────────────
TESTS = {
    "short":   "สวัสดีค่ะ วันนี้อากาศดีนะคะ",
    "number":  "สวัสดีค่ะ วันนี้อากาศดีนะคะ ราคาน้ำมันสามสิบแปดจุดแปดห้าบาทต่อลิตรค่ะ",
    "medium":  "รอสเต้เข้ามาแล้ว อากาศวันนี้ร้อนมากเลย อย่าลืมดื่มน้ำด้วยนะคะ",
    "or_mid":  "วันนี้อากาศร้อนมากค่ะ อยากแนะนำให้ดื่มน้ำเยอะนะคะ",
}

# ── combinations ─────────────────────────────────────────────────────
COMBOS = [
    # (model, speed, steps, max_chars)
    ("v1", 1.0, 32, 150),
    ("v1", 0.9, 32, 150),
    ("v1", 0.8, 32, 150),
    ("v2", 1.0, 32, 150),
    ("v2", 0.9, 32, 150),
    ("v2", 0.8, 32, 150),
    # speed เดิม แต่ลด steps
    ("v1", 1.0, 16, 150),
    ("v2", 1.0, 16, 150),
]

from f5_tts_th.tts import TTS
import soundfile as sf

results = []

for model_ver in ["v1", "v2"]:
    print(f"\n{'='*60}")
    print(f"โหลด model {model_ver}...")
    t0 = time.perf_counter()
    tts = TTS(model=model_ver)
    load_t = time.perf_counter() - t0
    print(f"  โหลดเสร็จใน {load_t:.1f}s")

    combos_this = [c for c in COMBOS if c[0] == model_ver]

    for model_v, speed, steps, max_chars in combos_this:
        tag = f"{model_v}_sp{int(speed*10):02d}_st{steps}"
        print(f"\n  [{tag}]  speed={speed}  steps={steps}  max_chars={max_chars}")

        for test_name, text in TESTS.items():
            out_path = os.path.join(OUT_DIR, f"{tag}_{test_name}.wav")
            t1 = time.perf_counter()
            try:
                import io, contextlib
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    wav = tts.infer(
                        ref_audio=REF_AUDIO,
                        ref_text=REF_TEXT,
                        gen_text=text,
                        step=steps,
                        speed=speed,
                        max_chars=max_chars,
                    )
                elapsed = time.perf_counter() - t1
                duration = len(wav) / 24000
                sf.write(out_path, wav, 24000)
                ratio = duration / (len(text) * 0.085)
                ok = "✅" if ratio > 0.6 else "⚠️ สั้นเกิน"
                print(f"    {test_name:<8} → {duration:.1f}s audio  gen={elapsed:.1f}s  {ok}")
                results.append({
                    "tag": tag, "test": test_name,
                    "duration": round(duration, 2),
                    "gen_time": round(elapsed, 2),
                    "ratio": round(ratio, 2),
                    "ok": ratio > 0.6,
                    "file": os.path.basename(out_path),
                })
            except Exception as e:
                print(f"    {test_name:<8} → ❌ {e}")
                results.append({"tag": tag, "test": test_name, "ok": False, "error": str(e)})

    del tts  # free VRAM before next model

# ── สรุป ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("สรุปทุก combo (duration ratio — ควร > 0.6):")
print(f"{'='*60}")

COLS = list(TESTS.keys())
tags_done = []
for r in results:
    if r["tag"] not in tags_done:
        tags_done.append(r["tag"])

print(f"  {'tag':<22}", end="")
for c in COLS:
    print(f"  {c:<8}", end="")
print()
print("  " + "-"*60)

for tag in tags_done:
    print(f"  {tag:<22}", end="")
    for c in COLS:
        row = next((r for r in results if r["tag"]==tag and r["test"]==c), None)
        if row is None:
            print(f"  {'?':<8}", end="")
        elif not row.get("ok"):
            print(f"  {'❌':<8}", end="")
        else:
            print(f"  {row['duration']:.1f}s✅  ", end="")
    print()

# save JSON
report_path = os.path.join(OUT_DIR, "tuning_report.json")
with open(report_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"\nไฟล์ .wav อยู่ใน: {OUT_DIR}")
print(f"report: {report_path}")
print(f"\nเปิดฟังเทียบ:")
for tag in tags_done:
    print(f"  {tag}_medium.wav")
