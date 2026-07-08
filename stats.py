"""
📊 stats.py — เก็บสถิติ latency ต่อข้อความ/TTS ไว้ในหน่วยความจำล้วนๆ (ไม่เขียนไฟล์)

ห้ามเก็บเนื้อหาข้อความ/user id/ชื่อ user เด็ดขาด — เก็บแค่ตัวเลข (เวลาแต่ละ stage) กับ
ชื่อ stage คงที่ที่รู้ล่วงหน้าเท่านั้น (ตามวินัย PII ของโปรเจค กันไม่ให้ dashboard ที่จะสร้าง
ต่อจากนี้ (monitor.py) กลายเป็นรูรั่วข้อมูลส่วนตัว)

ใช้ contextvars แทนการส่ง timer object ผ่านทุกฟังก์ชัน — ask_ollama/​_speak_in_voice แค่
start_message()/finish_message() ครอบตัวเอง แล้วเรียก stage(...) ที่จุดที่สนใจได้เลย
โดยไม่ต้องแก้ signature ของฟังก์ชันอื่นที่อยู่ระหว่างทาง งานแต่ละ asyncio task (รวมถึงที่ spawn
ผ่าน create_task) จะได้ context ของตัวเอง (copy-on-task-creation) จึงไม่ปนกันระหว่างข้อความ
ที่ประมวลผลพร้อมกันจากคนละ user"""
import contextvars
import time
from collections import deque
from contextlib import contextmanager

_HISTORY_MAXLEN = 200
_history: deque[dict] = deque(maxlen=_HISTORY_MAXLEN)

_current: contextvars.ContextVar = contextvars.ContextVar("stats_current_timer", default=None)


class _MessageTimer:
    __slots__ = ("kind", "stages", "start")

    def __init__(self, kind: str):
        self.kind = kind
        self.stages: dict[str, float] = {}
        self.start = time.monotonic()


def start_message(kind: str = "llm"):
    """เริ่มจับเวลา 1 หน่วยงาน (เช่น 1 รอบ ask_ollama หรือ 1 รอบพูดใน voice) — เรียกก่อน
    stage() ใดๆ เสมอ คืน token ไว้ปิดงานด้วย finish_message(token) ตอนจบ"""
    timer = _MessageTimer(kind)
    return _current.set(timer)


def finish_message(token) -> None:
    """จบหน่วยงาน — บันทึกลง ring buffer แล้วคืน contextvar กลับตามเดิมด้วย token"""
    timer = _current.get()
    if timer is not None:
        record = {"ts": time.time(), "kind": timer.kind,
                   "total": time.monotonic() - timer.start, **timer.stages}
        _history.append(record)
    _current.reset(token)


@contextmanager
def stage(name: str):
    """จับเวลา stage หนึ่งภายในหน่วยงานปัจจุบัน — เรียกซ้ำชื่อเดียวกันได้ในหน่วยงานเดียวกัน
    (เวลาบวกสะสม) ถ้ายังไม่ได้ start_message() ไว้ก่อน (เช่น เทส/เรียกนอกบริบท) จะไม่ error
    แค่ไม่มีอะไรถูกบันทึก"""
    timer = _current.get()
    if timer is None:
        yield
        return
    t0 = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - t0
        timer.stages[name] = timer.stages.get(name, 0.0) + elapsed


def get_recent(n: int = 50, kind: str | None = None) -> list[dict]:
    """คืน record ล่าสุด n อัน (ใหม่สุดอยู่ท้ายลิสต์) กรองด้วย kind ได้ถ้าระบุ"""
    items = list(_history)
    if kind is not None:
        items = [r for r in items if r.get("kind") == kind]
    return items[-n:]


def get_summary() -> dict:
    """avg/max/count ต่อ stage (รวมทุก kind ปนกัน) จากทั้ง ring buffer"""
    items = list(_history)
    if not items:
        return {}
    stage_names = {"total"}
    for r in items:
        stage_names.update(k for k in r if k not in ("ts", "kind", "total"))

    summary = {}
    for name in stage_names:
        vals = [r[name] for r in items if name in r]
        if vals:
            summary[name] = {
                "avg": sum(vals) / len(vals),
                "max": max(vals),
                "count": len(vals),
            }
    return summary
