import os
import sys
import re
import random
import time
import asyncio
import logging
import msvcrt
from logging.handlers import RotatingFileHandler
import discord
import aiohttp

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

# ============================================================
#  📝  Logging — เดิมใช้ print() ล้วน หายหมดตอนปิด console ไม่มีล็อกย้อนหลังดูตอนบอทมีปัญหา
#      ตั้งที่ root logger เพื่อให้จับ log ของ discord.py (discord.client, discord.gateway ฯลฯ)
#      เข้าไฟล์เดียวกันด้วย ไม่ใช่แค่ของ roste เอง
# ============================================================
os.makedirs("logs", exist_ok=True)
_log_formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)-8s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_file_handler = RotatingFileHandler(
    "logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_file_handler.setFormatter(_log_formatter)

_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_log_formatter)

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _console_handler])
logger = logging.getLogger("roste")

# ============================================================
#  🔒  Singleton lock — กันรัน bot.py ซ้อนกันสองตัวพร้อมกัน
#      (ปัญหาที่เจอจริงหลายรอบตอน dev: ลืมปิด instance เก่าแล้ว restart ใหม่ทับ — บอทสองตัว
#      ต่อ token เดียวกันพร้อมกัน ทำให้ตอบข้อความซ้ำสองครั้งเงียบๆ โดยไม่มี error ใดๆ ให้เห็น)
# ============================================================
_LOCK_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.lock")
_PID_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pid")
_lock_file_handle = None   # ต้องเก็บ reference ไว้ตลอดอายุโปรแกรม ไม่งั้น GC ปิดไฟล์แล้ว lock หลุด


def _acquire_singleton_lock() -> None:
    """ล็อกไฟล์ bot.lock ผ่าน msvcrt.locking กันรัน instance ซ้อน — ถ้ามีตัวเก่ารันอยู่แล้ว
    log PID ตัวเก่า (จากไฟล์ bot.pid แยกต่างหาก) แล้ว SystemExit ทันที ก่อนถึง client.run()

    ใช้ file lock ของ OS (msvcrt.locking) แทนการเช็คว่าไฟล์มีอยู่ไหมเฉยๆ เพราะ Windows ปล่อย
    lock อัตโนมัติเมื่อ process ตาย (รวม crash/kill -9) — ไม่มีปัญหา stale lockfile ค้างหลัง
    crash แบบวิธีเช็คไฟล์ที่ต้องมาลบมือทุกครั้ง

    ตั้งใจแยก PID ออกเป็นไฟล์ต่างหาก (bot.pid) ไม่ได้เก็บรวมใน bot.lock — ทดสอบแล้วว่า Windows
    (msvcrt.locking/LockFileEx) ปฏิเสธการเปิดไฟล์ที่มี byte ใดถูกล็อกอยู่จากโพรเซสอื่นทั้งไฟล์
    แม้จะพยายามอ่านคนละ byte range จากที่ถูกล็อกจริงก็ตาม (ต่างจาก POSIX advisory lock ที่ปกติ
    จำกัดผลแค่ byte range ที่ล็อก) เลยอ่าน PID เดิมจากไฟล์เดียวกับที่ถือ lock ไม่ได้เลย ต้องแยกไฟล์"""
    global _lock_file_handle
    old_pid = "ไม่ทราบ"
    try:
        with open(_PID_FILE_PATH, "r") as f:
            text = f.read().strip()
        if text:
            old_pid = text
    except OSError:
        pass   # ไฟล์ยังไม่เคยมี (รันครั้งแรก) — ไม่ใช่ error

    if not os.path.exists(_LOCK_FILE_PATH):
        with open(_LOCK_FILE_PATH, "wb"):
            pass
    _lock_file_handle = open(_LOCK_FILE_PATH, "r+b")
    # msvcrt.locking ล็อกช่วง byte เริ่มจากตำแหน่งปัจจุบัน — ไฟล์ว่าง (รันครั้งแรก) ต้องมีอย่าง
    # น้อย 1 byte ก่อนล็อก ไม่งั้นแยกไม่ออกระหว่าง "ไฟล์ว่าง" กับ "ถูกล็อกอยู่แล้ว"
    _lock_file_handle.seek(0, os.SEEK_END)
    if _lock_file_handle.tell() == 0:
        _lock_file_handle.write(b" ")
        _lock_file_handle.flush()
    _lock_file_handle.seek(0)
    try:
        msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        _lock_file_handle.close()
        logger.error(f"❌ บอทกำลังรันอยู่แล้ว (PID เดิม: {old_pid}) — ปิดตัวเก่าก่อนค่อยรันใหม่")
        raise SystemExit(1)

    with open(_PID_FILE_PATH, "w") as f:
        f.write(str(os.getpid()))

import printing   # 🖨️ ระบบพิมพ์ PDF (อยู่ในไฟล์ printing.py)
import music      # 🎵 ระบบเพลง (อยู่ในไฟล์ music.py)
import voice      # 🎙️ voice pipeline (edge-tts → ffmpeg → RVC subprocess)
import memory     # 🧠 ระบบความจำ (load/save/facts/recall + คำสั่งจำ-ลืม)
import vectormemory  # 🔎 ความจำ/ค้นหาเชิงความหมาย (RAG PDF + semantic recall ผ่าน ChromaDB)
import websearch  # 🔎 ค้นเว็บ/Google Maps ผ่าน SerpApi (มี ddgs สำรอง)
import datasources  # 🌦️⛽🔌🕐 weather/oil/outage/เวลาไทย/แผนที่จังหวัด
import ollama_client  # 🤖 Ollama HTTP client — ทั่วไป ไม่รู้จัก TOOLS
import llm_tools  # 🛠️ TOOLS schema + tool handlers (tool calling)
import chat  # 🧠 สมองบทสนทนา — ask_ollama + tool-calling loop (ไม่รู้จัก Discord)

