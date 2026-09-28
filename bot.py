import os
import sys
import re
import json
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

# alpha = ยังเปลี่ยนโครงสร้าง/พฤติกรรมได้โดยไม่ถือว่า breaking (ตาม SemVer 0.y.z)
__version__ = "0.1.1-alpha"

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
from discord.ext import voice_recv  # 👂 รับเสียงเข้า — discord.py เปล่าๆ ทำไม่ได้ (ดู stt_listener)
import stt_client    # 👂 SttWorker — warm subprocess ถอดเสียง (typhoon-asr-realtime)
import stt_listener  # 👂 AudioSink ตัดประโยคจากเสียงในห้อง → ถอด → callback
import memory     # 🧠 ระบบความจำ (load/save/facts/recall + คำสั่งจำ-ลืม)
import vectormemory  # 🔎 ความจำ/ค้นหาเชิงความหมาย (RAG PDF + semantic recall ผ่าน ChromaDB)
import websearch  # 🔎 ค้นเว็บ/Google Maps ผ่าน SerpApi (มี ddgs สำรอง)
import datasources  # 🌦️⛽🔌🕐 weather/oil/outage/เวลาไทย/แผนที่จังหวัด
import ollama_client  # 🤖 Ollama HTTP client — ทั่วไป ไม่รู้จัก TOOLS
import llm_tools  # 🛠️ TOOLS schema + tool handlers (tool calling)
import chat  # 🧠 สมองบทสนทนา — ask_ollama + tool-calling loop (ไม่รู้จัก Discord)
import stats  # 📊 เก็บสถิติ latency ต่อข้อความ/TTS (ตัวเลขล้วน ไม่มีเนื้อหา/user id)
import monitor  # 📈 เว็บเฝ้าดูสถานะบอท (/stats.json) — localhost-only by default

# สวิตช์ปิด STT ทั้งระบบ — ปิดไว้ชั่วคราวเพราะยังมีปัญหาอยู่ (รอแก้แล้วค่อยเปิดกลับ)
# ปิดที่จุดเดียวคือ _start_stt_worker() ทำให้ _stt_worker เป็น None ตลอด session ซึ่ง
# _ensure_listening() มี early-return รองรับอยู่แล้ว (ไม่ได้ยิน แต่ยัง join/ทักทาย/พูดในห้อง
# voice ได้ปกติ) — ไม่ต้องแตะจุดอื่น
STT_ENABLED = False

# state ระบบเสียง
_voice_worker: voice.RvcWorker | None = None  # RVC warm worker (None = ยังโหลดไม่เสร็จ/โหลดไม่ได้)
_f5_worker: voice.F5Worker | None = None      # F5 warm worker (None = ยังโหลดไม่เสร็จ/โหลดไม่ได้)
_voxcpm_worker: "voice.VoxCpmWorker | None" = None  # VoxCPM2 warm worker (TTS หลัก; F5 เป็น fallback)
_stt_worker: "stt_client.SttWorker | None" = None   # 👂 STT warm worker (None = โหลดไม่เสร็จ/ไม่ได้ → ไม่ฟังเสียง)
_stt_listener = None   # SttListener ที่ attach อยู่กับ voice client ปัจจุบัน (คนละอายุกับ worker —
                       # worker อยู่ยาวทั้ง session ส่วน listener ผูกกับการต่อ voice แต่ละครั้ง)
_ready_once = False  # on_ready ไม่การันตีว่าเรียกครั้งเดียว (fire ใหม่ได้ตอน gateway
                      # re-IDENTIFY หลัง session ขาด) — guard กันสร้าง worker/monitor server ซ้อน
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
# _purge_unlocked_locks, get_user_lock, _THAI_MONTHS — อยู่ใน chat.py (เรียกผ่าน chat.xxx)

# ============================================================
#  ⚙️  ตั้งค่าหลัก — แก้ตรงนี้
# ============================================================

# Token ถูกเก็บแยกไว้ในไฟล์ config.py (เปิดไฟล์นั้นเพื่อใส่/แก้ Token)
try:
    from config import DISCORD_TOKEN
except ImportError:
    logger.error("❌ ไม่พบไฟล์ config.py — วางไฟล์ config.py ไว้โฟลเดอร์เดียวกับ bot.py")
    # SystemExit เปล่าๆ (ไม่ใส่ 1) = exit code 0 — start.bat/CI จะมองว่า "สำเร็จ" ทั้งที่บอทไม่ขึ้น
    raise SystemExit(1)

# TMD_TOKEN — อยู่ใน datasources.py (เรียกผ่าน datasources.TMD_TOKEN)

# SERPAPI_KEY, _serpapi_quota_ok — อยู่ใน websearch.py (เรียกผ่าน websearch.xxx)

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

# MONITOR_HOST/MONITOR_PORT — หน้าเฝ้าดูสถานะบอท (monitor.py) ไม่ตั้งไว้ = 127.0.0.1:8765
try:
    from config import MONITOR_HOST, MONITOR_PORT
except ImportError:
    MONITOR_HOST, MONITOR_PORT = "127.0.0.1", 8765

# เช็กว่าใส่ Token จริงแล้วหรือยัง ถ้ายังให้เตือนชัดๆ
if not DISCORD_TOKEN or DISCORD_TOKEN == "วาง_TOKEN_ของคุณ_ที่นี่":
    logger.warning("⚠️ ยังไม่ได้ใส่ Token! เปิดไฟล์ config.py แล้ววาง Token จาก Discord ก่อนนะครับ")
    # SystemExit เปล่าๆ (ไม่ใส่ 1) = exit code 0 — start.bat/CI จะมองว่า "สำเร็จ" ทั้งที่บอทไม่ขึ้น
    # (เจอจริงจาก CI: เทส singleton คาดว่า subprocess ที่ถูกปฏิเสธต้อง exit != 0 แต่บน runner
    # ที่ไม่มี .env โพรเซสมาตายที่ด่านนี้ด้วยโค้ด 0 ก่อนถึง lock — เทสเลย fail เฉพาะบน CI)
    raise SystemExit(1)

# OLLAMA_URL, MODEL — อยู่ใน ollama_client.py (เรียกผ่าน ollama_client.xxx)

# 🖨️ ระบบพิมพ์อยู่ในไฟล์ printing.py | 🎵 ระบบเพลงอยู่ในไฟล์ music.py
# (แก้ตั้งค่าเครื่องพิมพ์ในไฟล์ printing.py, ตั้งค่าโฟลเดอร์เพลงในไฟล์ music.py)


# ============================================================
#  🔎  เครื่องมือค้นเว็บ — อยู่ใน websearch.py (cache, SerpApi, ddgs fallback)
#      เรียกผ่าน websearch.xxx (SERPAPI_KEY, search_web, search_places_serpapi ฯลฯ)
# ============================================================


# TOOLS, TOOL_HANDLERS, _validate_tool_args, _strip_ungrounded_optional_args, _search_places,
# make_search_query, _tool_get_current_time, _tool_get_weather, _tool_get_power_outage,
# _tool_get_oil_price, _tool_search_places, _tool_search_web — อยู่ใน llm_tools.py
# (เรียกผ่าน llm_tools.xxx) — ต่อ tool ใหม่ (IoT, reminder, ...) แก้ที่ llm_tools.py แทน


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
            if _voxcpm_worker is not None:
                _voxcpm_worker.stop()
                logger.info("   🎙️ VoxCPM2 worker ปิดแล้ว")
            _stop_listening()   # ก่อน stop worker — listener ยังอาจถือ job ค้างอยู่ในคิว
            if _stt_worker is not None:
                _stt_worker.stop()
                logger.info("   👂 STT worker ปิดแล้ว")
            await _monitor_server.stop()
            await super().close()


client = RosteClient(intents=intents)

# auto_remember, _check_condition_b, _SUMMARY_NOTICE_*, _maybe_append_summary_notice,
# detect_topic_change, summarize_and_verify, flush_user_history, flush_all_users, ask_ollama,
# ask_ollama_stream — อยู่ใน chat.py — เรียกจาก on_message/on_close ผ่าน chat.xxx แบบเต็มชื่อเสมอ


def _worker_status(worker) -> str:
    if worker is None:
        return "not_started"
    if worker.load_time == 0.0:
        return "loading"
    if not worker.alive:
        return "dead"
    return "ready"


