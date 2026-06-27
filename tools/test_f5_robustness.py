"""
ทดสอบความทนทาน F5-TTS กับข้อความจริงจาก Qwen
เปรียบเทียบ: raw text vs preprocessed text
"""
import sys, os, time, json, subprocess, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F5_PY     = os.path.join(BOT_DIR, "f5_venv", "Scripts", "python.exe")
RVC_PY    = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")
STAGE1    = os.path.join(BOT_DIR, "tools", "_f5_stage1_16.py")
STAGE2    = os.path.join(BOT_DIR, "tools", "_rvc_stage2.py")
OUT_DIR   = os.path.join(BOT_DIR, "f5_out", "robustness")
os.makedirs(OUT_DIR, exist_ok=True)

REF_AUDIO = os.path.join(BOT_DIR, "f5_out", "ref_laibaht.wav")
REF_TEXT  = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"

# ════════════════════════════════════════════════════════
# ตัวอย่างคำตอบจริงของรอสเต้ จาก Qwen
# ════════════════════════════════════════════════════════
TESTS = [
    {
        "id": "01_greet",
        "label": "ทักทาย",
        "raw": "สวัสดีค่ะ รอสเต้ยินดีให้บริการนะคะ มีอะไรให้ช่วยไหมคะ",
    },
    {
        "id": "02_number_oil",
        "label": "ตัวเลข (ราคาน้ำมัน)",
        "raw": "ราคาน้ำมันวันนี้ เบนซิน 95 อยู่ที่ 47.38 บาทต่อลิตรค่ะ ดีเซลอยู่ที่ 29.94 บาทต่อลิตรนะคะ",
    },
    {
        "id": "03_number_temp",
        "label": "ตัวเลข (อุณหภูมิ)",
        "raw": "อุณหภูมิวันนี้อยู่ที่ 34 องศาเซลเซียสค่ะ อากาศร้อนมากเลยนะคะ ระวังด้วยนะคะ",
    },
    {
        "id": "04_long",
        "label": "คำตอบยาว",
        "raw": "เรื่องนี้มีหลายปัจจัยเลยค่ะ อย่างแรกคือเรื่องของเวลา อย่างที่สองคือเรื่องของค่าใช้จ่าย แล้วก็อย่างสุดท้ายคือเรื่องของความสะดวกด้วยนะคะ รอสเต้แนะนำให้ลองพิจารณาทั้งสามข้อก่อนตัดสินใจค่ะ",
    },
    {
        "id": "05_or_mid",
        "label": "อ+สระยาว กลางประโยค",
        "raw": "วันนี้อากาศร้อนมากเลยค่ะ อยากแนะนำให้ดื่มน้ำเยอะด้วยนะคะ อย่าลืมทาครีมกันแดดด้วยนะ",
    },
    {
        "id": "06_mai_yamok_naka",
        "label": "ๆ และ นะคะ ซ้ำ",
        "raw": "ดีมากเลยค่ะ รอสเต้แนะนำให้ลองดูนะคะ มันน่าสนใจมากๆ เลยนะคะ และก็ง่ายๆ ด้วยนะคะ",
    },
    {
        "id": "07_mixed",
        "label": "ผสม (ตัวเลข + ๆ + อ กลางประโยค)",
        "raw": "อุณหภูมิพรุ่งนี้จะอยู่ที่ 36 องศาค่ะ อากาศจะร้อนมากๆ เลยนะคะ อย่าลืมพกน้ำด้วยนะคะ",
    },
]

# ════════════════════════════════════════════════════════
# Preprocessing function
# ════════════════════════════════════════════════════════
def preprocess(text: str) -> str:
    # 1) ๆ → repeat previous word
    def expand_mai_yamok(t):
        return re.sub(r'(\S+)ๆ', lambda m: m.group(1) + m.group(1), t)

    # 2) ลด นะคะ/นะ ซ้ำ — เก็บแค่ครั้งสุดท้าย
    def reduce_naka(t):
        # แทนทุก "นะคะ" ที่ไม่ใช่ตัวสุดท้ายด้วย ""
        parts = re.split(r'(นะคะ)', t)
        last = len(parts) - 1 - next(
            i for i, p in enumerate(reversed(parts)) if p == "นะคะ"
        ) if "นะคะ" in parts else -1
        result = []
        for i, p in enumerate(parts):
            if p == "นะคะ" and i != last:
                result.append("")
            else:
                result.append(p)
        return "".join(result).strip()

    # 3) คำขึ้นต้นด้วย อ+สระยาว หลัง space → เลื่อนไปต้นประโยคย่อย
    #    แก้แบบ conservative: เพิ่ม zero-width space ก่อนคำ (ให้ F5 boundary ใหม่)
    #    ไม่ reorder — แค่ log ว่าเจอ
    or_pattern = re.compile(r'(?<= )(อา|อี|อู|เอ|โอ|อย|อว)\w+')
    or_found = or_pattern.findall(text)

    t = expand_mai_yamok(text)
    t = reduce_naka(t)
    return t, or_found