# state ระบบเสียง
_voice_worker: voice.RvcWorker | None = None  # RVC warm worker (None = ยังโหลดไม่เสร็จ/โหลดไม่ได้)
_f5_worker: voice.F5Worker | None = None      # F5 warm worker (None = ยังโหลดไม่เสร็จ/โหลดไม่ได้)
_tts_lock = asyncio.Lock()                    # serialize TTS — กัน 2 user ยิง convert() พร้อมกัน
_leave_timer: asyncio.Task | None = None       # leave timer task (cancel ได้ถ้าคนกลับมา)
LEAVE_IDLE_SEC = 15                            # วินาทีที่รอก่อน disconnect เมื่อห้องว่าง

# dedup — กัน gateway resume replay ส่ง message event ซ้ำ
from collections import deque
_seen_msg_ids: deque[int] = deque(maxlen=200)

# ── rate limit — cooldown ต่อ user กันสแปมเผา GPU (F5+RVC)/API quota ────────
_COOLDOWN_SEC = 3
_COOLDOWN_STALE_SEC = 3600   # ล้าง entry ที่เก่ากว่านี้ทิ้งตอนเขียนใหม่ (กัน dict โตไม่จำกัดตามจำนวน user)
_last_message_at: dict[int, float] = {}


def _purge_stale_cooldowns(now: float) -> None:
    stale = [uid for uid, t in _last_message_at.items() if now - t > _COOLDOWN_STALE_SEC]
    for uid in stale:
        del _last_message_at[uid]


def _check_cooldown(user_id: int, now: float | None = None) -> bool:
    """True = ผ่าน (ให้ตอบได้) — เรียกครั้งเดียวต่อข้อความ เพราะ side-effect บันทึกเวลาไว้เทียบครั้งถัดไป"""
    now = time.monotonic() if now is None else now
    if now - _last_message_at.get(user_id, 0.0) < _COOLDOWN_SEC:
        return False
    _last_message_at[user_id] = now
    _purge_stale_cooldowns(now)
    return True


def _guild_allowed(guild_id: int | None) -> bool:
    """True = ตอบได้ — guild_id=None (DM) ผ่านเสมอ, ไม่ตั้ง ALLOWED_GUILD_IDS ไว้ = ตอบทุกเซิร์ฟเวอร์"""
    if guild_id is None:
        return True
    if not ALLOWED_GUILD_IDS:
        return True
    return guild_id in ALLOWED_GUILD_IDS


def _dm_allowed(user_id: int, is_dm: bool) -> bool:
    """True = ตอบได้ — ไม่ใช่ DM ผ่านเสมอ (ไปเช็ค guild allowlist แยกต่างหาก), ไม่ตั้ง
    DM_ALLOWED_USER_IDS ไว้ = เปิดรับ DM จากทุกคน (เดิม ไม่กระทบของเก่า)"""
    if not is_dm:
        return True
    if not DM_ALLOWED_USER_IDS:
        return True
    return user_id in DM_ALLOWED_USER_IDS


# กัน PDF ใหญ่เกินทำบอทค้าง — เช็คจาก attachment.size ก่อนโหลดเข้า RAM เลย ไม่ต้อง .read() ก่อน
MAX_PDF_SIZE_BYTES = 10 * 1024 * 1024   # 10MB

# _bg_queue, _bg_worker, _ensure_bg_worker, _enqueue_bg, _user_locks, _USER_LOCKS_MAX,
# _purge_unlocked_locks, get_user_lock, _THAI_MONTHS — ย้ายไป chat.py แล้ว (re-export ไว้ด้านบน)

# ============================================================
#  ⚙️  ตั้งค่าหลัก — แก้ตรงนี้
# ============================================================

# Token ถูกเก็บแยกไว้ในไฟล์ config.py (เปิดไฟล์นั้นเพื่อใส่/แก้ Token)
try:
    from config import DISCORD_TOKEN
except ImportError:
    logger.error("❌ ไม่พบไฟล์ config.py — วางไฟล์ config.py ไว้โฟลเดอร์เดียวกับ bot.py")
    raise SystemExit

# TMD_TOKEN — ย้ายไป datasources.py แล้ว (re-export ไว้ด้านบน)

# SERPAPI_KEY, _serpapi_quota_ok — ย้ายไป websearch.py แล้ว (re-export ไว้ด้านบนให้ชื่อเดิมยังใช้ได้)

# PRINT_ALLOWED_USER_IDS — รายชื่อคนที่สั่งพิมพ์ PDF จริงได้ ไม่ตั้งไว้ = ไม่มีใครสั่งพิมพ์ได้ (ปลอดภัยไว้ก่อน)
try:
    from config import PRINT_ALLOWED_USER_IDS
except ImportError:
    PRINT_ALLOWED_USER_IDS = []

# ALLOWED_GUILD_IDS — เซิร์ฟเวอร์ที่บอทตอบ ไม่ตั้งไว้ (list ว่าง) = ตอบทุกเซิร์ฟเวอร์ (เดิม ไม่กระทบของเก่า)
try:
    from config import ALLOWED_GUILD_IDS
except ImportError:
    ALLOWED_GUILD_IDS = []

