"""
test_voxcpm2_v2.py — รอบสอง แก้จากผลรอบแรกที่เสียง "ทุ้มยืด" ใช้ไม่ได้

สิ่งที่รอบแรก (test_voxcpm2.py) ทำผิด 3 จุด:
  1. ใช้ prompt_wav_path = โหมด "continuation" (พูดต่อจากคลิป) ไม่ใช่โหมดโคลนเสียง
     → เลียนจังหวะ/โทนของ ref มาทั้งดุ้น ซึ่ง ref เราคือคนเล่าเรื่องเนิบๆ 160 วินาที
     → ตามซอร์ส core.py: โคลนเสียงต้องใช้ reference_wav_path
       ("structurally isolated via ref_audio tokens")
  2. ยัด style description ปนเข้าไปใน text → โมเดลอ่านออกมาเป็นเสียงด้วย
  3. ไม่ได้ตั้ง normalize=True (default False) → ยังไม่เคยทดสอบ text normalizer จริง

รอบนี้ทดสอบแยกตัวแปรทีละอย่าง เพื่อรู้ว่าอะไรทำให้เสียงเสีย

รันด้วย: voxcpm_venv\Scripts\python.exe tools\test_voxcpm2_v2.py
"""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "voxcpm2_v2")
os.makedirs(OUT_DIR, exist_ok=True)

REF_FULL = os.path.join(BOT_DIR, "ref_audio", "lai_seg4_160s.wav")
REF_TEXT = ("ตีสอง ตีสาม ตีสี่ อะไรทรงเนี้ยแบบก่อนเช้าอ่ะ มันจะเป็นช่วงผีออกอะไรสักอย่างนึง "
            "แหลมบาดก็แบบว่า")
# ref สั้น 10 วิ ตัดจากไฟล์เดิม — F5/VoxCPM แนะนำ ref สั้น (5-15s) ไม่ใช่ 160s
REF_SHORT = os.path.join(OUT_DIR, "_ref_10s.wav")

TEXT = "รอสเต้เข้ามาแล้วค่ะ วันนี้เป็นยังไงบ้างคะ"
TEXT_NUM = "สวัสดีค่ะ วันนี้อากาศดีนะคะ ราคาน้ำมัน 38.85 บาทต่อลิตรค่ะ"


def make_short_ref():
    """ตัด ref 10 วินาทีแรกจากไฟล์ 160s (ตัดที่ความเงียบใกล้ 10s ถ้าหาเจอ)"""
    import soundfile as sf
    import numpy as np
    data, sr = sf.read(REF_FULL, dtype="float32", always_2d=True)
    target = int(10 * sr)
    if len(data) > target:
        data = data[:target]
    sf.write(REF_SHORT, data, sr)
    print(f"  ตัด ref สั้น: {len(data)/sr:.1f}s @ {sr}Hz → {os.path.basename(REF_SHORT)}")


