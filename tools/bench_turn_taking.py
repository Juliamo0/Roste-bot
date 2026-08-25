"""
เทียบกลยุทธ์ตัดประโยค (end-of-turn) 3 แบบ บนเสียงที่มีช่วง "หยุดคิด" กลางประโยค

ทำไมต้องวัด: stt_listener ตัดประโยคเมื่อเงียบเกิน SILENCE_MS (800ms) เจอคนเว้นวรรคคิด
900-1600ms ประโยคถูกหักเป็นสองก้อน บอทตอบครึ่งแรกแล้วคำถามจริงหาย (ดูเหตุผลเต็มที่
tools/gen_turn_cases.py ซึ่งสร้างไฟล์ให้ bench นี้) คำถามคือกลยุทธ์ไหนเก็บประโยคไว้
ครบโดย "ตอบช้าเพิ่มน้อยที่สุด" — accuracy อย่างเดียวไม่พอ เพราะกลยุทธ์ที่รอ 1500ms
ทุกครั้งจะถูกเสมอแต่ UX แย่สุด

กลยุทธ์ที่เทียบ:
  A silence-800  — พฤติกรรมปัจจุบัน: เงียบเกิน SILENCE_MS (import ค่าจริงจาก
                   stt_listener เพื่อให้ bench ตาม config จริงเสมอ) ก็ตัด
  B silence-XXXX — กฎเดียวกันแต่ threshold ยาวขึ้น (default 1200/1500 —
                   --thresholds 1300,1800,2200 เพื่อ sweep ค่าอื่นได้)
  C semantic-800 — ตัดที่ 800 เหมือน A แต่ถอดเสียงก้อนนั้นก่อน แล้วดูว่าข้อความ
                   "จบหรือยัง" ถ้ายัง (ลงท้ายคำเชื่อม/ค้าง list) จะถือก้อนต่อ
                   รอช่วงถัดไปมาแปะ จนกว่าข้อความจะจบ หรือเงียบไปเกิน
                   SEMANTIC_IDLE_GIVEUP_MS จึงยอมปล่อยก้อนที่มีอยู่
                   ⚠️ looks_unfinished() ด้านล่างเป็น heuristic ตัวแทน semantic-VAD
                   ของจริง (โมเดลจำพวก turn-taking predictor) — คุณภาพของมันคือ
                   คุณภาพของลิสต์คำล้วนๆ แก้ลิสต์ = แก้พฤติกรรม อ่านผลแบบนั้น

simulation (ไม่แตะ Discord เลย): อ่าน wav 16k mono มาเดินทีละ 20ms chunk วัด RMS ด้วย
เกณฑ์เดียวกับ stt_listener (_SILENCE_RMS) และจัดจังหวะตัดแบบเดียวกับ
_silence_checker_loop (ตรวจทุก ~100ms → จุดตัด quantify เป็น step 100ms เหมือนของจริง)
รวมถึงกฎ MIN_UTTERANCE_MS (ก้อนสั้นเกินทิ้ง) และ MAX_UTTERANCE_MS (พูดยาวถึงฝาตัดทันที)
เมื่อกลยุทธ์ตัดสินใจจบประโยค ช่วงเสียงนั้นจะถูกเขียนเป็น wav temp แล้วส่ง SttWorker จริง
(โมเดลเดียวกับที่บอทใช้) — ทุกกลยุทธ์ใช้ ASR ตัวเดียวกัน ความต่างที่เหลือจึงเป็นของ
"การตัด" ล้วนๆ

metric ต่อเคส:
  ครบ/แตก   — จำนวน utterance ที่ผ่านมา (1 = ครบ, ≥2 = แตก) เทียบกับ expect
              ที่ generator ประกาศ (กลุ่ม done_then_add expect = split!)
  CER       — ข้อความรวมทุกก้อน (normalized) เทียบ ground truth — วัดว่าเนื้อหารอด
              ไหม (การแตกเองไม่ทำ CER แย่เสมอ เพราะเอามาต่อกันได้ จึงต้องอ่านคู่
              กับครบ/แตก ไม่ใช้ CER ตัวเดียวตัดสิน)
  delay     — จุดจบ utterance ลบ speech_end_ms จาก manifest = "ตอบช้ากว่าที่คนพูด
              จบไปกี่ ms" (ค่าติดลบ = บอทตัดสินใจก่อนคนพูดจบ = ขัดคนพูด)
รายงานทั้ง delay คำตอบแรก (UX เร็ว) และ delay คำตอบสุดท้าย (เมื่อรู้เรื่องครบ)

รันด้วย: venv\\Scripts\\python.exe tools\\bench_turn_taking.py
         (ต้องรัน tools\\gen_turn_cases.py ก่อน · SttWorker spawn typhoon_asr_venv เอง)

ข้อจำกัดที่ต้องรู้ตอนอ่านผล: ไฟล์ทดสอบเป็นเสียงสังเคราะห์ + digital silence ล้วน
(ดู docstring ของ gen_turn_cases.py) ช่องหยุดของคนจริงมีเสียงหายใจ/เสียงห้อง/โน้ตเสียง
ปลายประโยค ที่ detector ทุกแบบใน bench นี้มองไม่เห็น ตัวเลขจึงเป็นพื้นบน — ใช้เรียง
ลำดับกลยุทธ์ได้ ใช้ทำนายพฤติกรรมในห้อง voice จริงไม่ได้ และกลยุทธ์ C ที่ชนะใน bench
นี้ไม่ได้แปลว่า semantic-VAD จะชนะจริง เพราะที่นี่ "ความฉลาดทางความหมาย" ถูกแทนด้วย
ลิสต์คำไทยไม่กี่สิบคำ ซึ่ง ASR สะกดเพี้ยน/ตัด particle ทิ้งเมื่อไร กลไกนี้เงียบตายทันที
"""
import sys, os, json, time, argparse, tempfile, wave, audioop

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)   # import โมดูลฝั่ง root (script อยู่ใน tools/)

