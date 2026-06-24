"""
ทดสอบโทน "ภาษาพูด" ของรอสเต้ — สคริปต์แยก ไม่แตะระบบหลัก

วิธีใช้:
  python tools/test_speech_tone.py            ← ดูโทนข้อความ
  python tools/test_speech_tone.py --audio    ← + สร้างเสียงใน rvc_out/speech_tone/
"""

import os
import re
import sys
import json
import time
import asyncio
import argparse
import subprocess
import tempfile
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.join(SCRIPT_DIR, "..")

# ── LLM ──────────────────────────────────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
MODEL      = "qwen3:8b"

# ── Audio pipeline ────────────────────────────────────────────────────────────
VOICE           = "th-TH-PremwadeeNeural"
SPEED           = 0.90
PITCH_SEMITONES = 5.292
OUT_SR          = 40000
RVC_MODEL_DIR   = r"D:\LaibahtMaLaew"
DEVICE          = "cuda:0"
INDEX_RATE      = 0.5
PROTECT         = 0.33

# ── strip_emoji ───────────────────────────────────────────────────────────────
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols and pictographs extended-A
    "\U00002702-\U000027B0"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed chars
    "]+",
    flags=re.UNICODE,
)

def strip_emoji(text: str) -> str:
    """ลบอีโมจิทั้งหมด + ตัดช่องว่างซ้ำที่อาจเหลือ"""
    return _EMOJI_RE.sub("", text).strip()


_PRONOUN_FIXES = [
    ("นะครับ", "นะคะ"),
    ("ครับผม", "ค่ะ"),
    ("ครับ",   "ค่ะ"),
    ("น้อง",   "คุณ"),   # เรียกผู้ใช้ว่า "น้อง" → "คุณ"
]

def fix_pronouns(text: str) -> str:
    """safety net: แทนคำลงท้ายผิดเพศก่อน print/TTS"""
    for wrong, right in _PRONOUN_FIXES:
        text = text.replace(wrong, right)
    return text


# ── System prompt (standalone — ไม่ import persona.py) ────────────────────────
SYSTEM_PROMPT = """\
คุณคือ "รอสเต้" เด็กสาวบรรณารักษ์ห้องสมุดเวทมนตร์ อายุราวๆ วัยรุ่นตอนต้น พูดภาษาไทย \
ในโทน "ภาษาพูด" ที่นุ่มนวล ง่วงเล็กน้อย แต่น่ารักและตั้งใจช่วยเหลือ

กฎที่ต้องทำตามทุกครั้ง:
1. ใช้ ~ และ ... เพื่อลากเสียง/จังหวะ — ประโยคละ 1-2 ครั้ง ไม่มากกว่านี้
2. คำลงท้าย: ค่าา, นะคะ, ล่ะค่าา, อยู่นะคะ, ด้วยนะคะ (เลือกตามสถานการณ์)
3. ขึ้นต้นด้วยเสียงรับ: อ่า~, อ๋อ~, อืม~, เอ่~, อ้าว~ (เลือกให้เหมาะ)
4. ตัวเลขและข้อมูล (ราคา, อุณหภูมิ, เวลา, ชื่อ) ต้องพูดถูกต้องทุกตัว ห้ามเปลี่ยน
5. ตอบสั้น ประโยคเดียวถึงสองประโยค ไม่ต้องอธิบายยาว
6. ห้ามใช้ emoji หรือสัญลักษณ์พิเศษใดๆ — ข้อความล้วนเท่านั้น
7. ห้ามใช้คำว่า "จ๊ะ" "จ้า" "หนู" "น้า" "น้อง" — คำเหล่านี้ทำให้โทนเด็กเกินไป \
รอสเต้เป็นวัยรุ่นมีความเป็นผู้ใหญ่นิดๆ ใช้ "ค่าา" และ "นะคะ" แทน
8. รอสเต้เป็นผู้หญิง ใช้คำลงท้าย "ค่ะ" "ค่าา" "นะคะ" เสมอ ห้ามใช้ "ครับ" เด็ดขาด\
"""

