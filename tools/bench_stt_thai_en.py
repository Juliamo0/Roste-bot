"""
เทียบโมเดล STT 3 ตัวบนประโยคที่ผู้ใช้พูดกับรอสเต้จริง (ไทย / ไทยปนอังกฤษ / ชื่อเฉพาะ)

ทำไมต้องวัดเอง: benchmark สาธารณะทุกตัว (CommonVoice, FLEURS, Gigaspeech2)
เป็นไทยล้วน ไม่มีใครวัด "ไทยปนอังกฤษ" ซึ่งเป็นวิธีที่คนไทยพูดจริง และ
Table 29 ของ Typhoon2 paper (arXiv:2412.13702) ชี้ว่าการ fine-tune ไทยทำให้
WER อังกฤษเสื่อม 6.02 -> 9.15 คำถามคือเสื่อมแค่ไหนในประโยคปน

ตัวที่เทียบ:
  1. Typhoon Whisper Turbo (0.8B) — turbo ที่ fine-tune ไทย ~11,000 ชม.
  2. Thonburian Whisper medium — งาน BiodatLab ม.มหิดล (ตัวที่ SCB 10X
     เลือกเป็น speech encoder ของ Typhoon2-Audio)
  3. faster-whisper large-v3 — baseline สองภาษา (ไม่ใช่ turbo เพราะ OpenAI
     ระบุเองว่า turbo เสียหายหนักกับไทย)

metric: CER เป็นตัวหลัก (ไทยไม่มีช่องว่างระหว่างคำ WER จึงไม่มีความหมาย)
        แต่รายงาน WER ด้วยสำหรับกลุ่มที่มีอังกฤษปน

รันด้วย: f5_venv\\Scripts\\python.exe tools\\bench_stt_thai_en.py
         (ต้องรัน tools\\gen_stt_cases.py ด้วย venv หลักก่อน)
"""
import sys, os, json, time, argparse, subprocess, gc

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(BOT_DIR, "f5_out", "stt_cases", "manifest.json")
RESULT = os.path.join(BOT_DIR, "tools", "stt_bench_result.json")

# (label, path/repo, ขนาดที่ประกาศ)
# Typhoon/Thonburian บน HF เป็น transformers format ที่ faster-whisper โหลดตรงไม่ได้
# (มันหา model.bin ของ CTranslate2) ต้องแปลงก่อนด้วย:
#   f5_venv\\Scripts\\python.exe -m ctranslate2.converters.transformers \\
#     --model <hf_repo> --output_dir ct2_models/<label> \\
#     --copy_files tokenizer.json preprocessor_config.json --quantization float16
_CT2 = os.path.join(BOT_DIR, "ct2_models")
MODELS = [
    ("typhoon-turbo",     os.path.join(_CT2, "typhoon-turbo"),     "0.8B"),
    ("thonburian-medium", os.path.join(_CT2, "thonburian-medium"), "0.8B"),
    ("faster-large-v3",   "large-v3",                              "1.5B"),
]

GROUPS = ["th", "th_en", "proper"]


# ── metrics ────────────────────────────────────────────────────────────────
def _levenshtein(a: list, b: list) -> int:
    """ระยะแก้ไข — ใช้กับ list ของ char (CER) หรือ list ของ token (WER)"""
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm(text: str) -> str:
    """ตัดช่องว่าง/วรรคตอน/ตัวพิมพ์ ก่อนเทียบ — ASR แต่ละตัวใส่ไม่เหมือนกัน
    ไม่ควรนับเป็นความผิด"""
    import re
    text = text.lower().strip()
    text = re.sub(r"[.,!?;:\"'()\[\]{}…ๆฯ]", "", text)
    return re.sub(r"\s+", "", text)


def cer(ref: str, hyp: str) -> float:
    r = _norm(ref)
    if not r:
        return 0.0
    return _levenshtein(list(r), list(hyp and _norm(hyp) or "")) / len(r)


def wer(ref: str, hyp: str) -> float:
    """WER บน token ที่ตัดด้วย newmm — ใช้ตัวตัดคำเดียวกับที่ memory.py ใช้
    เพื่อให้ผลเทียบกันได้ ถ้าไม่มี pythainlp จะ fallback เป็น split()"""
    try:
        from pythainlp.tokenize import word_tokenize
        rt = word_tokenize(ref.lower().strip(), engine="newmm")
        ht = word_tokenize((hyp or "").lower().strip(), engine="newmm")
    except Exception:
        rt, ht = ref.lower().split(), (hyp or "").lower().split()
    rt = [t for t in rt if t.strip()]
    ht = [t for t in ht if t.strip()]
    if not rt:
        return 0.0
    return _levenshtein(rt, ht) / len(rt)


# ── VRAM ───────────────────────────────────────────────────────────────────
def vram_used() -> int:
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        return int(r.stdout.strip().split("\n")[0])
    except Exception:
        return -1