# DM_ALLOWED_USER_IDS — คนที่ DM บอทได้ ไม่ตั้งไว้ (list ว่าง) = เปิดรับทุกคน (เดิม ไม่กระทบของเก่า)
try:
    from config import DM_ALLOWED_USER_IDS
except ImportError:
    DM_ALLOWED_USER_IDS = []

# เช็กว่าใส่ Token จริงแล้วหรือยัง ถ้ายังให้เตือนชัดๆ
if not DISCORD_TOKEN or DISCORD_TOKEN == "วาง_TOKEN_ของคุณ_ที่นี่":
    logger.warning("⚠️ ยังไม่ได้ใส่ Token! เปิดไฟล์ config.py แล้ววาง Token จาก Discord ก่อนนะครับ")
    raise SystemExit

# OLLAMA_URL, MODEL — ย้ายไป ollama_client.py แล้ว (re-export ไว้ด้านบน)

# 🖨️ ระบบพิมพ์อยู่ในไฟล์ printing.py | 🎵 ระบบเพลงอยู่ในไฟล์ music.py
# (แก้ตั้งค่าเครื่องพิมพ์ในไฟล์ printing.py, ตั้งค่าโฟลเดอร์เพลงในไฟล์ music.py)


# ============================================================
#  🔎  เครื่องมือค้นเว็บ — ย้ายไป websearch.py แล้ว (cache, SerpApi, ddgs fallback)
#      re-export ชื่อเดิมไว้ด้านบน (SERPAPI_KEY, search_web, search_places_serpapi ฯลฯ)
#      ให้ยังใช้ผ่าน bot.xxx ได้เหมือนเดิมระหว่างช่วงเปลี่ยนผ่าน
# ============================================================


# TOOLS, TOOL_HANDLERS, _validate_tool_args, _strip_ungrounded_optional_args, _search_places,
# make_search_query, _tool_get_current_time, _tool_get_weather, _tool_get_power_outage,
# _tool_get_oil_price, _tool_search_places, _tool_search_web — ย้ายไป llm_tools.py แล้ว
# (re-export ไว้ด้านบน) — ต่อ tool ใหม่ (IoT, reminder, ...) แก้ที่ llm_tools.py แทน


# ============================================================
#  ส่วนการทำงาน — มือใหม่ยังไม่ต้องแก้ก็ได้
# ============================================================

intents = discord.Intents.default()
intents.message_content = True  # ต้องเปิด MESSAGE CONTENT INTENT ในเว็บ Discord ด้วย

_CLOSE_FLUSH_TIMEOUT_SEC = 120   # กันแขวนตอนปิดบอท ถ้า _bg_queue ค้าง (ดู docstring RosteClient.close)


class RosteClient(discord.Client):
    async def close(self):
        """เรียกจริงตอนบอทปิด (Ctrl+C หรือ crash) ผ่าน __aexit__ ใน discord.py client.run()
        (ของเดิมใช้ @client.event async def on_close() ซึ่งไม่มี event ชื่อนี้อยู่จริงในไลบรารี
        เลยไม่เคยถูกเรียกเลย — flush/worker.stop() เป็น dead code มาตลอด แก้โดย override method นี้แทน)"""
        if self.is_closed():
            return  # กันเรียกซ้ำ (idempotent) — super().close() เรียกมาแล้วรอบหนึ่งก็จบ ไม่ flush/stop ซ้ำ
        try:
            if chat._active_users:
                logger.info(f"🔒 บอทปิด — flush history ของ {len(chat._active_users)} user(s)...")
                try:
                    # timeout กันแขวน — ตอน Ctrl+C ตัว _bg_worker_task อาจถูก cancel ไปพร้อมกัน
                    # ทำให้ flush_user_history ที่รอ _bg_queue.join() ค้างตลอดกาล (worker ที่จะมา
                    # task_done() ตายไปแล้ว) หมดเวลาแล้วยอมทิ้งได้ เพราะ save_memory เซฟทุกเทิร์น
                    # ไว้อยู่แล้ว ไม่มีข้อมูลดิบหาย แค่ไม่ได้สรุปบทสุดท้ายเป็น summary เฉยๆ
                    await asyncio.wait_for(chat.flush_all_users(), timeout=_CLOSE_FLUSH_TIMEOUT_SEC)
                    logger.info("   ✅ flush เสร็จ")
                except asyncio.TimeoutError:
                    logger.warning(f"   ⚠️ flush history หมดเวลา ({_CLOSE_FLUSH_TIMEOUT_SEC}s) — ข้ามไป (history ดิบยังอยู่ครบ)")
        finally:
            # worker.stop() + super().close() ต้องเกิดเสมอแม้ flush ข้างบนพัง/หมดเวลา/โดน cancel
            # ไม่งั้น subprocess ใน rvc_venv/f5_venv จะกลายเป็น orphan ค้างกิน VRAM ต่อ (บั๊กเดิมที่แก้อยู่)
            if _voice_worker is not None:
                _voice_worker.stop()
                logger.info("   🎙️ RVC worker ปิดแล้ว")
            if _f5_worker is not None:
                _f5_worker.stop()
                logger.info("   🎙️ F5 worker ปิดแล้ว")
            await super().close()


client = RosteClient(intents=intents)

# auto_remember, _check_condition_b, _SUMMARY_NOTICE_*, _maybe_append_summary_notice,
# detect_topic_change, summarize_and_verify, flush_user_history, flush_all_users, ask_ollama
# — ย้ายไป chat.py แล้ว (re-export ไว้ด้านบน) — เรียกจาก on_message/on_close ผ่าน chat.xxx
# แบบเต็มชื่อ (ไม่ผ่าน bot re-export) ตามมาตรฐานเดียวกันทั้งไฟล์


