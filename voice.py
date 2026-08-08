"""
voice.py — Roste voice pipeline

text_to_roste_voice(text) -> wav_path:
  F5 pipeline (ถ้าส่ง f5_worker):
    strip_emoji → preprocess → F5 (warm) → RVC (warm/oneshot)
  fallback pipeline:
    strip_emoji → edge-tts → ffmpeg adjust → RVC (warm/oneshot)

text_to_roste_voice_segments(text) -> Iterator[wav_path]:
  แบบ streaming — yield ทีละ segment ทันทีที่เสร็จ (เริ่มเล่นได้ไม่ต้องรอทั้งก้อน)
  fail-safe ต่อ segment: F5 retry 1 ครั้ง → edge-tts → ข้าม segment

RVC warm worker (โหลดโมเดลครั้งเดียว):
  with RvcWorker() as w:
      path = text_to_roste_voice("...", worker=w)

F5 warm worker:
  with F5Worker() as f5:
      path = text_to_roste_voice("...", worker=rvc_w, f5_worker=f5)
"""

import asyncio
import io
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path

# กัน console window เด้งบน Windows ตอน spawn ffmpeg/worker subprocess — จำเป็นตอนรันบอทเบื้องหลัง
# แบบไม่มีหน้าต่าง (pythonw): child ที่เป็น console app ของ parent ที่ไม่มี console จะสร้างหน้าต่างใหม่
# ถ้าไม่ตั้ง flag นี้ → ffmpeg (เด้งทุกครั้งที่พูด) + RVC/F5 worker จะเด้งหน้าต่างกวนจอ
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

import soundfile as sf
from dotenv import load_dotenv

# ไม่ต้อง config handler เอง — bot.py ตั้ง root logger ไว้แล้ว (rotating file + console)
logger = logging.getLogger("roste.voice")

# ── constants ──────────────────────────────────────────────────────────────────
VOICE       = "th-TH-PremwadeeNeural"
SPEED       = 0.90
PITCH_SEMI  = 5.292
OUT_SR      = 40000

# path โมเดลเสียง RVC — ตั้งผ่าน .env (RVC_MODEL_DIR) ได้ เพราะแต่ละเครื่องวางคนละที่
# (แล็ปท็อป D:\rvc_voice_model, server ที่ไม่มีไดรฟ์ D: → เช่น C:\Users\User\rvc_voice_model)
# load_dotenv ที่นี่กัน voice ถูก import ก่อน config → getenv อ่านค่าใน .env ไม่เจอ (idempotent เรียกซ้ำได้)
load_dotenv()
MODEL_DIR   = os.getenv("RVC_MODEL_DIR", r"D:\rvc_voice_model")
DEVICE      = "cuda:0"
INDEX_RATE  = 0.5
PROTECT     = 0.33
F0_UP_KEY   = 0
F0_METHOD   = "rmvpe"

# ── pitch ของเสียง F5 ก่อนเข้า RVC ────────────────────────────────────────────
# ผู้ใช้ปรับใน WavePad แล้วเลือก 108% (จาก 100% เดิม) = ×1.08 = +1.33 semitone
# ทำเป็นขั้นแยกก่อน RVC เพราะ RVC รับ f0_up_key เป็น semitone *จำนวนเต็ม* เท่านั้น
# (+1 = 105.9% ต่ำไป, +2 = 112.2% สูงไป) ปรับ 1.08 ตรงๆ ผ่าน f0_up_key ไม่ได้
# ตั้ง 1.0 เพื่อปิดขั้นตอนนี้ (ข้าม ffmpeg ไปเลย ไม่เสียเวลา)
F5_PITCH_RATIO = 1.08

# ── VoxCPM2 (TTS หลักตัวใหม่) ─────────────────────────────────────────────────
# เลือกแทน F5 เพราะเสียงเป็นธรรมชาติกว่า แลกกับช้ากว่า ~6s/segment
#   VoxCPM2 steps=10 ~12.9s  vs  F5+RVC ~6.8s  (ผู้ใช้ทดสอบแล้วยอมรับ)
#   steps=6 เร็วกว่า (8.5s) แต่ผู้ใช้ฟังแล้วว่า "มีเสียงตะกุกแปลกๆ ไม่ใสเหมือน 10"
#
# ref เป็นเสียง *รอสเต้เอง* (F5 + pitch108 ที่ผู้ใช้คัดแล้ว) ไม่ใช่เสียงคนต้นฉบับ
# → ได้เสียงรอสเต้ตั้งแต่ VoxCPM2 เลย ไม่ต้องผ่าน RVC ซ้ำ
# ใช้ reference_wav_path (โคลนเสียงล้วน) ไม่ใช่ prompt_wav_path (continuation ที่
# เลียนจังหวะ ref มาด้วย) — ผู้ใช้ฟังเทียบแล้วยืนยันว่า ref ดีกว่า prompt ชัดเจน
VOXCPM_ENABLED = True
VOXCPM_STEPS = 10
VOXCPM_CFG = 2.0

# ── ลด latency + เสียงต่อเนื่อง: รวม segment ให้ใหญ่ขึ้นสำหรับ VoxCPM2 ─────────
# วัดแล้ว: gen ≈ 0.067 × chars + 4.6s  → overhead คงที่ ~4.6s ต่อ segment
# (ข้อความ 20 ตัวอักษรยังใช้ 11.5s — ค่าคงที่ครอบงำ ไม่ใช่ความยาวข้อความ)
#
# ผลคือยิ่งซอยย่อย ยิ่งแย่ 2 ทาง:
#   1. overhead คูณจำนวนก้อน (3 ก้อน = 13.8s หายไปเปล่าๆ)
#   2. RTF ~1.67 เจนไม่ทันเล่น → ช่องว่างระหว่างก้อน + โทนเสียงไม่ต่อเนื่อง
#      เพราะแต่ละก้อนเจนแยกกันโดยไม่รู้บริบทของก้อนก่อนหน้า
#
# ตราบใดที่ RTF > 1 จะต้องแลกกันเสมอระหว่าง "รอเสียงแรกนาน" กับ "เสียงต่อเนื่อง"
# กวาดค่าจริงกับคำตอบยาว 178c (segment ดิบ 54/107/23c):
#   limit   ก้อน  เสียงแรก  รวม     รอยต่อ
#   0(ปิด)   3     8.2s     26.1s   2
#   140      2     8.2s     21.6s   1   ← เลือกอันนี้: รอยต่อลด + เร็วขึ้น 4.5s
#   170      2    15.5s     21.6s   1      โดยเสียงแรกไม่ช้าลงเลย
#   200      1    17.1s     17.1s   0      (ต่อเนื่องสุด แต่รอนานเท่าตัว)
#
# 140 คือจุดที่ยุบก้อนท้ายๆ เข้าด้วยกันได้โดยไม่แตะก้อนแรก — ก้อนแรกจึงยังสั้น
# เท่าเดิม ผู้ใช้ได้ยินเสียงเร็วเท่าเดิม แต่ท่อนหลังต่อเนื่องขึ้นและจบเร็วขึ้น
#
# ตั้งสูงมาก = รวมเป็นก้อนเดียว (ต่อเนื่องสุด รอนานสุด)
# ตั้ง 0 = ปิดการรวม (กลับไปใช้ segment ตามที่ตัวซอยแบ่งไว้)
VOXCPM_MERGE_CHARS = 140
# ผ่าน RVC ต่อท้ายไหม — ปกติไม่ต้อง เพราะ ref เป็นเสียงรอสเต้อยู่แล้ว
# (RVC ยังจำเป็นสำหรับ "ร้องเพลง" ซึ่งเป็นคนละเส้นทาง ไม่เกี่ยวกับ TTS)
VOXCPM_THEN_RVC = False
# VOXCPM_REF_AUDIO ประกาศหลัง _ROOT (ดูหมวด VoxCPM2 constants ด้านล่าง)

