# ============================================================
#  📋 tasks.py — task state machine (ร่าง ตาม docs/roste-plan.md รอบที่ 2)
#
#  ⚠️ ไฟล์นี้ยังไม่ต่อเข้า bot.py/chat.py — เป็นโครงเปล่าที่รันเดี่ยวๆ ได้และมีเทสของตัวเอง
#  รอจนกว่าจะมี "งานที่สั่งแล้วต้อง track ยาวข้ามหลายขั้นตอน" จริง (ตัวแรกที่วางแผนไว้คือ
#  news digest ตาม docs/ROADMAP.md → "ค้างไว้/ยังไม่ต้องรีบ") ถึงจะเดินสาย TOOLS/bot.py
#  เข้ามาใช้ table นี้จริง — สร้างไว้ก่อนเพื่อร่าง schema+state machine ให้นิ่งก่อนมี use case
#  มาบังคับ (กันแก้ schema กลางคันตอนมีงานจริงมาทดสอบ)
#
#  ทำไมต้องมี table แยกจากของที่มีอยู่แล้ว:
#    - chat._bg_queue (asyncio.Queue) = fire-and-forget ไม่มี state ให้ query "งานไหนค้างอยู่"
#      ไม่ persist ข้าม restart บอท
#    - printing.pending_prints (dict in-memory) = confirmation layer ของงานเดียว (พิมพ์)
#      ไม่รองรับหลายชนิดงาน ไม่ query ย้อนหลังได้ว่างานเก่าจบยังไง
#  ทั้งสองพอใช้กับงานที่มันรองรับอยู่ แต่ไม่มีตัวไหนตอบ "มีงานอะไรค้างอยู่บ้างตอนนี้" ข้าม
#  หลายชนิดงานพร้อมกัน — นั่นคือหน้าที่ของไฟล์นี้
#
#  ทำไมสถานะเป็น column ตายตัว แต่ payload เป็น JSON:
#    งานที่ยกตัวอย่างในแผน (news digest / สั่งปลั๊กไฟ / proactive) มีรูปร่างต่างกันมาก
#    ยัดใส่ schema normalize ตั้งแต่แรกจะตันทันทีที่เจองานชนิดใหม่ (ต้อง migrate ทุกครั้ง)
#    แต่ state machine (pending/running/...) เหมือนกันทุกงาน ต้อง query ได้เร็วแบบ column จริง
#    จึงแยกสองชั้น: column ตายตัว = สถานะ+เวลา (query ได้), JSON blob = เนื้องานเฉพาะทาง
#    (ยืดหยุ่นแต่ query เจาะฟิลด์ในนั้นไม่ได้ — ยอมแลก เพราะยังไม่รู้ว่าจะต้อง query แบบไหน
#    จนกว่าจะมีงานจริงมาใช้)
# ============================================================
import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("roste.tasks")

DB_PATH = "data/tasks.db"

# สถานะที่เป็นไปได้ทั้งหมด — ตรงตามที่ระบุใน docs/roste-plan.md รอบที่ 2 เป๊ะๆ ห้ามเพิ่มเอง
# ลอยๆ โดยไม่แก้เอกสารแผนด้วย (กัน state แตกแขนงจนกลไก "เช็คว่างานค้างไหม" พังไม่ครบ)
PENDING = "pending"
RUNNING = "running"
WAITING = "waiting"      # รอ external event (เช่น รอคนยืนยัน, รอ sensor อ่านค่า) ไม่ใช่รอ CPU
COMPLETED = "completed"
FAILED = "failed"

_TERMINAL = {COMPLETED, FAILED}
_VALID_STATES = {PENDING, RUNNING, WAITING, COMPLETED, FAILED}

# state transition ที่ยอมให้เกิด — กัน bug เผลอเปลี่ยนสถานะมั่ว (เช่น completed → running)
# ซึ่งจะทำให้ agent loop รอบที่ 4.5 เข้าใจผิดว่างานที่จบแล้วยังไม่จบ
_ALLOWED_TRANSITIONS = {
    PENDING: {RUNNING, FAILED},              # FAILED ตรงนี้ = ยกเลิกก่อนเริ่ม (เช่น validate ไม่ผ่าน)
    RUNNING: {WAITING, COMPLETED, FAILED},
    WAITING: {RUNNING, FAILED},               # กลับมา RUNNING ได้เมื่อ external event มาถึง
    COMPLETED: set(),                         # terminal — ห้ามย้ายออกจากนี่อีก
    FAILED: set(),                            # terminal เหมือนกัน
}


class InvalidTransition(Exception):
    """พยายามเปลี่ยนสถานะที่ไม่อยู่ใน _ALLOWED_TRANSITIONS"""


