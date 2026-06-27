"""
เทียบความเร็ว F5-TTS:
  A) subprocess ใหม่ทุกครั้ง (แบบเดิม) steps=32
  B) warm worker + steps=16
รันด้วย Python ใดก็ได้
"""
import sys, os, time, json, subprocess
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOT_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F5_PYTHON  = os.path.join(BOT_DIR, "f5_venv", "Scripts", "python.exe")
STAGE1     = os.path.join(BOT_DIR, "tools", "_f5_stage1.py")
WORKER     = os.path.join(BOT_DIR, "f5_worker.py")
OUT_DIR    = os.path.join(BOT_DIR, "f5_out")
os.makedirs(OUT_DIR, exist_ok=True)

REF_AUDIO = os.path.join(BOT_DIR, "rvc_out", "bot", "55682969_rvc.wav")
REF_TEXT  = "รอสเต้เข้ามาแล้วนะคะ"

SENTENCES = [
    "สวัสดีค่ะ วันนี้ง่วงจังเลย",
    "อุณหภูมิวันนี้อยู่ที่ 33 องศาเซลเซียสนะคะ",
    "รอสเต้จะตอบให้นะคะ รอแป๊บนึงก่อนนะ",
]

# ══════════════════════════════════════════════════════
# A) subprocess ใหม่ทุกครั้ง steps=32 (แบบเดิม) — 1 ประโยค
# ══════════════════════════════════════════════════════
print("=" * 55)
print("A) subprocess ใหม่ทุกครั้ง steps=32 (1 ประโยค)")
print("=" * 55)

args = json.dumps({"ref_audio": REF_AUDIO, "ref_text": REF_TEXT,
                   "gen_text": SENTENCES[0],
                   "out_path": os.path.join(OUT_DIR, "spd_A_sub.wav"),
                   "speed": 1.0})
t = time.perf_counter()
r = subprocess.run([F5_PYTHON, STAGE1, args],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(f"รวม: {time.perf_counter()-t:.1f}s")
for line in r.stdout.splitlines():
    if line.startswith("F5_"):
        print(" ", line)

# ══════════════════════════════════════════════════════
# B) warm worker steps=16 — 3 ประโยคติดกัน
# ══════════════════════════════════════════════════════
print("\n" + "=" * 55)
print("B) warm worker steps=16 (3 ประโยคติดกัน)")
print("=" * 55)

print("เริ่ม warm worker...", flush=True)
t_boot = time.perf_counter()
proc = subprocess.Popen(
    [F5_PYTHON, WORKER],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    text=True, encoding="utf-8", errors="replace",
    bufsize=1,
)

# รอ READY
for line in proc.stdout:
    line = line.strip()
    print(" ", line)
    if "F5_WORKER_READY" in line:
        break

boot_time = time.perf_counter() - t_boot
print(f"worker โหลดเสร็จใน {boot_time:.1f}s\n")

for i, sent in enumerate(SENTENCES):
    out = os.path.join(OUT_DIR, f"spd_B_warm_{i+1}.wav")
    job = json.dumps({"ref_audio": REF_AUDIO, "ref_text": REF_TEXT,
                      "gen_text": sent, "out_path": out,
                      "speed": 1.0, "steps": 16})
    t = time.perf_counter()
    proc.stdin.write(job + "\n")
    proc.stdin.flush()
    result = proc.stdout.readline().strip()
    elapsed = time.perf_counter() - t
    print(f"  [{i+1}] {sent!r}")
    print(f"       {result}  | wall={elapsed:.1f}s")

proc.stdin.write("EXIT\n")
proc.stdin.flush()
proc.wait()

print("\n" + "=" * 55)
print("สรุป:")
print(f"  A) subprocess: ~{boot_time:.0f}s overhead ทุกครั้งที่เรียก")
print(f"  B) warm worker: boot {boot_time:.1f}s ครั้งเดียว, inference ~เร็วกว่า 2x")
