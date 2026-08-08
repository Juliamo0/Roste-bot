"""
test_voxcpm2.py — ทดสอบ VoxCPM2 เทียบกับ F5-TTS-THAI ที่ใช้อยู่

รันด้วย: voxcpm_venv\Scripts\python.exe tools\test_voxcpm2.py

ทดสอบ 3 อย่างที่ตัดสินว่าจะย้ายจาก F5 หรือไม่:
  1. คุณภาพ/ความเร็ว — ประโยคชุดเดียวกับ tune_f5_params.py เทียบกันได้ตรงๆ
  2. controllable cloning — ref เดิม + สั่งอารมณ์เป็นข้อความ (จุดขายที่ F5 ทำไม่ได้)
  3. VRAM peak — ต้องรู้ว่าเหลือที่ให้ qwen3:8b + VLM หรือเปล่า

ไม่แตะ pipeline เสียงที่ใช้งานอยู่ — venv แยก, output แยก
"""
import sys, os, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "voxcpm2")
os.makedirs(OUT_DIR, exist_ok=True)

# ref เดียวกับที่บอทใช้จริง (voice.py: F5_REF_AUDIO / F5_REF_TEXT) — เทียบได้ตรง
REF_AUDIO = os.path.join(BOT_DIR, "ref_audio", "lai_seg4_160s.wav")
REF_TEXT = ("ตีสอง ตีสาม ตีสี่ อะไรทรงเนี้ยแบบก่อนเช้าอ่ะ มันจะเป็นช่วงผีออกอะไรสักอย่างนึง "
            "แหลมบาดก็แบบว่า")

# ── ชุดที่ 1: ประโยคเดียวกับ tune_f5_params.py ──────────────────────
# ตั้งใจใช้ข้อความ *ดิบ* (ไม่ผ่าน f5_preprocess) เพื่อทดสอบคำโฆษณาที่ว่า
# VoxCPM2 อ่านตัวเลข/ไทยปนอังกฤษได้เองโดยไม่ต้อง normalize
TESTS = {
    "short":  "สวัสดีค่ะ วันนี้อากาศดีนะคะ",
    "number": "สวัสดีค่ะ วันนี้อากาศดีนะคะ ราคาน้ำมัน 38.85 บาทต่อลิตรค่ะ",
    "medium": "รอสเต้เข้ามาแล้ว อากาศวันนี้ร้อนมากเลย อย่าลืมดื่มน้ำด้วยนะคะ",
    "or_mid": "วันนี้อากาศร้อนมากค่ะ อยากแนะนำให้ดื่มน้ำเยอะนะคะ",
}

# ข้อความที่ f5_preprocess.py ต้องแก้เป็นพิเศษ — ดูว่า VoxCPM2 รอดเองไหม
TESTS_RAW = {
    "unit":    "ฝนตก 0.2 มม. ความชื้น 75% ค่ะ",
    "year":    "วันนี้วันที่ 7 สิงหาคม พ.ศ. 2569 ค่ะ",
    "codesw":  "เดี๋ยวรอสเต้ generate ไฟล์ให้นะคะ รอสักครู่",
}

# ── ชุดที่ 2: controllable cloning — ref เดิม + สั่งอารมณ์ ─────────
# นี่คือหัวใจของการทดสอบ: แก้ปัญหา "ref ตัวเดียวโทนเดียว" ได้จริงไหม
STYLE_TEXT = "รอสเต้เข้ามาแล้วค่ะ วันนี้เป็นยังไงบ้างคะ"
STYLES = {
    "none":     None,
    "cheerful": "(สดใส ร่าเริง พูดเร็วนิดหน่อย)",
    "calm":     "(นุ่มนวล ใจเย็น พูดช้าๆ)",
    "playful":  "(ขี้เล่น แซว ยิ้มขณะพูด)",
}


def vram_mb():
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 1024**2
    except Exception:
        pass
    return 0.0


