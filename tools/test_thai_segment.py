"""
test_thai_segment.py — เทียบวิธีแบ่ง text ก่อนส่ง F5-TTS
รันด้วย: f5_venv\Scripts\python.exe tools\test_thai_segment.py

ทดสอบ 3 วิธี:
  A) nosplit   — ส่ง F5 ทั้งก้อน (เดิม)
  B) crfcut    — sent_tokenize engine="crfcut"
  C) clause    — clause_tokenize (CRF บน word_tokenize)

โบนัส: เทียบ bahttext vs _int_to_thai สำหรับตัวเลขราคาน้ำมัน
"""
import sys, os, time, io, contextlib
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR  = os.path.join(BOT_DIR, "f5_out", "segment_test")
os.makedirs(OUT_DIR, exist_ok=True)

REF_AUDIO = os.path.join(BOT_DIR, "f5_out", "ref_laibaht.wav")
REF_TEXT  = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"

# ── ประโยคทดสอบ (preprocessed — ตัวเลขแปลงแล้ว) ──────────────────────────────
TESTS = [
    ("medium",
     "วันนี้อากาศร้อนมากเลยค่ะ ควรดื่มน้ำเยอะๆ นะคะ และหลีกเลี่ยงการออกแดดช่วงเที่ยงด้วยนะคะ"),
    ("roste",
     "ฉันชอบนั่งอ่านหนังสือในห้องสมุดมากเลยค่ะ เงียบสงบดี แต่บางทีก็มีคนมาคุยด้วยซึ่งก็น่ารักดีเหมือนกันนะคะ "
     "ถ้าเธอสนใจเรื่องอะไรเป็นพิเศษก็บอกได้นะคะ"),
    ("oil_short",
     "แก๊สโซฮอล์ เก้าสิบห้า: สามสิบแปดจุดศูนย์ห้า บาท/ลิตร ดีเซล: สามสิบเจ็ดจุดห้าศูนย์ บาท/ลิตร "
     "ราคาขยับขึ้นเยอะเลยนะคะ ถ้าจะเติมควรดูปั๊มที่ใกล้กันนะคะ"),
    ("oil_long",
     "อัปเดตล่าสุด ยี่สิบแปด มิถุนายน สองพันห้าร้อยหกสิบเก้า "
     "แก๊สโซฮอล์ เก้าสิบห้า: สามสิบแปดจุดศูนย์ห้า บาท/ลิตร "
     "แก๊สโซฮอล์ อี ยี่สิบ: สามสิบสามจุดศูนย์ห้า บาท/ลิตร "
     "แก๊สโซฮอล์ อี แปดสิบห้า: ยี่สิบแปดจุดเก้าเก้า บาท/ลิตร "
     "แก๊สโซฮอล์ เก้าสิบเอ็ด: สามสิบเจ็ดจุดหกแปด บาท/ลิตร "
     "ดีเซล: สามสิบเจ็ดจุดห้าศูนย์ บาท/ลิตร "
     "ราคาขยับขึ้นบ้างในบางประเภทนะคะ ควรเลือกเติมให้เหมาะกับรถตัวเองค่ะ"),
]

# ── segmentation helpers ──────────────────────────────────────────────────────

def segment_crfcut(text: str, min_chars: int = 40) -> list[str]:
    from pythainlp.tokenize import sent_tokenize
    segs = sent_tokenize(text, engine="crfcut")
    return _merge_short([s.strip() for s in segs if s.strip()], min_chars)

def segment_word_group(text: str, max_chars: int = 200, min_chars: int = 40) -> list[str]:
    """แบ่งตาม word_tokenize แล้วจัดกลุ่มตามความยาว"""
    from pythainlp.tokenize import word_tokenize
    words = word_tokenize(text, engine="newmm")
    segs, buf = [], ""
    for w in words:
        if len(buf) + len(w) > max_chars and buf:
            segs.append(buf.strip())
            buf = w
        else:
            buf += w
    if buf.strip():
        segs.append(buf.strip())
    return _merge_short(segs, min_chars)

def _merge_short(segs: list[str], min_chars: int) -> list[str]:
    """รวม segment ที่สั้นเกินเข้ากับ segment ถัดไป"""
    result, buf = [], ""
    for seg in segs:
        seg = seg.strip()
        if not seg:
            continue
        buf = (buf + " " + seg).strip() if buf else seg
        if len(buf) >= min_chars:
            result.append(buf)
            buf = ""
    if buf:
        if result:
            result[-1] = result[-1] + " " + buf
        else:
            result.append(buf)
    return result