async def _start_voice_worker() -> None:
    """โหลด RVC worker ใน thread แยก (readline blocks ~8s) — ไม่บล็อก event loop"""
    global _voice_worker
    try:
        await asyncio.to_thread(_voice_worker.start)
        logger.info(f"🎙️ RVC worker พร้อม — โหลดเสร็จใน {_voice_worker.load_time:.1f}s")
    except Exception as e:
        logger.warning(f"⚠️ RVC worker เริ่มไม่ได้ ({type(e).__name__}: {e}) — TTS ถูกปิดใช้งาน")
        _voice_worker = None


async def _start_f5_worker() -> None:
    """โหลด F5 worker ใน thread แยก (~14s boot) — ไม่บล็อก event loop"""
    global _f5_worker
    try:
        await asyncio.to_thread(_f5_worker.start)
        logger.info(f"🎙️ F5 worker พร้อม — โหลดเสร็จใน {_f5_worker.load_time:.1f}s")
    except Exception as e:
        logger.warning(f"⚠️ F5 worker เริ่มไม่ได้ ({type(e).__name__}: {e}) — ใช้ edge-tts แทน")
        _f5_worker = None


async def _generate_tts(text: str, uid: int) -> str | None:
    """สร้างไฟล์เสียง TTS ใน thread แยก — คืน path .wav หรือ None ถ้า skip/error"""
    # worker.load_time > 0 = start() เสร็จแล้ว (ready)
    if _voice_worker is None or _voice_worker.load_time == 0.0 or not _voice_worker.alive:
        if _voice_worker is not None and _voice_worker.load_time == 0.0:
            logger.info("   🎙️ TTS skip — worker ยังโหลดอยู่")
        return None
    try:
        t0 = time.perf_counter()
        async with _tts_lock:   # serialize — กัน 2 user ยิง convert() พร้อมกัน
            wav_path = await asyncio.to_thread(
                voice.text_to_roste_voice,
                text,
                worker=_voice_worker,
                f5_worker=_f5_worker,
                out_dir=str(voice._OUT_DIR / "bot"),
            )
        elapsed = time.perf_counter() - t0
        logger.info(f"   🎙️ TTS เสร็จใน {elapsed:.1f}s → {wav_path}")
        return wav_path
    except Exception as e:
        logger.warning(f"   ⚠️ TTS error ({type(e).__name__}: {e})")
        return None


async def _generate_tts_stream(text: str, uid: int):
    """AsyncIterator[str] — yield path .wav ทีละ segment ทันทีที่ segment เสร็จ
    producer (thread เดียว sequential ถือ _tts_lock ครอบทั้งคำตอบ) ผลิตต่อเนื่อง
    ระหว่างที่ consumer เล่น segment ก่อนหน้า — ลำดับรักษาผ่าน Queue ตัวเดียว"""
    if _voice_worker is None or _voice_worker.load_time == 0.0 or not _voice_worker.alive:
        if _voice_worker is not None and _voice_worker.load_time == 0.0:
            logger.info("   🎙️ TTS skip — worker ยังโหลดอยู่")
        return

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _produce() -> None:
        # รันใน thread — ส่ง path เข้า queue ฝั่ง event loop; sentinel None ปิดท้ายเสมอ
        try:
            for wav in voice.text_to_roste_voice_segments(
                    text,
                    worker=_voice_worker,
                    f5_worker=_f5_worker,
                    out_dir=str(voice._OUT_DIR / "bot")):
                loop.call_soon_threadsafe(queue.put_nowait, wav)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    async def _run_producer() -> None:
        t0 = time.perf_counter()
        async with _tts_lock:   # serialize — กัน 2 user ยิง convert() พร้อมกัน
            try:
                await asyncio.to_thread(_produce)
            except Exception as e:
                logger.warning(f"   ⚠️ TTS stream error ({type(e).__name__}: {e})")
        logger.info(f"   🎙️ TTS stream จบใน {time.perf_counter() - t0:.1f}s")

    producer_task = asyncio.create_task(_run_producer())
    try:
        while True:
            wav = await queue.get()
            if wav is None:
                break
            yield wav
    finally:
        # consumer หยุดก่อนจบ (หลุดห้อง/error) — thread cancel ไม่ได้ ต้องรอจบ
        # แล้วเก็บกวาดไฟล์ segment ที่ค้างในคิว (ไม่มีใครเล่นแล้ว)
        await producer_task
        while not queue.empty():
            leftover = queue.get_nowait()
            if leftover:
                try:
                    os.remove(leftover)
                except OSError:
                    pass


async def _play_wav(vc: discord.VoiceClient, wav_path: str) -> None:
    """เล่นไฟล์ .wav รอจนจบ — pattern เดียวกับ music.py"""
    loop = asyncio.get_running_loop()
    done = asyncio.Event()

    def _after(err):
        if err:
            logger.warning(f"   ⚠️ audio playback error: {err}")
        loop.call_soon_threadsafe(done.set)

    vc.play(discord.FFmpegPCMAudio(wav_path), after=_after)
    try:
        await asyncio.wait_for(done.wait(), timeout=120)
    except asyncio.TimeoutError:
        if vc.is_playing():
            vc.stop()


_GREETING_WAV: str | None = None   # cache ทักทายตลอด session
_GREETING_TEXT = "รอสเต้เข้ามาแล้วนะคะ"