MANIFEST = os.path.join(BOT_DIR, "f5_out", "turn_cases", "manifest.json")
RESULT   = os.path.join(BOT_DIR, "tools", "turn_bench_result.json")

# ── constants จาก stt_listener ตัวจริง — bench ต้องเดินด้วยกฎเดียวกับ listener ──
# import ไม่ได้ (เช่น เครื่องไม่มี discord.py) ก็ยังรันได้ด้วยค่า fallback แต่ต้อง
# แจ้งดังๆ และจดลงผลลัพธ์ เพราะตัวเลขทั้งชุดขึ้นกับค่าพวกนี้โดยตรง
try:
    from stt_listener import SILENCE_MS, MIN_UTTERANCE_MS, MAX_UTTERANCE_MS, _SILENCE_RMS
    CONSTANTS_SOURCE = "stt_listener (import จริง)"
except Exception as _exc:
    print(f"[!] import stt_listener ไม่สำเร็จ ({_exc}) — ใช้ค่า hardcoded (ผลอาจต่างจาก config จริง)")
    SILENCE_MS, MIN_UTTERANCE_MS, MAX_UTTERANCE_MS, _SILENCE_RMS = 800, 400, 30000, 150
    CONSTANTS_SOURCE = "fallback hardcoded (import stt_listener ไม่ได้)"

# ── simulation timing — mirror โครงของ stt_listener ─────────────────────────────
CHUNK_MS           = 20    # granular ของ PCM stream (write() ได้ packet ถี่กว่านี้แต่ผลเทียบเท่ากัน)
CHECK_INTERVAL_SEC = 0.1   # ความละเอียด checker — ทำให้จุดตัด quantify เป็น step 100ms เหมือนของจริง
_TARGET_RATE    = 16000    # ไฟล์จาก gen_turn_cases.py เป็น 16k mono s16 ตรงๆ
_SAMPLE_WIDTH   = 2
_BYTES_PER_CHUNK = _TARGET_RATE * _SAMPLE_WIDTH * CHUNK_MS // 1000

# ── พารามิเตอร์ของกลยุทธ์ C ──────────────────────────────────────────────────────
# รอข้อความต่อได้นานสุด "หลังจากเงียบ" เท่านี้ แล้วค่อยยอมปล่อยก้อน — ตั้งระหว่าง
# 800 (กฎเดิม) กับ 1500 เพื่อให้ C มี margin จับช่องหยุดถัดไปแต่ไม่แพงกว่า B
SEMANTIC_IDLE_GIVEUP_MS = 1500

WHOLE_CER_MAX = 0.30       # ประโยคเดียวที่ CER เกินนี้ = โดน ASR กินเนื้อหา นับว่าไม่ "ครบ"
                            # (เกณฑ์เดียวกับ flag !! ใน bench_stt_thai_en.py)

