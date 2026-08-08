"""
make_ref_candidates.py — ขุด ref audio หลายตัวจากไฟล์ต้นฉบับที่มีอยู่แล้ว

ใช้ 1_Lai_ref_(Vocals).mp3 + JSON transcript (มี timestamp ตรงกับข้อความ)
ตัดเป็นชิ้น ~10 วิ พร้อม ref_text ที่ตรงกันเป๊ะ — ซึ่งเป็นสิ่งที่ VoxCPM2 ต้องการ
(โหมด prompt_wav_path + prompt_text ต้องการ transcript ที่ตรง ไม่งั้นเสียงเพี้ยน)

วัดคุณภาพแต่ละชิ้นด้วยตัวเลข แล้วคัดตัวที่น่าจะดีที่สุดมาให้ฟัง:
  - RMS (ความดัง) — ดังพอไหม
  - silence ratio — มีช่วงเงียบเยอะไปไหม
  - pitch variance — น้ำเสียงมีชีวิตชีวาหรือแบน (ใช้เลือกโทน)
  - clipping — เสียงแตกไหม

รันด้วย: voxcpm_venv\Scripts\python.exe tools\make_ref_candidates.py
ผลลัพธ์: ref_audio/candidates/*.wav + candidates.json (ref_text คู่กัน)
"""
import sys, os, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_AUDIO = os.path.join(BOT_DIR, "ref_audio", "1_Lai_ref_(Vocals).mp3")
SRC_JSON = os.path.join(BOT_DIR, "ref_audio", "1_Lai_ref_Vocalsmp3.json")
OUT_DIR = os.path.join(BOT_DIR, "ref_audio", "candidates")

TARGET_SEC = 10.0      # ความยาว ref ที่ต้องการ (VoxCPM/F5 ชอบ 5-15s)
MIN_SEC = 7.0


def analyze(y, sr):
    """วัดคุณภาพเสียงเชิงตัวเลข"""
    import numpy as np
    import librosa

    rms = float(np.sqrt(np.mean(y ** 2)))
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    clip_ratio = float(np.mean(np.abs(y) > 0.99))

    # สัดส่วนความเงียบ (frame ที่เบากว่า 20% ของ RMS รวม)
    frame = 2048
    hop = 512
    if len(y) >= frame:
        frames = librosa.util.frame(y, frame_length=frame, hop_length=hop)
        fr = np.sqrt(np.mean(frames ** 2, axis=0))
        silence_ratio = float(np.mean(fr < rms * 0.2))
    else:
        silence_ratio = 1.0

    # pitch — ใช้ pyin เอาเฉพาะช่วงที่มีเสียงพูด
    try:
        f0, voiced, _ = librosa.pyin(
            y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
            sr=sr, frame_length=frame,
        )
        f0v = f0[~np.isnan(f0)]
        if len(f0v) > 10:
            pitch_mean = float(np.median(f0v))
            # ความแปรปรวนเป็น semitone — บอกว่าน้ำเสียงขึ้นลงมากแค่ไหน
            semis = 12 * np.log2(f0v / pitch_mean)
            pitch_std = float(np.std(semis))
            voiced_ratio = float(np.mean(~np.isnan(f0)))
        else:
            pitch_mean = pitch_std = voiced_ratio = 0.0
    except Exception:
        pitch_mean = pitch_std = voiced_ratio = 0.0

    return {"rms": round(rms, 4), "peak": round(peak, 3),
            "clip_ratio": round(clip_ratio, 5),
            "silence_ratio": round(silence_ratio, 3),
            "pitch_hz": round(pitch_mean, 1),
            "pitch_std_semitone": round(pitch_std, 2),
            "voiced_ratio": round(voiced_ratio, 3)}