@dataclass
class Task:
    id: str
    kind: str                          # ชื่อ tool/งาน เช่น "news_digest", "smart_plug_toggle"
    user_id: int | None                # None = งานที่ระบบเริ่มเอง ไม่มีคนสั่ง (เช่น proactive)
    status: str
    payload: dict[str, Any]            # อินพุตของงาน — รูปร่างขึ้นกับ kind ล้วนๆ
    result: dict[str, Any] | None      # ผลลัพธ์หลัง verify แล้ว (ดู หลักการข้อ 4: tool
                                        # สำเร็จ ≠ งานสำเร็จ) — None จนกว่าจะถึง terminal state
    error: str | None                  # เหตุผลถ้า FAILED (ข้อความสั้น ให้รายงานผู้ใช้ได้ตรงๆ)
    created_at: float                  # time.time() — เก็บเป็น epoch ไม่ใช่ monotonic เพราะ
                                        # ต้อง persist ข้าม restart (monotonic รีเซ็ตทุกครั้งที่บูต)
    updated_at: float
    attempt: int = 0                   # จำนวนครั้งที่ลองรันแล้ว — agent loop รอบ 4.5 ใช้เทียบ
                                        # กับเพดาน (แผนกำหนด: tool เดิม argument เดิม 2 ครั้งติด → หยุด)


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"], kind=row["kind"], user_id=row["user_id"], status=row["status"],
        payload=json.loads(row["payload"]),
        result=json.loads(row["result"]) if row["result"] is not None else None,
        error=row["error"], created_at=row["created_at"], updated_at=row["updated_at"],
        attempt=row["attempt"],
    )


def _connect() -> sqlite3.Connection:
    # check_same_thread=False: chat.py เรียกจาก asyncio event loop เดียว แต่ bench/tools
    # สคริปต์บางตัวรันแบบ sync แยก thread — sqlite3 เตือนข้ามเธรดโดย default กันเหนียวไว้
    # (งานเขียนจริงยังคอขวดที่ _bg_queue worker เดี่ยวอยู่ดี ไม่มี concurrent write จริง)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # กัน writer บล็อก reader ตอน agent loop poll สถานะ
    return conn


def init_db() -> None:
    """เรียกครั้งเดียวตอน startup (idempotent — CREATE TABLE IF NOT EXISTS)"""
    import os
    os.makedirs("data", exist_ok=True)
    with closing(_connect()) as conn, conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id         TEXT PRIMARY KEY,
                kind       TEXT NOT NULL,
                user_id    INTEGER,
                status     TEXT NOT NULL,
                payload    TEXT NOT NULL,
                result     TEXT,
                error      TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                attempt    INTEGER NOT NULL DEFAULT 0
            )
        """)
        # ดัชนีคู่นี้รองรับ query ที่คาดว่าจะใช้บ่อยสุด: "งานที่ค้างอยู่ของ user นี้" (list_active)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")


def create_task(kind: str, payload: dict[str, Any], *, user_id: int | None = None) -> Task:
    now = time.time()
    task = Task(
        id=str(uuid.uuid4()), kind=kind, user_id=user_id, status=PENDING,
        payload=payload, result=None, error=None, created_at=now, updated_at=now,
    )
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO tasks (id, kind, user_id, status, payload, result, error, "
            "created_at, updated_at, attempt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task.id, task.kind, task.user_id, task.status, json.dumps(payload, ensure_ascii=False),
             None, None, task.created_at, task.updated_at, task.attempt),
        )
    logger.info(f"   📋 task สร้างใหม่: {task.id[:8]} kind={kind!r} user_id={user_id}")
    return task


def get_task(task_id: str) -> Task | None:
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def list_active(user_id: int | None = None) -> list[Task]:
    """งานที่ยังไม่ถึง terminal state — ใช้ตอบ "มีงานอะไรค้างอยู่บ้าง" (เหตุผลหลักที่มีไฟล์นี้)"""
    query = "SELECT * FROM tasks WHERE status NOT IN ('completed', 'failed')"
    params: tuple = ()
    if user_id is not None:
        query += " AND user_id = ?"
        params = (user_id,)
    query += " ORDER BY created_at ASC"
    with closing(_connect()) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_task(r) for r in rows]


def update_status(
    task_id: str, new_status: str, *,
    result: dict[str, Any] | None = None, error: str | None = None,
) -> Task:
    """เปลี่ยนสถานะ — ตรวจ _ALLOWED_TRANSITIONS ก่อนเขียนเสมอ (กัน state เพี้ยนแบบเงียบๆ)

    result ใส่ได้เฉพาะตอนเปลี่ยนเป็น COMPLETED (ดู หลักการข้อ 4 — ต้องเป็นผลที่ verify
    แล้ว ไม่ใช่แค่ tool คืนค่าไม่ error) error ใส่ได้เฉพาะตอนเปลี่ยนเป็น FAILED
    """
    if new_status not in _VALID_STATES:
        raise ValueError(f"สถานะไม่รู้จัก: {new_status!r}")

    task = get_task(task_id)
    if task is None:
        raise KeyError(f"ไม่พบ task: {task_id}")

    if new_status not in _ALLOWED_TRANSITIONS[task.status]:
        raise InvalidTransition(
            f"task {task_id[:8]}: {task.status} → {new_status} ไม่อนุญาต "
            f"(อนุญาตแค่ {_ALLOWED_TRANSITIONS[task.status] or '(terminal, ห้ามเปลี่ยนต่อ)'})"
        )

    now = time.time()
    attempt = task.attempt + (1 if new_status == RUNNING else 0)
    with closing(_connect()) as conn, conn:
        conn.execute(
            "UPDATE tasks SET status = ?, result = ?, error = ?, updated_at = ?, attempt = ? "
            "WHERE id = ?",
            (new_status,
             json.dumps(result, ensure_ascii=False) if result is not None else None,
             error, now, attempt, task_id),
        )
    logger.info(f"   📋 task {task_id[:8]}: {task.status} → {new_status}")
    return get_task(task_id)
