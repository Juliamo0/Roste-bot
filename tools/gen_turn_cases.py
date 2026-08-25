"""
สร้างชุดเสียงทดสอบ turn-taking — ประโยคที่ "หยุดคิด" กลางทาง — สำหรับ bench_turn_taking.py

ปัญหาที่ต้องการวัด: stt_listener.py ตัดประโยคเมื่อเงียบเกิน SILENCE_MS (800ms) ซึ่งหักกลาง
ประโยคทุกทีที่คนพูดเว้นวรรคคิดนานเกินนั้น เช่น "เออ คือเมื่อวานผมไปดูโน้ตบุ๊กมาสองรุ่น
... [หยุดคิด] ... รอสเต้คิดว่าอันไหนดีกว่ากัน" กลายเป็นสองก้อน บอทตอบครึ่งแรกแล้ว
คำถามจริง (ครึ่งหลัง) หายไป — ไฟล์ชุดนี้สร้างช่องหยุด "เท่าที่วางใจไว้พอดี" (edge-tts
ทีละช่วงประโยค + ต่อด้วย digital silence กี่ ms ก็ได้ตามสเปก) เพื่อให้ bench วัดได้ว่า
กลยุทธ์ตัดประโยคแบบไหนเก็บประโยคไว้ครบและตอบช้าไปเท่าไร

วิธีสร้าง: เจนแต่ละช่วงด้วย edge-tts แยกกัน (VOICE เดียวกับ fallback ใน voice.py)
แล้ว trim หัว/ท้ายทิ้งก่อนประกบ — จำเป็น เพราะ edge-tts แถมความเงียบต้นไฟล์ ~200ms+
ท้ายไฟล์ ~900ms+ มาให้เอง ถ้าไม่ trim ช่องหยุดจริงจะยาวกว่าที่ประกาศใน manifest
จากนั้นประกบด้วย silence 0x00 ตรงตามจำนวน ms (stdlib wave/audioop ไม่ใช้ dependency
ใหม่) + หัวไฟล์ 300ms / ท้ายไฟล์ 2000ms — ท้ายต้องยาวกว่า threshold ที่แพงสุดใน bench
(1500ms) เพราะเลียนแบบที่คนพูดจบแล้ว "เงียบต่อ" ไม่ใช่ปิดไมค์ทันที กลยุทธ์ที่รอนาน
จึงตัดเองได้ภายในไฟล์ ไม่ต้องพึ่ง EOF

manifest.json เก็บต่อเคส: wav, group, ข้อความเต็ม (ground truth), ข้อความ+offset
เริ่ม-จบ (ms) ของแต่ละช่วง, pause_ms และ speech_end_ms = จุดที่เสียงพูดจบจริง
(speech_end คือ anchor ให้ bench คำนวณ "ตอบช้ากว่าที่คนพูดจบไปกี่ ms")

expect = พฤติกรรมที่กลยุทธ์ที่ "ดี" ควรทำ ใช้ตัดสินคะแนนใน bench:
  whole = ต้องเก็บทั้งประโยคไว้ก้อนเดียว (หยุดเพราะกำลังคิด/คำเชื่อมค้าง/ไล่ list)
  split = ตัดก่อนถือว่าถูกแล้ว (ประโยคแรกจบสมบูรณ์ ที่เหลือเป็นความคิดแทรกทีหลัง
          — บอทตอบปุ๊บคนพูดค่อยเสริม ดีกว่าบอทนิ่งรอ)

รันด้วย: venv\\Scripts\\python.exe tools\\gen_turn_cases.py
         (edge_tts อยู่ใน venv หลัก ไม่ใช่ f5_venv — เหมือน gen_stt_cases.py)

ข้อจำกัดที่ต้องรู้ตอนอ่านผล: ช่องหยุดในไฟล์ชุดนี้เป็น digital silence ล้วน (RMS = 0
ตรงตามสเปก) แต่ช่วงหยุดคิดของคนจริงมีเสียงหายใจ เสียงห้อง เสียง "อ้า.. เอ่อ" และที่
สำคัญที่สุดคือโน้ตเสียง/พลังงานปลายประโยคที่บอกใบ้ว่า "ยังไม่จบ" — สัญญาณ turn-taking
ที่งานวิจัยเรื่อง turn-taking ใช้กัน ซึ่ง benchmark นี้วัด "ไม่ได้เลย" detector ทุก
กลยุทธ์เห็นช่องเงียบชัดเจนเกินจริงเท่ากันหมด ตัวเลขที่ได้จึงเป็น "พื้นบน" (optimistic)
ใช้*เรียงลำดับ*กลยุทธ์ได้ แต่ทำนายพฤติกรรมในห้อง voice จริง (comfort noise ระดับไหน
จะล้ำ _SILENCE_RMS หรือไม่) ไม่ได้ อีกข้อ: เสียงเดียว สำเนียงเดียว ไม่มีคนอื่นพูดแทรก
และ ASR ผิดเองได้ คะแนน ครบ/แตก ที่ bench รายงานจึงต้องอ่านคู่กับ CER ของข้อความเสมอ
"""
import sys, os, json, asyncio, subprocess, shutil, hashlib, wave, audioop

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)   # import โมดูลฝั่ง root (script อยู่ใน tools/) — เหมือน bench_turn_taking.py
OUT_DIR = os.path.join(BOT_DIR, "f5_out", "turn_cases")
SEG_CACHE = os.path.join(OUT_DIR, "_segcache")   # เสียงช่วงประโยคซ้ำๆ (core p500/900/1600 ใช้ชุดเดียวกัน) — cache ไว้ไม่ต้องยิง net ซ้ำ
MANIFEST = os.path.join(OUT_DIR, "manifest.json")