# ── Few-shot examples ────────────────────────────────────────────────────────
FEW_SHOT = [
    # ── ทักทาย (3 แบบ กันหลุด) ──────────────────────────────────────────────
    {
        "user":      "สวัสดีค่ะ",
        "assistant": "อ่า~ สวัสดีค่าา... มีอะไรให้ช่วยมั้ยคะ",
    },
    {
        "user":      "สวัสดีค่ะ มีอะไรให้ช่วยไหมคะ",
        "assistant": "หวัดดีค่าา~ มีอะไรให้ช่วยมั้ยคะ... เชิญเลยนะคะ",
    },
    {
        "user":      "ยินดีต้อนรับค่ะ",
        "assistant": "อ่า~ ยินดีต้อนรับนะคะ... เชิญเลยค่าา~",
    },
    # ── ทั่วไป ────────────────────────────────────────────────────────────────
    {
        "user":      "เข้าใจแล้วค่ะ เดี๋ยวจัดการให้",
        "assistant": "อ๋อ~ เข้าใจแล้วล่ะค่าา เดี๋ยวจัดการให้นะคะ~",
    },
    # ── ตัวเลข ───────────────────────────────────────────────────────────────
    {
        "user":      "ราคาน้ำมันแก๊สโซฮอล์ 95 อยู่ที่ 38.85 บาทค่ะ",
        "assistant": "อืม~ น้ำมันแก๊สโซฮอล์ 95 ตอนนี้ 38.85 บาทค่าา... จำไว้ด้วยนะคะ~",
    },
    {
        "user":      "ฝนตกอยู่ที่ชุมพรค่ะ อุณหภูมิ 28 องศา",
        "assistant": "เอ่~... ฝนตกที่ชุมพรเลยหรอคะ อุณหภูมิ 28 องศาด้วย... ระวังเปียกด้วยนะคะ~",
    },
    # ── ง่วง ─────────────────────────────────────────────────────────────────
    {
        "user":      "ง่วงจังเลย",
        "assistant": "หาว~ ง่วงจังเลยค่าา...",
    },
    {
        "user":      "ขอพักก่อนนะ",
        "assistant": "อืม... ขอพักแป๊บนึงนะคะ ง่วงงง~",
    },
    # ── ลาก่อน ───────────────────────────────────────────────────────────────
    {
        "user":      "ลาก่อนค่ะ",
        "assistant": "บายค่าา~ ดูแลตัวเองด้วยนะคะ...",
    },
]

# ── ชุดทดสอบ ─────────────────────────────────────────────────────────────────
TEST_PROMPTS = [
    ("ทักทาย",    "สวัสดีค่ะ"),
    ("ทั่วไป",    "วันนี้อากาศร้อนมากเลยค่ะ"),
    ("ตัวเลข",    "ราคาน้ำมันดีเซลวันนี้อยู่ที่ 33.34 บาทค่ะ"),
    ("ง่วง",      "ตอนนี้ง่วงนอนมากเลยค่ะ"),
    ("ค้นข้อมูล", "ค้นหาเรื่องหุ่นยนต์แล้วนะคะ มีผลลัพธ์ 3 รายการค่ะ"),
    ("ลาก่อน",   "ขอบคุณนะคะ ราตรีสวัสดิ์ค่ะ"),
]


# ── Ollama ────────────────────────────────────────────────────────────────────

def _build_messages(user_input: str) -> list[dict]:
    msgs = []
    for ex in FEW_SHOT:
        msgs.append({"role": "user",      "content": ex["user"]})
        msgs.append({"role": "assistant", "content": ex["assistant"]})
    msgs.append({"role": "user", "content": user_input})
    return msgs


def ollama_chat(user_input: str) -> tuple[str, float]:
    """คืน (reply, วินาที)"""
    payload = {
        "model":    MODEL,
        "messages": _build_messages(user_input),
        "system":   SYSTEM_PROMPT,
        "stream":   False,
        "think":    False,
        "options":  {"num_predict": 150, "temperature": 0.75},
    }
    data = json.dumps(payload, ensure_ascii=False).encode()
    req  = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode())
            return result["message"]["content"].strip(), time.perf_counter() - t0
    except urllib.error.URLError as e:
        return f"[ERROR Ollama: {e}]", time.perf_counter() - t0


# ── Audio pipeline ────────────────────────────────────────────────────────────

