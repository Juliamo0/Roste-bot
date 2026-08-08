"""
test_ref_candidates.py — สร้างเสียงจาก ref candidate หลายตัว แล้วฟังเทียบ

ใช้ ref ที่ make_ref_candidates.py ขุดมา (พร้อม ref_text ที่ตรงกันเป๊ะ)
สร้างประโยคเดียวกันจากทุก ref เพื่อดูว่า ref ตัวไหนให้ "เสียงรอสเต้" ที่สุด

ทดสอบ 2 โหมด เพราะ ref ที่มี transcript ตรงกันเปิดทางให้ใช้ได้ทั้งคู่:
  - ref   = reference_wav_path (โคลนเสียง, ไม่ต้องมี transcript)
  - prompt = prompt_wav_path + prompt_text (ต้องมี transcript ที่ตรง)

รันด้วย: voxcpm_venv\Scripts\python.exe tools\test_ref_candidates.py
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAND_DIR = os.path.join(BOT_DIR, "ref_audio", "candidates")
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "ref_test")
os.makedirs(OUT_DIR, exist_ok=True)

TOP_N = 5   # เอาเฉพาะ ref คะแนนสูงสุด N ตัว
TEXT = "รอสเต้เข้ามาแล้วค่ะ วันนี้เป็นยังไงบ้างคะ"


def main():
    import torch
    from voxcpm import VoxCPM
    import soundfile as sf

    cands = json.load(open(os.path.join(CAND_DIR, "candidates.json"), encoding="utf-8"))
    cands = cands[:TOP_N]
    print(f"จะทดสอบ ref {len(cands)} ตัว (คะแนนสูงสุด)\n")

    print("โหลดโมเดล...")
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2")
    SR = model.tts_model.sample_rate          # 48000 — อย่าใช้ getattr กับ default
    print(f"  sample rate = {SR} Hz\n")

    results = []

    def run(tag, out_name, **kw):
        t1 = time.perf_counter()
        try:
            wav = model.generate(**kw)
            el = time.perf_counter() - t1
            sf.write(os.path.join(OUT_DIR, out_name), wav, SR)
            dur = len(wav) / SR
            print(f"    {tag:<24} → {dur:5.2f}s  gen={el:5.1f}s  RTF={el/dur:.2f}")
            results.append({"tag": tag, "file": out_name, "duration": round(dur, 2),
                            "gen_time": round(el, 2), "rtf": round(el/dur, 3), "ok": True})
        except Exception as e:
            print(f"    {tag:<24} → ❌ {type(e).__name__}: {e}")
            results.append({"tag": tag, "ok": False, "error": f"{type(e).__name__}: {e}"})

    for c in cands:
        path = os.path.join(CAND_DIR, c["file"])
        stem = c["file"].replace(".wav", "")
        pitch = c["metrics"]["pitch_hz"]
        print(f"[{c['score']:.1f}] {c['file']}  pitch={pitch}Hz  "
              f"ขึ้นลง={c['metrics']['pitch_std_semitone']}st")
        print(f"       ref_text: \"{c['ref_text'][:60]}...\"")
        run(f"{stem} ref", f"{stem}_ref.wav",
            text=TEXT, reference_wav_path=path)
        run(f"{stem} prompt", f"{stem}_prompt.wav",
            text=TEXT, prompt_wav_path=path, prompt_text=c["ref_text"])
        print()

    ok = [r for r in results if r.get("ok")]
    print("=" * 62)
    print(f"สำเร็จ {len(ok)}/{len(results)}")
    print(f"ไฟล์อยู่ที่: {OUT_DIR}")
    print("\nฟังแล้วเลือกว่าตัวไหน 'เสียงรอสเต้' ที่สุด")
    print("แล้วเอาตัวนั้นไปปรับ pitch ใน WavePad ต่อได้เลย")

    meta = {"text": TEXT, "sample_rate": SR, "results": results,
            "candidates": cands}
    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
