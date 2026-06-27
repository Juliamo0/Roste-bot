"""
1) ตัด ref_laibaht.wav จากไฟล์ต้นทาง (191.7s → 198.5s ≈ 6.8 วิ)
2) ทดสอบ F5 → RVC ด้วย ref ใหม่
"""
import sys, os, time, json, subprocess
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F5_PYTHON  = os.path.join(BOT_DIR, "f5_venv",  "Scripts", "python.exe")
RVC_PYTHON = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")
STAGE1     = os.path.join(BOT_DIR, "tools", "_f5_stage1.py")
STAGE2     = os.path.join(BOT_DIR, "tools", "_rvc_stage2.py")
OUT_DIR    = os.path.join(BOT_DIR, "f5_out")
os.makedirs(OUT_DIR, exist_ok=True)

SRC_AUDIO  = r"C:\Users\julia\OneDrive\Desktop\Lai_ref.mp3"
REF_OUT    = os.path.join(OUT_DIR, "ref_laibaht.wav")

# ── ตั้งค่า ref ──────────────────────────────────────────────
CUT_START  = 191.7
CUT_END    = 198.5   # 6.8 วิ — จบที่ "ไม่ได้กลิ่นไง"
REF_TEXT   = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"

GEN_TEXT   = "อากาศวันนี้ร้อนมากเลยค่ะ อย่าลืมดื่มน้ำด้วย แล้วก็พักผ่อนให้เพียงพอด้วยนะคะ"
SPEED      = 1.0
STEPS      = 32

# ════════════════════════════════════════════════════════════
# Step 1: ตัด ref_laibaht.wav
# ════════════════════════════════════════════════════════════
print("=" * 55)
print(f"Step 1: ตัด ref_laibaht.wav ({CUT_END-CUT_START:.1f} วิ)")
print(f"  {CUT_START}s → {CUT_END}s")
print(f"  ref_text: {REF_TEXT!r}")
print("=" * 55)

r = subprocess.run([
    "ffmpeg", "-y", "-loglevel", "error",
    "-i", SRC_AUDIO,
    "-ss", str(CUT_START), "-to", str(CUT_END),
    "-ar", "24000", "-ac", "1",   # 24kHz mono ตาม F5 spec
    REF_OUT
], capture_output=True, text=True)

if r.returncode != 0:
    print(f"ffmpeg error:\n{r.stderr}")
    sys.exit(1)

size_kb = os.path.getsize(REF_OUT) / 1024
print(f"  บันทึก: {REF_OUT}  ({size_kb:.0f} KB)")

# ════════════════════════════════════════════════════════════
# Step 2: F5-TTS
# ════════════════════════════════════════════════════════════
F5_OUT  = os.path.join(OUT_DIR, "newref6_f5_raw.wav")
RVC_OUT = os.path.join(OUT_DIR, "newref6_f5_rvc.wav")

print(f"\n{'='*55}")
print(f"Step 2: F5-TTS")
print(f"  gen_text : {GEN_TEXT!r}")
print(f"  speed    : {SPEED}  steps: {STEPS}")
print(f"{'='*55}")

s1_args = json.dumps({
    "ref_audio": REF_OUT,
    "ref_text":  REF_TEXT,
    "gen_text":  GEN_TEXT,
    "out_path":  F5_OUT,
    "speed":     SPEED,
})
# override steps ใน _f5_stage1 ปกติ hardcode steps=32 → ส่ง via env แทน
# แก้ชั่วคราว: สร้าง stage1 แบบ steps=16
STAGE1_16 = os.path.join(BOT_DIR, "tools", "_f5_stage1_16.py")
if not os.path.exists(STAGE1_16):
    src = open(STAGE1, encoding="utf-8").read().replace("step=32,", "step=16,")
    open(STAGE1_16, "w", encoding="utf-8").write(src)

t = time.perf_counter()
r1 = subprocess.run([F5_PYTHON, STAGE1_16, s1_args],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
s1_time = time.perf_counter() - t

if r1.returncode != 0:
    print(f"F5 error:\n{r1.stderr[-600:]}")
    sys.exit(1)

kv = {}
for line in r1.stdout.splitlines():
    if "=" in line and line.split("=")[0].isupper():
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()

print(f"  F5 เสร็จใน {kv.get('F5_GEN_TIME','?')}s  |  เสียง {kv.get('F5_DURATION','?')}s  |  VRAM {kv.get('F5_VRAM_PEAK','?')} MiB")
print(f"  wall clock: {s1_time:.1f}s  (รวม load model)")

# ════════════════════════════════════════════════════════════
# Step 3: RVC Laibaht
# ════════════════════════════════════════════════════════════
print(f"\n{'='*55}")
print("Step 3: RVC Laibaht")
print(f"{'='*55}")

s2_args = json.dumps({"in_path": F5_OUT, "out_path": RVC_OUT, "f0_key": 0})
t = time.perf_counter()
r2 = subprocess.run([RVC_PYTHON, STAGE2, s2_args],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace")
s2_time = time.perf_counter() - t

if r2.returncode != 0:
    print(f"RVC error:\n{r2.stderr[-600:]}")
    sys.exit(1)

kv2 = {}
for line in r2.stdout.splitlines():
    if "=" in line and line.split("=")[0].isupper():
        k, v = line.split("=", 1)
        kv2[k.strip()] = v.strip()

print(f"  RVC เสร็จใน {kv2.get('RVC_CONV_TIME','?')}s")
print(f"  wall clock: {s2_time:.1f}s")

print(f"\n{'='*55}")
print("ผลลัพธ์:")
print(f"  ref_audio    → {REF_OUT}")
print(f"  F5 raw       → {F5_OUT}")
print(f"  F5 + RVC     → {RVC_OUT}")
print(f"  รวมทั้งหมด    {s1_time+s2_time:.1f}s")
print(f"{'='*55}")
print("เปิดฟังไฟล์ newref_f5_rvc.wav ใน f5_out/")