async def _get_greeting_wav() -> str | None:
    """คืน path ไฟล์ทักทาย — gen ครั้งแรกแล้ว cache ไว้"""
    global _GREETING_WAV
    if _GREETING_WAV is not None:
        return _GREETING_WAV
    wav = await _generate_tts(_GREETING_TEXT, 0)
    _GREETING_WAV = wav
    return wav


async def _speak_in_voice(message, reply_text: str) -> None:
    """Join voice → just_joined: เล่นทักทายทันที + TTS คำตอบ concurrent → เล่นคำตอบ
    not_just_joined: TTS คำตอบ → เล่นคำตอบ  ค้างห้อง — leave timer ทำ step ต่อไป"""
    user_vc = getattr(message.author, "voice", None)
    if not user_vc or not user_vc.channel:
        return
    if music.voice_lock.locked():
        logger.info("   🎙️ TTS skip — music กำลังเล่น")
        return

    channel = user_vc.channel
    bot_vc  = message.guild.voice_client

    # Join / move ห้อง — ติดตามว่าเพิ่งเข้าหรือไม่
    just_joined = False
    try:
        if bot_vc is None or not bot_vc.is_connected():
            if bot_vc is not None:
                try:
                    await bot_vc.disconnect(force=True)
                except Exception:
                    pass
            bot_vc = await channel.connect()
            just_joined = True
        elif bot_vc.channel.id != channel.id:
            await bot_vc.move_to(channel)
            just_joined = True
    except Exception as e:
        logger.warning(f"   ⚠️ voice connect error ({type(e).__name__}: {e})")
        return

    logger.info(f"   🎙️ voice — {'เพิ่งเข้า' if just_joined else 'อยู่แล้ว'} ห้อง {channel.name!r}")

    # ดึง greeting (cache instantaneous ยกเว้นครั้งแรกของ session ~8-10s)
    greeting_wav = await _get_greeting_wav() if just_joined else None

    if music.voice_lock.locked():
        logger.info("   🎙️ TTS skip (race) — music เริ่มระหว่างรอ")
        return

    async with music.voice_lock:
        stream = _generate_tts_stream(reply_text, message.author.id)
        try:
            if greeting_wav:
                # เริ่มดึง segment แรก concurrent กับ เล่นทักทาย
                # (การเรียก anext ครั้งแรกคือจุดที่ producer เริ่ม generate)
                first_task = asyncio.create_task(anext(stream, None))
                logger.info("   🎙️ เล่นทักทาย")
                await _play_wav(bot_vc, greeting_wav)
                seg_wav = await first_task
            else:
                seg_wav = await anext(stream, None)

            n_played = 0
            while seg_wav is not None:
                # Re-check connection ก่อนเล่นทุก segment (bot_vc อาจหลุดระหว่าง TTS)
                if not bot_vc.is_connected():
                    logger.info("   🎙️ reconnect — bot_vc หลุดระหว่าง TTS")
                    fresh_vc = getattr(message.author, "voice", None)
                    if not fresh_vc or not fresh_vc.channel:
                        logger.info("   🎙️ skip — user ออก voice แล้ว")
                        break
                    try:
                        bot_vc = await fresh_vc.channel.connect()
                    except Exception as e:
                        logger.warning(f"   ⚠️ reconnect error ({type(e).__name__}: {e})")
                        break

                n_played += 1
                logger.info(f"   🎙️ เล่น segment {n_played}")
                await _play_wav(bot_vc, seg_wav)
                try:
                    os.remove(seg_wav)
                except OSError:
                    pass
                seg_wav = await anext(stream, None)

        except Exception as e:
            logger.warning(f"   ⚠️ voice play error ({type(e).__name__}: {e})")
        finally:
            # ปิด generator เสมอ — รอ producer จบ + เก็บกวาด segment ค้างคิว
            try:
                await stream.aclose()
            except Exception as e:
                logger.warning(f"   ⚠️ TTS stream close error ({type(e).__name__}: {e})")
    # ไม่ disconnect — ค้างห้อง (leave timer ทำ step ต่อไป)


# ── leave timer helpers ────────────────────────────────────────────────────────

def _human_count_in_channel(channel: discord.VoiceChannel) -> int:
    return sum(1 for m in channel.members if not m.bot)


async def _leave_after_idle(vc: discord.VoiceClient) -> None:
    """รอ LEAVE_IDLE_SEC วิ ถ้าห้องยังว่างอยู่ → รอเสียงจบ → disconnect"""
    await asyncio.sleep(LEAVE_IDLE_SEC)
    if not vc.is_connected():
        return
    channel = vc.channel
    if _human_count_in_channel(channel) > 0:
        return
    # รอเสียงเล่นจบก่อน ไม่ตัดกลางคัน (max 120s)
    for _ in range(240):
        if not vc.is_playing():
            break
        await asyncio.sleep(0.5)
    # re-check หลังเสียงจบ
    if _human_count_in_channel(channel) > 0:
        return
    logger.info(f"   🎙️ ว่างมา {LEAVE_IDLE_SEC}s — disconnect จากห้อง {channel.name!r}")
    await vc.disconnect()