def main():
    import torch
    from voxcpm import VoxCPM
    import soundfile as sf

    print(f"torch {torch.__version__}  cuda={torch.cuda.is_available()}")
    make_short_ref()

    print("\nโหลดโมเดล...")
    t0 = time.perf_counter()
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2")
    print(f"  โหลดเสร็จใน {time.perf_counter()-t0:.1f}s  (รอบนี้ไม่ต้องดาวน์โหลดแล้ว)")

    # ⚠️ sample rate อยู่ที่ model.tts_model.sample_rate (= 48000) ไม่ใช่ model.sample_rate
    # รอบก่อนใช้ getattr(model, "sample_rate", 24000) ซึ่ง "ไม่มี" attr นี้ → ตกไปใช้ default
    # 24000 เงียบๆ ทุกครั้ง = เขียนเสียง 48k ลงไฟล์ที่บอกว่า 24k → เล่นช้าครึ่งหนึ่ง
    # ทุ้มลง 1 อ็อกเทฟ (นี่คือต้นเหตุอาการ "ทุ้มยืด" ทั้งหมด)
    # ไม่ใส่ default อีกแล้ว — ถ้าหาไม่เจอให้พังไปเลย ดีกว่าเดาผิดเงียบๆ
    SR = model.tts_model.sample_rate
    print(f"  sample rate = {SR} Hz")

    results = []

    def run(tag, out_name, **kw):
        t1 = time.perf_counter()
        try:
            wav = model.generate(**kw)
            el = time.perf_counter() - t1
            sf.write(os.path.join(OUT_DIR, out_name), wav, SR)
            dur = len(wav) / SR
            print(f"    {tag:<26} → {dur:5.1f}s  gen={el:5.1f}s  RTF={el/dur:.2f}  {out_name}")
            results.append({"tag": tag, "duration": round(dur, 2),
                            "gen_time": round(el, 2), "rtf": round(el/dur, 3),
                            "file": out_name, "ok": True,
                            "kw": {k: v for k, v in kw.items() if k != "text"}})
        except Exception as e:
            print(f"    {tag:<26} → ❌ {type(e).__name__}: {e}")
            results.append({"tag": tag, "ok": False, "error": f"{type(e).__name__}: {e}"})

    print("\n" + "=" * 66)
    print("ก) โหมด ref (โคลนเสียงจริง) vs prompt (continuation) — ต้นเหตุ 'ทุ้มยืด'")
    print("=" * 66)
    print("  ประโยคเดียวกันหมด เทียบว่าโหมดไหน/ref ยาวเท่าไหร่ให้เสียงดีกว่า")
    run("prompt_160s (รอบแรก)", "a1_prompt_160s.wav",
        text=TEXT, prompt_wav_path=REF_FULL, prompt_text=REF_TEXT)
    run("ref_160s", "a2_ref_160s.wav",
        text=TEXT, reference_wav_path=REF_FULL)
    run("ref_10s", "a3_ref_10s.wav",
        text=TEXT, reference_wav_path=REF_SHORT)
    run("prompt_10s", "a4_prompt_10s.wav",
        text=TEXT, prompt_wav_path=REF_SHORT, prompt_text=REF_TEXT)

    print("\n" + "=" * 66)
    print("ข) cfg_value — คุมความเหมือน/ความนิ่ง (default 2.0)")
    print("=" * 66)
    for cfg in (1.5, 2.0, 3.0):
        run(f"ref_10s cfg={cfg}", f"b_cfg{str(cfg).replace('.','')}.wav",
            text=TEXT, reference_wav_path=REF_SHORT, cfg_value=cfg)

    print("\n" + "=" * 66)
    print("ค) inference_timesteps — จำนวน step (default 10)")
    print("=" * 66)
    for st in (10, 20, 30):
        run(f"ref_10s steps={st}", f"c_steps{st}.wav",
            text=TEXT, reference_wav_path=REF_SHORT, inference_timesteps=st)

    print("\n" + "=" * 66)
    print("ง) normalize=True — text normalizer ในตัว (รอบแรกลืมเปิด)")
    print("=" * 66)
    run("number normalize=False", "d1_num_nonorm.wav",
        text=TEXT_NUM, reference_wav_path=REF_SHORT, normalize=False)
    run("number normalize=True", "d2_num_norm.wav",
        text=TEXT_NUM, reference_wav_path=REF_SHORT, normalize=True)

    peak = torch.cuda.max_memory_allocated() / 1024**2 if torch.cuda.is_available() else 0
    ok = [r for r in results if r.get("ok")]
    print("\n" + "=" * 66)
    print(f"สำเร็จ {len(ok)}/{len(results)}   VRAM peak {peak:.0f} MB")
    print(f"ไฟล์อยู่ที่: {OUT_DIR}")
    print("\nฟังเรียงแบบนี้:")
    print("  1. a1 (รอบแรก ที่ว่าทุ้มยืด) → a2 → a3   ดูว่าดีขึ้นไหม")
    print("  2. ถ้า a3 ดีสุด ค่อยฟัง b_* / c_* หาค่าที่เหมาะ")

    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results, "vram_peak_mb": round(peak)},
                  f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
