"""
test_vox_from_roste.py — ใช้เสียงรอสเต้ที่ปรับ pitch แล้ว เป็น ref ให้ VoxCPM2

ไอเดียจากผู้ใช้: แทนที่จะให้ VoxCPM2 โคลนจากเสียงคนต้นฉบับ (ซึ่งเป็นคนเล่าเรื่อง
โทนเนิบๆ) ให้โคลนจาก "เสียงรอสเต้ที่เราชอบแล้ว" (F5 + pitch 108%) แทน
= เอาบุคลิกเสียงที่ผ่านการคัดเลือกมาแล้ว ไปต่อยอดกับโมเดลที่เป็นธรรมชาติกว่า

ทดสอบทั้ง ref สั้น (3.4s) และยาว (13.5s) เพราะความยาว ref มีผลกับคุณภาพ

รันด้วย: voxcpm_venv\Scripts\python.exe tools\test_vox_from_roste.py
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF_DIR = os.path.join(BOT_DIR, "ref_audio", "roste_v2")
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "vox_from_roste")
os.makedirs(OUT_DIR, exist_ok=True)

# ประโยคทดสอบ — ตั้งใจใช้ข้อความที่ *ไม่ได้* อยู่ใน ref เพื่อดูว่าโคลนแล้วพูดคำใหม่ได้ดีไหม
TESTS = {
    "greet":  "สวัสดีค่ะ วันนี้อากาศดีนะคะ",
    "chat":   "รอสเต้ว่าวันนี้น่าจะเป็นวันที่ดีนะคะ อยากทำอะไรสนุกๆ บ้างไหม",
    "number": "ตอนนี้อุณหภูมิ 32 องศา ความชื้น 68 เปอร์เซ็นต์ค่ะ",
}


def main():
    import torch
    from voxcpm import VoxCPM
    import soundfile as sf

    refs = {}
    for tag, stem in [("short", "roste_pitch108_short"), ("long", "roste_pitch108_long")]:
        wav = os.path.join(REF_DIR, f"{stem}.wav")
        txt = os.path.join(REF_DIR, f"{stem}.txt")
        if os.path.exists(wav) and os.path.exists(txt):
            refs[tag] = (wav, open(txt, encoding="utf-8").read().strip())
            print(f"  ref {tag}: {sf.info(wav).duration:.2f}s")
    if not refs:
        print(f"❌ ไม่พบ ref ใน {REF_DIR}")
        return 1

    print("\nโหลดโมเดล...")
    model = VoxCPM.from_pretrained("openbmb/VoxCPM2")
    SR = model.tts_model.sample_rate
    print(f"  sample rate = {SR} Hz\n")

    results = []

    def run(tag, out_name, **kw):
        t1 = time.perf_counter()
        try:
            wav = model.generate(**kw)
            el = time.perf_counter() - t1
            sf.write(os.path.join(OUT_DIR, out_name), wav, SR)
            dur = len(wav) / SR
            print(f"    {tag:<30} → {dur:5.2f}s  gen={el:5.1f}s  RTF={el/dur:.2f}")
            results.append({"tag": tag, "file": out_name, "duration": round(dur, 2),
                            "rtf": round(el/dur, 3), "ok": True})
        except Exception as e:
            print(f"    {tag:<30} → ❌ {type(e).__name__}: {e}")
            results.append({"tag": tag, "ok": False, "error": str(e)[:200]})

    for rtag, (rwav, rtext) in refs.items():
        print(f"=== ref {rtag} ({sf.info(rwav).duration:.1f}s) ===")
        for ttag, text in TESTS.items():
            # โหมด ref: โคลนเสียงล้วน ไม่ต้องมี transcript
            run(f"{rtag}/{ttag} ref", f"{rtag}_{ttag}_ref.wav",
                text=text, reference_wav_path=rwav)
            # โหมด prompt: มี transcript ที่ตรงกันเป๊ะ (เราสร้างเองเลยตรงแน่นอน)
            run(f"{rtag}/{ttag} prompt", f"{rtag}_{ttag}_prompt.wav",
                text=text, prompt_wav_path=rwav, prompt_text=rtext)
        print()

    ok = [r for r in results if r.get("ok")]
    print("=" * 62)
    print(f"สำเร็จ {len(ok)}/{len(results)}")
    print(f"ไฟล์: {OUT_DIR}")
    with open(os.path.join(OUT_DIR, "results.json"), "w", encoding="utf-8") as f:
        json.dump({"sample_rate": SR, "tests": TESTS, "results": results},
                  f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