def main():
    import torch
    print(f"torch {torch.__version__}  cuda={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    if not os.path.exists(REF_AUDIO):
        print(f"❌ ไม่พบ ref audio: {REF_AUDIO}")
        return 1

    from voxcpm import VoxCPM
    import soundfile as sf

    print("\nโหลดโมเดล VoxCPM2 (ครั้งแรกจะดาวน์โหลด ~หลาย GB)...")
    t0 = time.perf_counter()
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2")
    load_t = time.perf_counter() - t0
    print(f"  โหลดเสร็จใน {load_t:.1f}s   VRAM peak {vram_mb():.0f} MB")

    results = []

    def run(tag, text, out_name, style=None):
        """สังเคราะห์ 1 ประโยค บันทึกไฟล์ + เก็บตัวเลข"""
        prompt = f"{style} {text}" if style else text
        t1 = time.perf_counter()
        try:
            wav = model.generate(
                text=prompt,
                prompt_wav_path=REF_AUDIO,
                prompt_text=REF_TEXT,
            )
            elapsed = time.perf_counter() - t1
            # sample rate อยู่ที่ tts_model (48000) — เวอร์ชันแรกใช้ getattr(model,...)
            # ซึ่งไม่มี attr นี้ เลยตกไปใช้ 24000 → เสียงทุ้ม/ยืดลงครึ่งหนึ่ง
            sr = model.tts_model.sample_rate
            path = os.path.join(OUT_DIR, out_name)
            sf.write(path, wav, sr)
            dur = len(wav) / sr
            rtf = elapsed / dur if dur else 0
            print(f"    {tag:<10} → {dur:5.1f}s audio  gen={elapsed:5.1f}s  RTF={rtf:.2f}  {out_name}")
            results.append({"tag": tag, "duration": round(dur, 2),
                            "gen_time": round(elapsed, 2), "rtf": round(rtf, 3),
                            "file": out_name, "style": style, "ok": True})
        except Exception as e:
            print(f"    {tag:<10} → ❌ {type(e).__name__}: {e}")
            results.append({"tag": tag, "ok": False, "error": f"{type(e).__name__}: {e}"})

    print("\n" + "=" * 62)
    print("ชุดที่ 1 — ประโยคเดียวกับ tune_f5_params.py (เทียบกับ F5 ได้ตรง)")
    print("=" * 62)
    for name, text in TESTS.items():
        run(name, text, f"t1_{name}.wav")

    print("\n" + "=" * 62)
    print("ชุดที่ 2 — ข้อความดิบที่ f5_preprocess ต้องแก้ (VoxCPM2 รอดเองไหม)")
    print("=" * 62)
    for name, text in TESTS_RAW.items():
        run(name, text, f"t2_{name}.wav")

    print("\n" + "=" * 62)
    print("ชุดที่ 3 — controllable cloning: ref เดิม + สั่งอารมณ์ (หัวใจของการทดสอบ)")
    print("=" * 62)
    for name, style in STYLES.items():
        run(f"style_{name}", STYLE_TEXT, f"t3_style_{name}.wav", style=style)

    peak = vram_mb()
    ok = [r for r in results if r.get("ok")]
    print("\n" + "=" * 62)
    print("สรุป")
    print("=" * 62)
    print(f"  สำเร็จ {len(ok)}/{len(results)}")
    if ok:
        avg_rtf = sum(r["rtf"] for r in ok) / len(ok)
        print(f"  RTF เฉลี่ย {avg_rtf:.3f}   (เปเปอร์อ้าง 0.30 บน RTX 4090)")
    print(f"  VRAM peak {peak:.0f} MB / 16311 MB")
    print(f"  เหลือให้ qwen3:8b (5.58GB) + bge-m3 (0.66GB): "
          f"{(16311 - peak - 6390) / 1024:.1f} GB")
    print(f"\n  ไฟล์เสียงอยู่ที่: {OUT_DIR}")
    print("  → ฟังเทียบกับ f5_out/tuning/ ของเดิม แล้วตัดสินว่าดีกว่าไหม")

    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"results": results, "vram_peak_mb": round(peak),
                   "load_time_s": round(load_t, 1)}, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