GROUPS = ["core", "connective", "done_then_add", "control", "list"]


# ── metric — ทำซ้ำจาก bench_stt_thai_en.py แทน import ข้าม (convention เดียวกับ
#    stt_client.py ที่ทำซ้ำ helper ของ voice.py: tool แต่ละตัวพกของตัวเองครบ) ──────
def _levenshtein(a: list, b: list) -> int:
    """ระยะแก้ไข — ใช้กับ list ของ char (CER)"""
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
    """ตัดช่องว่าง/วรรคตอน/ตัวพิมพ์ก่อนเทียบ — ASR ใส่ไม่เหมือนกันไม่ควรนับเป็นความผิด"""
    import re
    text = text.lower().strip()
    text = re.sub(r"[.,!?;:\"'()\[\]{}…ๆฯ]", "", text)
    return re.sub(r"\s+", "", text)


def cer(ref: str, hyp: str) -> float:
    r = _norm(ref)
    if not r:
        return 0.0
    return _levenshtein(list(r), list(hyp and _norm(hyp) or "")) / len(r)


# ── heuristic "ข้อความนี้จบหรือยัง" — หัวใจของกลยุทธ์ C ─────────────────────────
# ⚠️ นี่คือตัวแทน semantic-VAD ด้วยลิสต์คำล้วนๆ คุณภาพ = คุณภาพลิสต์ (ดู docstring)
# เช็คเฉพาะ "ท้ายข้อความ" (หน้าตัด 15 ตัวอักษรหลังตัดช่องว่าง) เพราะคำเชื่อมอย่าง
# "คือ" ปรากฏกลางประโยคได้ตลอด ("คือเมื่อวานผมไป...") ถ้าดูทั้งประโยคจะจับผิดเพียบ
_NOT_DONE = (
    # คำเชื่อม/บอกว่ากำลังจะอธิบายต่อ — ค้างไว้รอ
    "แล้วก็", "ก็คือ", "คือว่า", "คือ",
    "ประมาณว่า", "ประมาณ",
    "อย่างแรก", "อย่างที่สอง", "อย่างที่สาม",        # กำลังไล่ list — ยังไม่ครบ
    "รวมถึง", "รวมทั้ง", "แถม", "บวกกับ",
    "และ", "หรือ", "กับ", "แต่", "เพราะ", "เพราะว่า",
    "เนื่องจาก", "ถ้า", "ถ้าหาก", "เมื่อ", "ตอนที่",
    "ที่", "ซึ่ง", "ดังนั้น", "ฉะนั้น", "ส่วน", "สำหรับ",
    "เช่น", "ได้แก่", "เหมือน", "เพื่อ", "ก่อนที่", "หลังจาก",
)
_DONE = (
    # คำถาม — ถามแล้วต้องได้คำตอบ
    "ไหม", "มั้ย", "มั้ง", "หรอ", "ปะ", "หรือเปล่า", "เปล่า", "ใช่ไหม", "ใช่มั้ย",
    "ยังไง", "อย่างไง", "เท่าไหร่", "เท่าไหน", "กี่โมง", "กี่", "อะไร", "ใคร",
    "ตรงไหน", "ที่ไหน", "เมื่อไหร่", "เมื่อไร",
    # คำลงท้ายของคนไทยที่ปิดประโยค — ขอ/เล่า/เห็นด้วยจบวง
    "หน่อย", "ด้วย", "สิ", "ซิ", "จ้ะ", "จ๊ะ", "ครับ", "ค่ะ", "นะ",
    "เลย", "จัง", "มาก", "ล่ะ", "ละ", "แน่ะ",
)
# "แล้ว" เดี่ยวๆ ไม่อยู่ในลิสต์ไหนตั้งใจ — กำกวมทั้งสองทาง ("ทำเสร็จแล้ว" = จบ vs
# "...แล้วก็" = ค้าง) ปล่อยให้ตกไปที่ default ด้านล่าง ดีกว่าเดาผิดเป็นระบบ
_MARKER_WINDOW_CHARS = 15   # ครอบคลุม marker ยาวสุด ("อย่างที่สองคือ" ฯลฯ) + vocative "รอสเต้" ท้ายประโยค
_DEFAULT_UNFINISHED = True  # ไม่เจอ marker ทั้งสองฝั่ง → เชื่อว่า "ยังไม่จบ" (bench นี้เกิดจากปัญหาตัดเร็วเกิน
                            # จึง bias ฝั่งรอ — พลิกเป็น False แล้วรันซ้ำเป็น experiment ได้)