def _get_bot_status() -> dict:
    """สถานะภายในบอทสำหรับ /stats.json — ตัวเลข/สถานะล้วนๆ ห้ามมีเนื้อหาข้อความ/user id เด็ดขาด
    (นับจำนวน user ที่คุยวันนี้เฉยๆ ไม่โชว์ ID ตามวินัย PII ของโปรเจค)"""
    return {
        "discord_connected": not client.is_closed(),
        "rvc_worker": _worker_status(_voice_worker),
        "f5_worker": _worker_status(_f5_worker),
        "voxcpm_worker": _worker_status(_voxcpm_worker),
        "bg_queue_size": chat._bg_queue.qsize(),
        "is_speaking_or_singing": music.voice_lock.locked(),
        "is_printing": printing.print_lock.locked(),
        "active_users_today": len(chat._active_users),
    }


_monitor_server = monitor.MonitorServer(_get_bot_status, host=MONITOR_HOST, port=MONITOR_PORT)


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


async def _start_stt_worker() -> None:
    """โหลด STT worker (typhoon-asr-realtime บน NeMo) ใน thread แยก (~12s boot)

    ล้มเหลว = _stt_worker เป็น None แล้วบอทก็แค่ "ไม่ได้ยิน" — พิมพ์คุยได้ตามปกติ
    ทุกอย่างที่เหลือไม่พึ่ง STT เลย จึงไม่ต้อง retry/บล็อก startup
    """
    global _stt_worker
    if not STT_ENABLED:
        logger.info("👂 STT ปิดใช้งาน (STT_ENABLED=False) — บอทจะไม่ได้ยินเสียงในห้อง")
        _stt_worker = None
        return
    try:
        await asyncio.to_thread(_stt_worker.start)
        logger.info(f"👂 STT worker พร้อม — โหลดเสร็จใน {_stt_worker.load_time:.1f}s")
    except Exception as e:
        logger.warning(f"⚠️ STT worker เริ่มไม่ได้ ({type(e).__name__}: {e}) — บอทจะไม่ได้ยินเสียงในห้อง")
        _stt_worker = None


async def _start_voxcpm_worker() -> None:
    """โหลด VoxCPM2 worker ใน thread แยก (~60-75s boot — ช้ากว่า F5 มาก)

    ระหว่างที่ยังโหลดไม่เสร็จ บอทตอบด้วย F5 ไปก่อนได้ตามปกติ (fail-safe chain
    เลือก engine ตอน generate ไม่ใช่ตอน startup) จึงไม่ต้องรอตัวนี้
    """
    global _voxcpm_worker
    if not voice.VOXCPM_ENABLED:
        logger.info("🎙️ VoxCPM2 ปิดใช้งาน (VOXCPM_ENABLED=False) — ใช้ F5")
        _voxcpm_worker = None
        return
    try:
        await asyncio.to_thread(_voxcpm_worker.start)
        logger.info(f"🎙️ VoxCPM2 worker พร้อม — โหลดเสร็จใน {_voxcpm_worker.load_time:.1f}s")
    except Exception as e:
        logger.warning(f"⚠️ VoxCPM2 worker เริ่มไม่ได้ ({type(e).__name__}: {e}) — ใช้ F5 แทน")
        _voxcpm_worker = None