async def _play_karaoke(message, song_path: str, pretty_name: str) -> None:
    """Join voice → TTS เกริ่น → เล่นเพลง karaoke → disconnect หลังจบ"""
    user_vc = getattr(message.author, "voice", None)
    if not user_vc or not user_vc.channel:
        return
    channel = user_vc.channel
    bot_vc = message.guild.voice_client
    try:
        if bot_vc is None or not bot_vc.is_connected():
            if bot_vc is not None:
                try:
                    await bot_vc.disconnect(force=True)
                except Exception:
                    pass
            bot_vc = await channel.connect()
        elif bot_vc.channel.id != channel.id:
            await bot_vc.move_to(channel)
    except Exception as e:
        logger.warning(f"   🎵 karaoke connect error ({type(e).__name__}: {e})")
        return

    intro_wav = await _generate_tts(
        f"รอสเต้จะร้องเพลง {pretty_name} ให้ฟังนะคะ", message.author.id)

    if music.voice_lock.locked():
        logger.info("   🎵 karaoke skip — voice_lock ถูกจอง")
        return

    async with music.voice_lock:
        try:
            if intro_wav and bot_vc.is_connected():
                await _play_wav(bot_vc, intro_wav)
            if intro_wav:
                try:
                    os.remove(intro_wav)
                except OSError:
                    pass
            if not bot_vc.is_connected():
                try:
                    bot_vc = await channel.connect()
                except Exception:
                    return
            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after_karaoke(err):
                loop.call_soon_threadsafe(done.set)

            bot_vc.play(discord.FFmpegPCMAudio(song_path), after=after_karaoke)
            logger.info(f"   🎵 เล่น karaoke: {pretty_name}")
            await asyncio.wait_for(done.wait(), timeout=900)
            if bot_vc.is_playing():
                bot_vc.stop()

            # 🎤 พูดปิดท้ายก่อนออกจากห้อง — เดิม disconnect ทันทีไม่พูดอะไรเลย รู้สึกห้วน
            outro_wav = await _generate_tts(
                f"ร้องเพลง {pretty_name} จบแล้วค่ะ เป็นไงบ้างคะ เพราะไหม~", message.author.id)
            if outro_wav and bot_vc.is_connected():
                await _play_wav(bot_vc, outro_wav)
            if outro_wav:
                try:
                    os.remove(outro_wav)
                except OSError:
                    pass
        except Exception as e:
            logger.warning(f"   🎵 karaoke play error ({type(e).__name__}: {e})")

    try:
        if bot_vc.is_connected():
            await bot_vc.disconnect()
    except Exception:
        pass
    await message.channel.send(
        f"{message.author.mention} ร้องจบแล้วค่ะ เป็นไงบ้างคะ เพราะไหม~ 🎶")


@client.event
async def on_ready():
    global _voice_worker, _f5_worker
    chat._ensure_bg_worker()   # เริ่ม background queue worker
    _voice_worker = voice.RvcWorker()
    _f5_worker = voice.F5Worker()
    asyncio.create_task(_start_voice_worker())   # โหลด RVC เบื้องหลัง ไม่บล็อก startup
    asyncio.create_task(_start_f5_worker())      # โหลด F5 เบื้องหลัง ไม่บล็อก startup
    logger.info(f"✅ ล็อกอินสำเร็จในชื่อ: {client.user}")
    logger.info(f"🖨️ ระบบพิมพ์: {'โหมดจริง' if printing.PRINT_REAL_MODE else 'โหมดจำลอง (ยังไม่สั่งเครื่องจริง)'}")
    logger.info("🎙️ RVC+F5 workers กำลังโหลดในเบื้องหลัง (RVC ~8s, F5 ~14s)...")
    logger.info("บอทพร้อมทำงานแล้ว! ลอง @ ชื่อบอทในเซิร์ฟเวอร์ หรือทักผ่าน DM ได้เลย")


@client.event
async def on_voice_state_update(member, before, after):
    global _leave_timer
    # ข้าม event ของบอทเอง (join/leave ของรอสเต้เอง ไม่นับ)
    if member.id == client.user.id:
        return
    bot_vc = member.guild.voice_client
    if bot_vc is None or not bot_vc.is_connected():
        return
    bot_channel = bot_vc.channel
    # มีคน join ห้องที่รอสเต้อยู่ → ยกเลิก leave timer
    if after.channel is not None and after.channel.id == bot_channel.id:
        if _leave_timer is not None and not _leave_timer.done():
            _leave_timer.cancel()
            _leave_timer = None
            logger.info(f"   🎙️ leave timer ยกเลิก — {member.display_name} กลับเข้าห้อง")
        return
    # มีคน leave ห้องที่รอสเต้อยู่ → เช็คว่าว่างไหม
    if before.channel is not None and before.channel.id == bot_channel.id:
        if _human_count_in_channel(bot_channel) == 0:
            if _leave_timer is not None and not _leave_timer.done():
                _leave_timer.cancel()
            _leave_timer = asyncio.create_task(_leave_after_idle(bot_vc))
            logger.info(f"   🎙️ ห้องว่าง — เริ่ม leave timer {LEAVE_IDLE_SEC}s")


