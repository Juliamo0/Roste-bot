"""
ทดสอบ streaming TTS จริง (F5+RVC บน GPU) — text_to_roste_voice_segments

วัดสองอย่าง:
  1. time-to-first-segment vs เวลารวม (ประโยชน์หลักของ streaming)
  2. per-segment fail-safe จริง — kill F5 worker หลัง segment แรก
     segment ที่เหลือต้องออกเสียงผ่าน edge-tts→RVC ต่อ ไม่เงียบ

วิธีใช้:  python tools/test_voice_stream.py
ผลลัพธ์: rvc_out/stream_test/
"""

import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.join(_TOOLS_DIR, "..")
sys.path.insert(0, _ROOT)

from voice import RvcWorker, F5Worker, text_to_roste_voice_segments

OUT_DIR = os.path.join(_ROOT, "rvc_out", "stream_test")

# ข้อความหลายประโยค — crfcut ควรแบ่งได้หลาย segment
LONG_TEXT = ("วันนี้อากาศดีมากเลยนะคะ ท้องฟ้าแจ่มใสไม่มีเมฆเลยค่ะ "
             "รอสเต้แนะนำให้ออกไปเดินเล่นข้างนอกบ้างนะคะ "
             "แต่อย่าลืมทาครีมกันแดดก่อนออกจากบ้านด้วยนะคะ "
             "เดี๋ยวผิวเสียแล้วจะหาว่ารอสเต้ไม่เตือนค่ะ")


def run_stream(label: str, rvc_w, f5_w, kill_f5_after_first: bool) -> bool:
    print(f"\n{'='*56}\n[{label}]\n{'='*56}")
    t0 = time.perf_counter()
    times, ok = [], True
    gen = text_to_roste_voice_segments(
        LONG_TEXT, worker=rvc_w, f5_worker=f5_w,
        out_dir=OUT_DIR, filename=label)
    for i, wav in enumerate(gen):
        dt = time.perf_counter() - t0
        times.append(dt)
        size = os.path.getsize(wav) // 1024
        print(f"  segment {i}: พร้อมเล่นที่ t={dt:5.1f}s  ({size} KB)  {os.path.basename(wav)}")
        if kill_f5_after_first and i == 0:
            print("  💀 kill F5 worker กลางคัน — segment ที่เหลือต้องมาทาง edge-tts")
            f5_w._proc.kill()

    total = time.perf_counter() - t0
    if not times:
        print("  ❌ ไม่มี segment ออกมาเลย")
        return False
    print(f"\n  time-to-first-segment: {times[0]:.1f}s | segments: {len(times)} | รวม: {total:.1f}s")
    if kill_f5_after_first and len(times) < 2:
        print("  ❌ fail-safe ไม่ทำงาน — ได้แค่ segment เดียวหลัง kill")
        ok = False
    return ok


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("[กำลังโหลด F5 + RVC workers (cold ~27s)...]")

    results = {}
    with RvcWorker() as rvc_w:
        print(f"  RVC พร้อมใน {rvc_w.load_time:.1f}s")

        with F5Worker() as f5_w:
            print(f"  F5 พร้อมใน {f5_w.load_time:.1f}s")
            results["streaming ปกติ"] = run_stream("normal", rvc_w, f5_w, False)

        # รอบสอง: worker ใหม่ แล้ว kill กลาง stream
        with F5Worker() as f5_w2:
            results["fail-safe (kill F5 กลางคัน)"] = run_stream(
                "killtest", rvc_w, f5_w2, True)

    print(f"\n{'='*56}")
    for name, ok in results.items():
        print(f"  {'✅' if ok else '❌'} {name}")
    print(f"ไฟล์อยู่ที่: {OUT_DIR}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