# เสียงเดียวกับ fallback ใน voice.py (VOICE) — เหตุผลเดียวกับ gen_stt_cases.py
VOICE = "th-TH-PremwadeeNeural"

# ── พารามิเตอร์ประกอบไฟล์ ──────────────────────────────────────────────────────
TARGET_RATE = 16000        # 16kHz mono s16 — ฟอร์แมตเดียวกับที่ stt_listener เขียนให้ ASR
CHUNK_MS    = 20           # granular ของการ trim/ตรวจ RMS — ต้องตรงกับ CHUNK_MS ใน bench
# ตัดขอบด้วยเกณฑ์ RMS ค่าเดียวกับ _SILENCE_RMS ของ stt_listener เพื่อให้ "จุดเริ่ม/จบ
# เสียง" ที่ generator คิด กับที่ detector ใน bench เห็น คือเกณฑ์เดียวกัน (import เอา
# ค่าจริง ถ้า import ไม่ได้ใช้ 150 เหมือนเดิม + แจ้งดังๆ ไม่ให้ตัวเลขเพี้ยนแบบเงียบๆ)
try:
    from stt_listener import _SILENCE_RMS as TRIM_RMS
except Exception as _exc:
    print(f"[!] import _SILENCE_RMS จาก stt_listener ไม่ได้ ({_exc}) — ใช้ fallback 150")
    TRIM_RMS = 150
PAD_MS            = 60     # คงเงียบไว้รอบๆ ช่วงพูดหลัง trim กันหัดพยัญชนะต้น/สระท้าย
LEAD_SILENCE_MS   = 300    # เงียบหัวไฟล์ — ไม่ให้เสียงเริ่มที่ byte 0 เหมือนสตรีมจริง
TAIL_SILENCE_MS   = 2000   # เงียบท้ายไฟล์ > threshold แพงสุด (1500) — ดูเหตุผลใน docstring