@client.event
async def on_message(message):
    # ไม่ตอบข้อความของตัวเอง (กันลูป)
    if message.author == client.user:
        return
    # กัน gateway resume replay ส่ง event ซ้ำ → ตอบ 2 ครั้ง
    if message.id in _seen_msg_ids:
        return
    _seen_msg_ids.append(message.id)

    # 🔍 รายงานทุกข้อความที่บอทเห็น (ไว้ดีบัก) — เนื้อหาข้อความจริงแยกไป DEBUG level
    # กัน PII (ข้อความส่วนตัวผู้ใช้) ถูกเขียนลงไฟล์ log ถาวรโดย default (INFO)
    is_dm = message.guild is None
    is_mention = client.user in message.mentions
    logger.info(f"[เห็นข้อความ] จาก {message.author} | DM={is_dm} | ถูก@={is_mention}")
    logger.debug(f"เนื้อหาข้อความ: {message.content!r}")

    # กัน guild ที่ไม่ได้รับอนุญาต (ถ้าไม่ตั้ง ALLOWED_GUILD_IDS ไว้ = ตอบทุกเซิร์ฟเวอร์ เหมือนเดิม)
    if not _guild_allowed(None if is_dm else message.guild.id):
        logger.info(f"   ↳ ข้าม: guild {message.guild.id} ไม่อยู่ใน allowlist")
        return

    # กัน DM ที่ไม่ได้รับอนุญาต (ถ้าไม่ตั้ง DM_ALLOWED_USER_IDS ไว้ = เปิดรับ DM ทุกคน เหมือนเดิม)
    if not _dm_allowed(message.author.id, is_dm):
        logger.info(f"   ↳ ข้าม: DM จาก {message.author.id} ไม่อยู่ใน allowlist")
        return

    # ตอบเมื่อ: ถูก @mention ในห้อง หรือ ถูกทักผ่าน DM
    if not (is_dm or is_mention):
        logger.info("   ↳ ข้าม: ไม่ได้ถูก @ และไม่ใช่ DM")
        return

    user_id = message.author.id
    user_name = message.author.display_name

    # 🚦 rate limit — กันสแปมถี่เกินไปเผา GPU/API quota (ต่อ user)
    if not _check_cooldown(user_id):
        logger.info(f"   ↳ ข้าม: {user_name} ส่งถี่เกินไป (cooldown {_COOLDOWN_SEC}s)")
        return

    # ลบส่วน mention ออกจากข้อความ เหลือแค่เนื้อหาที่ผู้ใช้พิมพ์
    user_message = re.sub(r"<@!?\d+>", "", message.content).strip()
    if not user_message:
        logger.info("   ↳ ข้าม: ข้อความว่างหลังตัด mention "
              "(มักเพราะ MESSAGE CONTENT INTENT ยังไม่เปิดในเว็บ Discord)")
        return

    logger.debug(f"   ↳ ส่งให้โมเดล: {user_message!r}")

    # ===== 🖨️ ระบบพิมพ์ PDF (อยู่ในไฟล์ printing.py) =====
    # หาไฟล์ PDF ที่แนบมา (ถ้ามี) และดูว่าข้อความสื่อถึงการพิมพ์ไหม
    pdf_attach = next(
        (a for a in message.attachments if a.filename.lower().endswith(".pdf")), None)
    wants_print = any(k in user_message.lower() for k in printing.PRINT_TRIGGERS)

    # ===== 📄 RAG PDF — แนบ PDF มาแต่ไม่ได้สั่งพิมพ์ = ให้รอสเต้ "อ่าน" เก็บไว้ถามได้ =====
    # เก็บแบบ persist ต่อ user (vectormemory.py) — ถามถึงเนื้อหาไฟล์นี้ทีหลัง (คนละเซสชัน) ได้เลย
    if pdf_attach and not wants_print and pdf_attach.size > MAX_PDF_SIZE_BYTES:
        logger.warning(f"   ⚠️ ปฏิเสธ PDF {pdf_attach.filename!r} — ไฟล์ใหญ่เกิน "
              f"({pdf_attach.size / 1024 / 1024:.1f}MB > {MAX_PDF_SIZE_BYTES / 1024 / 1024:.0f}MB)")
        await message.reply(f"ไฟล์นี้ใหญ่เกินไปค่ะ (เกิน {MAX_PDF_SIZE_BYTES // 1024 // 1024}MB) รอสเต้ขอไม่อ่านนะคะ")
    elif pdf_attach and not wants_print:
        try:
            pdf_bytes = await pdf_attach.read()
            n_chunks = await vectormemory.ingest_pdf(user_id, pdf_attach.filename, pdf_bytes)
            if n_chunks:
                logger.info(f"   📄 อ่าน PDF {pdf_attach.filename!r} เก็บไว้แล้ว ({n_chunks} chunks)")
            else:
                logger.warning(f"   ⚠️ อ่าน PDF {pdf_attach.filename!r} ไม่ได้ข้อความเลย (อาจเป็นสแกน/รูปภาพ)")
        except Exception as e:
            logger.warning(f"   ⚠️ RAG PDF พลาด: {type(e).__name__}: {e}")
        # ไม่ return — ปล่อยให้ไหลต่อไปตอบแชตตามปกติ (ask_ollama จะค้นเนื้อหานี้ประกอบคำตอบเอง)

    # ถ้ากำลังพิมพ์งานอื่นอยู่ — ล็อก ตอบว่ายุ่งก่อน (ทุกข้อความ)
    if printing.print_lock.locked():
        await message.reply(
            "ขอโทษค่ะ ตอนนี้รอสเต้กำลังพิมพ์งานอยู่ ขอพิมพ์ให้เสร็จก่อนนะคะ เดี๋ยวมาคุยต่อค่ะ")
        return

    # ยืนยันงานใหญ่ที่ค้างอยู่ (ต้องเป็นคนสั่งคนเดิม)
    if user_message.strip() in ("ยืนยัน", "ยืนยันค่ะ", "ยืนยันครับ") and user_id in printing.pending_prints:
        job = printing.pop_pending_if_valid(user_id)
        if job is None:
            await message.reply("งานที่รอยืนยันหมดอายุไปแล้วนะคะ (เกิน 5 นาที) ส่งไฟล์มาสั่งพิมพ์ใหม่ได้เลยค่ะ")
            return
        logger.info(f"   🖨️ ยืนยันพิมพ์: {job['filename']} × {job['copies']} ชุด")
        await printing.run_print_job(message, job)
        return

    # คำสั่งพิมพ์ใหม่: ต้องมีไฟล์ PDF แนบ + มีคำว่าพิมพ์ + เป็นคนที่ได้รับอนุญาต
    if pdf_attach and wants_print:
        if user_id not in PRINT_ALLOWED_USER_IDS:
            logger.warning(f"   🚫 ปฏิเสธคำสั่งพิมพ์จากผู้ใช้ที่ไม่ได้รับอนุญาต: {user_name} ({user_id})")
            await message.reply("ขอโทษค่ะ คำสั่งพิมพ์นี้ใช้ได้เฉพาะเจ้าของรอสเต้เท่านั้นนะคะ")
            return
        logger.info(f"   🖨️ รับคำสั่งพิมพ์: {pdf_attach.filename}")
        await printing.start_print_request(message, user_id, user_name, pdf_attach, user_message)
        return

    # ===== 🎵 ระบบเพลง karaoke =====
    wants_song = ("เพลง" in user_message and
                  any(w in user_message for w in ("ร้อง", "เปิด", "เล่น", "ขอ")))
    if wants_song:
        if music.voice_lock.locked():
            # ใช้ voice_lock ร่วมกับ TTS พูดตอบปกติด้วย ("กำลังร้องเพลง" อาจไม่ตรงถ้า lock ถูกจองจากพูดตอบ)
            await message.reply("ตอนนี้รอสเต้กำลังใช้เสียงอยู่ (พูดหรือร้องเพลง) รอแป๊บนึงแล้วลองใหม่นะคะ")
            return
        if not message.author.voice or not message.author.voice.channel:
            await message.reply("เข้าห้อง voice ก่อนนะคะ เดี๋ยวรอสเต้ร้องให้ฟัง~")
            return
        query = music.extract_song_query(user_message)
        result = music.find_karaoke(query) if query else music.get_random_karaoke()
        music.log_song_request(user_name, query or "(สุ่ม)", found=bool(result))
        if result:
            song_path, stem = result
            pretty = music.prettify_song_name(stem)
            logger.info(f"   🎵 karaoke: {pretty!r} (ขอโดย {user_name})")
            await message.reply(f"🎵 รอสเต้จะร้องเพลง \"{pretty}\" ให้ฟังนะคะ~")
            asyncio.create_task(_play_karaoke(message, song_path, pretty))
        else:
            not_found = ("รอสเต้ไม่เคยฟังเพลงนั้นมาก่อนเลยค่ะ เดี๋ยวไปหัดร้องก่อนนะคะ~"
                         if query else "รอสเต้ยังไม่มีเพลงในคลังเลยค่ะ ยังต้องเตรียมให้ค่ะ~")
            logger.info(f"   🎵 karaoke ไม่เจอ: {query!r} (ขอโดย {user_name})")
            await message.reply(not_found)
            asyncio.create_task(_speak_in_voice(message, not_found))
        return

    # เช็กก่อนว่าเป็น "คำสั่งความจำ" ไหม (เช่น จำไว้ว่า...) ถ้าใช่ตอบเลยไม่ต้องเรียกโมเดล
    mem_reply = memory.handle_memory_command(user_id, user_name, user_message)
    if mem_reply is not None:
        logger.info("   ↳ จัดการคำสั่งความจำ")
        await message.reply(mem_reply)
        return

    # แสดงสถานะ "กำลังพิมพ์..." ระหว่างรอโมเดลคิด
    async with message.channel.typing():
        try:
            reply = await chat.ask_ollama(user_id, user_name, user_message)
            logger.info(f"   ↳ ได้คำตอบแล้ว ({len(reply)} ตัวอักษร)")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            if "Timeout" in type(e).__name__:
                reply = "หืม... ขอโทษค่ะ คิดนานเกินไปจนหมดเวลาพอดี (โมเดลอาจกำลังรันบน CPU เลยช้า)"
            else:
                reply = f"ขอโทษค่ะ มีข้อผิดพลาด ({err}) ลองเช็กว่า Ollama เปิดอยู่ไหมนะคะ"
            logger.error(f"   ↳ ❌ ERROR: {err}")

    # Discord จำกัดข้อความไม่เกิน 2000 ตัวอักษร
    if len(reply) > 2000:
        reply = reply[:1990] + "…"

    await message.reply(reply)

    # 🎙️ TTS — join voice + ทักทาย (ถ้าเพิ่งเข้า) + เล่นคำตอบ + ค้างห้อง
    asyncio.create_task(_speak_in_voice(message, reply))

    # 🪄 จำเอง — ทำเบื้องหลังหลังตอบไปแล้ว (ไม่บล็อก ผู้ใช้ไม่ต้องรอ)
    #    เฉพาะข้อความที่ไม่ใช่คำสั่ง/เพลง และผ่านการกรองหยาบใน auto_remember
    chat._enqueue_bg(chat.auto_remember(user_id, user_name, user_message))


if __name__ == "__main__":
    _acquire_singleton_lock()   # กันรัน instance ซ้อน — ต้องทำก่อน client.run() เสมอ
    # log_handler=None — เราตั้ง logging เองแล้วด้านบน (rotating file + console) ไม่ให้ discord.py
    # ผูก handler ของตัวเองซ้อนเข้า root logger อีกชุด (เดิมทำให้ log ของ discord.py ซ้ำสองบรรทัดทุกครั้ง)
    client.run(DISCORD_TOKEN, log_handler=None)
