"""
test_vox_rvc_chain.py — ตอบ 2 คำถามพร้อมกัน:

  1. RVC เป็นตัวทำให้เสียง "แปลกๆ" หรือเปล่า?
     → เอาไฟล์ VoxCPM2 ที่ฟังแล้วโอเค ไปผ่าน RVC แล้วเทียบก่อน/หลัง
       ถ้าผ่านแล้วแปลก = RVC ผิด   ถ้ายังดี = RVC ไม่ผิด

  2. VoxCPM2 → RVC ให้ผลดีกว่า F5 → RVC ไหม?
     → สร้างคู่เทียบด้วยประโยคเดียวกัน

รวมทั้งใส่ pitch 108% (ที่ผู้ใช้เลือกจาก WavePad บน ref12_237s) เป็นตัวเลือกด้วย
  108% = ×1.08 = +1.33 semitone  (12*log2(1.08))
RVC รับ f0_up_key เป็น semitone จำนวนเต็ม จึงเทียบทั้ง 0 / +1 / และปรับ ratio ตรงๆ

รันด้วย: venv\Scripts\python.exe tools\test_vox_rvc_chain.py
"""
import sys, os, json, time, subprocess, math, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "vox_rvc")
SRC_DIR = os.path.join(BOT_DIR, "f5_out", "ref_test")
RVC_PY = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")
STAGE2 = os.path.join(BOT_DIR, "tools", "_rvc_stage2.py")

os.makedirs(OUT_DIR, exist_ok=True)

PITCH_PERCENT = 108.0                       # ที่ผู้ใช้เลือก
PITCH_SEMI = 12 * math.log2(PITCH_PERCENT / 100)   # ≈ +1.33

# ไฟล์ต้นทางที่ผู้ใช้เลือก + ตัวเทียบ
SRC_FILES = {
    "ref12": os.path.join(SRC_DIR, "ref12_237s_ref.wav"),
    "ref16": os.path.join(SRC_DIR, "ref16_328s_ref.wav"),
}


def load_env():
    env = os.environ.copy()
    p = os.path.join(BOT_DIR, ".env")
    if "RVC_MODEL_DIR" not in env and os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.strip().startswith("RVC_MODEL_DIR="):
                env["RVC_MODEL_DIR"] = line.split("=", 1)[1].strip()
                break
    return env


def pitch_shift(src, dst, ratio):
    """เปลี่ยน pitch แบบรักษาความยาว (ใช้ librosa) — เทียบเท่าที่ทำใน WavePad"""
    import librosa, soundfile as sf
    y, sr = librosa.load(src, sr=None, mono=True)
    semi = 12 * math.log2(ratio)
    y2 = librosa.effects.pitch_shift(y=y, sr=sr, n_steps=semi)
    sf.write(dst, y2, sr)
    return dst


def run_rvc(src, dst, f0_key, env):
    payload = json.dumps({"in_path": src, "out_path": dst, "f0_key": f0_key},
                         ensure_ascii=False)
    t0 = time.perf_counter()
    p = subprocess.run([RVC_PY, STAGE2, payload], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    el = time.perf_counter() - t0
    if p.returncode != 0 or not os.path.exists(dst):
        err = (p.stderr or "").strip().splitlines()
        return None, (err[-1][:180] if err else f"exit {p.returncode}")
    return el, None


def main():
    import soundfile as sf

    env = load_env()
    print(f"RVC_MODEL_DIR = {env.get('RVC_MODEL_DIR')}")
    print(f"pitch {PITCH_PERCENT}% = {PITCH_SEMI:+.2f} semitone\n")

    missing = [k for k, v in SRC_FILES.items() if not os.path.exists(v)]
    if missing:
        print(f"❌ ไม่พบไฟล์ต้นทาง: {missing}")
        print(f"   รัน tools/test_ref_candidates.py ก่อน")
        return 1

    results = []
    print("=" * 68)
    print("คำถามที่ 1: RVC ทำให้เสียงแปลกไหม — เทียบ VoxCPM2 ก่อน/หลังผ่าน RVC")
    print("=" * 68)

    for tag, src in SRC_FILES.items():
        info = sf.info(src)
        print(f"\n[{tag}] ต้นทาง {os.path.basename(src)}  "
              f"{info.duration:.2f}s @ {info.samplerate}Hz")

        # ต้นฉบับ (ก๊อปมาไว้ที่เดียวกันเพื่อฟังง่าย)
        import shutil
        plain = os.path.join(OUT_DIR, f"{tag}_0_vox_only.wav")
        shutil.copy(src, plain)
        print(f"    {'vox ล้วน (ต้นฉบับ)':<28} → {os.path.basename(plain)}")

        # ผ่าน RVC f0=0
        dst = os.path.join(OUT_DIR, f"{tag}_1_vox_rvc_f0_0.wav")
        el, err = run_rvc(src, dst, 0, env)
        if err:
            print(f"    {'vox → RVC (f0=0)':<28} → ❌ {err}")
        else:
            print(f"    {'vox → RVC (f0=0)':<28} → {os.path.basename(dst)}  ({el:.1f}s)")
            results.append({"tag": f"{tag}_vox_rvc_f0_0", "ok": True})

        # ผ่าน RVC f0=+1 (ใกล้ 108% ที่สุดในหน่วย semitone จำนวนเต็ม)
        dst = os.path.join(OUT_DIR, f"{tag}_2_vox_rvc_f0_+1.wav")
        el, err = run_rvc(src, dst, 1, env)
        if err:
            print(f"    {'vox → RVC (f0=+1)':<28} → ❌ {err}")
        else:
            print(f"    {'vox → RVC (f0=+1)':<28} → {os.path.basename(dst)}  ({el:.1f}s)")
            results.append({"tag": f"{tag}_vox_rvc_f0_1", "ok": True})

        # pitch 108% ตรงๆ ก่อนเข้า RVC (ตรงกับที่ผู้ใช้ปรับใน WavePad)
        shifted = os.path.join(OUT_DIR, f"{tag}_3_vox_pitch108.wav")
        try:
            pitch_shift(src, shifted, PITCH_PERCENT / 100)
            print(f"    {'vox + pitch 108% (ไม่ผ่าน RVC)':<28} → {os.path.basename(shifted)}")
            dst = os.path.join(OUT_DIR, f"{tag}_4_vox_pitch108_rvc.wav")
            el, err = run_rvc(shifted, dst, 0, env)
            if err:
                print(f"    {'vox + 108% → RVC':<28} → ❌ {err}")
            else:
                print(f"    {'vox + 108% → RVC':<28} → {os.path.basename(dst)}  ({el:.1f}s)")
        except Exception as e:
            print(f"    pitch shift ❌ {type(e).__name__}: {e}")

    # คำถามที่ 2: เทียบกับ F5 → RVC ของเดิม
    print("\n" + "=" * 68)
    print("คำถามที่ 2: เทียบกับ F5 → RVC ของเดิม (ประโยคเดียวกัน)")
    print("=" * 68)
    f5rvc = os.path.join(BOT_DIR, "f5_out", "ab_compare", "f5rvc_style_none.wav")
    if os.path.exists(f5rvc):
        import shutil
        dst = os.path.join(OUT_DIR, "zz_f5_rvc_ของเดิม.wav")
        shutil.copy(f5rvc, dst)
        i = sf.info(dst)
        print(f"  ก๊อปมาให้ฟังคู่กัน: {os.path.basename(dst)}  "
              f"{i.duration:.2f}s @ {i.samplerate}Hz")
    else:
        print(f"  ⚠️ ไม่พบ {f5rvc}")

    print(f"\nไฟล์ทั้งหมด: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