# ── bench หนึ่งโมเดล ────────────────────────────────────────────────────────
def bench_model(label: str, repo: str, size: str, cases: list, device: str,
                compute_type: str) -> dict:
    from faster_whisper import WhisperModel

    print(f"\n{'=' * 66}")
    print(f"  {label}  ({repo}, {size})")
    print(f"{'=' * 66}")

    base_vram = vram_used()
    t0 = time.perf_counter()
    try:
        model = WhisperModel(repo, device=device, compute_type=compute_type)
    except Exception as e:
        print(f"  ERR: โหลดโมเดลไม่ได้ — {e}")
        return {"label": label, "repo": repo, "error": str(e)}
    load_s = time.perf_counter() - t0
    load_vram = vram_used()

    print(f"  โหลด {load_s:.1f}s   VRAM +{load_vram - base_vram} MiB\n")

    rows, total_audio, total_infer = [], 0.0, 0.0
    for c in cases:
        t1 = time.perf_counter()
        segments, info = model.transcribe(c["wav"], language="th", beam_size=5)
        hyp = "".join(s.text for s in segments).strip()
        infer_s = time.perf_counter() - t1

        total_infer += infer_s
        total_audio += getattr(info, "duration", 0.0) or 0.0

        row = {
            "group": c["group"], "ref": c["text"], "hyp": hyp,
            "cer": cer(c["text"], hyp), "wer": wer(c["text"], hyp),
            "infer_s": infer_s,
        }
        rows.append(row)
        flag = "  " if row["cer"] < 0.10 else ("!!" if row["cer"] > 0.30 else " ~")
        print(f"  {flag} [{c['group']:6s}] CER {row['cer']:5.1%}  {infer_s:4.2f}s")
        print(f"       ref: {c['text']}")
        print(f"       hyp: {hyp}")

    del model
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass

    by_group = {}
    for g in GROUPS:
        gr = [r for r in rows if r["group"] == g]
        if gr:
            by_group[g] = {
                "cer": sum(r["cer"] for r in gr) / len(gr),
                "wer": sum(r["wer"] for r in gr) / len(gr),
                "n": len(gr),
            }

    return {
        "label": label, "repo": repo, "size": size,
        "load_s": load_s, "vram_mib": load_vram - base_vram,
        "cer": sum(r["cer"] for r in rows) / len(rows) if rows else 0.0,
        "wer": sum(r["wer"] for r in rows) / len(rows) if rows else 0.0,
        "rtf": (total_infer / total_audio) if total_audio else 0.0,
        "by_group": by_group, "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--compute-type", default="float16")
    ap.add_argument("--only", help="รันเฉพาะ label นี้")
    args = ap.parse_args()

    if not os.path.exists(MANIFEST):
        print(f"ERR: ไม่พบ {MANIFEST}")
        print("     รัน venv\\Scripts\\python.exe tools\\gen_stt_cases.py ก่อน")
        return 1

    with open(MANIFEST, encoding="utf-8") as f:
        cases = json.load(f)
    cases = [c for c in cases if os.path.exists(c["wav"])]
    print(f"เคสทดสอบ {len(cases)} ไฟล์  "
          f"(th={sum(c['group'] == 'th' for c in cases)}, "
          f"th_en={sum(c['group'] == 'th_en' for c in cases)}, "
          f"proper={sum(c['group'] == 'proper' for c in cases)})")

    models = [m for m in MODELS if not args.only or m[0] == args.only]
    results = [bench_model(l, r, s, cases, args.device, args.compute_type)
               for l, r, s in models]

    ok = [r for r in results if "error" not in r]

    print(f"\n\n{'=' * 78}")
    print("  สรุป — CER (ต่ำ=ดี)")
    print(f"{'=' * 78}")
    print(f"  {'โมเดล':<20} {'ไทยล้วน':>9} {'ไทย+อังกฤษ':>12} {'ชื่อเฉพาะ':>10} "
          f"{'รวม':>8} {'RTF':>6} {'VRAM':>8}")
    print(f"  {'-' * 76}")
    for r in ok:
        g = r["by_group"]
        f_ = lambda k: f"{g[k]['cer']:.1%}" if k in g else "-"
        print(f"  {r['label']:<20} {f_('th'):>9} {f_('th_en'):>12} {f_('proper'):>10} "
              f"{r['cer']:>7.1%} {r['rtf']:>6.2f} {r['vram_mib']:>6} MiB")

    if ok:
        best_th = min(ok, key=lambda r: r["by_group"].get("th", {}).get("cer", 9))
        best_mix = min(ok, key=lambda r: r["by_group"].get("th_en", {}).get("cer", 9))
        print(f"\n  ไทยล้วนดีสุด    : {best_th['label']}")
        print(f"  ไทย+อังกฤษดีสุด : {best_mix['label']}")

    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  ผลเต็ม: {RESULT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
