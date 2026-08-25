"""
stt_client.py — client ฝั่ง main process ของ warm worker ถอดเสียง (speech-to-text)

SttWorker เป็น counterpart ฝั่ง STT ของ F5Worker/RvcWorker/VoxCpmWorker ใน voice.py
(โครงชีวิต process เหมือนกันทุกอย่าง แต่แยกไฟล์เพราะ voice.py import heavy TTS deps
— client ตัวนี้ใช้ได้จากที่ไหนก็ได้โดยไม่ลาก torch/RVC มาด้วย จึงทำซ้ำ helper เล็กๆ
2 ตัวของ voice.py ไว้ที่นี่แทนการ import ข้าม)

worker subprocess รันใน typhoon_asr_venv (ต้องใช้ dependency stack ของ NVIDIA NeMo):
    typhoon_asr_venv\\Scripts\\python.exe stt_worker.py
โมเดล scb10x/typhoon-asr-realtime โหลดครั้งเดียวตอน start() แล้วรับ job ผ่าน
stdin/stdout — ถอดเสียงแบบ warm เร็วกว่า realtime หลายเท่า (ดูรายละเอียดโมเดล/
protocol ที่ stt_worker.py)

การใช้:
    from stt_client import SttWorker
    with SttWorker() as stt:
        print(stt.transcribe(r"C:\\path\\to\\clip.wav"))

หรือ manual:
    stt = SttWorker(); stt.start()
    ...
    stt.stop()
"""

import json
import logging
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

# กัน console window เด้งบน Windows ตอน spawn worker subprocess — เหตุผลเดียวกับ voice.py
# (บอทรันแบบ pythonw ไม่มี console child ที่เป็น console app จะสร้างหน้าต่างใหม่เอง)
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# ไม่ต้อง config handler เอง — bot.py ตั้ง root logger ไว้แล้ว (rotating file + console)
logger = logging.getLogger("roste.stt")

# ── paths ─────────────────────────────────────────────────────────────────────
_ROOT          = Path(__file__).parent
_STT_VENV_PY   = _ROOT / "typhoon_asr_venv" / "Scripts" / "python.exe"
_STT_WORKER_PY = _ROOT / "stt_worker.py"

_WORKER_READ_TIMEOUT_SEC = 60   # กัน worker subprocess ค้าง (GPU stall/driver hang) ทำ caller ค้างตลอดไป


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

    ⚠️ เจอซ้ำกับ STT จริงตอนเทส: NeMo log เยอะกว่า TTS อีก ท่อล้นระหว่าง transcribe ทำ worker
    ค้างกลางงานตลอดไป — drain thread จึงไม่ใช่แค่เรื่องช่วงโหลดโมเดล แต่ต้องมีตลอดอายุ process

    thread เป็น daemon จบเองเมื่อ pipe ปิด (readline คืน "") ไม่ต้อง join ตอน stop()"""
    try:
        for line in iter(proc.stderr.readline, ""):
            ring.append(line.rstrip("\n"))
            logger.debug(f"   [worker stderr] {line.rstrip()}")
    except (ValueError, OSError):
        pass  # pipe ถูกปิดระหว่างอ่าน (stop() เรียก stdin.close() พอดีช่วงนี้) — ไม่ใช่ error จริง


# ── STT warm worker ───────────────────────────────────────────────────────────

class SttWorker:
    """
    Typhoon ASR subprocess ที่โหลดโมเดลครั้งเดียว รับ job ผ่าน stdin/stdout
    Protocol: stdin JSON {"wav": "<path>"} → stdout "OK:<text>" หรือ "ERR:<msg>"
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
        if not _STT_VENV_PY.exists():
            raise RuntimeError(f"ไม่พบ typhoon_asr_venv: {_STT_VENV_PY}")
        if not _STT_WORKER_PY.exists():
            raise RuntimeError(f"ไม่พบ stt_worker.py: {_STT_WORKER_PY}")

        t0 = time.perf_counter()
        self._proc = subprocess.Popen(
            [str(_STT_VENV_PY), str(_STT_WORKER_PY)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
        # เริ่ม drain stderr ทันที (ก่อน ready) — กัน pipe buffer เต็มตอนโหลดโมเดล (ดู docstring
        # _drain_stderr) STT เจอจริง: NeMo log ท่วม stderr จนท่อล้นระหว่าง transcribe worker
        # ค้างกลางงาน ถ้าเริ่ม thread นี้หลังรอ READY เท่ากับเว้นช่วงเสี่ยงที่ยาวที่สุดไว้ไม่มีใครดูแล
        threading.Thread(target=_drain_stderr, args=(self._proc, self._stderr_ring), daemon=True).start()
        while True:
            line = self._proc.stdout.readline()
            if not line:
                # ให้ drain thread เก็บบรรทัดสุดท้ายๆ เข้า ring buffer ให้ครบก่อน (เหตุผลเดียวกับ
                # RvcWorker.start()) — stdout ปิดไม่ได้แปลว่า drain thread อ่าน stderr ทันบรรทัดสุดท้าย
                time.sleep(0.2)
                err = "\n".join(self._stderr_ring)
                raise RuntimeError(f"STT worker died before ready.\nstderr:\n{err}")
            if line.strip().startswith("STT_WORKER_READY"):
                break
        self.load_time = time.perf_counter() - t0

    def transcribe(self, wav_path: str, timeout: float = _WORKER_READ_TIMEOUT_SEC) -> str:
        """ถอดเสียงจากไฟล์ wav คืนข้อความ — worker ค้างเกิน timeout จะถูก kill ทิ้ง
        (.alive กลาย False ให้ caller ตรวจแล้ว fallback เอง)"""
        if not self.alive:
            raise RuntimeError("SttWorker not running (call start() first)")
        # ensure_ascii ค่า default ตั้งใจไม่ override — ให้ job line เป็น ASCII ล้วน เพราะ worker
        # reconfigure encoding เฉพาะ stdout/stderr ไม่แตะ stdin (job นี้มีแค่ path ไม่มีเนื้อหาภาษาไทย)
        job = json.dumps({"wav": str(wav_path)})
        self._proc.stdin.write(job + "\n")
        self._proc.stdin.flush()
        while True:
            line = _readline_with_timeout(self._proc, timeout)
            if line is None:
                # kill ทันทีที่ timeout — ไม่งั้น job ถัดไปจะอ่านคำตอบค้างจาก job เกิน sync และค้างซ้ำ
                # แบบเดิม kill ทำ .alive = False ให้ caller เลือก fallback ได้
                self._kill()
                raise RuntimeError(f"STT worker ไม่ตอบสนองเกิน {timeout:.0f}s (killed)")
            if not line:
                raise RuntimeError("STT worker closed unexpectedly")
            line = line.strip()
            if line.startswith("OK:") or line.startswith("ERR:"):
                break
        if line.startswith("ERR:"):
            raise RuntimeError(f"STT error: {line[4:]}")
        return line[3:]

    def _kill(self) -> None:
        """ฆ่า process ทันที (ไม่รอ) — เรียกตอน worker ค้างเกิน timeout กัน transcribe()
        ครั้งถัดไปพังซ้ำแบบเดิม ทำให้ .alive กลาย False ให้ caller ตรวจแล้ว fallback เอง"""
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

    def __enter__(self) -> "SttWorker":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()