async def _generate_tts(text: str, uid: int) -> str | None:
    """สร้างไฟล์เสียง TTS ใน thread แยก — คืน path .wav หรือ None ถ้า skip/error"""
    # worker.load_time > 0 = start() เสร็จแล้ว (ready)
    # VoxCPM2 ไม่ต้องพึ่ง RVC (ref เป็นเสียงรอสเต้อยู่แล้ว) — ถ้ามันพร้อม ปล่อยผ่าน
    # แม้ RVC ยังโหลดไม่เสร็จ ไม่งั้นจะเสียเสียงไปเปล่าๆ ช่วงแรกหลัง startup
    _vox_ready = _voxcpm_worker is not None and _voxcpm_worker.alive
    if not _vox_ready and (
        _voice_worker is None or _voice_worker.load_time == 0.0 or not _voice_worker.alive
    ):
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
                voxcpm_worker=_voxcpm_worker,
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
    # VoxCPM2 ไม่ต้องพึ่ง RVC (ref เป็นเสียงรอสเต้อยู่แล้ว) — ถ้ามันพร้อม ปล่อยผ่าน
    # แม้ RVC ยังโหลดไม่เสร็จ ไม่งั้นจะเสียเสียงไปเปล่าๆ ช่วงแรกหลัง startup
    _vox_ready = _voxcpm_worker is not None and _voxcpm_worker.alive
    if not _vox_ready and (
        _voice_worker is None or _voice_worker.load_time == 0.0 or not _voice_worker.alive
    ):
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
                    voxcpm_worker=_voxcpm_worker,
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
    not_just_joined: TTS คำตอบ → เล่นคำตอบ  ค้างห้อง — leave timer ทำ step ต่อไป

    แยกจับเวลาเป็นหน่วยงานของตัวเอง (kind="tts") ไม่รวมกับ "llm" ของ ask_ollama — ฟังก์ชันนี้
    ถูกยิงแบบ fire-and-forget (asyncio.create_task ไม่ await) เลยจบช้ากว่าข้อความตอบเป็นข้อความ
    มาก บางทีก็ข้ามไปเลยถ้าไม่มีใครอยู่ใน voice ถือเป็น "งาน" คนละหน่วยไปเลยแม่นกว่าฝืนรวม"""
    _stats_token = stats.start_message("tts")
    try:
        await _speak_in_voice_impl(message, reply_text)
    finally:
        stats.finish_message(_stats_token)


async def _prepare_voice_speech(message):
    """โปรลอกก่อนพูดทุกเส้น (เส้นพิมพ์/เส้น stream ใช้ร่วมกัน — เคย copy สองที่ก่อนหน้านี้
    แล้วเส้นเดียวเผลอแก้ อีกเส้นเหลือพฤติกรรมเก่าเงียบๆ): เช็คว่า user อยู่ voice จริง กันชน
    music, connect/ย้ายห้อง, เริ่มฟังเสียง, เตรียมเสียงทักทาย

    คืน (bot_vc, greeting_wav) — None = ไม่พูด (เหตุผล log ไว้แล้วทุก branch)"""
    user_vc = getattr(message.author, "voice", None)
    if not user_vc or not user_vc.channel:
        return None
    if music.song_playing:
        # เพลงเล่นอยู่จริง — ไม่ตัดกลางคัน (คนสั่งให้ร้องยังฟังอยู่) อยากให้หยุดต้องสั่ง
        # "เงียบหน่อย" ซึ่งมีเส้นทางของมันเองใน _on_voice_utterance
        logger.info("   🎙️ TTS skip — เพลงกำลังเล่น")
        return None

    channel = user_vc.channel
    bot_vc  = message.guild.voice_client

    # Join / move ห้อง — ติดตามว่าเพิ่งเข้าหรือไม่
    just_joined = False
    try:
        with stats.stage("voice_connect"):
            if bot_vc is None or not bot_vc.is_connected():
                if bot_vc is not None:
                    try:
                        _stop_listening()
                        await bot_vc.disconnect(force=True)
                    except Exception:
                        pass
                bot_vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
                just_joined = True
            elif bot_vc.channel.id != channel.id:
                await bot_vc.move_to(channel)
                just_joined = True
    except Exception as e:
        logger.warning(f"   ⚠️ voice connect error ({type(e).__name__}: {e})")
        return None

    logger.info(f"   🎙️ voice — {'เพิ่งเข้า' if just_joined else 'อยู่แล้ว'} ห้อง {channel.name!r}")
    # พูดแจ้งว่าเริ่มฟังเฉพาะตอนเพิ่งเข้าห้อง — ไม่งั้นพูดซ้ำทุกครั้งที่คุยด้วยเสียง
    await _ensure_listening(bot_vc, announce=just_joined)

    # ดึง greeting (cache instantaneous ยกเว้นครั้งแรกของ session ~8-10s)
    greeting_wav = await _get_greeting_wav() if just_joined else None

    if music.voice_lock.locked():
        logger.info("   🎙️ TTS skip (race) — music เริ่มระหว่างรอ")
        return None

    return bot_vc, greeting_wav


async def _speak_in_voice_impl(message, reply_text: str) -> None:
    """เส้นพิมพ์/เส้นขอเพลงไม่เจอ — รับ "ข้อความเต็ม" → _generate_tts_stream ตามเดิม
    (โปรลอกห้องรวมกับเส้น stream ที่ _prepare_voice_speech แล้ว)"""
    prepared = await _prepare_voice_speech(message)
    if prepared is None:
        return
    bot_vc, greeting_wav = prepared

    async with music.voice_lock:
        with stats.stage("tts_gen_play"):
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
                            bot_vc = await fresh_vc.channel.connect(cls=voice_recv.VoiceRecvClient)
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


async def _aclose_async_gen(gen) -> None:
    """ปิด async generator อย่างเงียบๆ — ใช้ตอน bail ก่อนเริ่มพูด เพื่อให้ finally ข้างใน
    (stats.finish_message ของ ask_ollama_stream) วิ่งทันที ไม่ต้องรอ GC มาเก็บ"""
    try:
        await gen.aclose()
    except Exception:
        pass


# ── 🎙️ เส้นเสียงแบบ stream — ประโยคจากโมเดลไหลเข้า TTS/ลำโพงทันทีที่จบประโยค ──────

async def _speak_stream_in_voice(message, sentence_iter) -> None:
    """พูดคำตอบจาก async iterator ของประโยค (chat.ask_ollama_stream) — เริ่มเจน/เล่นเสียง
    ประโยคแรกได้ทันทีที่โมเดลเขียนประโยคแรกจบ ไม่ต้องรอคำตอบทั้งก้อน

    เป็นท่อ 3 ชั้น โดยแต่ละชั้นมีผู้เล่น "ตัวเดียว" ลำดับเสียงจึงการันตีด้วยโครงสร้าง
    (FIFO ของ Queue) ไม่ใช่ด้วยความหวังว่า worker จะเสร็จตามกันเอง:
      _pump       → ผู้เล่นตัวเดียวของ sentence_iter — ยัดประโยคลง sent_q
      _tts_worker → ผู้เล่นตัวเดียวของ sent_q — เรียก _generate_tts_stream *ต่อประโยค*
                    (ข้างในยังเป็น producer thread เดียว + Queue + _tts_lock เหมือนเดิม
                     แค่ scope ล็อกเปลี่ยนจาก "ครอบทั้งคำตอบ" เป็น "ครอบทีละประโยค" — ยัง
                     serialize เหมือนเดิมเพราะ worker มีตัวเดียว ไม่มีทางเจนแข่งกันเอง)
                    แล้วยัด .wav ลง wav_q
      (ลูปด้านล่าง) → ผู้เล่นตัวเดียวของ wav_q — เล่นทีละ segment รอจบก่อนเล่นถัดไปเสมอ

    วัดจริง (chat.ask_ollama_stream): คุยชิลๆ เสียงแรกพร้อมที่ 1560ms คำตอบเต็ม 3867ms
    (5 chunks) → เริ่มพูดได้เร็วขึ้น ~2.3 วิ | ส่วนเทิร์น tool ได้ chunk เดียว 3590 ≈ 3591ms
    = ไม่มีกำไร (ประโยคเดียวไม่มีอะไรให้ pipeline) แต่ก็ไม่เสียอะไร จึงใช้สายเดียวกันทุกเทิร์น
    """
    prepared = await _prepare_voice_speech(message)
    if prepared is None:
        # ไม่ได้เข้าเส้นพูดเลย (ไม่มีคนอยู่ห้อง/music ชนะแข่ง) — ปิด generator ให้สนิท
        await _aclose_async_gen(sentence_iter)
        return
    bot_vc, greeting_wav = prepared

    uid = message.author.id
    gid = message.guild.id if message.guild else None

    # เคลียร์ธง "เพิ่งถูกสั่งหยุด" ของเทิร์นก่อน — ไม่งั้นคำตอบใหม่จะโดนยกเลิกทันทีที่เริ่ม
    # (ธงค้างข้ามเทิร์นได้ pattern เดียวกับ _play_karaoke ที่ discard ก่อนเริ่มเพลง)
    if gid is not None:
        music.stopped_guilds.discard(gid)

    def _user_stopped() -> bool:
        # คำสั่งหยุด ("เงียบหน่อย") ถูกจัดการใน _on_voice_utterance อีก task — สื่อสารกัน
        # ผ่านธงกลาง music.stopped_guilds ฝั่งเดียวกับเส้น karaoke
        return gid is not None and gid in music.stopped_guilds

    sent_q: asyncio.Queue = asyncio.Queue()   # ประโยค (str) — ไม่จำกัดคิวตามเส้นเดิมที่ producer เจนนำเสมอ
    wav_q: asyncio.Queue = asyncio.Queue()    # path .wav พร้อมเล่น เรียงตามลำดับประโยค
    stop_pipe = asyncio.Event()               # สั่งปิดท่อ (โดนหยุด/เล่นจบ/พัง)

    async def _pump() -> None:
        # ผู้เล่นตัวเดียวของ sentence_iter — ถ้าถูก cancel ตรง __anext__ CancelledError จะทะลุ
        # ผ่าน generator ของ chat ทำให้ finally ข้างใน (stats + คืน user lock) วิ่งเอง
        try:
            async for piece in sentence_iter:
                piece = piece.strip()
                if piece:
                    await sent_q.put(piece)
        finally:
            await sent_q.put(None)   # sentinel ปิดท้ายเสมอ — worker ไม่มีทางรอประโยคค้างตลอด

    async def _tts_worker() -> None:
        # แปลงประโยคเป็นเสียง "ทีละประโยคตามลำดับ" — จบประโยคนึงค่อยหยิบประโยคถัดไป
        # ลำดับเสียงจึงตรงกับลำดับประโยคเสมอแม้ประโยคหลังเจนเร็วกว่า
        while True:
            sentence = await sent_q.get()
            if sentence is None or stop_pipe.is_set():
                break
            seg_stream = _generate_tts_stream(sentence, uid)
            try:
                async for wav in seg_stream:
                    await wav_q.put(wav)
            except Exception as e:
                # ประโยคนี้เจนไม่รอด — ข้ามไปประโยคถัดไปดีกว่าทำทั้งคำตอบร่วง
                # (ขาดหนึ่งประโยคผู้ฟังยังตามเรื่องได้ เงียบทั้งคำตอบคือพังหนักกว่า)
                logger.warning(f"   ⚠️ TTS ประโยคนี้พัง ({type(e).__name__}: {e}) — ข้าม")
            finally:
                # ปิดทุกครั้ง — finally ข้างในรอ producer thread จบ + เก็บกวาด segment ค้าง
                # (thread cancel ไม่ได้ ประโยคสั้นจึงปล่อยให้รอบปัจจุบันจบก่อนเสมอ)
                try:
                    await seg_stream.aclose()
                except Exception:
                    pass
        await wav_q.put(None)

    pump_task = asyncio.create_task(_pump())
    tts_task = asyncio.create_task(_tts_worker())

    n_played = 0
    aborted = False
    async with music.voice_lock:
        with stats.stage("tts_gen_play"):
            try:
                if greeting_wav:
                    # เสียงทักทายออกก่อน — ระหว่างเล่น tts_worker เจนประโยคแรกเสร็จไปแล้ว
                    # (แทนเทคนิค anext-concurrent ของเส้นพิมพ์ เพราะ worker วิ่งนำอยู่แล้ว)
                    logger.info("   🎙️ เล่นทักทาย")
                    await _play_wav(bot_vc, greeting_wav)

                while True:
                    # รอ segment แบบ poll ธงหยุดทุก 0.25s — คำสั่ง "เงียบหน่อย" ต้องตอบสนอง
                    # ทันทีแม้ตอนนั้น TTS ยังเจนประโยคถัดไปไม่เสร็จ (ไม่งั้นต้องรอเจนจบก่อน
                    # ถึงจะเช็คธงได้ = หยุดช้ากว่าควร)
                    try:
                        wav = await asyncio.wait_for(wav_q.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        if _user_stopped():
                            aborted = True
                            break
                        continue
                    if wav is None:
                        break                      # ประโยคหมด — คำตอบจบปกติ
                    if _user_stopped():
                        aborted = True
                        break
                    # Re-check connection ก่อนเล่นทุก segment (bot_vc อาจหลุดระหว่าง TTS)
                    if not bot_vc.is_connected():
                        logger.info("   🎙️ reconnect — bot_vc หลุดระหว่าง TTS")
                        fresh_vc = getattr(message.author, "voice", None)
                        if not fresh_vc or not fresh_vc.channel:
                            logger.info("   🎙️ skip — user ออก voice แล้ว")
                            break
                        try:
                            bot_vc = await fresh_vc.channel.connect(cls=voice_recv.VoiceRecvClient)
                        except Exception as e:
                            logger.warning(f"   ⚠️ reconnect error ({type(e).__name__}: {e})")
                            break

                    n_played += 1
                    logger.info(f"   🎙️ เล่น segment {n_played}")
                    await _play_wav(bot_vc, wav)
                    try:
                        os.remove(wav)
                    except OSError:
                        pass

            except Exception as e:
                logger.warning(f"   ⚠️ voice play error ({type(e).__name__}: {e})")
            finally:
                # ── ปิดท่อให้สนิททั้งสองกรณี (เล่นจบเอง / โดนสั่งหยุดกลางคัน) ──
                # ลำดับสำคัญ: ตั้งธง → ปลุก worker → หยุด pump → รอ worker เก็บงานจบ → กวาดไฟล์
                # ห้าม cancel tts_task ทิ้งเปล่า เพราะ thread generate ที่วิ่งอยู่ข้างใน cancel
                # ไม่ได้ — ปล่อยให้จบ "ประโยคปัจจุบัน" (สั้น ไม่กี่วินาที) แล้วมันออกเองที่เช็คธง
                stop_pipe.set()
                sent_q.put_nowait(None)          # ปลุก worker ที่อาจรอประโยคอยู่ (คิวไม่มีขอบเขต ไม่มีทาง raise)
                pump_task.cancel()               # หยุดดึงประโยคจากโมเดลทันที — ไม่ปล่อยให้เขียนต่อเปล่าๆ
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass
                # จับ error ของ pump ไว้ก่อน (อย่าปล่อยทิ้ง) — ถ้าสาย streaming พังจริง ๆ
                # ต้อง throw ต่อให้ _on_voice_utterance ถอยไปเส้น non-streaming
                pump_exc = None if pump_task.cancelled() else pump_task.exception()
                await tts_task
                # เก็บกวาด .wav ที่เจนล่วงหน้าไว้แล้วแต่ไม่มีวันได้เล่น (โดนสั่งหยุด/ข้ามประโยค)
                while not wav_q.empty():
                    leftover = wav_q.get_nowait()
                    if leftover:
                        try:
                            os.remove(leftover)
                        except OSError:
                            pass

    # throw หลังปล่อย voice_lock แล้วเท่านั้น — fail-safe ฝั่งผู้เรียกจะได้เข้ามา take over
    # โดยไม่ต้องมาแย่งล็อกกับงานที่กำลังจะตาย
    if pump_exc is not None:
        raise pump_exc
    logger.info(f"   🎙️ พูดจบ ({n_played} segments{' — โดนสั่งหยุดกลางคัน' if aborted else ''})")


# ── leave timer helpers ────────────────────────────────────────────────────────

def _human_count_in_channel(channel: discord.VoiceChannel) -> int:
    return sum(1 for m in channel.members if not m.bot)


# ── 👂 ฟังเสียงในห้อง (STT) ────────────────────────────────────────────────────

# บอทตอบเฉพาะประโยคที่เรียกชื่อมัน — stt_listener แก้ตัวสะกดที่ ASR เขียนเพี้ยนให้เป็น
# "รอสเต้" ก่อนส่งมาถึงตรงนี้แล้ว (ดู _NAME_FIXES) แต่ยังเผื่อ variant ไว้ด้วย เพราะ
# ASR อาจเพี้ยนแบบใหม่ที่ยังไม่มีในตาราง — พลาดแล้วบอทเงียบ ผู้ใช้ไม่รู้ว่าทำไม
_BOT_NAME_RE = re.compile(r"รอสเต|ลอสเต|ล็อตเต|ลอตเต|roste", re.IGNORECASE)

# ── ตัดสิน "นี่คือการเรียกรอสเต้จริงไหม" ด้วย LLM ─────────────────────────────
#
# ที่มา: transcript จริงจากห้อง voice (26 ส.ค. 2569) มีข้อความที่ผ่าน _BOT_NAME_RE มาแล้ว
# (มีคำว่า "รอสเต้"/variant อยู่จริง) แต่ไม่ใช่การเรียกบอทจริงเลย 2 แบบ:
#   1. ASR hallucinate ทั้งประโยคจาก noise/เสียงพูดเร็ว แล้ว stt_listener._NAME_LOOSE_RE
#      (หลวมโดยตั้งใจ — ยอมรับ false positive มากกว่า false negative) บิดคำที่ไม่เกี่ยวข้อง
#      ให้กลายเป็น "รอสเต้": "รอสเต้เขา", "รอสเต้รอตีก็เร็ว", "รอสเต้องออกกันคีกี่ตัวว่า"
#      — ไม่ใช่ประโยคไทยที่มีความหมาย
#   2. คนในห้องคุยกันเอง บังเอิญเอ่ยชื่อบอทหรือคุยกับคนอื่นถึงบอท ไม่ได้ตั้งใจสั่งงาน:
#      "รอสเต้" (เรียกเฉยๆ ไม่มีคำสั่ง/คำถาม), "รอสเต้ได้รับ" (ประโยคบอกเล่า ไม่ใช่คำสั่ง)
#
# regex เดิม (มีคำว่า "รอสเต้" = ตอบ) จับ false positive ทั้งสองแบบ เพราะเช็คแค่การมีคำ
# ไม่เช็คว่าทั้งประโยคสมเหตุสมผล/มุ่งหาบอทจริงไหม — ทั้งสองสัญญาณอยู่ใน *ข้อความที่ถอดแล้ว*
# เอง ไม่ต้องมีเสียงต้นฉบับมาเทียบ (ตัวอย่างข้างบนตัดสินได้จากตัวหนังสือล้วนๆ)
#
# ⚠️ ลองโมเดลเล็ก (OLLAMA_EXTRACT_MODEL = qwen3:4b) ก่อนตามแพทเทิร์นของ
# stt_listener._ask_llm_finished แล้ว **วัดจริงแล้วพัง**: 3/10 บนชุดเคสจริงจาก transcript
# ห้อง voice (26 ส.ค. 2569 — 9 เคส false-positive ที่ตั้งใจแก้ + 1 เคสเรียกจริง) พรอมป์ต์
# เดียวกันเป๊ะยิงกับ MODEL หลัก (qwen3:8b) ได้ 10/10 เต็ม — พิสูจน์ว่าปัญหาไม่ใช่ prompt
# แต่เป็นความสามารถของโมเดล งานนี้ยากกว่า end-of-turn detection ที่ qwen3:4b ทำได้ 77%
# (ต้องตัดสิน "สมเหตุสมผล" + "มุ่งหาบอท" พร้อมกัน ไม่ใช่แค่ดู marker ท้ายประโยค) จึงใช้ MODEL
# หลักแทน แลกกับ latency ที่ต้องแชร์คิวกับงานตอบจริง (ต่างจาก EOT ที่จงใจใช้โมเดลแยกเพื่อ
# ไม่ให้ p95 พุ่งตอนโมเดลหลักงานยุ่ง — ที่นี่รับ trade-off นี้เพราะความแม่นสำคัญกว่า latency
# เมื่อผลลัพธ์คือ "ตอบไหม" ไม่ใช่แค่ "หยุดรอนานแค่ไหน")
#
# ถ้าจะลองโมเดลเล็กอีกตัว/ปรับ prompt ในอนาคต ต้อง re-run เทียบกับชุดเคสเดียวกันนี้ก่อน
# เปลี่ยน ห้ามเดาว่าดีขึ้นจากการอ่าน prompt เฉยๆ (บทเรียนซ้ำจากทั้งไฟล์นี้)
_INTENT_FEWSHOT = (
    "ข้อความต่อไปนี้เป็น transcript จากการถอดเสียงพูดในห้องแชทเสียง Discord (อาจมีคำผิด/"
    "ไม่เป็นประโยค เพราะมาจากการถอดเสียงอัตโนมัติ) มีคำว่า \"รอสเต้\" (ชื่อ AI ผู้ช่วย) อยู่ "
    "จงตัดสินว่าข้อความนี้กำลัง \"เรียก/สั่ง/ถามรอสเต้จริง\" หรือไม่ โดยต้องผ่านทั้ง 2 ข้อ:\n"
    "1. เป็นประโยคภาษาไทยที่มีความหมายสมเหตุสมผล (ไม่ใช่คำเละที่ถอดเสียงผิดจน noise)\n"
    "2. ฟังดูเหมือนกำลังพูดคุย/สั่งงาน/ถามรอสเต้ตรงๆ (ไม่ใช่แค่เอ่ยชื่อผ่านๆ หรือคุยกับคนอื่น)\n"
    "ตอบเป็น JSON รูปแบบ {\"call\": true} หรือ {\"call\": false} เท่านั้น\n\n"
    'ข้อความ: รอสเต้ตอนนี้กี่โมงแล้ว\n{"call": true}\n\n'
    'ข้อความ: รอสเต้พรุ่งนี้สภาพอากาศเป็นยังไงบ้าง\n{"call": true}\n\n'
    'ข้อความ: เฮ้รอสเต้ช่วยเปิดเพลงหน่อย\n{"call": true}\n\n'
    'ข้อความ: รอสเต้\n{"call": false}\n\n'
    'ข้อความ: รอสเต้ได้รับ\n{"call": false}\n\n'
    'ข้อความ: เดี๋ยวรอสเต้ตอบเองแหละ อย่าไปยุ่ง\n{"call": false}\n\n'
    'ข้อความ: รอสเต้เขา\n{"call": false}\n\n'
    'ข้อความ: รอสเต้รอตีก็เร็ว\n{"call": false}\n\n'
    'ข้อความ: รอสเต้องออกกันคีกี่ตัวว่า\n{"call": false}\n\n'
    "ข้อความ: "
)

_INTENT_FORMAT_SCHEMA = {
    "type": "object",
    "properties": {"call": {"type": "boolean"}},
    "required": ["call"],
}

# สวิตช์ปิดได้โดยไม่ต้องแกะโค้ด กลับไปพฤติกรรมเดิม (regex ล้วน) — ในจิตวิญญาณเดียวกับ
# stt_listener.TURN_LLM
INTENT_LLM = True
# ใช้ MODEL หลัก = แทบไม่มี cold start (โมเดลเดียวกับที่ตอบแชต อยู่ใน VRAM ตลอดช่วงคุยด้วย
# เสียงอยู่แล้ว) วัดจริงตอน warm/ไม่มีคิวรอ: 0.3-0.5s/ครั้ง
#
# ⚠️ timeout ต้องกว้างกว่านั้นมาก เพราะ call นี้ยิง MODEL เดียวกับที่ตอบแชต/เสียงจริง —
# ถ้ามีคำตอบยาวกำลัง generate อยู่ก่อน (วัดไว้ที่อื่นในโปรเจกต์นี้: full answer ~12s,
# EOT call ของ qwen3:4b ใต้ contention พุ่งจาก 410ms เป็น 5375ms เพราะคิวหลังงานแชต —
# ดู stt_listener.py comment เหนือ TURN_LLM) intent gate ที่ยิงโมเดลเดียวกับงานแชตเลย
# (ไม่ใช่โมเดลแยกแบบ EOT) เสี่ยงคิวนานกว่านั้นอีก timeout สั้นเกินจะทำให้ "Ollama ช้าเพราะ
# กำลังยุ่ง" ถูกนับเป็น "Ollama ตาย" ผิดๆ ผ่าน ollama_client._record_failure() ซึ่งเป็น
# breaker ระดับ**โมดูล** (คุมทุกการเรียก Ollama ในบอท ไม่ใช่แค่ตัวนี้) — คนพูดชื่อบอทติดกัน
# 3 คนตอน Ollama ยุ่งอยู่แล้วจะทำให้ breaker เปิดปิดกั้นแชตข้อความ/เสียงทั้งหมด 30 วิ
# ทั้งที่ Ollama ไม่ได้ล่มจริง จึงตั้งกว้างพอให้คิวผ่านได้จริงแม้มีคำตอบยาวค้างอยู่ก่อน
INTENT_LLM_TIMEOUT_SEC = 20.0


async def _ask_llm_is_call(text: str) -> bool | None:
    """ถามโมเดลหลักว่า "ข้อความนี้เรียกรอสเต้จริงไหม" — คืน True/False หรือ None ถ้าพลาด
    (Ollama ล่ม/timeout/breaker เปิด/JSON ผิดรูป) ผู้เรียกต้อง fallback เมื่อได้ None
    ใช้ ollama_client.MODEL (เดียวกับที่ตอบแชต) ไม่ใช่ OLLAMA_EXTRACT_MODEL — วัดจริงแล้วว่า
    โมเดลเล็กทำงานนี้ไม่ไหว (ดู comment เหนือ _INTENT_FEWSHOT)"""
    payload = {
        "model": ollama_client.MODEL,
        "messages": [{"role": "user", "content": _INTENT_FEWSHOT + text.strip()}],
        "stream": False, "think": False,
        "format": _INTENT_FORMAT_SCHEMA,
        "options": {"temperature": 0.0},
    }
    try:
        data = await ollama_client._get_json_post(payload, timeout=INTENT_LLM_TIMEOUT_SEC)
        # _strip_think ตัด <think> ที่หลุดมาปนก่อน parse เสมอ (เหมือนทุกจุดใน chat.py ที่
        # parse JSON จาก Ollama) — แม้ format+think:False จะบังคับไว้แล้ว โมเดล reasoning
        # ตระกูล qwen3 เคยพิสูจน์แล้วว่าไม่เคารพ think:False 100% ในบางเงื่อนไข (ดู comment
        # ใน config.py) ไม่มีต้นทุนเพิ่มถ้าไม่มี tag เลย จึงใส่ไว้กันเหนียว
        content = ollama_client._strip_think(data["message"]["content"])
        call = json.loads(content)["call"]
        return bool(call)
    except Exception as e:
        logger.debug(f"   👂 ถาม LLM intent-gate ล้มเหลว: {type(e).__name__}: {e}")
        return None


async def _passes_intent_gate(text: str) -> bool:
    """True = ควรตอบ (ผ่าน echo เข้าห้องแชต + ป้อนเข้า chat pipeline)

    fail-safe: ถามไม่สำเร็จ (Ollama ล่ม/timeout/breaker เปิด) → คืน True คือถอยไปพฤติกรรม
    เดิมก่อนมีตัวกรองนี้ (มีคำเรียก = ตอบ) ไม่ใช่เงียบทั้งห้อง — โครงสร้างพัง (Ollama ตาย)
    ไม่ควรทำให้ทั้งฟีเจอร์ฟังเสียงใช้งานไม่ได้ไปด้วย ต่างจาก "ไม่แน่ใจเพราะเนื้อหากำกวม"
    (โมเดลตอบมาแล้วว่า False) ซึ่งเชื่อคำตอบนั้นตรงๆ — ผู้เรียกต้องเช็ค _BOT_NAME_RE ก่อน
    เรียกฟังก์ชันนี้เสมอ (ไม่เช่นนั้นเสีย LLM call กับทุกประโยคที่ไม่มีคำเรียกเลย)"""
    if not INTENT_LLM:
        return True
    verdict = await _ask_llm_is_call(text)
    if verdict is None:
        return True
    return verdict

class _VoiceMessage:
    """shim ให้เสียงพูดใช้เส้นทางเดียวกับข้อความพิมพ์ได้

    _speak_in_voice_impl() แตะแค่ .author.voice / .guild / .author.display_name —
    ไม่ได้ใช้ .content, .reply(), .channel.typing() ฯลฯ ที่มีเฉพาะ Message จริง
    จึงห่อ member ให้พอดีกับที่มันใช้ ดีกว่าแยกเขียน TTS path ที่สองมาให้ต่างกันเงียบๆ
    """

    __slots__ = ("author", "guild")

    def __init__(self, member: discord.Member):
        self.author = member
        self.guild = member.guild


async def _on_voice_utterance(member: discord.Member, text: str) -> None:
    """คนในห้องพูดจบหนึ่งประโยค → ป้อนเข้า chat pipeline เหมือนพิมพ์ แล้วตอบด้วยเสียง

    เรียกจาก SttListener บน event loop ของบอท (มัน schedule มาให้แล้ว — ดู
    stt_listener._dispatch_callback) จึง await ได้ตามปกติ
    """
    if not text.strip():
        return
    # ต้องเรียกชื่อบอทก่อน — ห้อง voice มีคนคุยกันเองตลอด ถ้าตอบทุกประโยคที่ได้ยิน
    # บอทจะแทรกบทสนทนาคนอื่นและเปลือง LLM ทุกครั้ง (ตรรกะเดียวกับที่แชตต้อง @ ก่อน)
    if _BOT_NAME_RE.search(text) is None:
        logger.debug(f"   👂 ข้าม (ไม่ได้เรียกชื่อ) — {member.display_name}: {text}")
        return

    logger.info(f"   👂 {member.display_name} พูดว่า: {text}")

    # แสดง transcript ทันทีที่ได้ยิน — ต้องอยู่ *ก่อน* ทุก branch ที่ return ออกไป (สั่งหยุด/
    # intent gate/ขอเพลง) ไม่งั้นคำสั่งพวกนั้นจะเงียบไม่มี feedback เลย ทั้งที่เป็นตอนที่ผู้ใช้
    # อยากรู้ที่สุดว่าบอทได้ยินถูกไหม (ASR สะกดชื่อเพลงเพี้ยนบ่อย — เห็น transcript แล้วรู้ทันที
    # ว่าทำไมได้เพลงผิด, เห็น transcript ที่ intent gate กรองทิ้งก็ช่วย debug ว่า gate ตัดสิน
    # ถูกไหม) ส่ง fire-and-forget ไม่ให้ไปหน่วงการเล่นเพลง/หยุดเสียง
    text_channel = _find_text_channel(member)
    if text_channel:
        asyncio.create_task(_safe_send(text_channel, f"🎙️ **{member.display_name}:** {text}"))

    # ===== 🔇 สั่งหยุด — ต้องมาก่อนทุกอย่างรวมถึง intent gate ด้านล่าง =====
    # เหตุผลเดียวกับเส้นทางแชต: คนสั่งหยุดตอนบอทกำลังส่งเสียงอยู่ ถ้าไปเข้าคิว LLM ก่อน
    # จะรออีก 6 วินาทีกว่าจะหยุด — ซึ่งนานเกินจนคนต้องตะโกนซ้ำ (เจอจริง: พูด "เงียบหน่อย"
    # สองรอบติด บอทตอบเป็นข้อความยาวทั้งสองรอบแทนที่จะหยุด) — ต้องอยู่*ก่อน*_passes_intent_gate
    # ด้วยเหตุผลเดียวกันเป๊ะ (เคยเผลอวาง gate ไว้ก่อนตอน dev แล้วเจอบั๊กเดิมซ้ำ — ทั้งช้าลง
    # จากคิว LLM และเสี่ยง gate ตัดสินว่าคำสั่งหยุดสั้นๆ ไม่ใช่การเรียก แล้วทิ้งไปเงียบๆ)
    # เป็น pure regex ไม่มี LLM เลย จึงไม่มีต้นทุนต้องแลกกับความแม่นของ intent gate
    vc = member.guild.voice_client if member.guild else None
    if music.looks_like_pure_stop(text):
        if vc and (vc.is_playing() or vc.is_paused()):
            if member.guild:
                music.stopped_guilds.add(member.guild.id)
            vc.stop()
            logger.info(f"   🔇 หยุดเสียงตามคำสั่งเสียงของ {member.display_name}")
        return                     # ไม่ต้องพูดตอบ — คนขอให้เงียบ การพูดตอบคือสิ่งที่เขาไม่อยากได้

    # ด่านสอง — regex เช็คแค่ "มีคำว่ารอสเต้ไหม" ผ่านแล้วไม่ได้แปลว่าถูกเรียกจริง (เจอจริง:
    # ASR hallucinate ข้อความเละที่มีคำว่ารอสเต้ปนมา / คนอื่นคุยกันเองบังเอิญเอ่ยชื่อ —
    # ดู comment เหนือ _INTENT_FEWSHOT) ให้ LLM เล็กอ่านทั้งประโยคตัดสินอีกชั้น — ทำงานหลัง
    # echo เสมอ (transcript ถูกส่งไปแล้วข้างบน) เพื่อให้ debug ได้ว่า gate ตัดสินถูกไหมจากดูคู่
    # กับข้อความที่เห็นในห้องแชตจริง ไม่ใช่กรอง echo ด้วย
    if not await _passes_intent_gate(text):
        logger.debug(f"   👂 ข้าม (LLM ตัดสินว่าไม่ได้เรียก) — {member.display_name}: {text}")
        return

    # ขอเพลง — ต้องเช็คก่อนเรียก LLM เหมือนเส้นทางแชต (on_message) ไม่งั้นโมเดลจะตอบเป็น
    # ข้อความว่า "ได้ค่ะเดี๋ยวร้องให้" แล้วไม่ร้องจริง (เจอจริง: ขอทางเสียงแล้วบอทพูดตอบ
    # 160 ตัวอักษรแต่ไม่เคยเข้า _play_karaoke เลย)
    if await _handle_voice_song_request(member, text):
        return

    # 🎙️ ตอบเป็นเสียงแบบ stream — ประโยคไหนของโมเดลเขียนจบก่อน ประโยคนั้นเข้า TTS/ลำโพงก่อน
    # ไม่ต้องรอคำตอบทั้งก้อน (วัดจริง: คุยชิลๆ เริ่มพูดได้เร็วขึ้น ~2.3 วิ; เทิร์น tool ได้
    # คำตอบประโยคเดียวจึงเท่าเดิม — ไม่มีกำไรแต่ไม่เสีย ยอมรับไว้)
    # ตั้งใจให้มี fallback สองชั้น: ask_ollama_stream ถอยไป ask_ollama เองได้ข้างในแล้ว
    # รอดมาถึงตรงนี้ = fallback ข้างในพังซ้ำ หรือท่อ TTS/เล่นเสียงเองมีปัญหา — ชั้นนี้จึง
    # ย้อนกลับไปพฤติกรรมเดิม "รอคำตอบเต็มแล้วค่อยพูด" คนรอเสียงต้องไม่มีวันเจอความเงียบ
    try:
        stream = chat.ask_ollama_stream(member.id, member.display_name, text)
        await _speak_stream_in_voice(_VoiceMessage(member), stream)
        return
    except Exception as e:
        logger.warning(f"   👂 ↳ streaming พัง ({type(e).__name__}: {e}) — ถอยไปเส้นรอคำตอบเต็ม")

    try:
        # voice_reply=True — คำตอบจะถูกพูดอย่างเดียว สั่งให้สั้นลง (ดู persona.build_author_note)
        reply = await chat.ask_ollama(member.id, member.display_name, text,
                                      is_speaking=False, voice_reply=True)
    except ollama_client.OllamaUnavailable as e:
        # breaker เปิดอยู่ — fallback ชั้นบน (บรรทัด 876) ก็เจอ breaker เดียวกันแล้วถอยลงมา
        # ที่นี่ ดังนั้นจะซ้ำ raise แบบเดิมแน่ๆ ถ้าปล่อยผ่าน except Exception เฉยๆ ผู้ใช้จะ
        # เงียบสนิท ขัดกับที่คอมเมนต์ด้านบนตั้งใจไว้ว่า "คนรอเสียงต้องไม่มีวันเจอความเงียบ"
        # จึงพูดสั้นๆ แทน error เงียบ
        logger.error(f"   👂 ❌ Ollama ไม่พร้อม: {e}")
        await _speak_in_voice(_VoiceMessage(member),
                              "ตอนนี้สมองรอสเต้ยังไม่พร้อมค่ะ รออีกสักครู่แล้วลองใหม่นะคะ")
        return
    except Exception as e:
        logger.error(f"   👂 ❌ ตอบเสียงไม่ได้ ({type(e).__name__}: {e})")
        return

    logger.info(f"   👂 ↳ ตอบ ({len(reply)} ตัวอักษร)")
    # ตอบเป็นเสียงอย่างเดียว — คนพูดอยู่ในห้อง voice ไม่ได้จ้องแชต การส่งข้อความด้วย
    # จะกลายเป็นสแปมห้องแชตทุกครั้งที่คุยด้วยเสียง
    await _speak_in_voice(_VoiceMessage(member), reply)


# ประโยคที่รอสเต้พูดตอนเริ่มฟังเสียงได้แล้ว — cache เหมือน _GREETING_WAV เพราะข้อความคงที่
# TTS ใช้เวลา ~7s ทุกครั้งถ้าไม่ cache ซึ่งช้าเกินสำหรับสัญญาณ "พร้อมแล้ว"
_LISTEN_READY_TEXT = "รอสเต้เข้ามาแล้วนะคะ ฟังอยู่ค่ะ เรียกชื่อรอสเต้แล้วพูดได้เลย"
_LISTEN_READY_WAV: str | None = None


async def _get_listen_ready_wav() -> str | None:
    global _LISTEN_READY_WAV
    if _LISTEN_READY_WAV is None:
        _LISTEN_READY_WAV = await _generate_tts(_LISTEN_READY_TEXT, 0)
    return _LISTEN_READY_WAV


def _find_text_channel(member: discord.Member):
    """ห้องที่ควรโพสต์ transcript ของคนที่พูด — คืน None ถ้าไม่มีที่ส่ง

    ใช้ห้อง voice ที่เขาอยู่เป็นหลัก: discord.py 2.x รองรับ text-in-voice (VoiceChannel
    เป็น Messageable) ข้อความจึงไปอยู่ในห้องเดียวกับที่กำลังคุยด้วยเสียงพอดี — ไม่ต้องเดา
    ว่าห้องแชตไหนเกี่ยวข้อง และคนที่ไม่ได้อยู่ในห้องก็ไม่โดนสแปม
    """
    vc = getattr(member, "voice", None)
    return vc.channel if vc and vc.channel else None


async def _safe_send(channel, content: str) -> None:
    """ส่งข้อความแบบไม่ให้ error ทำงานอื่นพัง — transcript หายไม่ใช่เรื่องคอขาดบาดตาย
    (ห้องอาจปิดสิทธิ์ส่งข้อความ / rate limit / ห้องถูกลบระหว่างนั้น)"""
    try:
        await channel.send(content[:2000])
    except Exception as e:
        logger.debug(f"   👂 ส่ง transcript ไม่ได้ ({type(e).__name__}: {e})")


async def _handle_voice_song_request(member: discord.Member, text: str) -> bool:
    """ขอเพลงทางเสียง — คืน True ถ้าจัดการแล้ว (ผู้เรียกต้องไม่ไปเรียก LLM ต่อ)

    เงื่อนไขตรวจจับเดียวกับเส้นทางแชตใน on_message ตั้งใจ — สองทางต้องเข้าใจ "ขอเพลง"
    เหมือนกัน ไม่งั้นผู้ใช้เจอพฤติกรรมต่างกันโดยไม่มีเหตุผลที่อธิบายได้
    ตอบกลับเป็นเสียงอย่างเดียว (คนพูดอยู่ในห้อง voice ไม่ได้จ้องแชต)
    """
    if not ("เพลง" in text and any(w in text for w in ("ร้อง", "เปิด", "เล่น", "ขอ"))):
        return False

    msg = _VoiceMessage(member)
    if music.voice_lock.locked():
        await _speak_in_voice(msg, "ตอนนี้รอสเต้กำลังใช้เสียงอยู่ค่ะ รอแป๊บนึงนะคะ")
        return True

    user_vc = getattr(member, "voice", None)
    if not user_vc or not user_vc.channel:
        return True          # ไม่ได้อยู่ในห้อง = ไม่มีทางได้ยินอยู่แล้ว

    query = music.extract_song_query(text)
    result = music.find_karaoke(query) if query else music.get_random_karaoke()
    music.log_song_request(member.display_name, query or "(สุ่ม)", found=bool(result))
    if result:
        song_path, stem = result
        pretty = music.prettify_song_name(stem)
        logger.info(f"   🎵 karaoke (เสียง): {pretty!r} (ขอโดย {member.display_name})")
        # บอกว่าได้เพลงอะไร — ASR สะกดชื่อเพลงเพี้ยนบ่อย (fuzzy match ช่วยหาเจอ แต่ผู้ใช้
        # ควรเห็นว่ามันเลือกเพลงไหน ไม่ใช่รอฟังแล้วค่อยรู้ว่าผิด)
        ch = _find_text_channel(member)
        if ch:
            asyncio.create_task(_safe_send(ch, f"🎵 กำลังร้อง **{pretty}** ให้ฟังค่ะ~"))
        asyncio.create_task(_play_karaoke(msg, song_path, pretty))
    else:
        not_found = ("รอสเต้ไม่เคยฟังเพลงนั้นมาก่อนเลยค่ะ เดี๋ยวไปหัดร้องก่อนนะคะ~"
                     if query else "รอสเต้ยังไม่มีเพลงในคลังเลยค่ะ ยังต้องเตรียมให้ค่ะ~")
        logger.info(f"   🎵 karaoke (เสียง) ไม่เจอ: {query!r}")
        await _speak_in_voice(msg, not_found)
    return True


async def _ensure_listening(vc, announce: bool = False) -> None:
    """เริ่มฟังเสียงในห้องถ้ายังไม่ได้ฟัง — idempotent เรียกทุกครั้งที่ต่อ/ย้ายห้องได้

    announce: ให้รอสเต้ *พูดออกเสียง* ว่าเริ่มฟังแล้ว — ผู้ใช้อยู่ในห้อง voice ไม่ได้จ้อง
    แชตหรือ log จึงไม่มีทางรู้ว่าบอทฟังอยู่ไหม (เจอจริงตอนทดสอบ: พูดใส่ไปแล้วเงียบ
    โดยไม่รู้ว่าเพราะยังไม่เริ่มฟัง หรือฟังแล้วแต่ถอดเสียงไม่ออก) เสียงบอกได้ตรงจุดกว่า
    """
    global _stt_listener
    if _stt_worker is None or not _stt_worker.alive:
        return          # ไม่พูดอะไร — บอทเข้าห้องมาทักทายตามปกติอยู่แล้ว แค่ไม่ได้ยิน
    if _stt_listener is not None and vc.is_connected():
        return                    # ฟังอยู่แล้วกับ client ตัวนี้
    try:
        _stt_listener = await stt_listener.start_listening(
            vc, _stt_worker, _on_voice_utterance, on_speech_start=_barge_in)
        logger.info("   👂 เริ่มฟังเสียงในห้องแล้ว")
    except Exception as e:
        logger.warning(f"   ⚠️ เริ่มฟังเสียงไม่ได้ ({type(e).__name__}: {e})")
        _stt_listener = None
        return

    if not announce:
        return
    # เล่นหลัง listener พร้อมแล้วเท่านั้น — ถ้าพูดก่อนจะโกหกผู้ใช้ว่าฟังอยู่ทั้งที่ยัง
    # fire-and-forget: ไม่ให้การทักทายไปหน่วง TTS คำตอบจริงที่กำลังจะตามมา
    async def _announce():
        try:
            wav = await _get_listen_ready_wav()
            if wav and vc.is_connected():
                async with music.voice_lock:
                    await _play_wav(vc, wav)
        except Exception:
            logger.debug("   👂 พูดแจ้งเริ่มฟังไม่สำเร็จ", exc_info=True)

    asyncio.create_task(_announce())


def _stop_listening() -> None:
    """หยุดฟัง — ต้องเรียกก่อน vc.disconnect() ทุกครั้ง ไม่งั้น thread ของ listener
    ค้างอ้างอิง voice client ที่ตายแล้ว"""
    global _stt_listener
    if _stt_listener is None:
        return
    try:
        _stt_listener.cleanup()
    except Exception:
        logger.debug("   👂 cleanup listener มีปัญหา", exc_info=True)
    _stt_listener = None


def _barge_in(member: discord.Member) -> None:
    """มีคนเริ่มพูดขณะบอทกำลังพูด → หยุดเสียงบอททันที (barge-in)

    เรียกจาก sink thread ผ่าน loop.call_soon_threadsafe — vc.stop() แตะ state ของ
    discord.py จึงต้องรันบน event loop เท่านั้น

    ไม่แตะตอน karaoke/เพลง (music.voice_lock) — คนสั่งให้ร้องแล้วบังเอิญคุยกันต่อ
    ไม่ควรทำให้เพลงหยุดกลางคัน ต่างจาก TTS ที่การพูดขัดคือเจตนาชัดเจน
    """
    vc = member.guild.voice_client if member.guild else None
    if vc is None or not vc.is_playing():
        return
    if music.voice_lock.locked():
        return
    vc.stop()
    logger.info(f"   ✋ {member.display_name} พูดขัด — หยุดเสียงบอท")


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
    _stop_listening()
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
            bot_vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
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

    # ธงว่า "ถูกผู้ใช้สั่งหยุด" — ตั้งโดย on_message ตอนเจอคำสั่งหยุด
    # เคลียร์ตอนเริ่มเพลงใหม่ กันธงค้างจากเพลงก่อนหน้า
    _gid = message.guild.id if message.guild else None
    if _gid is not None:
        music.stopped_guilds.discard(_gid)

    def stopped_by_user() -> bool:
        return _gid is not None and _gid in music.stopped_guilds

    async with music.voice_lock:
        # ธงนี้ต่างจาก voice_lock.locked() — บอกว่าเป็น "เพลง" ไม่ใช่บอทพูดตอบ
        # _prepare_voice_speech ใช้แยกสองกรณี: เพลงห้ามตัดกลางคัน ส่วน TTS รอคิวได้
        music.song_playing = True
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
                    bot_vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
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
            # ⚠️ ข้ามถ้าถูกสั่งหยุดกลางเพลง — ผู้ใช้เพิ่งสั่งให้เงียบ การพูดต่อ
            #    "ร้องจบแล้วค่ะ เพราะไหม~" คือการไม่ฟังคำสั่ง
            outro_wav = None if stopped_by_user() else await _generate_tts(
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
        finally:
            # ต้องปลดเสมอ — ธงค้าง = บอทเงียบถาวรจนกว่าจะรีสตาร์ท (แย่กว่าบั๊กเดิม)
            music.song_playing = False

    try:
        if bot_vc.is_connected():
            _stop_listening()
            await bot_vc.disconnect()
    except Exception:
        pass
    if stopped_by_user():
        music.stopped_guilds.discard(_gid)
        logger.info("   🔇 karaoke ถูกสั่งหยุดกลางเพลง — ไม่ส่งข้อความปิดท้าย")
        return
    await message.channel.send(
        f"{message.author.mention} ร้องจบแล้วค่ะ เป็นไงบ้างคะ เพราะไหม~ 🎶")


@client.event
async def on_ready():
    global _voice_worker, _f5_worker, _voxcpm_worker, _stt_worker, _ready_once
    logger.info(f"✅ ล็อกอินสำเร็จในชื่อ: {client.user}")
    chat._ensure_bg_worker()   # เริ่ม background queue worker (idempotent อยู่แล้ว — เรียกซ้ำได้)

    if _ready_once:
        # discord.py ไม่การันตีว่า on_ready เรียกครั้งเดียว — gateway re-IDENTIFY หลัง session
        # ขาด (เน็ตสะดุดนาน) fire ซ้ำได้ ถ้าสร้าง worker/monitor server ใหม่ทับตัวเดิมโดยไม่ guard
        # จะได้ subprocess ผีค้าง VRAM (RVC/F5) + monitor server ตัวที่สองชนพอร์ตตัวแรก crash
        logger.info("   ↳ on_ready ยิงซ้ำ (gateway reconnect) — ข้าม re-init worker/monitor")
        return
    _ready_once = True

    _voice_worker = voice.RvcWorker()
    _f5_worker = voice.F5Worker()
    _voxcpm_worker = voice.VoxCpmWorker()
    _stt_worker = stt_client.SttWorker()
    asyncio.create_task(_start_voice_worker())   # โหลด RVC เบื้องหลัง ไม่บล็อก startup
    asyncio.create_task(_start_f5_worker())      # โหลด F5 เบื้องหลัง ไม่บล็อก startup
    asyncio.create_task(_start_voxcpm_worker())  # โหลด VoxCPM2 เบื้องหลัง (ช้าสุด ~60-75s)
    asyncio.create_task(_start_stt_worker())     # โหลด STT เบื้องหลัง (~12s)
    await _monitor_server.start()
    logger.info(f"🖨️ ระบบพิมพ์: {'โหมดจริง' if printing.PRINT_REAL_MODE else 'โหมดจำลอง (ยังไม่สั่งเครื่องจริง)'}")
    logger.info("🎙️ workers กำลังโหลดในเบื้องหลัง (RVC ~8s, F5 ~14s, VoxCPM2 ~60-75s)...")
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

    # กัน DM ที่ไม่ได้รับอนุญาต (ถ้าไม่ตั้ง DM_ALLOWED_USER_IDS ไว้ = ตอบทุกคน (เดิม ไม่กระทบของเก่า))
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

    # ===== 🔇 สั่งหยุดร้อง/หยุดพูด =====
    # ต้องเช็ค **ก่อน** ด่าน voice_lock ของ karaoke — ไม่งั้นคำสั่งหยุดจะโดนเด้ง
    # "รอแป๊บนึงแล้วลองใหม่นะคะ" ซึ่งเป็นตอนที่ผู้ใช้ต้องการใช้มันที่สุดพอดี
    #
    # vc.stop() ทำให้ callback `after` ของ discord.py ยิงทันที -> done.set() ->
    # _play_karaoke/_play_wav ที่ await อยู่เดินต่อจนจบและคืน voice_lock เอง
    # จึงไม่ต้องแย่ง lock และไม่มี task ค้าง
    # ทางลัด keyword — เฉพาะคำสั่งหยุด **ล้วนๆ** ที่ชัดเจน ("เงียบหน่อย" "พอแล้ว")
    # ตอบทันทีโดยไม่ต้องยิงโมเดล = เร็วกว่าและแน่นอนกว่า
    #
    # ส่วนสำนวนที่กว้างกว่านี้ **ไม่ไล่เก็บคำเอง** — ยื่น tool stop_voice ให้โมเดลตัดสินแทน
    # (§4: "กริยาไม่มีวันครบ" · วัดได้ว่าลิสต์คำจับได้แค่ 6/35 สำนวนที่ผู้ใช้น่าจะพิมพ์)
    _vc = message.guild.voice_client if message.guild else None
    _is_speaking = bool(_vc and (_vc.is_playing() or _vc.is_paused()))
    if music.looks_like_pure_stop(user_message):
        if _is_speaking:
            if message.guild:
                music.stopped_guilds.add(message.guild.id)
            _vc.stop()
            logger.info(f"   🔇 หยุดเสียงตามคำสั่งของ {user_name}")
            await message.reply("ค่ะ รอสเต้หยุดแล้วนะคะ~")
        else:
            await message.reply("ตอนนี้รอสเต้ไม่ได้ส่งเสียงอยู่นะคะ~")
        return

    # ===== 🎵 ระบบเพลง karaoke =====
    wants_song = ("เพลง" in user_message and
                  any(w in user_message for w in ("ร้อง", "เปิด", "เล่น", "ขอ")))
    if wants_song:
        if music.voice_lock.locked():
            # ใช้ voice_lock ร่วมกับ TTS พูดตอบปกติด้วย ("กำลังร้องเพลง" อาจไม่ตรงถ้า lock ถูกจองจากพูดตอบ)
            await message.reply("ตอนนี้รอสเต้กำลังใช้เสียงอยู่ (พูดหรือร้องเพลง) รอแป๊บนึงแล้วลองใหม่นะคะ")
            return
        # ใช้ getattr แทน message.author.voice ตรงๆ — DM ใช้ discord.User ซึ่งไม่มี .voice
        # attribute เลย (มีแค่ discord.Member ในเซิร์ฟเวอร์เท่านั้นที่มี) เข้าถึงตรงๆ ตอน DM จะ
        # โยน AttributeError ทำให้ขอเพลงผ่าน DM เงียบไม่ตอบอะไรเลย (pattern เดียวกับบรรทัด 402/457/515)
        user_voice = getattr(message.author, "voice", None)
        if not user_voice or not user_voice.channel:
            await message.reply("เข้าห้อง voice ก่อนนะคะ เดี๋ยวรอสเต้ร้องให้ฟัง~")
            return
        query = music.extract_song_query(user_message)
        result = music.find_karaoke(query) if query else music.get_random_karaoke()
        music.log_song_request(user_name, query or "(สุ่ม)", found=bool(result))
        if result:
            song_path, stem = result
            pretty = music.prettify_song_name(stem)
            logger.info(f"   🎵 karaoke: {pretty!r} (ขอโดย {user_name})")
            await message.reply(f'🎵 รอสเต้จะร้องเพลง "{pretty}" ให้ฟังนะคะ~')
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
            music.stop_requested = False   # เคลียร์ธงก่อนถาม กันค้างจากเทิร์นก่อน
            reply = await chat.ask_ollama(user_id, user_name, user_message,
                                          is_speaking=_is_speaking)
            logger.info(f"   ↳ ได้คำตอบแล้ว ({len(reply)} ตัวอักษร)")
            # โมเดลเรียก tool stop_voice — ตัวหยุดจริงอยู่ที่นี่ (llm_tools ไม่มี voice client)
            if music.stop_requested:
                music.stop_requested = False
                _vc2 = message.guild.voice_client if message.guild else None
                if _vc2 and (_vc2.is_playing() or _vc2.is_paused()):
                    if message.guild:
                        music.stopped_guilds.add(message.guild.id)
                    _vc2.stop()
                    logger.info(f"   🔇 หยุดเสียง (โมเดลตัดสินใจ) ตามคำขอของ {user_name}")
        except ollama_client.OllamaUnavailable as e:
            # breaker เปิดอยู่ (Ollama ล่ม/กำลังโหลดโมเดล) — ตอบทันทีแทนรอ timeout เต็ม
            reply = "ตอนนี้สมองรอสเต้ยังไม่พร้อมค่ะ (กำลังโหลดอยู่หรือเพิ่งรีสตาร์ท) รออีกสักครู่แล้วลองใหม่นะคะ"
            logger.error(f"   ↳ ❌ Ollama ไม่พร้อม: {e}")
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
    # (เส้นพิมพ์ยังใช้ข้อความเต็มตามเดิม — เฉพาะเส้นเสียงเท่านั้นที่ใช้ streaming)
    asyncio.create_task(_speak_in_voice(message, reply))

    # 🪄 จำเอง — ทำเบื้องหลังหลังตอบไปแล้ว (ไม่บล็อก ผู้ใช้ไม่ต้องรอ)
    #    เฉพาะข้อความที่ไม่ใช่คำสั่ง/เพลง และผ่านการกรองหยาบใน auto_remember
    chat._enqueue_bg(chat.auto_remember(user_id, user_name, user_message))


if __name__ == "__main__":
    _acquire_singleton_lock()   # กันรัน instance ซ้อน — ต้องทำก่อน client.run() เสมอ
    # log_handler=None — เราตั้ง logging เองแล้วด้านบน (rotating file + console) ไม่ให้ discord.py
    # ผูก handler ของตัวเองซ้อนเข้า root logger อีกชุด (เดิมทำให้ log ของ discord.py ซ้ำสองบรรทัดทุกครั้ง)
    client.run(DISCORD_TOKEN, log_handler=None)
