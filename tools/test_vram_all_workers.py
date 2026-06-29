"""
ทดสอบ VRAM เมื่อโหลด F5 + RVC + Qwen พร้อมกัน
เช็คว่า OOM ไหมก่อนใช้ใน bot จริง
"""
import sys, os, time, subprocess, json, urllib.request, threading
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice

BOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEN_TEXT = "รอสเต้เข้ามาแล้วนะคะ อากาศวันนี้ร้อนมากเลย อย่าลืมดื่มน้ำด้วยนะคะ"
OUT_DIR  = os.path.join(BOT_DIR, "f5_out", "vram_test")
os.makedirs(OUT_DIR, exist_ok=True)

def vram():
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used,memory.free,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    used, free, total = [int(x.strip()) for x in r.stdout.strip().split(",")]
    return used, free, total

def vram_str(label):
    used, free, total = vram()
    pct = used / total * 100
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"  [{label:<18}] VRAM: {used:>4} / {total} MiB used  ({pct:.0f}%)  free={free} MiB")
    print(f"  [{' '*18}] [{bar}]")
    return used, free, total

# ══════════════════════════════════════════════════════════
print("=" * 60)
print("VRAM test: F5 + RVC + Qwen")
print("=" * 60)

# baseline
print("\n[0] Baseline (ก่อนโหลดอะไร)")
used0, free0, total = vram_str("baseline")

# ══════════════════════════════════════════════════════════
print("\n[1] โหลด F5 Worker...")
t0 = time.perf_counter()
f5w = voice.F5Worker()
try:
    f5w.start()
    t_f5 = time.perf_counter() - t0
    print(f"  F5 worker พร้อม — {t_f5:.1f}s")
    used_f5, free_f5, _ = vram_str("after F5")
    print(f"  F5 ใช้ VRAM เพิ่ม: +{used_f5 - used0} MiB")
except Exception as e:
    print(f"  ❌ F5 worker เริ่มไม่ได้: {e}")
    f5w = None
    used_f5 = used0

# ══════════════════════════════════════════════════════════
print("\n[2] โหลด RVC Worker...")
t0 = time.perf_counter()
rvcw = voice.RvcWorker()
try:
    rvcw.start()
    t_rvc = time.perf_counter() - t0
    print(f"  RVC worker พร้อม — {t_rvc:.1f}s")
    used_rvc, free_rvc, _ = vram_str("after F5+RVC")
    print(f"  RVC ใช้ VRAM เพิ่ม: +{used_rvc - used_f5} MiB")
    print(f"  F5+RVC รวม: +{used_rvc - used0} MiB")
except Exception as e:
    print(f"  ❌ RVC worker เริ่มไม่ได้: {e}")
    rvcw = None
    used_rvc = used_f5

# ══════════════════════════════════════════════════════════
print("\n[3] Trigger Qwen (Ollama) ให้โหลดใน GPU...")
try:
    payload = json.dumps({
        "model": "qwen2.5:7b-instruct-q4_K_M",
        "prompt": "สวัสดี",
        "stream": False,
        "options": {"num_predict": 5}
    }).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
    t_qwen = time.perf_counter() - t0
    print(f"  Qwen response: {result.get('response','?')!r}  ({t_qwen:.1f}s)")
    used_qwen, free_qwen, _ = vram_str("after F5+RVC+Qwen")
    print(f"  Qwen ใช้ VRAM เพิ่ม: +{used_qwen - used_rvc} MiB")
    print(f"  รวมทั้งหมด: {used_qwen} MiB / {total} MiB ({used_qwen/total*100:.0f}%)")
    if used_qwen > total * 0.90:
        print(f"  ⚠️⚠️  เสี่ยง OOM! ใช้ > 90% VRAM")
    elif used_qwen > total * 0.80:
        print(f"  ⚠️  ตึง VRAM (80-90%) — ระวังตอน inference")
    else:
        print(f"  ✅  VRAM เหลือพอ ({free_qwen} MiB free)")
except Exception as e:
    print(f"  ❌ Qwen error: {e}")
    used_qwen = used_rvc

# ══════════════════════════════════════════════════════════
print("\n[4] ทดสอบ F5 → RVC generation (ขณะ Qwen โหลดอยู่)...")
if f5w and f5w.alive and rvcw and rvcw.alive:
    try:
        from f5_preprocess import preprocess_for_f5
        preprocessed, warns = preprocess_for_f5(GEN_TEXT)
        print(f"  gen_text: {preprocessed!r}")
        f5_wav  = os.path.join(OUT_DIR, "test_f5.wav")
        rvc_wav = os.path.join(OUT_DIR, "test_rvc.wav")

        t0 = time.perf_counter()
        dur = f5w.generate(
            ref_audio=voice.F5_REF_AUDIO,
            ref_text=voice.F5_REF_TEXT,
            gen_text=preprocessed,
            out_path=f5_wav,
            speed=voice.F5_SPEED,
            steps=voice.F5_STEPS,
        )
        t_gen = time.perf_counter() - t0
        print(f"  F5 เสร็จ: {t_gen:.1f}s  audio={dur:.1f}s")

        used_peak, _, _ = vram_str("peak F5 inference")

        t0 = time.perf_counter()
        rvcw.convert(f5_wav, rvc_wav)
        t_rvc2 = time.perf_counter() - t0
        print(f"  RVC เสร็จ: {t_rvc2:.1f}s")
        print(f"  ✅  pipeline สำเร็จ → {rvc_wav}")
        print(f"  เวลารวม F5+RVC: {t_gen+t_rvc2:.1f}s")

        used_after, free_after, _ = vram_str("after inference")
    except Exception as e:
        import traceback
        print(f"  ❌ generation error: {e}")
        traceback.print_exc()
else:
    print("  ข้าม (worker ไม่พร้อม)")

# ══════════════════════════════════════════════════════════
print("\n[5] Cleanup workers...")
if rvcw:
    rvcw.stop()
    print("  RVC stopped")
if f5w:
    f5w.stop()
    print("  F5 stopped")

print("\n" + "=" * 60)
print("สรุป VRAM:")
print(f"  GPU: NVIDIA RTX 3050 Ti  {total} MiB total")
print(f"  Baseline:        {used0:>4} MiB")
if f5w is not None:
    print(f"  + F5 model:    → {used_f5:>4} MiB  (+{used_f5-used0})")
if rvcw is not None:
    print(f"  + RVC model:   → {used_rvc:>4} MiB  (+{used_rvc-used_f5})")
print(f"  + Qwen model:  → {used_qwen:>4} MiB  (+{used_qwen-used_rvc})")
print(f"  VRAM หลังโหลดครบ: {used_qwen} / {total} MiB")
remaining = total - used_qwen
print(f"  เหลือ buffer:    {remaining} MiB")
if remaining < 200:
    print("  ⚠️⚠️  buffer น้อยมาก — เสี่ยง OOM ตอน inference")
elif remaining < 400:
    print("  ⚠️  buffer ตึง — อาจ OOM ถ้า VRAM spike ตอน inference")
else:
    print("  ✅  buffer เพียงพอ")
print("=" * 60)
