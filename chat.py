"""
🧠 chat.py — สมองบทสนทนา: ask_ollama + tool-calling loop + summarize/auto-remember orchestration

รู้จัก Ollama/persona/memory/llm_tools แต่ไม่รู้จัก Discord เลย — รับ (user_id, user_name,
user_message) คืน reply เป็น string ล้วน ไม่แตะ message object ของ discord.py เลย
เผื่ออนาคตอยากทำ proactive DM (ตาม ROADMAP) หรือเทสบทสนทนาโดยไม่มี Discord ก็เรียกไฟล์นี้ตรงๆ ได้
"""
import asyncio
import logging

logger = logging.getLogger("roste.chat")

# ── background Ollama queue ────────────────────────────────────────────────────
# summarize_and_verify และ auto_remember ทำทีละตัวเพื่อกัน Ollama timeout
_bg_queue: asyncio.Queue = asyncio.Queue()
_bg_worker_task: asyncio.Task | None = None


async def _bg_worker() -> None:
    """Worker เดี่ยว: ดึง coroutine จาก queue ทำทีละตัว
    กัน summarize_and_verify + auto_remember ยิง Ollama พร้อมกัน"""
    while True:
        coro = await _bg_queue.get()
        try:
            await coro
        except Exception as e:
            # logger.exception() แนบ traceback ให้อัตโนมัติ + เข้าไฟล์ log (เดิม print_exc() ไป stderr
            # เฉยๆ ไม่เข้าไฟล์ — error กลางดึกใน background worker จะหายไปเหมือนตอนใช้ print() ธรรมดา)
            logger.exception(f"   ⚠️ bg_worker error: {type(e).__name__}: {e}")
        finally:
            _bg_queue.task_done()


def _ensure_bg_worker() -> None:
    """เริ่ม worker ถ้ายังไม่ได้เริ่มหรือ task จบไปแล้ว — safe to call multiple times"""
    global _bg_worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # ยังไม่มี event loop (เช่น import ตอน test โดยตรง)
    if _bg_worker_task is None or _bg_worker_task.done():
        _bg_worker_task = loop.create_task(_bg_worker())


def _enqueue_bg(coro) -> None:
    """ส่ง coroutine เข้า background queue (fire-and-forget แต่ serialize ลำดับ)"""
    _ensure_bg_worker()
    _bg_queue.put_nowait(coro)


# state ชั่วคราวต่อ user — ไม่ควร persist ลง JSON
_user_locks: dict = {}             # {user_id: asyncio.Lock}
_USER_LOCKS_MAX = 1000   # เกินแล้วเก็บกวาด lock ที่ไม่ได้ถูกใช้งานอยู่ตอนนี้ (ปลอดภัย — get_user_lock
                         # สร้าง Lock ใหม่ให้เองถ้าโดนลบไปแล้วแต่มีคนต้องใช้อีก ไม่มีทางเสีย state จริง)


def _purge_unlocked_locks() -> None:
    unlocked = [uid for uid, lock in _user_locks.items() if not lock.locked()]
    for uid in unlocked:
        del _user_locks[uid]


def get_user_lock(user_id) -> asyncio.Lock:
    if user_id not in _user_locks:
        if len(_user_locks) >= _USER_LOCKS_MAX:
            _purge_unlocked_locks()
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


_active_users: set = set()         # ติดตาม user ที่คุยในเซสชันนี้ (ใช้ flush history ตอนปิดบอท)
_ACTIVE_USERS_MAX = 10_000         # เพดานกันโตไม่จำกัด (แทบไม่มีทางถึงจริง) — เกินแล้วเคลียร์ทิ้งทั้งชุด
                                    # (แค่พลาด flush ตอนปิดบอทรอบถัดไปสำหรับ user เก่าที่โดนเคลียร์ ไม่เสีย
                                    # ข้อมูลถาวร เพราะ Condition A/B ใน ask_ollama summarize เองอยู่แล้ว)


def _track_active_user(user_id: int) -> None:
    if len(_active_users) >= _ACTIVE_USERS_MAX:
        _active_users.clear()
    _active_users.add(user_id)
