"""
voice.py — Roste voice pipeline

text_to_roste_voice(text) -> wav_path:
  F5 pipeline (ถ้าส่ง f5_worker):
    strip_emoji → preprocess → F5 (warm) → RVC (warm/oneshot)
  fallback pipeline:
    strip_emoji → edge-tts → ffmpeg adjust → RVC (warm/oneshot)

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
import os
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import soundfile as sf

# ── constants ──────────────────────────────────────────────────────────────────
VOICE       = "th-TH-PremwadeeNeural"
SPEED       = 0.90
PITCH_SEMI  = 5.292
OUT_SR      = 40000

MODEL_DIR   = r"D:\LaibahtMaLaew"
DEVICE      = "cuda:0"
INDEX_RATE  = 0.5
PROTECT     = 0.33
F0_UP_KEY   = 0
F0_METHOD   = "rmvpe"

_ROOT        = Path(__file__).parent
_RVC_VENV_PY = _ROOT / "rvc_venv" / "Scripts" / "python.exe"
_WORKER_PY   = _ROOT / "voice_rvc_worker.py"
_OUT_DIR     = _ROOT / "rvc_out"

# ── F5-TTS constants ───────────────────────────────────────────────────────────
_F5_VENV_PY   = _ROOT / "f5_venv" / "Scripts" / "python.exe"
_F5_WORKER_PY = _ROOT / "f5_worker.py"
F5_REF_AUDIO  = str(_ROOT / "f5_out" / "ref_laibaht.wav")
F5_REF_TEXT   = "กลิ่นอะไรเอ่ย เพราะว่านอนเล่นอยู่ตั้งนานไม่ได้กลิ่นไง"
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
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg adjust failed: {r.stderr.decode(errors='replace')}")


def _adjust(in_wav: str, out_wav: str) -> None:
    src_sr = sf.info(in_wav).samplerate
    _ffmpeg_adjust(in_wav, out_wav, src_sr)


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
        )
        # scan stdout until we see {"status": "ready"} — skip RVC loading prints
        while True:
            line = self._proc.stdout.readline()
            if not line:
                err = self._proc.stderr.read()
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

    def convert(self, input_path: str, output_path: str) -> float:
        """แปลงไฟล์เดียว คืน elapsed seconds (warm ~1.4s)"""
        if not self.alive:
            raise RuntimeError("RvcWorker not running (call start() first)")
        req = json.dumps({"input": input_path, "output": output_path})
        self._proc.stdin.write(req + "\n")
        self._proc.stdin.flush()
        # scan for JSON response
        while True:
            line = self._proc.stdout.readline()
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
        )
        while True:
            line = self._proc.stdout.readline()
            if not line:
                err = self._proc.stderr.read()
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
            line = self._proc.stdout.readline()
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
    )
    if r.returncode != 0:
        raise RuntimeError(f"RVC oneshot failed:\n{r.stderr}")


# ── public API ─────────────────────────────────────────────────────────────────

def text_to_roste_voice(
    text: str,
    *,
    worker: RvcWorker | None = None,
    f5_worker: F5Worker | None = None,
    out_dir: str | None = None,
    filename: str | None = None,
) -> str:
    """
    ข้อความ → ไฟล์ .wav เสียงรอสเต้

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
    text = strip_emoji(text).strip()
    if not text:
        raise ValueError("text ว่างหลัง strip_emoji")

    out_dir = out_dir or str(_OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)

    uid     = filename or uuid.uuid4().hex[:8]
    tmp_dir = tempfile.mkdtemp(prefix="roste_")
    rvc_wav = os.path.join(out_dir, f"{uid}_rvc.wav")

    def _rvc(in_wav: str) -> None:
        if worker:
            worker.convert(in_wav, rvc_wav)
        else:
            _rvc_oneshot(in_wav, rvc_wav)

    try:
        if f5_worker and f5_worker.alive:
            from f5_preprocess import preprocess_for_f5
            preprocessed, warns = preprocess_for_f5(text)
            for w in warns:
                print(f"   ⚠️ F5 preprocess: {w}")
            f5_wav = os.path.join(tmp_dir, f"{uid}_f5.wav")
            try:
                f5_worker.generate(
                    ref_audio=F5_REF_AUDIO,
                    ref_text=F5_REF_TEXT,
                    gen_text=preprocessed,
                    out_path=f5_wav,
                    speed=F5_SPEED,
                    steps=F5_STEPS,
                )
                _rvc(f5_wav)
            except Exception as e:
                print(f"   ⚠️ F5 failed ({e}) — fallback edge-tts")
                raw_wav = os.path.join(tmp_dir, f"{uid}_raw.wav")
                adj_wav = os.path.join(tmp_dir, f"{uid}_adj.wav")
                _edge_tts(text, raw_wav)
                _adjust(raw_wav, adj_wav)
                _rvc(adj_wav)
        else:
            raw_wav = os.path.join(tmp_dir, f"{uid}_raw.wav")
            adj_wav = os.path.join(tmp_dir, f"{uid}_adj.wav")
            _edge_tts(text, raw_wav)
            _adjust(raw_wav, adj_wav)
            _rvc(adj_wav)
    finally:
        for fn in os.listdir(tmp_dir):
            try:
                os.remove(os.path.join(tmp_dir, fn))
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    return rvc_wav