# ── ชุดทดสอบ ───────────────────────────────────────────────────────────────────
# 5 กลุ่ม: core (โจทย์หลัก — เล่ายาว ถามท้าย), connective (ค้างคำเชื่อม),
# done_then_add (พูดจบแล้วเสริมทีหลัง — ตัดเร็วถือว่าถูก), control (ประโยคสั้น
# ไม่มีจังหวะหยุด — ต้องไม่ถดถอย), list (หยุดเพราะกำลังไล่ทีละข้อ)
# pause ของกลุ่ม core เลือกเป็นบันได 500/900/1600 โดยใจความ: 500 < 800 = กฎเดิม
# ก็รอด (baseline ว่าช่องสั้นไม่มีปัญหา), 900 = หลุดกฎเดิมแต่เอา 1200 รอด,
# 1600 = หลุดทุก threshold ที่รอไหว จะได้เห็นว่า "ขยับ threshold อย่างเดียวแก้ไม่จบ"
CASES = [
    # (id, group, [ข้อความแต่ละช่วง], pause_ms ระหว่างช่วง, expect)
    ("core01_p500",    "core", ["เออ คือเมื่อวานผมไปดูโน้ตบุ๊กมาสองรุ่น",
                                "รอสเต้คิดว่าอันไหนดีกว่ากัน"], 500, "whole"),
    ("core02_p900",    "core", ["เออ คือเมื่อวานผมไปดูโน้ตบุ๊กมาสองรุ่น",
                                "รอสเต้คิดว่าอันไหนดีกว่ากัน"], 900, "whole"),
    ("core03_p1600",   "core", ["เออ คือเมื่อวานผมไปดูโน้ตบุ๊กมาสองรุ่น",
                                "รอสเต้คิดว่าอันไหนดีกว่ากัน"], 1600, "whole"),
    # กับดัก lexical ตั้งใจ: ช่วงแรกลงท้าย "ดูนะ" ซึ่งหูคนไทยรู้ว่ายังไม่จบ แต่ heuristic
    # คำลงท้ายมักอ่านว่า "จบ" — bench ควรเห็นความพลาดแบบนี้ตรงๆ ไม่ซ่อน
    ("core04_trip900", "core", ["เมื่อคืนผมลองเขียนแผนทริปไปเชียงใหม่ดูนะ",
                                "รอสเต้ช่วยเช็คสภาพอากาศช่วงนั้นให้ทีไหม"], 900, "whole"),

    ("conn01_laewgor", "connective", ["พรุ่งนี้ผมจะไปส่งของที่แถวอารีย์แล้วก็",
                                      "แวะกินข้าวกับเพื่อน รอสเต้ช่วยตั้งปลุกเก้าโมงเช้าให้หน่อย"], 900, "whole"),
    ("conn02_kue",     "connective", ["เมื่อวานดูซีรีส์รวดสามตอนต่อกันคือ",
                                      "มันดันเล่าเรื่องย้อนหลังซะงั้น รอสเต้ว่าผมควรดูต่อไหม"], 950, "whole"),
    ("conn03_pramanwa","connective", ["กำลังคิดจะซื้อการ์ดจอรุ่นใหม่ประมาณว่า",
                                      "งบสิบห้าพันบาท รอสเต้ว่ามันคุ้มไหมเนี่ย"], 1100, "whole"),

    ("add01_song",     "done_then_add", ["รอสเต้เปิดเพลงให้ฟังหน่อยสิ",
                                         "อ๋อ แล้วก็อีกอย่าง พรุ่งนี้เตือนผมไปรับพัสดุด้วย"], 1000, "split"),
    ("add02_rain",     "done_then_add", ["วันนี้ฝนตกหนักจังเลย",
                                         "เออ ลืมบอกไป ช่วยสั่งกาแฟเย็นเปิดให้ผมแก้วหนึ่งนะ"], 1000, "split"),

    ("ctrl01_time",    "control", ["ตอนนี้กี่โมงแล้วรอสเต้"], 0, "whole"),
    ("ctrl02_music",   "control", ["ช่วยเปิดเพลงให้หน่อยสิ"], 0, "whole"),
    ("ctrl03_weather", "control", ["พรุ่งนี้ฝนจะตกไหม"], 0, "whole"),
    ("ctrl04_tired",   "control", ["วันนี้เหนื่อยมากเลยรอสเต้"], 0, "whole"),

    ("list01_two",     "list", ["ช่วยสองอย่างนะ อย่างแรกคือเปิดแอร์ห้องนอน",
                                "อย่างที่สองคือปิดไฟกับทีวีในห้องครัวด้วย"], 1000, "whole"),
]


