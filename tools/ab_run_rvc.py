"""
ab_run_rvc.py — เอาไฟล์ F5 จาก ab_voice_compare.py ไปผ่าน RVC
ให้ได้ "เสียงรอสเต้จริง" แบบที่บอทใช้ตอนนี้ เพื่อฟังเทียบกับ VoxCPM2

รันด้วย: venv\Scripts\python.exe tools\ab_run_rvc.py
(สคริปต์นี้เรียก rvc_venv ให้เองผ่าน subprocess เหมือนที่ voice.py ทำ)

ออกไฟล์ f5rvc_<ชื่อ>.wav ไว้ข้างๆ f5_<ชื่อ>.wav ในโฟลเดอร์เดียวกัน
"""
import sys, os, json, time, subprocess, glob
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "ab_compare")
RVC_PY = os.path.join(BOT_DIR, "rvc_venv", "Scripts", "python.exe")
STAGE2 = os.path.join(BOT_DIR, "tools", "_rvc_stage2.py")


def main():
    if not os.path.exists(RVC_PY):
        print(f"❌ ไม่พบ rvc_venv: {RVC_PY}")
        return 1

    # โหลด RVC_MODEL_DIR จาก .env แล้วส่งต่อให้ subprocess (rvc_venv ไม่เห็น .env เอง)
    env = os.environ.copy()
    env_path = os.path.join(BOT_DIR, ".env")
    if "RVC_MODEL_DIR" not in env and os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("RVC_MODEL_DIR="):
                    env["RVC_MODEL_DIR"] = line.split("=", 1)[1].strip()
                    break
    print(f"RVC_MODEL_DIR = {env.get('RVC_MODEL_DIR', '(ไม่ได้ตั้ง — จะใช้ default)')}")

    srcs = sorted(glob.glob(os.path.join(OUT_DIR, "f5_*.wav")))
    srcs = [s for s in srcs if not os.path.basename(s).startswith("f5rvc_")]
    if not srcs:
        print(f"❌ ไม่พบไฟล์ f5_*.wav ใน {OUT_DIR} — รัน ab_voice_compare.py ก่อน")
        return 1

    print(f"พบ {len(srcs)} ไฟล์ จะแปลงผ่าน RVC ทีละไฟล์\n")
    results = []
    for src in srcs:
        name = os.path.basename(src)[3:-4]          # f5_<name>.wav → <name>
        dst = os.path.join(OUT_DIR, f"f5rvc_{name}.wav")
        payload = json.dumps({"in_path": src, "out_path": dst, "f0_key": 0},
                             ensure_ascii=False)
        t0 = time.perf_counter()
        proc = subprocess.run([RVC_PY, STAGE2, payload],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)
        elapsed = time.perf_counter() - t0

        conv = None
        for line in (proc.stdout or "").splitlines():
            if line.startswith("RVC_CONV_TIME="):
                conv = float(line.split("=", 1)[1])

        if proc.returncode == 0 and os.path.exists(dst):
            print(f"  {name:<12} → f5rvc_{name}.wav   "
                  f"conv={conv if conv is not None else '?'}s  (รวม load {elapsed:.1f}s)")
            results.append({"tag": name, "conv_time": conv,
                            "total_time": round(elapsed, 2), "ok": True})
        else:
            err = (proc.stderr or "").strip().splitlines()
            print(f"  {name:<12} → ❌ exit={proc.returncode}")
            if err:
                print(f"      {err[-1][:200]}")
            results.append({"tag": name, "ok": False,
                            "error": err[-1][:300] if err else f"exit {proc.returncode}"})

    ok = [r for r in results if r.get("ok")]
    print(f"\nสำเร็จ {len(ok)}/{len(results)}")
    if ok:
        convs = [r["conv_time"] for r in ok if r["conv_time"] is not None]
        if convs:
            print(f"RVC conversion เฉลี่ย {sum(convs)/len(convs):.2f}s/ไฟล์ "
                  f"(ไม่รวม cold load — ของจริง worker warm อยู่แล้ว)")
    print(f"\nไฟล์อยู่ที่: {OUT_DIR}")

    with open(os.path.join(OUT_DIR, "rvc_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