# ── F5 helpers ────────────────────────────────────────────────────────────────

def gen_f5(tts, segments: list[str], out_path: str, silence_ms: int = 150) -> float:
    import numpy as np, soundfile as sf
    arrays, t0 = [], time.perf_counter()
    for i, seg in enumerate(segments):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            wav = tts.infer(
                ref_audio=REF_AUDIO, ref_text=REF_TEXT, gen_text=seg,
                step=32, cfg=2.0, speed=1.0, max_chars=200,
            )
        arrays.append(wav)
        if i < len(segments) - 1:
            arrays.append(np.zeros(int(24000 * silence_ms / 1000)))
    result = np.concatenate(arrays)
    sf.write(out_path, result, 24000)
    return time.perf_counter() - t0

# ── bahttext vs _int_to_thai comparison ──────────────────────────────────────

def compare_bahttext():
    from pythainlp.util import bahttext
    sys.path.insert(0, BOT_DIR)
    from f5_preprocess import numbers_to_thai

    cases = [
        "37.50 บาท",
        "28.99 บาท",
        "50.05 บาท",
        "19.00 บาท",
        "47.64 บาท",
        "38.05 บาท/ลิตร",
    ]
    print("\n=== เทียบ number converter ===")
    print(f"  {'input':<20} {'f5_preprocess':<35} {'bahttext'}")
    print("  " + "-"*80)
    for c in cases:
        # f5_preprocess: แปลงตัวเลขในประโยค
        our = numbers_to_thai(c)
        # bahttext: แปลงตัวเลขเป็น Baht reading (38.50 → สามสิบแปดบาทห้าสิบสตางค์)
        try:
            num_str = c.split()[0]
            bt = bahttext(float(num_str))
        except Exception as e:
            bt = f"ERR:{e}"
        print(f"  {c:<20} {our:<35} {bt}")

# ── main ──────────────────────────────────────────────────────────────────────

print("โหลด F5 model v2...")
t0 = time.perf_counter()
from f5_tts_th.tts import TTS
tts = TTS(model="v2")
print(f"  โหลดเสร็จใน {time.perf_counter()-t0:.1f}s\n")

compare_bahttext()

print("\n=== ทดสอบ segmentation + F5 TTS ===\n")

results = []

for name, text in TESTS:
    print(f"{'='*60}")
    print(f"[{name}] ({len(text)}c)")
    print(f"  text: {text[:80]}{'...' if len(text)>80 else ''}")

    # วิธี A: nosplit
    segs_a = [text]

    # วิธี B: crfcut
    segs_b = segment_crfcut(text)

    # วิธี C: word group
    segs_c = segment_word_group(text)

    print(f"\n  A nosplit : {len(segs_a)} segment")
    print(f"  B crfcut  : {len(segs_b)} segments → {[len(s) for s in segs_b]}")
    for i, s in enumerate(segs_b):
        print(f"    [{i}] {s[:70]}")
    print(f"  C wordgrp : {len(segs_c)} segments → {[len(s) for s in segs_c]}")
    for i, s in enumerate(segs_c):
        print(f"    [{i}] {s[:70]}")

    for method, segs in [("A_nosplit", segs_a), ("B_crfcut", segs_b), ("C_wordgrp", segs_c)]:
        out = os.path.join(OUT_DIR, f"{name}_{method}.wav")
        elapsed = gen_f5(tts, segs, out)
        dur = __import__('soundfile').info(out).duration
        print(f"\n  {method}: gen={elapsed:.1f}s  audio={dur:.1f}s  → {os.path.basename(out)}")
        results.append({"name": name, "method": method, "segs": len(segs),
                         "gen": round(elapsed,1), "dur": round(dur,1)})

# ── สรุป ──────────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("สรุป:")
print(f"  {'test':<12} {'method':<12} {'segs':>5} {'gen':>7} {'audio':>7}")
print("  " + "-"*50)
for r in results:
    print(f"  {r['name']:<12} {r['method']:<12} {r['segs']:>5} {r['gen']:>6.1f}s {r['dur']:>6.1f}s")

print(f"\nไฟล์ .wav อยู่ใน: {OUT_DIR}")
print("เปิดฟังเทียบ (ชื่อเดียวกัน A/B/C):")
for name, _ in TESTS:
    print(f"  {name}_A_nosplit.wav  vs  {name}_B_crfcut.wav  vs  {name}_C_wordgrp.wav")