# ════════════════════════════════════════════════════════
# รัน F5 (ไม่ RVC — เพื่อความเร็ว) แล้วดู duration
# ════════════════════════════════════════════════════════
def run_f5(gen_text, out_path, label_short):
    args = json.dumps({
        "ref_audio": REF_AUDIO,
        "ref_text":  REF_TEXT,
        "gen_text":  gen_text,
        "out_path":  out_path,
        "speed":     1.0,
    })
    t0 = time.perf_counter()
    r = subprocess.run([F5_PY, STAGE1, args],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - t0
    if r.returncode != 0:
        return None, elapsed, r.stderr[-300:]
    kv = {}
    for line in r.stdout.splitlines():
        if "=" in line and line.split("=")[0].isupper():
            k, v = line.split("=", 1)
            kv[k.strip()] = v.strip()
    dur = float(kv.get("F5_DURATION", 0))
    return dur, elapsed, None

# ════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════
print("=" * 65)
print("F5-TTS Robustness Test  (F5 only, no RVC — เพื่อความเร็ว)")
print("=" * 65)

REPORT = []

for test in TESTS:
    tid   = test["id"]
    label = test["label"]
    raw   = test["raw"]
    pre, or_found = preprocess(raw)
    changed = pre != raw

    print(f"\n[{tid}] {label}")
    print(f"  RAW : {raw}")
    if changed:
        print(f"  PRE : {pre}")
    if or_found:
        print(f"  ⚠️  อ+สระยาว กลางประโยค: {or_found}")

    # --- RAW ---
    out_raw = os.path.join(OUT_DIR, f"{tid}_raw.wav")
    dur_raw, t_raw, err_raw = run_f5(raw, out_raw, "raw")
    if err_raw:
        print(f"  RAW  → ❌ ERROR: {err_raw}")
        row_raw = f"[{tid}] RAW  ❌ ERROR"
    else:
        chars = len(raw)
        expected = chars * 0.12  # rough: ~0.12s/char Thai
        ratio = dur_raw / expected if expected else 0
        ok = "✅" if ratio > 0.6 else "⚠️ สั้นกว่าที่ควร (skip?)"
        print(f"  RAW  → {dur_raw:.1f}s  (คาด ~{expected:.1f}s)  {ok}  gen={t_raw:.1f}s")
        row_raw = f"[{tid}] RAW  {dur_raw:.1f}s/{expected:.1f}s  {'OK' if ratio>0.6 else 'SHORT'}"

    # --- PREPROCESSED (ถ้าเปลี่ยน) ---
    row_pre = None
    if changed:
        out_pre = os.path.join(OUT_DIR, f"{tid}_pre.wav")
        dur_pre, t_pre, err_pre = run_f5(pre, out_pre, "pre")
        if err_pre:
            print(f"  PRE  → ❌ ERROR: {err_pre}")
            row_pre = f"[{tid}] PRE  ❌ ERROR"
        else:
            chars2 = len(pre)
            expected2 = chars2 * 0.12
            ratio2 = dur_pre / expected2 if expected2 else 0
            ok2 = "✅" if ratio2 > 0.6 else "⚠️ สั้นกว่าที่ควร"
            print(f"  PRE  → {dur_pre:.1f}s  (คาด ~{expected2:.1f}s)  {ok2}  gen={t_pre:.1f}s")
            row_pre = f"[{tid}] PRE  {dur_pre:.1f}s/{expected2:.1f}s  {'OK' if ratio2>0.6 else 'SHORT'}"

    REPORT.append(row_raw)
    if row_pre:
        REPORT.append(row_pre)

# ════════════════════════════════════════════════════════
# สรุป
# ════════════════════════════════════════════════════════
print(f"\n{'='*65}")
print("สรุป (duration ratio < 0.6 = น่าจะมี skip):")
print(f"{'='*65}")
for r in REPORT:
    print(" ", r)

out_log = os.path.join(OUT_DIR, "robustness_report.txt")
with open(out_log, "w", encoding="utf-8") as f:
    for r in REPORT:
        f.write(r + "\n")
print(f"\nบันทึกที่: {out_log}")
print("ไฟล์ .wav อยู่ใน:", OUT_DIR)
print("เปิดฟัง *_raw.wav เทียบกับ *_pre.wav")