_ROOT        = Path(__file__).parent
_RVC_VENV_PY = _ROOT / "rvc_venv" / "Scripts" / "python.exe"
_WORKER_PY   = _ROOT / "voice_rvc_worker.py"
_OUT_DIR     = _ROOT / "rvc_out"

# ── VoxCPM2 constants ──────────────────────────────────────────────────────────
_VOXCPM_VENV_PY   = _ROOT / "voxcpm_venv" / "Scripts" / "python.exe"
_VOXCPM_WORKER_PY = _ROOT / "voxcpm_worker.py"
# ref = เสียงรอสเต้เอง (F5 + pitch108 ที่ผู้ใช้คัด) ไม่ใช่เสียงคนต้นฉบับ
# หมายเหตุ: start() ตรวจแค่ venv กับตัว worker script — *ไม่* ตรวจไฟล์ ref
# ถ้า ref หาย worker จะ start ผ่านแล้วไปพังตอน generate() job แรก ซึ่ง fail-safe
# chain จะสลับไป F5 ให้ (เสียงไม่หาย แต่จะเงียบๆ ใช้ engine เดิมตลอดโดยไม่มีใครรู้)
VOXCPM_REF_AUDIO  = str(_ROOT / "ref_audio" / "roste_v2" / "roste_pitch108_long.wav")

# ── F5-TTS constants ───────────────────────────────────────────────────────────
_F5_VENV_PY   = _ROOT / "f5_venv" / "Scripts" / "python.exe"
_F5_WORKER_PY = _ROOT / "f5_worker.py"
F5_REF_AUDIO  = str(_ROOT / "ref_audio" / "lai_seg4_160s.wav")
# เดิมชี้เข้า f5_out/ref_test/ ซึ่งอยู่ใน .gitignore (โฟลเดอร์ output ชั่วคราว) — clone ใหม่จะ
# ไม่มีไฟล์นี้ ทำให้ F5 หายเงียบ (fallback ไป edge-tts โดยไม่มี error ให้เห็น) ย้ายมาไว้ที่
# ref_audio/ ซึ่งเป็นที่ตั้งใจเก็บไฟล์ reference เสียงโดยเฉพาะ (ยัง gitignore เหมือนเดิมผ่าน
# กฎ *.wav — ไม่ commit ไฟล์เสียงจริงขึ้น GitHub แค่ให้เป็นที่เดียวที่ควรวางไฟล์นี้)
F5_REF_TEXT   = "ตีสอง ตีสาม ตีสี่ อะไรทรงเนี้ยแบบก่อนเช้าอ่ะ มันจะเป็นช่วงผีออกอะไรสักอย่างนึง แหลมบาดก็แบบว่า"
F5_SPEED      = 1.0
F5_STEPS      = 32

# ── emoji strip ────────────────────────────────────────────────────────────────
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

def strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


# ── edge-tts ───────────────────────────────────────────────────────────────────

async def _edge_tts_async(text: str, out_wav: str, retries: int = 3) -> None:
    import edge_tts
    last_err: Exception = RuntimeError("unknown")
    for attempt in range(retries):
        if attempt > 0:
            await asyncio.sleep(1.5)
        try:
            comm = edge_tts.Communicate(text, VOICE)
            buf = io.BytesIO()
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            mp3_data = buf.getvalue()
            if not mp3_data:
                raise RuntimeError("No audio received")
            tmp_mp3 = out_wav + ".tmp.mp3"
            with open(tmp_mp3, "wb") as f:
                f.write(mp3_data)
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp_mp3, out_wav],
                capture_output=True,
                creationflags=_NO_WINDOW,
            )
            os.remove(tmp_mp3)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg mp3→wav: {r.stderr.decode(errors='replace')}")
            return
        except Exception as exc:
            last_err = exc
    raise RuntimeError(f"edge-tts failed ({retries} attempts): {last_err}") from last_err


def _edge_tts(text: str, out_wav: str, retries: int = 3) -> None:
    asyncio.run(_edge_tts_async(text, out_wav, retries=retries))


# ── ffmpeg adjust ──────────────────────────────────────────────────────────────

def _atempo_chain(rate: float) -> list[str]:
    filters, r = [], rate
    while r < 0.5:
        filters.append("atempo=0.5")
        r /= 0.5
    while r > 2.0:
        filters.append("atempo=2.0")
        r /= 2.0
    filters.append(f"atempo={r:.8f}")
    return filters


def _ffmpeg_adjust(in_wav: str, out_wav: str, src_sr: int) -> None:
    filters: list[str] = []
    pitch_factor = 2 ** (PITCH_SEMI / 12) if PITCH_SEMI != 0 else 1.0
    if PITCH_SEMI != 0:
        filters.append(f"asetrate={int(src_sr * pitch_factor)}")
        filters.append(f"aresample={src_sr}")
    effective_tempo = SPEED / pitch_factor
    if abs(effective_tempo - 1.0) > 1e-9:
        filters += _atempo_chain(effective_tempo)
    filter_str = ",".join(filters) if filters else "anull"
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", in_wav,
            "-af", filter_str,
            "-ar", str(OUT_SR), "-ac", "1", "-sample_fmt", "s16",
            out_wav,
        ],
        capture_output=True,
        creationflags=_NO_WINDOW,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg adjust failed: {r.stderr.decode(errors='replace')}")


def _adjust(in_wav: str, out_wav: str) -> None:
    src_sr = sf.info(in_wav).samplerate
    _ffmpeg_adjust(in_wav, out_wav, src_sr)


def _pitch_shift(in_wav: str, out_wav: str, ratio: float = F5_PITCH_RATIO) -> str:
    """เปลี่ยน pitch โดย *รักษาความยาวเดิม* แล้วคืน path ของไฟล์ที่ควรใช้ต่อ

    asetrate เปลี่ยน pitch พร้อมความเร็วไปด้วย (เหมือนเร่งเทป) จึงต้อง atempo=1/ratio
    ชดเชยให้ความยาวเท่าเดิม — วิธีเดียวกับ _ffmpeg_adjust ที่ใช้กับ edge-tts อยู่แล้ว

    ratio=1.0 → ไม่ทำอะไร คืน in_wav (ผู้เรียกจึงส่งต่อไฟล์เดิมได้เลย ไม่เสียเวลา)
    ถ้า ffmpeg พัง → คืน in_wav เหมือนกัน เพราะเสียง pitch ไม่ตรงยังดีกว่าไม่มีเสียง
    """
    if abs(ratio - 1.0) < 1e-9:
        return in_wav
    src_sr = sf.info(in_wav).samplerate
    filters = [
        f"asetrate={int(src_sr * ratio)}",
        f"aresample={src_sr}",
        *_atempo_chain(1.0 / ratio),
    ]
    r = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", in_wav,
            "-af", ",".join(filters),
            "-ar", str(src_sr), "-ac", "1",
            out_wav,
        ],
        capture_output=True,
        creationflags=_NO_WINDOW,
    )
    if r.returncode != 0 or not os.path.exists(out_wav):
        logger.warning(
            f"   ⚠️ pitch shift ล้มเหลว ({r.stderr.decode(errors='replace')[:120]}) "
            f"— ใช้เสียง pitch เดิมต่อ"
        )
        return in_wav
    return out_wav


_WORKER_READ_TIMEOUT_SEC = 60   # กัน worker subprocess ค้าง (GPU stall/driver hang) ทำ voice_lock/_tts_lock ค้างตลอดไป


