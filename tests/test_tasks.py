"""
Unit tests for tasks.py — state machine + SQLite persistence (ร่างตาม docs/roste-plan.md รอบ 2)
Run: pytest tests/test_tasks.py -v
"""
import pytest

import tasks


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """แต่ละเทสได้ไฟล์ .db แยกของตัวเอง — กันเทสชนกัน/เขียนทับ data/tasks.db จริง"""
    monkeypatch.setattr(tasks, "DB_PATH", str(tmp_path / "test_tasks.db"))
    tasks.init_db()


class TestCreateAndGet:
    def test_create_returns_pending_task(self):
        t = tasks.create_task("news_digest", {"foo": "bar"}, user_id=123)
        assert t.status == tasks.PENDING
        assert t.kind == "news_digest"
        assert t.user_id == 123
        assert t.payload == {"foo": "bar"}
        assert t.result is None
        assert t.attempt == 0

    def test_create_without_user_id_for_system_initiated_task(self):
        """proactive/ระบบเริ่มเอง ไม่มีคนสั่ง — user_id ต้องเป็น None ได้ (ไม่บังคับ NOT NULL)"""
        t = tasks.create_task("proactive_check", {})
        assert t.user_id is None

    def test_get_task_round_trips_payload(self):
        created = tasks.create_task("smart_plug_toggle", {"device": "lamp1", "on": True})
        fetched = tasks.get_task(created.id)
        assert fetched.payload == {"device": "lamp1", "on": True}

    def test_get_nonexistent_task_returns_none(self):
        assert tasks.get_task("ไม่มีจริง") is None


class TestStateTransitions:
    def test_pending_to_running_allowed(self):
        t = tasks.create_task("k", {})
        updated = tasks.update_status(t.id, tasks.RUNNING)
        assert updated.status == tasks.RUNNING
        assert updated.attempt == 1   # เข้า RUNNING นับเป็น attempt แรก

    def test_running_to_completed_with_result(self):
        t = tasks.create_task("k", {})
        tasks.update_status(t.id, tasks.RUNNING)
        done = tasks.update_status(t.id, tasks.COMPLETED, result={"ok": True})
        assert done.status == tasks.COMPLETED
        assert done.result == {"ok": True}

    def test_running_to_failed_with_error(self):
        t = tasks.create_task("k", {})
        tasks.update_status(t.id, tasks.RUNNING)
        failed = tasks.update_status(t.id, tasks.FAILED, error="ollama timeout")
        assert failed.status == tasks.FAILED
        assert failed.error == "ollama timeout"

    def test_running_to_waiting_and_back(self):
        """WAITING = รอ external event (คนยืนยัน/sensor) ไม่ใช่รอ CPU — ต้องกลับ RUNNING ได้"""
        t = tasks.create_task("smart_plug_toggle", {})
        tasks.update_status(t.id, tasks.RUNNING)
        waiting = tasks.update_status(t.id, tasks.WAITING)
        assert waiting.status == tasks.WAITING
        resumed = tasks.update_status(t.id, tasks.RUNNING)
        assert resumed.status == tasks.RUNNING
        assert resumed.attempt == 2   # กลับเข้า RUNNING รอบสอง

    def test_completed_is_terminal(self):
        t = tasks.create_task("k", {})
        tasks.update_status(t.id, tasks.RUNNING)
        tasks.update_status(t.id, tasks.COMPLETED, result={})
        with pytest.raises(tasks.InvalidTransition):
            tasks.update_status(t.id, tasks.RUNNING)

    def test_failed_is_terminal(self):
        t = tasks.create_task("k", {})
        tasks.update_status(t.id, tasks.RUNNING)
        tasks.update_status(t.id, tasks.FAILED, error="x")
        with pytest.raises(tasks.InvalidTransition):
            tasks.update_status(t.id, tasks.COMPLETED)

    def test_pending_to_completed_skipping_running_rejected(self):
        """กันเผลอข้าม RUNNING ไปเลย — งานที่ "เสร็จ" ต้องผ่าน "กำลังทำ" มาก่อนเสมอ"""
        t = tasks.create_task("k", {})
        with pytest.raises(tasks.InvalidTransition):
            tasks.update_status(t.id, tasks.COMPLETED, result={})

    def test_invalid_status_string_rejected(self):
        t = tasks.create_task("k", {})
        with pytest.raises(ValueError):
            tasks.update_status(t.id, "ทำเสร็จแล้วมั้ง")

    def test_update_nonexistent_task_raises_keyerror(self):
        with pytest.raises(KeyError):
            tasks.update_status("ไม่มีจริง", tasks.RUNNING)


class TestListActive:
    def test_excludes_terminal_states(self):
        done = tasks.create_task("a", {})
        tasks.update_status(done.id, tasks.RUNNING)
        tasks.update_status(done.id, tasks.COMPLETED, result={})

        pending = tasks.create_task("b", {})

        active = tasks.list_active()
        ids = {t.id for t in active}
        assert pending.id in ids
        assert done.id not in ids

    def test_filters_by_user_id(self):
        mine = tasks.create_task("a", {}, user_id=1)
        other = tasks.create_task("b", {}, user_id=2)

        active = tasks.list_active(user_id=1)
        ids = {t.id for t in active}
        assert mine.id in ids
        assert other.id not in ids

    def test_orders_oldest_first(self):
        first = tasks.create_task("a", {})
        second = tasks.create_task("b", {})
        active = tasks.list_active()
        assert [t.id for t in active] == [first.id, second.id]


class TestPersistence:
    def test_survives_reconnect(self, tmp_path, monkeypatch):
        """จำลอง restart บอท — เปิด DB path เดิมใหม่ต้องเห็นงานเก่า (ต่างจาก _bg_queue ที่หาย
        ตอน restart) นี่คือเหตุผลหลักที่ต้องใช้ SQLite ไม่ใช่ dict in-memory เหมือน pending_prints"""
        db_path = str(tmp_path / "persist_test.db")
        monkeypatch.setattr(tasks, "DB_PATH", db_path)
        tasks.init_db()
        created = tasks.create_task("news_digest", {"x": 1}, user_id=99)

        # "restart" — ไม่มี object ไหนค้างในหน่วยความจำ อ่านจากดิสก์ใหม่ล้วนๆ
        fetched = tasks.get_task(created.id)
        assert fetched is not None
        assert fetched.kind == "news_digest"
        assert fetched.payload == {"x": 1}