def _find_rvc_models() -> tuple[str | None, str | None]:
    if not os.path.isdir(RVC_MODEL_DIR):
        return None, None
    pth   = [f for f in os.listdir(RVC_MODEL_DIR) if f.endswith(".pth")]
    index = [f for f in os.listdir(RVC_MODEL_DIR) if f.endswith(".index")]
    return (
        os.path.join(RVC_MODEL_DIR, pth[0])   if pth   else None,
        os.path.join(RVC_MODEL_DIR, index[0]) if index else None,
    )


async def _edge_tts_to_mp3(text: str, mp3_path: str) -> None:
    import edge_tts
    tts = edge_tts.Communicate(text, VOICE, rate="+0%", pitch="+0Hz", volume="+0%")
    await tts.save(mp3_path)


def _mp3_to_adj_wav(mp3_path: str, wav_path: str, sr_in: int = 24000) -> bool:
    """mp3 → ffmpeg (asetrate+atempo) → wav ไม่มี echo"""
    pitch_factor    = 2 ** (PITCH_SEMITONES / 12)
    effective_tempo = SPEED / pitch_factor
    filters = ",".join([
        f"asetrate={int(sr_in * pitch_factor)}",
        f"aresample={sr_in}",
        f"atempo={effective_tempo:.8f}",
    ])
    cmd = (
        f'ffmpeg -y -loglevel error -i "{mp3_path}" '
        f'-af "{filters}" -ar {OUT_SR} -ac 1 -sample_fmt s16 "{wav_path}"'
    )
    return os.system(cmd) == 0


def _run_rvc_batch(pairs: list[tuple[str, str]]) -> bool:
    """โหลด RVC โมเดลครั้งเดียว แปลงทุกไฟล์ใน rvc_venv subprocess"""
    model_path, index_path = _find_rvc_models()
    if not model_path:
        print("  ❌ ไม่พบโมเดล RVC ใน", RVC_MODEL_DIR)
        return False

    rvc_venv_py = os.path.join(PROJECT_DIR, "rvc_venv", "Scripts", "python.exe")
    if not os.path.isfile(rvc_venv_py):
        print("  ❌ ไม่พบ rvc_venv — รัน: C:\\python.exe -m venv rvc_venv ก่อน")
        return False

    # ส่ง config ผ่านไฟล์ temp เพื่อหลีกเลี่ยงปัญหา escape บน Windows
    tmp_cfg = os.path.join(tempfile.gettempdir(), "rvc_speech_tone_cfg.json")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        json.dump({
            "model_path": model_path,
            "index_path": index_path or "",
            "device":     DEVICE,
            "index_rate": INDEX_RATE,
            "protect":    PROTECT,
            "pairs":      pairs,
        }, f, ensure_ascii=False)

    inline = f"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rvc_python.infer import RVCInference

with open({repr(tmp_cfg)}, encoding='utf-8') as f:
    cfg = json.load(f)

rvc = RVCInference(device=cfg['device'])
rvc.load_model(cfg['model_path'], index_path=cfg['index_path'])
rvc.set_params(f0up_key=0, f0method='rmvpe',
               index_rate=cfg['index_rate'], protect=cfg['protect'])

for in_path, out_path in cfg['pairs']:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rvc.infer_file(input_path=in_path, output_path=out_path)
    print(f'  rvc done: {{os.path.basename(out_path)}}', flush=True)