def _readline_with_timeout(proc: subprocess.Popen, timeout: float) -> str | None:
    """อ่านบรรทัดเดียวจาก stdout ของ subprocess โดยจำกัดเวลารอ
    readline() ธรรมดาไม่มี timeout ในตัว และ select() ใช้กับ pipe บน Windows ไม่ได้
    เลยต้องอ่านในเธรดแยกแล้วรอผลแบบมี timeout แทน (thread ที่ยังอ่านค้างอยู่จะถูกทิ้งไว้เป็น daemon —
    ผู้เรียกต้อง kill subprocess เองถ้าจะเลิกใช้ worker ตัวนี้ ไม่งั้น thread จะรอ readline ค้างไปเรื่อยๆ)
    คืน None ถ้าหมดเวลาไม่ได้ผลลัพธ์"""
    result: queue.Queue = queue.Queue(maxsize=1)

    def _reader():
        try:
            line = proc.stdout.readline()
        except Exception:
            line = ""
        result.put(line)

    threading.Thread(target=_reader, daemon=True).start()
    try:
        return result.get(timeout=timeout)
    except queue.Empty:
        return None


_STDERR_RING_SIZE = 50   # เก็บบรรทัด stderr ล่าสุดไว้รายงานถ้า worker ตายก่อน ready


def _drain_stderr(proc: subprocess.Popen, ring: "deque[str]") -> None:
    """อ่าน stderr ของ worker subprocess ทีละบรรทัดตลอดอายุ process — เก็บบรรทัดล่าสุดไว้ใน ring
    buffer (ใช้ตอน error path รายงานสาเหตุที่ worker ตายก่อน ready) และ log เป็น DEBUG (เนื้อหา
    ML library spam ตามปกติ ไม่ควรท่วม INFO)

    ต้องเริ่ม thread นี้ทันทีหลัง Popen — ไม่ใช่รอหลัง ready — เพราะช่วงโหลดโมเดลคือช่วงที่ stderr
    พ่นเยอะสุด (torch/cuda warnings ฯลฯ) ถ้าไม่มีใคร drain แล้ว pipe buffer เต็ม (~64KB บน Windows)
    subprocess จะ block ตอนเขียน stderr เพิ่ม — อาการที่เห็นคือ TTS timeout ที่หาสาเหตุไม่เจอ เพราะ
    worker ไม่ได้ตายจริง แค่ค้างรอเขียน stderr ที่ไม่มีใครอ่าน

    thread เป็น daemon จบเองเมื่อ pipe ปิด (readline คืน "") ไม่ต้อง join ตอน stop()"""
    try:
        for line in iter(proc.stderr.readline, ""):
            ring.append(line.rstrip("\n"))
            logger.debug(f"   [worker stderr] {line.rstrip()}")
    except (ValueError, OSError):
        pass  # pipe ถูกปิดระหว่างอ่าน (stop() เรียก stdin.close() พอดีช่วงนี้) — ไม่ใช่ error จริง


# ── RVC warm worker ────────────────────────────────────────────────────────────