def score(m):
    """คะแนนรวม — ยิ่งสูงยิ่งเหมาะเป็น ref"""
    s = 0.0
    s += min(m["rms"] / 0.08, 1.0) * 30           # ดังพอ
    s += (1 - min(m["silence_ratio"] / 0.4, 1.0)) * 25   # เงียบน้อย
    s += min(m["voiced_ratio"] / 0.6, 1.0) * 25   # มีเสียงพูดเยอะ
    s -= min(m["clip_ratio"] * 1000, 20)          # ไม่แตก
    s += min(m["pitch_std_semitone"] / 3.0, 1.0) * 20   # น้ำเสียงมีชีวิตชีวา
    return round(s, 1)


def main():
    import numpy as np
    import librosa
    import soundfile as sf

    for p in (SRC_AUDIO, SRC_JSON):
        if not os.path.exists(p):
            print(f"❌ ไม่พบ {p}")
            return 1
    os.makedirs(OUT_DIR, exist_ok=True)

    segs = json.load(open(SRC_JSON, encoding="utf-8"))
    print(f"โหลดเสียงต้นฉบับ ({os.path.basename(SRC_AUDIO)}) ...")
    y, sr = librosa.load(SRC_AUDIO, sr=None, mono=True)
    print(f"  {len(y)/sr:.1f}s @ {sr}Hz   segments ใน JSON: {len(segs)}\n")

    cands = []
    print(f"{'#':<3} {'ช่วง(s)':<16} {'ยาว':<6} {'RMS':<7} {'เงียบ':<6} "
          f"{'pitch':<7} {'ขึ้นลง':<7} {'คะแนน':<6}")
    print("-" * 72)

    for i, s in enumerate(segs):
        st, en = s["start_time"], s["end_time"]
        text = s["transcript"].strip()
        if en - st < MIN_SEC:
            continue

        # ตัดจากต้น segment ยาว TARGET_SEC — ตัดที่ขอบเขตคำโดยประมาณ
        # โดยเทียบสัดส่วนความยาวเสียงกับความยาวข้อความ
        use_sec = min(TARGET_SEC, en - st)
        a, b = int(st * sr), int((st + use_sec) * sr)
        chunk = y[a:b]
        if len(chunk) < MIN_SEC * sr:
            continue

        # ตัดข้อความตามสัดส่วนเวลาที่ใช้จริง แล้วถอยมาจบที่ช่องว่างคำสุดท้าย
        ratio = use_sec / (en - st)
        cut = int(len(text) * ratio)
        sub = text[:cut]
        if " " in sub and ratio < 0.98:
            sub = sub.rsplit(" ", 1)[0]
        sub = sub.strip()
        if len(sub) < 10:
            continue

        m = analyze(chunk, sr)
        sc = score(m)
        name = f"ref{i:02d}_{int(st)}s.wav"
        sf.write(os.path.join(OUT_DIR, name), chunk, sr)

        cands.append({"file": name, "seg_index": i,
                      "start": round(st, 2), "used_sec": round(use_sec, 2),
                      "ref_text": sub, "metrics": m, "score": sc})
        print(f"{i:<3} {st:6.1f}-{st+use_sec:<8.1f} {use_sec:<6.1f} "
              f"{m['rms']:<7.4f} {m['silence_ratio']:<6.2f} "
              f"{m['pitch_hz']:<7.1f} {m['pitch_std_semitone']:<7.2f} {sc:<6.1f}")

    cands.sort(key=lambda c: -c["score"])
    print("\n" + "=" * 72)
    print("อันดับที่แนะนำ (คะแนนสูงสุด 5 ตัว):")
    print("=" * 72)
    for c in cands[:5]:
        print(f"  {c['score']:5.1f}  {c['file']:<18} pitch={c['metrics']['pitch_hz']}Hz "
              f"ขึ้นลง={c['metrics']['pitch_std_semitone']}st")
        print(f"         \"{c['ref_text'][:70]}\"")

    with open(os.path.join(OUT_DIR, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=2)
    print(f"\nได้ {len(cands)} ตัวเลือก → {OUT_DIR}")
    print("ขั้นต่อไป: tools/test_ref_candidates.py สร้างเสียงจากทุก ref แล้วฟังเทียบ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