# ── synth helpers — ทำซ้ำจาก gen_stt_cases.py แทน import ข้าม (เหตุผลเดียวกับที่
#    stt_client.py ทำซ้ำ helper ของ voice.py: script เดี่ยวๆ ควรพกของตัวเองครบ) ──
async def _synth(text: str, out_mp3: str, retries: int = 3) -> None:
    """เจนเสียงผ่าน edge-tts พร้อม retry — network flake เกิดได้ (เหมือน voice.py)"""
    import edge_tts

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            comm = edge_tts.Communicate(text, VOICE)
            await comm.save(out_mp3)
            if os.path.exists(out_mp3) and os.path.getsize(out_mp3) > 0:
                return
            last_err = RuntimeError("ไฟล์ว่าง")
        except Exception as e:
            last_err = e
        if attempt < retries:
            await asyncio.sleep(1.0 * attempt)
    raise RuntimeError(f"edge-tts failed ({retries} attempts): {last_err}") from last_err


def _to_wav16k(mp3_path: str, wav_path: str) -> bool:
    """แปลงเป็น wav 16kHz mono — รูปแบบเดียวกับที่ stt_listener เขียนให้ ASR"""
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_path,
         "-ar", str(TARGET_RATE), "-ac", "1", wav_path],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and os.path.exists(wav_path)