def looks_unfinished(text: str) -> bool:
    """ข้อความที่ถอดได้ดูเหมือน "ยังพูดไม่จบ" หรือเปล่า — heuristic คำท้ายประโยค
    (ตัวแทน semantic-VAD — ดู docstring และ comment เหนือลิสต์คำ)"""
    t = _norm(text)
    if not t:
        return False          # ก้อนว่าง = ไม่มีอะไรให้รอ ปล่อยไปเลย
    if t.endswith("?"):
        return False
    tail = t[-_MARKER_WINDOW_CHARS:]
    if any(m in tail for m in _NOT_DONE):
        return True
    if any(m in tail for m in _DONE):
        return False
    return _DEFAULT_UNFINISHED


# ── อ่านไฟล์เสียง ─────────────────────────────────────────────────────────────────
def _load_case_pcm(case: dict) -> bytes:
    with wave.open(case["wav"], "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (_TARGET_RATE, 1, _SAMPLE_WIDTH):
            raise RuntimeError(f"{case['wav']}: ต้องเป็น {_TARGET_RATE}Hz mono s16 — รัน gen_turn_cases.py ใหม่")
        return w.readframes(w.getnframes())


# ── ตัวเดินไฟล์ — mirror write() + _silence_checker_loop ของ stt_listener ─────────
def _walk_cuts(pcm: bytes, cut_ms: int) -> list:
    """เดิน PCM ทีละ 20ms คืนช่วง utterance [(start_ms, end_ms, reason)]
    reason: "silence" (เงียบครบ cut_ms), "max" (ยาวถึง MAX_UTTERANCE_MS), "eof"
    กฎทุกข้อมาจาก stt_listener: เกณฑ์ RMS, จังหวะ checker 100ms, MIN/MAX_UTTERANCE_MS
    ข้อต่างเดียว: listener เปิด buffer ตั้งแต่ packet แรกแม้เงียบ (แต่ has_sound=False
    ทำให้ทิ้งตอน enqueue) — ที่นี่เริ่มนับช่วงที่ chunk แรกที่ดัง ผลลัพธ์ต่อการถอดเสียงเท่ากัน"""
    check_every = max(1, round(CHECK_INTERVAL_SEC * 1000 / CHUNK_MS))
    total_ms = len(pcm) // _BYTES_PER_CHUNK * CHUNK_MS
    spans = []
    span_start = last_sound = None
    has_sound = False

    def _flush(end_ms: int, reason: str):
        nonlocal span_start, last_sound, has_sound
        if has_sound and end_ms - span_start >= MIN_UTTERANCE_MS:   # กฎทิ้งก้อนสั้นของ _enqueue_finished
            spans.append((span_start, end_ms, reason))
        span_start = last_sound = None
        has_sound = False

    for i in range(len(pcm) // _BYTES_PER_CHUNK):
        t_end = (i + 1) * CHUNK_MS
        chunk = pcm[i * _BYTES_PER_CHUNK:(i + 1) * _BYTES_PER_CHUNK]
        if audioop.rms(chunk, _SAMPLE_WIDTH) > _SILENCE_RMS:
            if span_start is None:
                span_start = i * CHUNK_MS
                has_sound = False
            last_sound = t_end
            has_sound = True
            if t_end - span_start >= MAX_UTTERANCE_MS:
                # พูดยาวถึงฝา — listener ตัดทันทีใน write() ไม่รอเงียบ (ดู docstring ของมัน)
                _flush(t_end, "max")
                continue
        # checker thread ตรวจทุก ~100ms ไม่ว่า chunk ล่าสุดดังหรือเงียบ
        if (i + 1) % check_every == 0 and has_sound and (t_end - last_sound) >= cut_ms:
            _flush(t_end, "silence")

    if has_sound:
        _flush(total_ms, "eof")   # ไฟล์จบค้างช่วงไว้ — เทียบเท่า cleanup() แบบไม่ทิ้ง เพื่อให้ถอดคะแนนได้
    return spans


# ── กลยุทธ์ C — พับช่วงที่ตัดด้วยกฎ A ด้วยการดู "จบหรือยัง" ของข้อความสะสม ────────
def _fold_semantic(case_id: str, cuts: list, transcribe, total_ms: int) -> list:
    utts, pending = [], None
    for start_ms, end_ms, reason in cuts:
        if pending is not None and start_ms >= pending["deadline"]:
            # เงียบยาวเกิน give-up แล้วค่อยกลับมาพูด — policy จริงปล่อยก้อนเก่าตอน deadline
            # ก่อนเริ่มประโยคใหม่ ไม่งั้นสองประโยคคนละเรื่องจะถูกแปะกัน
            utts.append({"start": pending["start"], "end": pending["deadline"],
                         "text": " ".join(filter(None, pending["texts"]))})
            pending = None
        text = transcribe(case_id, start_ms, end_ms)
        if pending is None:
            pending = {"start": start_ms, "texts": [text]}
        else:
            pending["texts"].append(text)
        acc = " ".join(filter(None, pending["texts"]))
        if not looks_unfinished(acc):
            utts.append({"start": pending["start"], "end": end_ms, "text": acc})
            pending = None
        else:
            # ถือก้อนต่อ — ตั้ง deadline กันรอไม่มีวันจบถ้าคนพูดหายเงียบไปเลย
            pending["deadline"] = end_ms + SEMANTIC_IDLE_GIVEUP_MS
    if pending is not None:
        end = min(total_ms, pending.get("deadline", total_ms))
        utts.append({"start": pending["start"], "end": end,
                     "text": " ".join(filter(None, pending["texts"]))})
    return utts


# ── ให้คะแนนเคสเดียว ─────────────────────────────────────────────────────────────
def _score_case(case: dict, utts: list) -> dict:
    ref = case["text"]
    joined = " ".join(u["text"] for u in utts)
    produced = "whole" if len(utts) == 1 else ("split" if utts else "none")
    return {
        "id": case["id"], "group": case["group"], "expect": case["expect"],
        "produced": produced, "success": produced == case["expect"],
        "n_utt": len(utts),
        "cer_joined": cer(ref, joined),
        # CER ของก้อนเดียวเทียบทั้งประโยค — ใช้แยก "ตัดถูกแต่ ASR ถอดเพี้ยน" ออกจาก "ตัดผิด"
        "cer_single": cer(ref, utts[0]["text"]) if len(utts) == 1 else None,
        "delay_first_ms": utts[0]["end"] - case["speech_end_ms"] if utts else None,
        "delay_final_ms": utts[-1]["end"] - case["speech_end_ms"] if utts else None,
        "utts": [{"start": u["start"], "end": u["end"], "text": u["text"]} for u in utts],
    }


# ── รันหนึ่งกลยุทธ์กับทุกเคส ──────────────────────────────────────────────────────
def run_strategy(label: str, kind: str, threshold_ms: int, cases: list,
                 pcms: dict, transcribe) -> dict:
    print(f"\n{'=' * 66}")
    desc = {"A": f"กฎปัจจุบัน — ตัดเมื่อเงียบ ≥{threshold_ms}ms",
            "B": f"กฎเดิมยืดเวลา — ตัดเมื่อเงียบ ≥{threshold_ms}ms",
            "C": f"ตัดที่ {threshold_ms}ms แล้วดูว่าข้อความจบหรือยัง (give-up {SEMANTIC_IDLE_GIVEUP_MS}ms)"}[kind]
    print(f"  {label}  — {desc}")
    print(f"{'=' * 66}\n")

    rows = []
    for c in cases:
        pcm = pcms[c["id"]]
        cuts = _walk_cuts(pcm, cut_ms=threshold_ms)
        # transcribe รับ (case_id, start, end) — cache key ต้องมี case_id ไม่งั้นเคสต่างไฟล์
        # ที่ช่วงเวลาบังเอิญตรงกันจะได้ข้อความของกันและกัน
        if kind == "C":
            utts = _fold_semantic(c["id"], cuts, transcribe,
                                  len(pcm) // _BYTES_PER_CHUNK * CHUNK_MS)
        else:
            utts = [{"start": s, "end": e, "text": transcribe(c["id"], s, e)}
                    for s, e, _ in cuts]

        row = _score_case(c, utts)
        rows.append(row)
        flag = "  " if row["success"] else "!!"
        d1 = f"{row['delay_first_ms']:+.0f}ms" if row["delay_first_ms"] is not None else "-"
        d2 = f"{row['delay_final_ms']:+.0f}ms" if row["delay_final_ms"] is not None else "-"
        shape = f"ครบ CER {row['cer_single']:5.1%}" if row["n_utt"] == 1 \
            else f"แตก x{row['n_utt']}  CER(รวม) {row['cer_joined']:5.1%}"
        print(f"  {flag} [{c['id']:18s}] want={c['expect']:5s} {shape}  ตอบแรก {d1:>8} สุดท้าย {d2:>8}")
        for j, u in enumerate(row["utts"], 1):
            print(f"         {j}) {u['text']}")

    ok = sum(1 for r in rows if r["success"])
    whole_only = [r for r in rows if r["produced"] == "whole"]
    summary = {
        "n": len(rows), "success": ok,
        "whole": sum(1 for r in rows if r["produced"] == "whole"),
        "split": sum(1 for r in rows if r["produced"] == "split"),
        "none":  sum(1 for r in rows if r["produced"] == "none"),
        "cer_joined": (sum(r["cer_joined"] for r in rows) / len(rows)) if rows else 0.0,
        "cer_when_whole": (sum(r["cer_single"] for r in whole_only) / len(whole_only)) if whole_only else None,
        "delay_first_ms": _mean([r["delay_first_ms"] for r in rows]),
        "delay_final_ms": _mean([r["delay_final_ms"] for r in rows]),
    }
    by_group = {}
    for g in GROUPS:
        gr = [r for r in rows if r["group"] == g]
        if gr:
            by_group[g] = {"n": len(gr), "success": sum(r["success"] for r in gr)}
    return {
        "label": label, "kind": kind, "threshold_ms": threshold_ms,
        "semantic_idle_giveup_ms": SEMANTIC_IDLE_GIVEUP_MS if kind == "C" else None,
        "summary": summary, "by_group": by_group, "rows": rows,
    }


def _mean(vals: list):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


# ── ถอดเสียงผ่าน SttWorker จริง + cache (กลยุทธ์ต่างกันมักตัดได้ช่วงเดียวกันพอดี
#    โดยเฉพาะกลุ่ม control — ถอดซ้ำเปล่างาน GPU) ─────────────────────────────────
def make_transcriber(stt, pcms: dict):
    cache = {}

    def transcribe(case_id: str, start_ms: int, end_ms: int) -> str:
        key = (case_id, start_ms, end_ms)
        if key in cache:
            return cache[key]
        pcm = pcms[case_id][start_ms * _BYTES_PER_CHUNK // CHUNK_MS:
                             end_ms * _BYTES_PER_CHUNK // CHUNK_MS]
        fd, path = tempfile.mkstemp(prefix="roste_turn_bench_", suffix=".wav")
        try:
            os.close(fd)
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(_SAMPLE_WIDTH)
                w.setframerate(_TARGET_RATE)
                w.writeframes(pcm)
            text = (stt.transcribe(path) or "").strip()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        cache[key] = text
        return text

    return transcribe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="รันเฉพาะ label นี้ (เช่น semantic-800)")
    ap.add_argument("--thresholds", default="1200,1500",
                    help="threshold ms ของกลยุทธ์ B คั่นด้วย comma (default: 1200,1500)")
    args = ap.parse_args()

    if not os.path.exists(MANIFEST):
        print(f"ERR: ไม่พบ {MANIFEST}")
        print("     รัน venv\\Scripts\\python.exe tools\\gen_turn_cases.py ก่อน")
        return 1
    with open(MANIFEST, encoding="utf-8") as f:
        cases = json.load(f)
    cases = [c for c in cases if os.path.exists(c["wav"])]

    print(f"เคสทดสอบ {len(cases)} ไฟล์  "
          f"(core={sum(c['group'] == 'core' for c in cases)}, "
          f"connective={sum(c['group'] == 'connective' for c in cases)}, "
          f"done_then_add={sum(c['group'] == 'done_then_add' for c in cases)}, "
          f"control={sum(c['group'] == 'control' for c in cases)}, "
          f"list={sum(c['group'] == 'list' for c in cases)})")
    print(f"constants: {CONSTANTS_SOURCE} — SILENCE_MS={SILENCE_MS} "
          f"MIN_UTTERANCE_MS={MIN_UTTERANCE_MS} MAX_UTTERANCE_MS={MAX_UTTERANCE_MS} "
          f"_SILENCE_RMS={_SILENCE_RMS}")

    # กลยุทธ์ B สร้างจาก --thresholds — ค่าซ้ำกับ A (800) ข้าม ไม่งั้น label ชนกัน
    b_thresholds = [t for t in (int(x) for x in args.thresholds.split(",") if x.strip())
                    if t != SILENCE_MS]
    strategies = ([("silence-800", "A", SILENCE_MS)]
                  + [(f"silence-{t}", "B", t) for t in sorted(b_thresholds)]
                  + [(f"semantic-{SILENCE_MS}", "C", SILENCE_MS)])
    if args.only:
        strategies = [s for s in strategies if s[0] == args.only]
    if not strategies:
        print(f"ERR: ไม่พบกลยุทธ์ label '{args.only}'")
        return 1

    pcms = {c["id"]: _load_case_pcm(c) for c in cases}

    from stt_client import SttWorker
    stt = SttWorker()
    try:
        t0 = time.perf_counter()
        stt.start()
        print(f"\nโหลดโมเดล STT (typhoon-asr-realtime) {time.perf_counter() - t0:.1f}s")
        transcribe = make_transcriber(stt, pcms)

        results = []
        for label, kind, th in strategies:
            res = run_strategy(label, kind, th, cases, pcms, transcribe)
            res["meta"] = {
                "constants_source": CONSTANTS_SOURCE, "silence_rms": _SILENCE_RMS,
                "min_utterance_ms": MIN_UTTERANCE_MS, "max_utterance_ms": MAX_UTTERANCE_MS,
                "chunk_ms": CHUNK_MS, "check_interval_sec": CHECK_INTERVAL_SEC,
            }
            results.append(res)
    finally:
        stt.stop()

    # ── สรุป ─────────────────────────────────────────────────────────────────────
    print(f"\n\n{'=' * 88}")
    print("  สรุป — เกณฑ์ 'สำเร็จ' = รูปร่างประโยคตรง expect ของแต่ละเคส (ครบ/แตก) ไม่ใช่ CER อย่างเดียว")
    print(f"{'=' * 88}")
    print(f"  {'กลยุทธ์':<16} {'สำเร็จ':>8} {'ครบ':>5} {'แตก':>5} "
          f"{'CER(รวม)':>9} {'ตอบช้า(แรก)':>12} {'ตอบช้า(สุด)':>12}")
    print(f"  {'-' * 84}")
    for r in results:
        s = r["summary"]
        d1 = f"{s['delay_first_ms']:+.0f}ms" if s["delay_first_ms"] is not None else "-"
        d2 = f"{s['delay_final_ms']:+.0f}ms" if s["delay_final_ms"] is not None else "-"
        print(f"  {r['label']:<16} {s['success']:>4}/{s['n']:<3} {s['whole']:>5} {s['split']:>5} "
              f"{s['cer_joined']:>8.1%} {d1:>12} {d2:>12}")

    print(f"\nสำเร็จแยกตามกลุ่ม:")
    print(f"  {'กลยุทธ์':<16} {'':>2}" + "".join(f" {g[:12]:>13}" for g in GROUPS))
    for r in results:
        cells = "".join(
            f" {r['by_group'][g]['success']}/{r['by_group'][g]['n']:>2}{'':>{13 - len(str(r['by_group'][g]['n'])) - 3}}"
            if g in r["by_group"] else f" {'-':>13}"
            for g in GROUPS)
        print(f"  {r['label']:<16} {'':>2}{cells}")

    for r in results:
        fails = [row["id"] for row in r["rows"] if not row["success"]]
        if fails:
            print(f"\n{r['label']} พลาด {len(fails)} เคส: {', '.join(fails)}")

    ok = [r for r in results if r["summary"]["n"]]
    if ok:
        best = max(ok, key=lambda r: (r["summary"]["success"],
                                      -(r["summary"]["delay_final_ms"] or 0)))
        print(f"\nดีที่สุดใน bench นี้: {best['label']} "
              f"(สำเร็จ {best['summary']['success']}/{best['summary']['n']})")
        print("  ⚠️ อ่านคู่กับข้อจำกัดใน docstring — digital silence ทำให้ทุกกลยุทธ์ได้เปรียบ")
        print("     และกลยุทธ์ C ฉลาดแค่ลิสต์คำใน looks_unfinished() เท่านั้น")

    with open(RESULT, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nผลเต็ม: {RESULT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