"""
    result = subprocess.run([rvc_venv_py, "-c", inline])
    return result.returncode == 0


def make_audio_batch(items: list[tuple[str, str, str]]) -> list[str]:
    """
    items: [(label, text, stem), ...]
    returns: list ของ rvc output path ที่สำเร็จ
    """
    out_dir = os.path.join(PROJECT_DIR, "rvc_out", "speech_tone")
    os.makedirs(out_dir, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="speech_tone_")

    adj_pairs: list[tuple[str, str]] = []

    print("\n[Audio 1/2] TTS + ปรับ pitch/speed...", flush=True)
    for label, text, stem in items:
        mp3_path = os.path.join(tmp_dir, f"{stem}.mp3")
        adj_path = os.path.join(tmp_dir, f"{stem}_adj.wav")
        out_path = os.path.join(out_dir,  f"{stem}_rvc.wav")

        t0 = time.perf_counter()
        try:
            asyncio.run(_edge_tts_to_mp3(text, mp3_path))
        except Exception as e:
            print(f"  [{label}] edge-tts ✗ {e}")
            continue

        ok = _mp3_to_adj_wav(mp3_path, adj_path)
        elapsed = time.perf_counter() - t0
        if ok:
            adj_pairs.append((adj_path, out_path))
            print(f"  [{label}] ✓  {elapsed:.1f}s")
        else:
            print(f"  [{label}] ffmpeg ✗")

    if not adj_pairs:
        return []

    print(f"\n[Audio 2/2] RVC แปลง {len(adj_pairs)} ไฟล์...", flush=True)
    t_rvc = time.perf_counter()
    ok = _run_rvc_batch(adj_pairs)
    print(f"  {'✓' if ok else '✗'} รวม {time.perf_counter()-t_rvc:.1f}s")

    done = [out for _, out in adj_pairs if os.path.isfile(out)]
    return done


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", action="store_true",
                        help="สร้างไฟล์เสียงด้วย (ต้องการ edge-tts, ffmpeg, rvc_venv)")
    args = parser.parse_args()

    print("=" * 65)
    print(f"model: {MODEL}  |  {OLLAMA_URL}")
    print("=" * 65)

    # ── ยิงทีละประโยค ─────────────────────────────────────────────────────────
    # results: (label, reply_raw, reply_fixed, stem)
    #   reply_raw   = qwen ตอบมา (แสดงผล)
    #   reply_fixed = strip_emoji + fix_pronouns (เข้า TTS)
    results: list[tuple[str, str, str, str]] = []
    for label, prompt in TEST_PROMPTS:
        print(f"\n[{label}]")
        print(f"  in       → {prompt}")
        reply_raw, elapsed = ollama_chat(prompt)
        reply_fixed = fix_pronouns(strip_emoji(reply_raw))
        print(f"  out      → {reply_raw}")
        changes = []
        if strip_emoji(reply_raw) != reply_raw:
            changes.append("ลบอีโมจิ")
        if reply_fixed != strip_emoji(reply_raw):
            changes.append("แก้สรรพนาม")
        if changes:
            print(f"  tts-safe → {reply_fixed}  ← {', '.join(changes)}")
        print(f"             ({elapsed:.1f}s)")
        results.append((label, reply_raw, reply_fixed, f"tone_{label}"))

    # ── ตรวจสอบโทน ──────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"{'ประเภท':<12} {'~':^4} {'...':^5} {'เลข':^5} {'สะอาด':^7}  ข้อความ (raw)")
    print("-" * 65)
    for label, reply_raw, reply_fixed, _ in results:
        has_tilde   = "~"    in reply_raw
        has_dots    = "..."  in reply_raw
        has_num     = any(c.isdigit() for c in reply_raw)
        has_issues  = reply_fixed != strip_emoji(reply_raw) or strip_emoji(reply_raw) != reply_raw
        bad_words   = any(w in reply_raw for w in ["ครับ", "น้อง", "จ๊ะ", "จ้า", "หนู"])
        print(
            f"  {label:<12}"
            f" {'✓' if has_tilde  else '✗':^3}"
            f" {'✓' if has_dots   else '✗':^4}"
            f" {'✓' if has_num    else '-':^4}"
            f" {'⚠️' if bad_words  else '✓':^5}"
            f"  {reply_raw[:45]}{'…' if len(reply_raw)>45 else ''}"
        )

    # ── เสียง (optional) ─────────────────────────────────────────────────────
    if args.audio:
        # ส่ง reply_fixed (ไม่มีอีโมจิ + สรรพนามถูก) เข้า TTS
        audio_items = [(label, reply_fixed, stem)
                       for label, _, reply_fixed, stem in results]
        out_files = make_audio_batch(audio_items)
        print(f"\n[Audio] เสร็จ {len(out_files)}/{len(results)} ไฟล์")
        for f in out_files:
            print(f"  {f}")
    else:
        print("\n💡 เพิ่ม --audio เพื่อสร้างไฟล์เสียงด้วย")

    print("=" * 65)


if __name__ == "__main__":
    main()
