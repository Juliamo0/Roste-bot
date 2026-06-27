"""
ทดสอบ F5 + preprocessing กับข้อความจริง
"""
import sys, os, time, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
from f5_preprocess import preprocess_for_f5

BOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F5_PY    = os.path.join(BOT_DIR, "f5_venv", "Scripts", "python.exe")
STAGE1   = os.path.join(BOT_DIR, "tools", "_f5_stage1_16.py")
OUT_DIR  = os.path.join(BOT_DIR, "f5_out", "preprocess_test")
os.makedirs(OUT_DIR, exist_ok=True)

REF_AUDIO = os.path.join(BOT_DIR, "f5_out", "ref_laibaht.wav")
REF_TEXT  = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"

TESTS = [
    {"id": "01", "label": "ราคาน้ำมัน",  "raw": "แก๊สโซฮอล์ 95 ราคา 38.85 บาทต่อลิตรค่ะ ดีเซลอยู่ที่ 29.94 บาทต่อลิตรนะคะ"},
    {"id": "02", "label": "อุณหภูมิ",    "raw": "อุณหภูมิวันนี้อยู่ที่ 33 องศาเซลเซียสค่ะ ร้อนมากเลยนะคะ"},
    {"id": "03", "label": "มี ๆ",        "raw": "ดีมากเลยค่ะ รอสเต้แนะนำให้ลองดูนะคะ มันน่าสนใจมากๆ เลยนะคะ และก็ง่ายๆ ด้วยนะคะ"},
    {"id": "04", "label": "นะคะ ซ้ำ",   "raw": "อย่าลืมดื่มน้ำด้วยนะคะ แล้วก็นอนหลับพักผ่อนด้วยนะคะ รอสเต้เป็นห่วงนะคะ"},
]

def run_f5(gen_text, out_path):
    args = json.dumps({"ref_audio": REF_AUDIO, "ref_text": REF_TEXT,
                        "gen_text": gen_text, "out_path": out_path, "speed": 1.0})
    t0 = time.perf_counter()
    r = subprocess.run([F5_PY, STAGE1, args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - t0
    if r.returncode != 0:
        return None, elapsed
    for line in r.stdout.splitlines():
        if line.startswith("F5_DURATION="):
            return float(line.split("=")[1]), elapsed
    return None, elapsed

print("=" * 60)
print("F5 + Preprocessing Test")
print("=" * 60)

for test in TESTS:
    tid, label, raw = test["id"], test["label"], test["raw"]
    pre, warns = preprocess_for_f5(raw)

    print(f"\n[{tid}] {label}")
    print(f"  RAW : {raw}")
    print(f"  PRE : {pre}")
    for w in warns:
        print(f"        {w}")

    # RAW
    dur_raw, t_raw = run_f5(raw, os.path.join(OUT_DIR, f"{tid}_raw.wav"))
    print(f"  RAW  → {dur_raw:.1f}s  (gen {t_raw:.0f}s)" if dur_raw else "  RAW  → ❌ ERROR")

    # PRE
    dur_pre, t_pre = run_f5(pre, os.path.join(OUT_DIR, f"{tid}_pre.wav"))
    print(f"  PRE  → {dur_pre:.1f}s  (gen {t_pre:.0f}s)" if dur_pre else "  PRE  → ❌ ERROR")

print(f"\nไฟล์อยู่ใน: {OUT_DIR}")
print("เปิดฟัง *_raw.wav vs *_pre.wav")
