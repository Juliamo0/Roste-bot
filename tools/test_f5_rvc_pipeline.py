"""
ทดสอบ F5-TTS → RVC Laibaht pipeline
รันด้วย Python ใดก็ได้ (orchestrator ไม่ต้องการ torch)
  python tools/test_f5_rvc_pipeline.py
"""
import sys, time, os, json, subprocess, shutil
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F5_PYTHON  = os.path.join(BOT_DIR, "f5_venv",  "Scripts", "python.exe")
RVC_PYTHON = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")
STAGE1     = os.path.join(BOT_DIR, "tools", "_f5_stage1.py")
STAGE2     = os.path.join(BOT_DIR, "tools", "_rvc_stage2.py")
OUT_DIR    = os.path.join(BOT_DIR, "f5_out")
os.makedirs(OUT_DIR, exist_ok=True)

# ─── ตั้งค่าการทดสอบ ────────────────────────────────────────────────
TESTS = [
    {
        "label": "สวัสดี (ง่วง)",
        "gen_text": "สวัสดีค่ะ วันนี้ง่วงจังเลย",
        "speed": 0.9,
        "f0_key": 0,
    },
    {
        "label": "ตัวเลข/ข้อมูล",
        "gen_text": "อุณหภูมิวันนี้อยู่ที่ 33 องศาเซลเซียสนะคะ แนะนำให้ดื่มน้ำเยอะๆ ด้วยนะ",
        "speed": 0.9,
        "f0_key": 0,
    },
]

# ref audio = เสียง Laibaht ที่มีอยู่แล้ว (F5 เอาไปเป็น style ref)
REF_AUDIO = os.path.join(BOT_DIR, "rvc_out", "bot", "350cab19_rvc.wav")
REF_TEXT  = "รอสเต้จะร้องเพลง Monster ให้ฟังนะคะ"

# เก็บเสียง edge-tts→RVC เดิมไว้เทียบ
EDGETTS_REF = os.path.join(BOT_DIR, "rvc_out", "bot", "c3ed201a_rvc.wav")

# ─── helper: parse key=value lines from subprocess stdout ───────────
def parse_kv(text):
    result = {}
    for line in text.splitlines():
        if "=" in line and line.split("=")[0].isupper():
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
    return result

# ─── รันแต่ละ test ───────────────────────────────────────────────────
print("=" * 60)
print("F5-TTS → RVC Laibaht Pipeline Test")
print("=" * 60)

for i, cfg in enumerate(TESTS):
    label   = cfg["label"]
    slug    = f"test{i+1}"
    f5_out  = os.path.join(OUT_DIR, f"{slug}_f5_raw.wav")
    rvc_out = os.path.join(OUT_DIR, f"{slug}_f5_rvc_laibaht.wav")

    print(f"\n[{i+1}/{len(TESTS)}] {label}")
    print(f"  gen_text : {cfg['gen_text']!r}")
    print(f"  speed    : {cfg['speed']} | f0_key : {cfg['f0_key']}")

    # ── Stage 1: F5-TTS ──────────────────────────────────────────────
    s1_args = json.dumps({
        "ref_audio": REF_AUDIO,
        "ref_text":  REF_TEXT,
        "gen_text":  cfg["gen_text"],
        "out_path":  f5_out,
        "speed":     cfg["speed"],
    })
    print("  [Stage 1] F5-TTS...", flush=True)
    t_s1 = time.perf_counter()
    r1 = subprocess.run([F5_PYTHON, STAGE1, s1_args],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    s1_elapsed = time.perf_counter() - t_s1
    kv1 = parse_kv(r1.stdout)

    if r1.returncode != 0:
        print(f"  ❌ Stage 1 error:\n{r1.stderr[-800:]}")
        continue

    print(f"  ✅ F5 เสร็จใน {kv1.get('F5_GEN_TIME','?')}s "
          f"| เสียง {kv1.get('F5_DURATION','?')}s "
          f"| VRAM peak {kv1.get('F5_VRAM_PEAK','?')} MiB")

    # ── Stage 2: RVC ─────────────────────────────────────────────────
    s2_args = json.dumps({
        "in_path":  f5_out,
        "out_path": rvc_out,
        "f0_key":   cfg["f0_key"],
    })
    print("  [Stage 2] RVC Laibaht...", flush=True)
    t_s2 = time.perf_counter()
    r2 = subprocess.run([RVC_PYTHON, STAGE2, s2_args],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
    s2_elapsed = time.perf_counter() - t_s2
    kv2 = parse_kv(r2.stdout)

    if r2.returncode != 0:
        print(f"  ❌ Stage 2 error:\n{r2.stderr[-800:]}")
        continue

    print(f"  ✅ RVC เสร็จใน {kv2.get('RVC_CONV_TIME','?')}s")

    total = s1_elapsed + s2_elapsed
    print(f"  ⏱  รวม: {total:.1f}s")
    print(f"  📁 f5_raw       → {f5_out}")
    print(f"  📁 f5_rvc_laibaht → {rvc_out}")

# ── คัดลอกเสียง edge-tts เดิมมาเทียบ ──────────────────────────────
if os.path.exists(EDGETTS_REF):
    dst = os.path.join(OUT_DIR, "compare_edgetts_rvc.wav")
    shutil.copy2(EDGETTS_REF, dst)
    print(f"\n📁 edge-tts→RVC เดิม → {dst}")

print("\n" + "=" * 60)
print("เปิดไฟล์ใน f5_out/ เพื่อฟังเปรียบเทียบ")
print("  test1_f5_raw.wav          = F5 ก่อน RVC")
print("  test1_f5_rvc_laibaht.wav  = F5 → RVC Laibaht")
print("  compare_edgetts_rvc.wav   = edge-tts → RVC เดิม")
