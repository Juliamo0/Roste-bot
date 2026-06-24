"""
ทดสอบ voice pipeline แบบ standalone — ไม่แตะ bot.py/persona.py

วิธีใช้:
  python tools/test_voice_pipeline.py           → ทดสอบ warm worker (แนะนำ)
  python tools/test_voice_pipeline.py --cold    → ทดสอบ oneshot cold (ช้า แต่เช็ค fallback)

ผลลัพธ์: rvc_out/pipeline_test/
"""

import os
import sys
import time
import argparse
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# เพิ่ม project root เข้า sys.path เพื่อ import voice.py
_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.join(_TOOLS_DIR, "..")
sys.path.insert(0, _ROOT)

from voice import (
    RvcWorker,
    _edge_tts,
    _adjust,
    strip_emoji,
    text_to_roste_voice,
    _OUT_DIR,
)

# ── ประโยคทดสอบ ────────────────────────────────────────────────────────────────
TEST_SENTENCES = [
    ("ทักทาย",   "สวัสดีค่ะ วันนี้มีอะไรให้ช่วยไหมคะ"),
    ("ตัวเลข",   "ราคาน้ำมันดีเซลวันนี้อยู่ที่ 33.34 บาทต่อลิตรค่ะ"),
    ("ยาว",      "ขณะนี้สภาพอากาศในกรุงเทพมีอุณหภูมิ 34 องศาเซลเซียส ความชื้นสัมพัทธ์ 72 เปอร์เซ็นต์ และมีโอกาสฝนตก 30 เปอร์เซ็นต์ค่ะ"),
    ("ลาก่อน",   "ราตรีสวัสดิ์ค่ะ ดูแลตัวเองด้วยนะคะ"),
]

OUT_DIR = os.path.join(_ROOT, "rvc_out", "pipeline_test")


def _run_sentence(label: str, text: str, worker: RvcWorker | None, cold: bool) -> None:
    print(f"\n{'─'*56}")
    print(f"[{label}]  {text}")

    clean = strip_emoji(text)
    tmp_dir = tempfile.mkdtemp(prefix="voice_test_")
    raw_wav = os.path.join(tmp_dir, f"{label}_raw.wav")
    adj_wav = os.path.join(tmp_dir, f"{label}_adj.wav")
    rvc_wav = os.path.join(OUT_DIR, f"{label}_rvc.wav")
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1. edge-tts
    t0 = time.perf_counter()
    try:
        _edge_tts(clean, raw_wav)
        t_tts = time.perf_counter() - t0
        print(f"  edge-tts  : {t_tts:.2f}s  →  {os.path.basename(raw_wav)}")
    except Exception as exc:
        print(f"  edge-tts  : FAIL — {exc}")
        return

    # 2. ffmpeg adjust
    t0 = time.perf_counter()
    try:
        _adjust(raw_wav, adj_wav)
        t_adj = time.perf_counter() - t0
        print(f"  adjust    : {t_adj:.2f}s  →  {os.path.basename(adj_wav)}")
    except Exception as exc:
        print(f"  adjust    : FAIL — {exc}")
        return

    # 3. RVC
    t0 = time.perf_counter()
    try:
        if cold:
            from voice import _rvc_oneshot
            _rvc_oneshot(adj_wav, rvc_wav)
        else:
            worker.convert(adj_wav, rvc_wav)
        t_rvc = time.perf_counter() - t0
        size  = os.path.getsize(rvc_wav) // 1024
        print(f"  RVC       : {t_rvc:.2f}s  →  {os.path.basename(rvc_wav)}  ({size} KB)")
        print(f"  ✅ output : {rvc_wav}")
    except Exception as exc:
        print(f"  RVC       : FAIL — {exc}")
        return
    finally:
        for f in (raw_wav, adj_wav):
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold", action="store_true",
                        help="ใช้ one-shot cold load แทน warm worker")
    args = parser.parse_args()

    print("=" * 56)
    print(f"voice pipeline test  |  mode={'cold' if args.cold else 'warm worker'}")
    print("=" * 56)

    if args.cold:
        print("\n[cold mode] โหลดโมเดลใหม่ทุกประโยค (~8s ต่อครั้ง)")
        for label, text in TEST_SENTENCES:
            _run_sentence(label, text, worker=None, cold=True)
    else:
        print("\n[กำลังโหลด RVC worker...]")
        with RvcWorker() as w:
            print(f"  โหลดเสร็จใน {w.load_time:.1f}s  (warm inference จากนี้ ~1.4s/ประโยค)")
            for label, text in TEST_SENTENCES:
                _run_sentence(label, text, worker=w, cold=False)

    print(f"\n{'='*56}")
    print(f"ไฟล์ทั้งหมดอยู่ที่: {OUT_DIR}")


if __name__ == "__main__":
    main()