def _load_seg_pcm(wav_path: str) -> bytes:
    """อ่าน wav ช่วงประโยค (ต้อง 16k/mono/s16 เท่านั้น — ป้องกันประกบแล้วเสียงเพี้ยนแบบเงียบๆ)"""
    with wave.open(wav_path, "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (TARGET_RATE, 1, 2):
            raise RuntimeError(f"{wav_path}: format ไม่ใช่ {TARGET_RATE}Hz mono s16")
        return w.readframes(w.getnframes())


def _rms(chunk: bytes) -> int:
    return audioop.rms(chunk, 2)


def _trim_edge_silence(pcm: bytes) -> bytes:
    """ตัดเงียบหัว/ท้ายออก เหลือ pad เล็กๆ — edge-tts แถมเงียบมาเอง ~200-900ms
    (วัดจริงจากไฟล์ทดลอง) ถ้าไม่ตัด ช่องหยุดที่ประกาศ 900ms จะกลายเป็น ~2000ms
    และตัวเลข delay ใน bench จะผิดทั้งชุด คิด offset เป็น chunk 20ms ให้ตรงกับ
    ที่ bench เดินไฟล์ แล้วคง pad ไว้รอบๆ กัน ASR กลืนพยัญชนะต้น"""
    step = TARGET_RATE * 2 * CHUNK_MS // 1000
    pad = TARGET_RATE * 2 * PAD_MS // 1000
    offs = [i for i in range(0, len(pcm) - step + 1, step) if _rms(pcm[i:i + step]) > TRIM_RMS]
    if not offs:
        return pcm[:step]   # เงียบทั้งช่วง = ข้อมูลใช้ไม่ได้ ส่งก้อนสั้นๆ ไปให้ caller เจอ error เอง
    return pcm[max(0, offs[0] - pad):min(len(pcm), offs[-1] + step + pad)]


async def _get_segment_pcm(text: str) -> bytes:
    """PCM ของช่วงประโยคหนึ่ง พร้อม cache ตาม hash ข้อความ — core p500/900/1600
    ใช้ประโยคชุดเดียวกันตั้งใจให้ 'สิ่งเดียวที่ต่างคือความยาวช่องหยุด' cache ทำให้
    ทั้งสามไฟล์ใช้เสียง byte เดียวกันจริง ไม่ใช่เสียง synth คนละรอบ"""
    os.makedirs(SEG_CACHE, exist_ok=True)
    key = hashlib.sha1(f"{VOICE}|{text}".encode("utf-8")).hexdigest()[:16]
    wav = os.path.join(SEG_CACHE, key + ".wav")
    if os.path.exists(wav) and os.path.getsize(wav) > 44:
        return _trim_edge_silence(_load_seg_pcm(wav))

    mp3 = wav + ".mp3"
    await _synth(text, mp3)
    if not _to_wav16k(mp3, wav):
        raise RuntimeError(f"แปลง wav ไม่สำเร็จ: {text[:30]}...")
    os.remove(mp3)
    return _trim_edge_silence(_load_seg_pcm(wav))


def _ms_to_bytes(ms: int) -> int:
    return TARGET_RATE * 2 * ms // 1000


async def main() -> int:
    if not shutil.which("ffmpeg"):
        print("ERR: ไม่พบ ffmpeg ใน PATH — ต้องใช้แปลง mp3 → wav 16k")
        return 1

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"trim RMS threshold: {TRIM_RMS} (ต้องตรงกับ _SILENCE_RMS ของ stt_listener)")

    manifest = []
    for i, (cid, group, seg_texts, pause_ms, expect) in enumerate(CASES, 1):
        try:
            parts = [await _get_segment_pcm(t) for t in seg_texts]
        except Exception as e:
            print(f"[{i:2d}/{len(CASES)}] ERR [{group:13s}] {cid} -> {e}")
            continue

        # ประกอบไฟล์: เงียบหัว → ช่วงพูด/เงียบสลับ → เงียบท้าย พร้อมจด offset จริง (ms)
        buf = bytearray(b"\x00\x00" * (_ms_to_bytes(LEAD_SILENCE_MS) // 2))
        seg_meta, cursor_ms = [], LEAD_SILENCE_MS
        for k, (txt, pcm) in enumerate(zip(seg_texts, parts)):
            start_ms = cursor_ms
            buf += pcm
            cursor_ms += len(pcm) * 1000 // (TARGET_RATE * 2)
            seg_meta.append({"text": txt, "start_ms": start_ms, "end_ms": cursor_ms})
            if k < len(parts) - 1:
                buf += b"\x00\x00" * (_ms_to_bytes(pause_ms) // 2)
                cursor_ms += pause_ms
        speech_end_ms = cursor_ms
        buf += b"\x00\x00" * (_ms_to_bytes(TAIL_SILENCE_MS) // 2)
        cursor_ms += TAIL_SILENCE_MS

        wav_path = os.path.join(OUT_DIR, f"{i:02d}_{cid}.wav")
        with wave.open(wav_path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(TARGET_RATE)
            w.writeframes(bytes(buf))

        manifest.append({
            "id": cid, "group": group, "wav": wav_path,
            "text": " ".join(seg_texts),          # ground truth เต็ม — เทียบกับข้อความที่ bench ถอดได้
            "segments": seg_meta,
            "pause_ms": pause_ms,
            "expect": expect,
            "speech_start_ms": LEAD_SILENCE_MS,
            "speech_end_ms": speech_end_ms,
            "duration_ms": cursor_ms,
        })
        print(f"[{i:2d}/{len(CASES)}] OK  [{group:13s}] {cid:18s} "
              f"pause={pause_ms:>4}ms ช่วง={len(seg_texts)} ยาว={cursor_ms / 1000:.1f}s expect={expect}")

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nสร้างเสร็จ {len(manifest)}/{len(CASES)} ไฟล์")
    print(f"manifest: {MANIFEST}")
    return 0 if manifest else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