class RvcWorker:
    """
    RVC subprocess ที่โหลดโมเดลครั้งเดียว รับงานหลายครั้งผ่าน stdin/stdout JSON
    warm inference ~1.4s/ไฟล์ (vs ~8s cold ทุกครั้ง)

    Context manager (แนะนำ):
        with RvcWorker() as w:
            path = text_to_roste_voice("...", worker=w)

    หรือ manual:
        w = RvcWorker(); w.start()
        ...
        w.stop()
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self.load_time: float = 0.0
        self._stderr_ring: deque[str] = deque(maxlen=_STDERR_RING_SIZE)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        if not _RVC_VENV_PY.exists():
            raise RuntimeError(f"ไม่พบ rvc_venv: {_RVC_VENV_PY}")
        if not _WORKER_PY.exists():
            raise RuntimeError(f"ไม่พบ voice_rvc_worker.py: {_WORKER_PY}")

        t0 = time.perf_counter()
        self._proc = subprocess.Popen(
            [str(_RVC_VENV_PY), str(_WORKER_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        # เริ่ม drain stderr ทันที (ก่อน ready) — กัน pipe buffer เต็มตอนโหลดโมเดล (ดู docstring _drain_stderr)
        threading.Thread(target=_drain_stderr, args=(self._proc, self._stderr_ring), daemon=True).start()
        # scan stdout until we see {"status": "ready"} — skip RVC loading prints
        while True:
            line = self._proc.stdout.readline()
            if not line:
                # ให้ drain thread เก็บบรรทัดสุดท้ายๆ เข้า ring buffer ให้ครบก่อน — stdout ปิด
                # (worker ตาย) ไม่ได้แปลว่า drain thread อ่าน stderr ทันบรรทัดสุดท้ายเสมอไป
                time.sleep(0.2)
                err = "\n".join(self._stderr_ring)
                raise RuntimeError(f"RVC worker died before ready.\nstderr:\n{err}")
            line = line.strip()
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            if resp.get("status") == "ready":
                break
            if resp.get("status") == "error":
                raise RuntimeError(f"RVC worker init error: {resp.get('msg')}")
        self.load_time = time.perf_counter() - t0

    def convert(self, input_path: str, output_path: str,
                timeout: float = _WORKER_READ_TIMEOUT_SEC) -> float:
        """แปลงไฟล์เดียว คืน elapsed seconds (warm ~1.4s)"""
        if not self.alive:
            raise RuntimeError("RvcWorker not running (call start() first)")
        req = json.dumps({"input": input_path, "output": output_path})
        self._proc.stdin.write(req + "\n")
        self._proc.stdin.flush()
        # scan for JSON response
        while True:
            line = _readline_with_timeout(self._proc, timeout)
            if line is None:
                self._kill()
                raise RuntimeError(f"RVC worker ไม่ตอบสนองเกิน {timeout:.0f}s (killed)")
            if not line:
                raise RuntimeError("RVC worker closed unexpectedly")
            line = line.strip()
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
        if resp.get("status") == "error":
            raise RuntimeError(f"RVC error: {resp.get('msg')}")
        return float(resp.get("elapsed", 0.0))

    def _kill(self) -> None:
        """ฆ่า process ทันที (ไม่รอ) — เรียกตอน worker ค้างเกิน timeout กัน convert()/generate()
        ครั้งถัดไปพังซ้ำแบบเดิม ทำให้ .alive กลาย False ให้ fail-safe chain สลับไป edge-tts แทน"""
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> "RvcWorker":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


# ── F5 warm worker ────────────────────────────────────────────────────────────

class F5Worker:
    """
    F5-TTS subprocess ที่โหลดโมเดลครั้งเดียว รับ job ผ่าน stdin/stdout
    warm inference ~3-5s/ไฟล์ (vs ~20s cold)
    Protocol: stdin JSON → stdout "OK:<path>|time=Xs|dur=Ys" หรือ "ERR:<msg>"
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self.load_time: float = 0.0
        self._stderr_ring: deque[str] = deque(maxlen=_STDERR_RING_SIZE)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        if not _F5_VENV_PY.exists():
            raise RuntimeError(f"ไม่พบ f5_venv: {_F5_VENV_PY}")
        if not _F5_WORKER_PY.exists():
            raise RuntimeError(f"ไม่พบ f5_worker.py: {_F5_WORKER_PY}")

        t0 = time.perf_counter()
        self._proc = subprocess.Popen(
            [str(_F5_VENV_PY), str(_F5_WORKER_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        # เริ่ม drain stderr ทันที (ก่อน ready) — กัน pipe buffer เต็มตอนโหลดโมเดล (ดู docstring _drain_stderr)
        threading.Thread(target=_drain_stderr, args=(self._proc, self._stderr_ring), daemon=True).start()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                # ให้ drain thread เก็บบรรทัดสุดท้ายๆ เข้า ring buffer ให้ครบก่อน (เหตุผลเดียวกับ
                # RvcWorker.start() ด้านบน)
                time.sleep(0.2)
                err = "\n".join(self._stderr_ring)
                raise RuntimeError(f"F5 worker died before ready.\nstderr:\n{err}")
            if line.strip().startswith("F5_WORKER_READY"):
                break
        self.load_time = time.perf_counter() - t0

    def generate(
        self,
        ref_audio: str,
        ref_text: str,
        gen_text: str,
        out_path: str,
        speed: float = 1.0,
        steps: int = 32,
        timeout: float = _WORKER_READ_TIMEOUT_SEC,
    ) -> float:
        """สร้างเสียง คืน duration seconds"""
        if not self.alive:
            raise RuntimeError("F5Worker not running (call start() first)")
        job = json.dumps({
            "ref_audio": ref_audio,
            "ref_text":  ref_text,
            "gen_text":  gen_text,
            "out_path":  out_path,
            "speed":     speed,
            "steps":     steps,
        })
        self._proc.stdin.write(job + "\n")
        self._proc.stdin.flush()
        while True:
            line = _readline_with_timeout(self._proc, timeout)
            if line is None:
                self._kill()
                raise RuntimeError(f"F5 worker ไม่ตอบสนองเกิน {timeout:.0f}s (killed)")
            if not line:
                raise RuntimeError("F5 worker closed unexpectedly")
            line = line.strip()
            if line.startswith("OK:") or line.startswith("ERR:"):
                break
        if line.startswith("ERR:"):
            raise RuntimeError(f"F5 error: {line[4:]}")
        dur = 0.0
        for part in line[3:].split("|"):
            if part.startswith("dur="):
                try:
                    dur = float(part[4:].rstrip("s"))
                except ValueError:
                    pass
        return dur

    def _kill(self) -> None:
        """ฆ่า process ทันที — เรียกตอน worker ค้างเกิน timeout กัน generate() ครั้งถัดไปพังซ้ำแบบเดิม
        ทำให้ .alive กลาย False ให้ fail-safe chain สลับไป edge-tts แทน"""
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.write("EXIT\n")
                self._proc.stdin.flush()
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> "F5Worker":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


class VoxCpmWorker:
    """
    VoxCPM2 subprocess — โครงเดียวกับ F5Worker (โหลดโมเดลครั้งเดียว รับ job ทาง stdin)

    cold load ~75s (ช้ากว่า F5 ~18s มาก) จึงต้อง warm ตอน startup เหมือนตัวอื่น
    warm inference ~12.9s/segment ที่ steps=10

    Protocol: stdin JSON → stdout "OK:<path>|time=Xs|dur=Ys" หรือ "ERR:<msg>"
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self.load_time: float = 0.0
        self._stderr_ring: deque[str] = deque(maxlen=_STDERR_RING_SIZE)

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        if not _VOXCPM_VENV_PY.exists():
            raise RuntimeError(f"ไม่พบ voxcpm_venv: {_VOXCPM_VENV_PY}")
        if not _VOXCPM_WORKER_PY.exists():
            raise RuntimeError(f"ไม่พบ voxcpm_worker.py: {_VOXCPM_WORKER_PY}")
        # ตรวจ ref ตั้งแต่ start() — ไม่งั้นจะ start ผ่านแล้วไปพังทุก job เงียบๆ
        # (fail-safe สลับไป F5 ให้ ผู้ใช้เลยไม่มีทางรู้ว่า VoxCPM2 ไม่เคยทำงานเลย)
        if not os.path.exists(VOXCPM_REF_AUDIO):
            raise RuntimeError(f"ไม่พบ ref audio ของ VoxCPM2: {VOXCPM_REF_AUDIO}")

        t0 = time.perf_counter()
        self._proc = subprocess.Popen(
            [str(_VOXCPM_VENV_PY), str(_VOXCPM_WORKER_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        threading.Thread(target=_drain_stderr, args=(self._proc, self._stderr_ring),
                         daemon=True).start()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                time.sleep(0.2)   # ให้ drain thread เก็บบรรทัดท้ายๆ ให้ครบก่อน
                err = "\n".join(self._stderr_ring)
                raise RuntimeError(f"VoxCPM worker died before ready.\nstderr:\n{err}")
            if line.strip().startswith("VOXCPM_WORKER_READY"):
                break
        self.load_time = time.perf_counter() - t0

    def generate(
        self,
        text: str,
        out_path: str,
        ref_audio: str = VOXCPM_REF_AUDIO,
        steps: int = VOXCPM_STEPS,
        cfg: float = VOXCPM_CFG,
        timeout: float = _WORKER_READ_TIMEOUT_SEC,
    ) -> float:
        """สร้างเสียง คืน duration seconds"""
        if not self.alive:
            raise RuntimeError("VoxCpmWorker not running (call start() first)")
        job = json.dumps({
            "text":      text,
            "ref_audio": ref_audio,
            "out_path":  out_path,
            "steps":     steps,
            "cfg":       cfg,
        }, ensure_ascii=False)
        self._proc.stdin.write(job + "\n")
        self._proc.stdin.flush()
        while True:
            line = _readline_with_timeout(self._proc, timeout)
            if line is None:
                self._kill()
                raise RuntimeError(f"VoxCPM worker ไม่ตอบสนองเกิน {timeout:.0f}s (killed)")
            if not line:
                raise RuntimeError("VoxCPM worker closed unexpectedly")
            line = line.strip()
            if line.startswith("OK:") or line.startswith("ERR:"):
                break
        if line.startswith("ERR:"):
            raise RuntimeError(f"VoxCPM error: {line[4:]}")
        dur = 0.0
        for part in line[3:].split("|"):
            if part.startswith("dur="):
                try:
                    dur = float(part[4:].rstrip("s"))
                except ValueError:
                    pass
        return dur

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.write("EXIT\n")
                self._proc.stdin.flush()
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self) -> "VoxCpmWorker":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()


# ── RVC one-shot (cold fallback) ───────────────────────────────────────────────

def _find_model_files() -> tuple[str | None, str | None]:
    if not os.path.isdir(MODEL_DIR):
        return None, None
    files = os.listdir(MODEL_DIR)
    pth = next((f for f in files if f.endswith(".pth")), None)
    idx = next((f for f in files if f.endswith(".index")), None)
    return (
        os.path.join(MODEL_DIR, pth) if pth else None,
        os.path.join(MODEL_DIR, idx) if idx else None,
    )


def _rvc_oneshot(in_wav: str, out_wav: str) -> None:
    """Cold load ทุกครั้ง (~8s) — ใช้เมื่อไม่มี RvcWorker"""
    model_path, index_path = _find_model_files()
    if not model_path:
        raise RuntimeError(f"ไม่พบ .pth ใน {MODEL_DIR}")

    cfg = {
        "model_path": model_path,
        "index_path": index_path or "",
        "device": DEVICE,
        "index_rate": INDEX_RATE,
        "protect": PROTECT,
        "in_wav": in_wav,
        "out_wav": out_wav,
    }
    tmp_cfg = os.path.join(tempfile.gettempdir(), "voice_rvc_oneshot.json")
    with open(tmp_cfg, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    inline = f"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# torch>=2.6 flipped torch.load default to weights_only=True, which rejects
# fairseq's hubert_base.pt and makes RVC fail with a downstream
# "'tuple' object has no attribute 'dtype'". Same patch as voice_rvc_worker.py —
# this cold-fallback path was missed when the worker was fixed.
import torch as _torch
_orig_load = _torch.load
def _load_compat(*a, **kw):
    kw.setdefault("weights_only", False)
    return _orig_load(*a, **kw)
_torch.load = _load_compat

from rvc_python.infer import RVCInference
with open({repr(tmp_cfg)}, encoding='utf-8') as f:
    c = json.load(f)
rvc = RVCInference(device=c['device'])
rvc.load_model(c['model_path'], index_path=c['index_path'] or None)
rvc.set_params(f0up_key=0, f0method='rmvpe',
               index_rate=c['index_rate'], protect=c['protect'])
os.makedirs(os.path.dirname(os.path.abspath(c['out_wav'])), exist_ok=True)
rvc.infer_file(input_path=c['in_wav'], output_path=c['out_wav'])
print('done', flush=True)
"""
    r = subprocess.run(
        [str(_RVC_VENV_PY), "-c", inline],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=_NO_WINDOW,
    )
    if r.returncode != 0:
        raise RuntimeError(f"RVC oneshot failed:\n{r.stderr}")


# ── Thai text splitter ────────────────────────────────────────────────────────

# ความยาว segment ที่ "กำลังดี" สำหรับ F5 — ไม่ใช่เพดานตายตัว แต่เป็นเป้าที่ตัวซอยพยายามเข้าใกล้
#
# ทำไมต้องมีเป้า ไม่ใช่แค่เพดาน: เดิมใช้แต่เพดาน (max_chars) ทำให้ได้ segment ยาวไม่เท่ากันมาก
# (วัดจริงจากคำตอบพยากรณ์อากาศ: 31c / 120c / 144c ต่างกัน 4 เท่า) — segment แรกสั้นเกินจนเล่นจบ
# ก่อนอันถัดไปจะ generate เสร็จ ผู้ฟังเลยได้ยินเงียบคั่นทั้งที่ระบบตามทันอยู่
_SEG_TARGET_CHARS = 90    # เป้าหมาย ~90c ≈ เสียง 3-4 วินาที (นานพอให้เจนอันถัดไปทัน)
_SEG_MIN_CHARS    = 45    # สั้นกว่านี้ให้ยุบรวมกับเพื่อนบ้าน กันเศษประโยคห้วนๆ


def _thai_word_bounds(text: str) -> list[int]:
    """คืนตำแหน่ง (index) ทุกจุดที่เป็น "ขอบเขตคำ" ของภาษาไทย — ตัดตรงนี้เท่านั้นถึงจะปลอดภัย

    ภาษาไทยไม่เขียนเว้นวรรคระหว่างคำ การตัดด้วยการนับตัวอักษรจึงผ่ากลางคำได้ง่ายมาก
    (เจอจริง: ตัดที่ตัวที่ 100 ได้ 'ทุกวั' | 'นที่ผ่าน' — คำว่า "วัน" ถูกผ่าครึ่ง F5 อ่านเพี้ยน)
    ใช้ newmm ของ pythainlp หาขอบเขตคำจริง — keep_whitespace=True สำคัญมาก เพราะต้องได้
    เนื้อหาคืนครบทุกตัวอักษร (ยืนยันแล้วว่า ''.join(tokens) == text)

    คืน [] ถ้า tokenize ไม่ได้ — ผู้เรียกต้องถือว่า "ไม่มีจุดตัดปลอดภัย" แล้วไม่ตัดเลย
    """
    try:
        from pythainlp.tokenize import word_tokenize
        tokens = word_tokenize(text, engine="newmm", keep_whitespace=True)
    except Exception:
        return []
    if "".join(tokens) != text:
        return []           # tokenizer ทำเนื้อหาเพี้ยน — ไม่ยอมใช้ ปลอดภัยไว้ก่อน
    bounds, off = [], 0
    for tok in tokens:
        off += len(tok)
        bounds.append(off)
    return bounds


def _cut_at_word_bound(text: str, target: int, bounds: list[int]) -> int:
    """หาจุดตัดที่เป็นขอบเขตคำ ใกล้ target ที่สุด — คืน 0 ถ้าไม่มีจุดที่ใช้ได้เลย

    เลือกจากขอบเขตคำที่อยู่ในช่วง [target*0.5, target*1.6] แล้วเอาตัวใกล้ target ที่สุด
    (ยอมให้เลย target ได้บ้าง ดีกว่าตัดสั้นจนเป็นเศษ) — ถ้าไม่มีเลยในช่วงนั้นคืน 0
    แปลว่า "ไม่ควรตัด" ปล่อยให้ segment ยาวไปดีกว่าตัดผิดที่จนเสียงเพี้ยน
    """
    if not bounds:
        return 0
    lo, hi = int(target * 0.5), int(target * 1.6)
    usable = [b for b in bounds if lo <= b <= hi and b < len(text)]
    if not usable:
        return 0
    return min(usable, key=lambda b: abs(b - target))


def _split_thai_text(text: str, max_chars: int = 300,
                     target: int = _SEG_TARGET_CHARS) -> list[str]:
    """แบ่งข้อความไทยสำหรับ F5 โดย "ตัดเฉพาะจุดที่ปลอดภัย" เรียงตามความน่าเชื่อถือ:

      1. ขอบเขตประโยคจาก crfcut  — ดีสุด โมเดลเข้าใจไวยากรณ์
      2. ขอบเขตคำจาก newmm       — กันตัดกลางคำ (ไทยไม่มีตัวคั่นคำ ตัดผิด = อ่านเพี้ยน)
      3. ไม่ตัดเลย               — ถ้าไม่มีจุดปลอดภัย ยอมให้ยาวดีกว่าเสียงพัง

    ต่างจากเดิมที่ fallback เป็น `remaining[:max_chars]` ดิบๆ (ตัดกลางคำได้) และใช้แค่
    เพดานความยาว ทำให้ segment ยาวไม่เท่ากันมากจนเกิดช่องเงียบระหว่างเล่น — ตอนนี้เล็งที่
    `target` เป็นหลัก แล้วยุบตัวที่สั้นเกิน (_SEG_MIN_CHARS) รวมกับเพื่อนบ้าน

    ช่องว่างระหว่างประโยคถูกรักษาไว้ (ไม่ strip ทิ้งกลางทาง) เพราะวัดแล้วว่ามีผลต่อจังหวะ
    หยุดที่ F5 สังเคราะห์ออกมาจริง — ข้อความเดียวกันแบบมี/ไม่มีช่องว่างให้ silence gap
    ต่างกัน (5 จังหวะ vs 3 จังหวะ)
    """
    text = text.strip()
    if not text:
        return []

    # ── ชั้น 1: ขอบเขตประโยค ──
    pieces: list[str] = []
    try:
        from pythainlp.tokenize import sent_tokenize
        pieces = [s for s in sent_tokenize(text, engine="crfcut") if s.strip()]
    except Exception:
        pieces = []
    if not pieces:
        pieces = [text]

    # ── ชั้น 2: ตัวไหนยังยาวเกินไป ซอยต่อที่ขอบเขตคำ ──
    # เกณฑ์คือ target (ไม่ใช่ max_chars) — max_chars เป็นเพดานกันพังของ F5 ส่วนเป้าหมาย
    # ที่อยากได้จริงคือความยาวสม่ำเสมอราว target เผื่อไว้เล็กน้อย (1.25x) ไม่ให้ซอยถี่เกิน
    # จนเป็นเศษ แต่ก็ไม่หลวมจนปล่อยก้อน 125c ผ่านทั้งที่ target แค่ 90
    limit = min(max_chars, int(target * 1.25))
    refined: list[str] = []
    for piece in pieces:
        while len(piece) > limit:
            bounds = _thai_word_bounds(piece)
            cut = _cut_at_word_bound(piece, target, bounds)
            if cut <= 0:
                break        # ไม่มีจุดปลอดภัย — ปล่อยยาวไปทั้งก้อน (ชั้น 3)
            refined.append(piece[:cut])
            piece = piece[cut:]
        if piece:
            refined.append(piece)

    # ── ยุบตัวที่สั้นเกินไปรวมกับเพื่อนบ้าน ──
    # ต่อกันตรงๆ ไม่แทรก/ตัดอักขระ — เนื้อหาต้องเท่าเดิมทุกตัวหลังรวม (มีเทสยืนยัน)
    #
    # ยุบได้เฉพาะเมื่อ "ผลลัพธ์ไม่บวมเกิน limit" — ไม่งั้นการแก้ segment สั้นจะไปสร้าง
    # segment ยาวผิดปกติแทน (เจอจริง: 36c + 125c → 160c ทั้งที่ target แค่ 90 กลายเป็น
    # ตัวที่เล่นนานจนตัวถัดไปเจนไม่ทัน ซึ่งเป็นปัญหาเดิมที่พยายามแก้อยู่พอดี)
    merged: list[str] = []
    for seg in refined:
        if (merged and len(seg.strip()) < _SEG_MIN_CHARS
                and len(merged[-1]) + len(seg) <= limit):
            merged[-1] = merged[-1] + seg
        else:
            merged.append(seg)
    # ตัวแรกสั้นเกิน (ไม่มีตัวก่อนหน้าให้ยุบตอนวนข้างบน) → ยุบเข้ากับตัวถัดไปแทน
    if (len(merged) > 1 and len(merged[0].strip()) < _SEG_MIN_CHARS
            and len(merged[0]) + len(merged[1]) <= limit):
        merged[1] = merged[0] + merged[1]
        merged.pop(0)

    return [s for s in (seg.strip() for seg in merged) if s]


def _merge_segments_for_voxcpm(segments: list[str],
                               limit: int = VOXCPM_MERGE_CHARS) -> list[str]:
    """รวม segment ให้ก้อนใหญ่ขึ้นสำหรับ VoxCPM2 — คืนลิสต์ใหม่ (ไม่แก้ของเดิม)

    ทำไมต้องรวม (ตรงข้ามกับที่ F5 ต้องการ):
      * overhead คงที่ ~4.6s ต่อ segment — 3 ก้อนเสีย 13.8s ไปกับ overhead ล้วนๆ
      * RTF ~1.67 (เจนช้ากว่าเสียงที่ได้) → prefetch ตามไม่ทัน เกิดช่องว่างระหว่างก้อน
      * แต่ละก้อนเจนแยกจาก ref เดียวกัน ไม่รู้บริบทก้อนก่อน → โทน/จังหวะไม่ต่อเนื่อง

    ไม่รวมเป็นก้อนเดียวรวดเพราะยังต้องการให้ "เสียงแรก" มาถึงผู้ใช้ก่อนคำตอบจบ
    limit จึงเป็นจุดสมดุล: ใหญ่พอให้ overhead คุ้ม แต่ไม่ใหญ่จนรอนานกว่าจะได้ยินอะไร
    """
    if not segments:
        return []
    merged: list[str] = [segments[0]]
    for seg in segments[1:]:
        if len(merged[-1]) + len(seg) + 1 <= limit:
            merged[-1] = f"{merged[-1]} {seg}"
        else:
            merged.append(seg)
    return merged


def _concat_wavs(paths: list[str], out_path: str, silence_ms: int = 150) -> None:
    """ต่อ wav หลายไฟล์ + เว้น silence ระหว่าง segment"""
    import numpy as np
    # ⚠️ segment อาจมี sample rate ต่างกันได้จริง: VoxCPM2 ออก 48kHz ส่วนเส้น
    # F5/edge-tts→RVC ออกคนละค่า ถ้า VoxCPM2 พังกลางคำตอบแล้ว fallback ไป F5
    # จะได้ไฟล์คละ rate — เดิมโค้ดนี้ `sr = file_sr` ทับทุกรอบแล้วใช้ค่าของไฟล์
    # *สุดท้าย* stamp ทั้งก้อน ทำให้ segment ก่อนหน้าเล่นช้า/ทุ้มผิด (บั๊กแบบเดียว
    # กับที่เคยเจอตอน sample rate ผิด) → resample ให้ตรงกันก่อนต่อ
    arrays, sr = [], None
    for i, p in enumerate(paths):
        data, file_sr = sf.read(p)
        if sr is None:
            sr = file_sr                      # ยึด rate ของ segment แรก
        elif file_sr != sr:
            logger.warning(
                f"   ⚠️ segment {i} sample rate ไม่ตรง ({file_sr} vs {sr}) — resample ให้ตรง"
            )
            import math
            n_out = int(round(len(data) * sr / file_sr))
            src_x = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
            dst_x = np.linspace(0.0, 1.0, num=n_out, endpoint=False)
            if data.ndim == 1:
                data = np.interp(dst_x, src_x, data).astype(data.dtype)
            else:
                data = np.stack(
                    [np.interp(dst_x, src_x, data[:, c]) for c in range(data.shape[1])],
                    axis=1,
                ).astype(data.dtype)
        arrays.append(data)
        if i < len(paths) - 1:
            arrays.append(np.zeros(int(sr * silence_ms / 1000), dtype=data.dtype))
    sf.write(out_path, np.concatenate(arrays), sr)


# ── public API ─────────────────────────────────────────────────────────────────

def _rvc_convert(in_wav: str, out_wav: str, worker: RvcWorker | None) -> None:
    if worker:
        worker.convert(in_wav, out_wav)
    else:
        _rvc_oneshot(in_wav, out_wav)


def _gen_one_segment(
    seg: str,
    label: str,
    out_path: str,
    *,
    worker: RvcWorker | None,
    f5_worker: F5Worker | None,
    tmp_dir: str,
    voxcpm_worker: "VoxCpmWorker | None" = None,
) -> str | None:
    """Generate เสียงหนึ่ง segment ตาม fail-safe chain (ต่อ segment ไม่ใช่ทั้งก้อน):
      0. VoxCPM2 (ถ้าเปิดใช้และ worker พร้อม) — ref เป็นเสียงรอสเต้อยู่แล้ว
         จึงไม่ต้องผ่าน RVC ซ้ำ (เว้นแต่ตั้ง VOXCPM_THEN_RVC)
      1. F5 → pitch → RVC (retry F5 อีก 1 ครั้ง — ความพังมักเป็น transient)
      2. edge-tts → adjust → RVC (เนื้อหาครบ ยังผ่าน RVC จึงยังเป็น timbre รอสเต้)
      3. ข้าม segment (คืน None) — ผู้ใช้ยังอ่านข้อความเต็มใน Discord ได้

    VoxCPM2 อยู่ชั้นบนสุดแทนที่จะแทน F5 ไปเลย เพราะ cold load ~75s และช้ากว่า
    F5 ~2 เท่า — ถ้ามันพัง/ยังไม่ warm ต้องมี F5 รับช่วงได้ทันทีโดยเสียงไม่หาย
    """
    if voxcpm_worker is not None and voxcpm_worker.alive:
        try:
            vox_wav = (out_path if not VOXCPM_THEN_RVC
                       else os.path.join(tmp_dir, f"{label}_vox.wav"))
            voxcpm_worker.generate(text=seg, out_path=vox_wav)
            # เชื่อบรรทัด OK: อย่างเดียวไม่พอ — ถ้าไฟล์เขียนไม่ครบ/ว่าง จะหลุด
            # fail-safe chain ไปพังทีหลังตอนเล่นหรือตอน _concat_wavs แทน
            if not os.path.exists(vox_wav) or os.path.getsize(vox_wav) == 0:
                raise RuntimeError(f"VoxCPM คืน OK แต่ไฟล์ว่าง/ไม่มีจริง: {vox_wav}")
            if VOXCPM_THEN_RVC:
                _rvc_convert(vox_wav, out_path, worker)
            return out_path
        except Exception as e:
            logger.warning(f"   ⚠️ VoxCPM segment {label} พัง ({e}) — ใช้ F5 แทน")

    f5_wav = os.path.join(tmp_dir, f"{label}_f5.wav")
    for attempt in (1, 2):
        if f5_worker is None or not f5_worker.alive:
            break  # worker ตายแล้ว retry ไปก็พังเหมือนเดิม — ข้ามไป edge-tts เลย
        try:
            f5_worker.generate(
                ref_audio=F5_REF_AUDIO,
                ref_text=F5_REF_TEXT,
                gen_text=seg,
                out_path=f5_wav,
                speed=F5_SPEED,
                steps=F5_STEPS,
            )
            # ปรับ pitch ก่อนเข้า RVC (คืน f5_wav เองถ้า ratio=1.0 หรือ ffmpeg พัง)
            pitched = _pitch_shift(f5_wav, os.path.join(tmp_dir, f"{label}_pitch.wav"))
            _rvc_convert(pitched, out_path, worker)
            return out_path
        except Exception as e:
            logger.warning(f"   ⚠️ F5 segment {label} พัง (ครั้งที่ {attempt}): {e}")

    try:
        raw_wav = os.path.join(tmp_dir, f"{label}_raw.wav")
        adj_wav = os.path.join(tmp_dir, f"{label}_adj.wav")
        _edge_tts(seg, raw_wav)
        _adjust(raw_wav, adj_wav)
        _rvc_convert(adj_wav, out_path, worker)
        logger.info(f"   🎙️ segment {label} ใช้ edge-tts fallback")
        return out_path
    except Exception as e:
        logger.warning(f"   ⚠️ edge-tts fallback segment {label} พังด้วย ({e}) — ข้าม segment นี้")
        return None


# จำนวน segment ที่ generate ล่วงหน้าเก็บไว้ในคิว "ระหว่างที่ segment ก่อนหน้ากำลังเล่นอยู่"
#
# ทำไมต้องมี: generator ธรรมดาจะค้างที่ yield จนกว่า caller จะขอชิ้นถัดไป แปลว่าตลอดเวลาที่
# เสียง segment ก่อนหน้าเล่นอยู่ (~4s) GPU ว่างเปล่า แล้วผู้ฟังต้องมารอเจนอีก ~2s ทุกช่วง
# วัดจริง (คำตอบ 6 segment ขณะ Ollama เจนอยู่เบื้องหลังด้วย): ช่วงเงียบกลางคำตอบรวม 20.7s
# ย้าย generate ไปอยู่ใน thread แยกที่เดินหน้าเติมคิวไม่รอ consumer → ช่วงเงียบเหลือ 0.0s
# และคำตอบทั้งก้อนจบเร็วขึ้นจาก 49.5s เหลือ 29.8s ด้วย worker ชุดเดิม (ไม่ต้องเพิ่ม VRAM)
#
# ทำไมเป็น 2 ไม่ใช่มากกว่า: ล่วงหน้า 1 ชิ้นก็พอกันเงียบในกรณีปกติแล้ว (เจน 2.2s < เล่น 4.4s)
# ชิ้นที่ 2 เผื่อ segment ที่เจนช้าผิดปกติ — วัดความแกว่งได้ worst/median 1.25x ยังมีของสำรอง
# ให้เล่นระหว่างนั้น ลึกกว่านี้ไม่ช่วยเพิ่ม แต่เปลืองงาน generate ทิ้งตอนผู้ใช้หยุดกลางคัน
_TTS_PREFETCH_DEFAULT = 2


def text_to_roste_voice_segments(
    text: str,
    *,
    worker: RvcWorker | None = None,
    f5_worker: F5Worker | None = None,
    out_dir: str | None = None,
    filename: str | None = None,
    prefetch: int = _TTS_PREFETCH_DEFAULT,
    voxcpm_worker: "VoxCpmWorker | None" = None,
):
    """ข้อความ → yield path .wav ทีละ segment ทันทีที่เสร็จ (ลำดับตาม text เสมอ)
    — ให้ caller เริ่มเล่น segment แรกได้โดยไม่รอทั้งก้อน

    generate ทำใน thread เบื้องหลังที่เดินหน้าเติมคิวล่วงหน้า `prefetch` ชิ้นโดยไม่รอ caller
    (ดู _TTS_PREFETCH_DEFAULT ว่าทำไม) — ลำดับยังตรงกับ text เสมอเพราะ producer มีตัวเดียว
    และ generate เรียงตามลำดับ ไม่ต้องมี reorder buffer

    prefetch=0 = พฤติกรรมเดิม (เจนทีละชิ้นตอน caller ขอ) ไว้เป็นทางถอยถ้าเจอปัญหา

    ไฟล์ที่ yield เขียนลง out_dir (persistent) — caller รับผิดชอบลบหลังใช้เสร็จ
    ยกเว้น segment ที่เจนล่วงหน้าไว้แล้วแต่ caller เลิกฟังก่อน — ฟังก์ชันนี้ลบให้เอง
    segment ที่พังทุกชั้น fail-safe จะถูกข้าม (ไม่ yield ไม่ raise)
    ถ้าไม่มี f5_worker → เส้น edge-tts ทั้งก้อนแบบเดิม (yield ไฟล์เดียว)
    """
    text = strip_emoji(text).strip()
    if not text:
        raise ValueError("text ว่างหลัง strip_emoji")

    out_dir = out_dir or str(_OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)

    uid     = filename or uuid.uuid4().hex[:8]
    tmp_dir = tempfile.mkdtemp(prefix="roste_")

    producer: threading.Thread | None = None
    stop = threading.Event()

    try:
        # เข้าโหมด streaming ถ้ามี worker ตัวใดตัวหนึ่งพร้อม — VoxCPM2 ใช้ได้เดี่ยวๆ
        # โดยไม่ต้องมี F5 (แต่ถ้ามีทั้งคู่ F5 จะเป็น fallback ให้อัตโนมัติ)
        _vox_ready = voxcpm_worker is not None and voxcpm_worker.alive
        if (f5_worker and f5_worker.alive) or _vox_ready:
            from f5_preprocess import preprocess_for_f5, split_lines_for_tts
            # preprocess ทีละบรรทัด แล้วซอยแยกกัน — ขอบเขตบรรทัดคือจุดตัดที่เชื่อถือได้ที่สุด
            # (คนเขียน/โมเดลขึ้นบรรทัดใหม่ = ตั้งใจให้เป็นคนละประโยค) ถ้า preprocess ทั้งก้อน
            # ก่อน \n จะถูกยุบเป็นช่องว่างจนตัวซอยมองไม่เห็นขอบเขตนั้นอีกเลย ดู split_lines_for_tts
            segments, parts = [], []
            for line in split_lines_for_tts(text):
                pre_line, warns = preprocess_for_f5(line)
                for w in warns:
                    logger.warning(f"   ⚠️ F5 preprocess: {w}")
                if not pre_line.strip():
                    continue
                parts.append(pre_line)
                segments.extend(_split_thai_text(pre_line, max_chars=300))
            preprocessed = " ".join(parts)

            # ซอย segment แรกให้สั้นลง เพื่อให้ "เสียงแรก" มาถึงผู้ใช้เร็วขึ้น
            # (เฉพาะตอนใช้ VoxCPM2 ซึ่งมี overhead คงที่สูง — F5 เร็วพออยู่แล้ว)
            # ทำหลังซอยเสร็จทั้งหมด เพื่อไม่ไปยุ่งกับ logic ยุบ segment สั้นข้างใน
            # VoxCPM2 มี overhead คงที่ ~4.6s ต่อ segment (วัดแล้ว: gen ≈ 0.067×chars + 4.6)
            # และแต่ละ segment เจนแยกกันจาก ref เดียวกันโดยไม่รู้ว่าก้อนก่อนหน้าพูด
            # โทน/ความเร็วไหน → ยิ่งซอยมาก ยิ่งมีทั้งช่องว่างและรอยต่อเสียงไม่สม่ำเสมอ
            #
            # ต่างจาก F5 (RTF 0.65 เจนทันเล่น prefetch กลบช่องว่างได้) — VoxCPM2
            # RTF ~1.67 เจนไม่ทันเสียงที่กำลังเล่น ช่องว่างจึงโผล่มาเสมอ
            # ทางแก้ที่ถูกคือ *ลดจำนวน segment* ไม่ใช่เพิ่ม
            if _vox_ready and len(segments) > 1 and VOXCPM_MERGE_CHARS > 0:
                before = len(segments)
                segments = _merge_segments_for_voxcpm(segments)
                if len(segments) < before:
                    logger.info(
                        f"   ⚡ รวม segment {before} → {len(segments)} ก้อน "
                        f"(ลด overhead ~{(before - len(segments)) * 4.6:.0f}s + เสียงต่อเนื่องขึ้น)"
                    )
            # เนื้อหาข้อความจริง (มาจากบทสนทนา) แยกไป DEBUG — INFO เห็นแค่จำนวนตัวอักษร/segment
            logger.info(f"   🔤 F5 gen_text ({len(preprocessed)}c, {len(segments)} ส่วน)")
            logger.debug(f"   🔤 F5 gen_text เนื้อหา: {preprocessed!r}")

            if prefetch <= 0:
                # ทางถอย: เจนทีละชิ้นตอน caller ขอ (พฤติกรรมก่อนมี prefetch)
                for i, seg in enumerate(segments):
                    out_path = os.path.join(out_dir, f"{uid}_{i}_rvc.wav")
                    got = _gen_one_segment(
                        seg, f"{uid}_{i}", out_path,
                        worker=worker, f5_worker=f5_worker, tmp_dir=tmp_dir,
                        voxcpm_worker=voxcpm_worker)
                    if got:
                        yield got
                return

            # คิวมีขนาดจำกัด → พอเต็ม put() บล็อกเอง เป็น backpressure ไม่ให้ producer
            # เจนรวดทั้งคำตอบทิ้งไว้ (เปลืองงาน+ดิสก์ ถ้า caller หยุดกลางคัน)
            q: queue.Queue = queue.Queue(maxsize=prefetch)
            sentinel = object()

            def _produce() -> None:
                try:
                    for i, seg in enumerate(segments):
                        if stop.is_set():
                            break
                        out_path = os.path.join(out_dir, f"{uid}_{i}_rvc.wav")
                        got = _gen_one_segment(
                            seg, f"{uid}_{i}", out_path,
                            worker=worker, f5_worker=f5_worker, tmp_dir=tmp_dir,
                        voxcpm_worker=voxcpm_worker)
                        if not got:
                            continue
                        # วน put แบบมี timeout แทน put() เปล่า — คิวเต็มแล้ว caller เลิกฟัง
                        # (ไม่มีใครดึงออกอีก) จะค้างตรงนี้ถาวรและ thread ไม่มีวันจบ
                        while not stop.is_set():
                            try:
                                q.put(got, timeout=0.2)
                                break
                            except queue.Full:
                                continue
                        else:
                            # caller หยุดแล้ว — ไฟล์นี้ไม่มีใครเล่น ลบทิ้งเลย (คิวไม่ได้รับไป
                            # จึงไม่ถูกเก็บกวาดในลูป drain ข้างล่าง)
                            try:
                                os.remove(got)
                            except OSError:
                                pass
                            break
                except Exception as exc:   # ส่งข้ามไปให้ฝั่ง consumer raise ในบริบทของ caller
                    q.put(exc)
                finally:
                    q.put(sentinel)   # ต้องมีเสมอ ไม่งั้น consumer ค้างรอตลอดไป

            producer = threading.Thread(
                target=_produce, name=f"tts-produce-{uid}", daemon=True)
            producer.start()

            while True:
                item = q.get()
                if item is sentinel:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        else:
            out_path = os.path.join(out_dir, f"{uid}_rvc.wav")
            raw_wav = os.path.join(tmp_dir, f"{uid}_raw.wav")
            adj_wav = os.path.join(tmp_dir, f"{uid}_adj.wav")
            _edge_tts(text, raw_wav)
            _adjust(raw_wav, adj_wav)
            _rvc_convert(adj_wav, out_path, worker)
            yield out_path
    finally:
        # ต้องรอ producer จบก่อนลบ tmp_dir เสมอ — ไม่งั้นลบไฟล์ที่มันกำลังเขียนอยู่
        # (caller ปิด generator กลางคันได้ทุกเมื่อ เช่น ผู้ใช้ออกจากห้อง voice)
        if producer is not None:
            stop.set()
            # ดึงคิวทิ้งระหว่างรอ — ปลด producer ที่อาจค้างอยู่ที่ put() แล้วเก็บกวาด
            # segment ที่เจนเสร็จแล้วแต่ไม่มีใครเล่นไปด้วยในตัว
            while producer.is_alive():
                try:
                    leftover = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                if isinstance(leftover, str):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
            producer.join(timeout=_WORKER_READ_TIMEOUT_SEC)
            while True:   # เก็บที่ค้างในคิวหลัง producer จบ
                try:
                    leftover = q.get_nowait()
                except queue.Empty:
                    break
                if isinstance(leftover, str):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass

        for fn in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, fn))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def text_to_roste_voice(
    text: str,
    *,
    worker: RvcWorker | None = None,
    f5_worker: F5Worker | None = None,
    out_dir: str | None = None,
    filename: str | None = None,
    voxcpm_worker: "VoxCpmWorker | None" = None,
) -> str:
    """
    ข้อความ → ไฟล์ .wav เสียงรอสเต้ (ไฟล์เดียว รอทุก segment เสร็จแล้ว concat)

    Args:
        text:      ข้อความ (strip_emoji อัตโนมัติ)
        worker:    RvcWorker ที่ start() แล้ว สำหรับ warm RVC inference
        f5_worker: F5Worker ที่ start() แล้ว → ใช้ F5 pipeline
                   ถ้า None → fallback edge-tts pipeline
        out_dir:   โฟลเดอร์ output (default: rvc_out/)
        filename:  ชื่อไฟล์ไม่รวม .wav (default: uuid สั้น)

    Returns:
        absolute path ไฟล์ .wav
    """
    out_dir = out_dir or str(_OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    uid = filename or uuid.uuid4().hex[:8]

    seg_wavs = list(text_to_roste_voice_segments(
        text, worker=worker, f5_worker=f5_worker, voxcpm_worker=voxcpm_worker,
        out_dir=out_dir, filename=f"{uid}_seg"))
    if not seg_wavs:
        raise RuntimeError("ทุก segment ล้มเหลว — ไม่มีเสียงออก")

    rvc_wav = os.path.join(out_dir, f"{uid}_rvc.wav")
    if len(seg_wavs) == 1:
        os.replace(seg_wavs[0], rvc_wav)
    else:
        _concat_wavs(seg_wavs, rvc_wav)
        for p in seg_wavs:
            try:
                os.remove(p)
            except OSError:
                pass
    return rvc_wav
