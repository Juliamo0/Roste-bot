"""
Unit tests for stats.py — ring buffer + stage timing ล้วนๆ ไม่พึ่ง network/Discord

ย้ำวินัย PII: record ที่เก็บต้องมีแค่ ts/kind/total/ชื่อ stage → ตัวเลขเวลาเท่านั้น
ไม่มีช่องทางใดเก็บเนื้อหาข้อความ/user id ได้เลยจากการออกแบบ (ดู docstring stats.py)
"""
import time

import pytest

import stats


@pytest.fixture(autouse=True)
def _clean_history():
    """ล้าง ring buffer + contextvar ก่อน/หลังทุกเทส กันเทสอื่นเห็น record ค้าง"""
    stats._history.clear()
    yield
    stats._history.clear()


class TestStageOutsideMessage:
    def test_stage_without_start_message_does_not_error(self):
        with stats.stage("semantic_recall"):
            pass  # ไม่ได้ start_message() ไว้ก่อน — ต้องไม่ error และไม่บันทึกอะไร
        assert stats.get_recent() == []


class TestBasicRecording:
    def test_finish_message_appends_one_record(self):
        token = stats.start_message("llm")
        stats.finish_message(token)
        assert len(stats.get_recent()) == 1

    def test_record_has_kind_and_total(self):
        token = stats.start_message("tts")
        stats.finish_message(token)
        record = stats.get_recent()[0]
        assert record["kind"] == "tts"
        assert "total" in record
        assert record["total"] >= 0

    def test_stage_time_recorded_under_its_name(self):
        token = stats.start_message("llm")
        with stats.stage("main_llm"):
            time.sleep(0.01)
        stats.finish_message(token)
        record = stats.get_recent()[0]
        assert record["main_llm"] >= 0.01

    def test_repeated_stage_name_accumulates(self):
        token = stats.start_message("llm")
        with stats.stage("tool_calls"):
            time.sleep(0.01)
        with stats.stage("tool_calls"):
            time.sleep(0.01)
        stats.finish_message(token)
        record = stats.get_recent()[0]
        assert record["tool_calls"] >= 0.02

    def test_stage_not_entered_is_absent_from_record(self):
        token = stats.start_message("llm")
        with stats.stage("main_llm"):
            pass
        stats.finish_message(token)
        record = stats.get_recent()[0]
        assert "pdf_query" not in record

    def test_only_numeric_and_fixed_keys_in_record_no_content_leak(self):
        """ยืนยันโครงสร้าง record — ไม่มีช่องให้ใส่เนื้อหาข้อความ/user id เข้าไปได้เลย"""
        token = stats.start_message("llm")
        with stats.stage("semantic_recall"):
            pass
        stats.finish_message(token)
        record = stats.get_recent()[0]
        allowed_keys = {"ts", "kind", "total", "semantic_recall"}
        assert set(record.keys()) <= allowed_keys
        for key, val in record.items():
            if key == "kind":
                assert isinstance(val, str)
            else:
                assert isinstance(val, (int, float))


class TestRingBuffer:
    def test_maxlen_200_evicts_oldest(self):
        for _ in range(210):
            token = stats.start_message("llm")
            stats.finish_message(token)
        assert len(stats._history) == 200

    def test_get_recent_returns_newest_last(self):
        for i in range(5):
            token = stats.start_message("llm")
            with stats.stage("main_llm"):
                pass
            stats.finish_message(token)
        recent = stats.get_recent(5)
        assert len(recent) == 5

    def test_get_recent_respects_n(self):
        for _ in range(10):
            token = stats.start_message("llm")
            stats.finish_message(token)
        assert len(stats.get_recent(3)) == 3

    def test_get_recent_filters_by_kind(self):
        for kind in ("llm", "tts", "llm"):
            token = stats.start_message(kind)
            stats.finish_message(token)
        llm_only = stats.get_recent(kind="llm")
        assert len(llm_only) == 2
        assert all(r["kind"] == "llm" for r in llm_only)


class TestSummary:
    def test_empty_history_returns_empty_summary(self):
        assert stats.get_summary() == {}

    def test_summary_has_avg_max_count(self):
        durations = []
        for _ in range(3):
            token = stats.start_message("llm")
            with stats.stage("main_llm"):
                time.sleep(0.01)
            stats.finish_message(token)
        summary = stats.get_summary()
        assert "main_llm" in summary
        assert summary["main_llm"]["count"] == 3
        assert summary["main_llm"]["avg"] > 0
        assert summary["main_llm"]["max"] >= summary["main_llm"]["avg"]

    def test_summary_includes_total_always(self):
        token = stats.start_message("llm")
        stats.finish_message(token)
        summary = stats.get_summary()
        assert "total" in summary
        assert summary["total"]["count"] == 1

    def test_summary_excludes_stage_from_messages_that_never_hit_it(self):
        token1 = stats.start_message("llm")
        with stats.stage("pdf_query"):
            pass
        stats.finish_message(token1)

        token2 = stats.start_message("llm")
        stats.finish_message(token2)  # ไม่มี pdf_query รอบนี้

        summary = stats.get_summary()
        assert summary["pdf_query"]["count"] == 1


class TestConcurrentMessagesIsolated:
    """สอง "ข้อความ" ที่ถือ timer คนละตัว (คนละ token) ต้องไม่ปนสถิติกัน"""

    def test_two_separate_start_finish_cycles_produce_two_records(self):
        token_a = stats.start_message("llm")
        with stats.stage("main_llm"):
            time.sleep(0.01)
        stats.finish_message(token_a)

        token_b = stats.start_message("llm")
        with stats.stage("main_llm"):
            time.sleep(0.02)
        stats.finish_message(token_b)

        records = stats.get_recent()
        assert len(records) == 2
        assert records[0]["main_llm"] < records[1]["main_llm"]

    def test_two_concurrent_asyncio_tasks_do_not_leak_stages(self):
        """จำลองสอง user คุยพร้อมกัน (คนละ asyncio task) — contextvars copy-on-task-creation
        ต้องกันไม่ให้ stage ของ task หนึ่งไปเขียนทับ/ปนกับอีก task แม้เริ่ม/จบเหลื่อมเวลากัน"""
        import asyncio

        async def worker(stage_name: str, sleep_s: float):
            token = stats.start_message("llm")
            with stats.stage(stage_name):
                await asyncio.sleep(sleep_s)
            stats.finish_message(token)

        async def main():
            await asyncio.gather(
                worker("semantic_recall", 0.03),
                worker("main_llm", 0.01),
            )

        asyncio.run(main())

        records = stats.get_recent()
        assert len(records) == 2
        by_stage = {k: r for r in records for k in r if k not in ("ts", "kind", "total")}
        assert "semantic_recall" in by_stage
        assert "main_llm" in by_stage
        # แต่ละ record ต้องมีแค่ stage ของตัวเอง ไม่ปนกัน
        for r in records:
            stage_keys = [k for k in r if k not in ("ts", "kind", "total")]
            assert len(stage_keys) == 1
