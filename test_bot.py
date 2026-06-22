"""
Unit tests for bot.py — new functions only, Ollama mocked out
Run: pytest test_bot.py -v
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import bot
import memory


# ── aiohttp mock helpers ──────────────────────────────────────────────────────

def make_aiohttp_mock(response_text: str):
    """คืน mock สำหรับ aiohttp.ClientSession ที่ตอบ response_text เสมอ"""
    mock_resp = MagicMock()
    mock_resp.json = AsyncMock(return_value={"message": {"content": response_text}})

    mock_post_ctx = MagicMock()
    mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_post_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_post_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return MagicMock(return_value=mock_session_ctx)


def make_aiohttp_mock_sequence(*responses):
    """คืน mock ที่ตอบตามลำดับ — ใช้เมื่อฟังก์ชันเรียก aiohttp หลายครั้ง
    (summarize_and_verify เรียก 2 ครั้ง: สรุป + ตรวจ)"""
    responses_list = list(responses)
    call_count = [0]

    def create_session_ctx():
        idx = call_count[0]
        call_count[0] += 1
        text = responses_list[idx] if idx < len(responses_list) else ""

        mock_resp = MagicMock()
        mock_resp.json = AsyncMock(return_value={"message": {"content": text}})

        mock_post_ctx = MagicMock()
        mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_post_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_ctx)

        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        return mock_session_ctx

    return MagicMock(side_effect=create_session_ctx)


# ── memory file helpers ───────────────────────────────────────────────────────

def _init_mem(tmp_path, user_id, *, summaries=None, facts=None, history=None):
    mem = {"name": "", "facts": facts or [], "history": history or [],
           "summaries": summaries or []}
    (tmp_path / f"{user_id}.json").write_text(json.dumps(mem), encoding="utf-8")


def _load_saved(tmp_path, user_id):
    return json.loads((tmp_path / f"{user_id}.json").read_text(encoding="utf-8"))


def _make_history(n: int):
    """สร้าง history n messages (user+assistant คู่กัน, 0-indexed)"""
    msgs = []
    for i in range(n // 2):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    return msgs[:n]


# ── get_user_lock ─────────────────────────────────────────────────────────────

class TestGetUserLock:
    def setup_method(self):
        bot._user_locks.clear()

    def test_returns_asyncio_lock(self):
        assert isinstance(bot.get_user_lock(1), asyncio.Lock)

    def test_same_user_id_returns_same_lock(self):
        assert bot.get_user_lock(123) is bot.get_user_lock(123)

    def test_different_user_ids_different_locks(self):
        assert bot.get_user_lock(111) is not bot.get_user_lock(222)

    def test_lock_stored_in_dict(self):
        bot.get_user_lock(42)
        assert 42 in bot._user_locks


# ── detect_topic_change ───────────────────────────────────────────────────────

class TestDetectTopicChange:
    def setup_method(self):
        bot._user_locks.clear()

    def test_empty_history_returns_false_no_llm(self):
        """ไม่มี history = ไม่มีหัวข้อเดิม → False และไม่เรียก LLM"""
        with patch("aiohttp.ClientSession") as mock_cls:
            result = asyncio.run(bot.detect_topic_change("ข้อความใหม่", []))
            mock_cls.assert_not_called()
        assert result is False

    def test_one_pair_history_skips_llm(self):
        """history 1 คู่ (บทสั้นเกิน) → False ไม่เรียก LLM"""
        history = [
            {"role": "user", "content": "คุยเรื่องหนังสือ"},
            {"role": "assistant", "content": "น่าอ่านมากเลย"},
        ]
        with patch("aiohttp.ClientSession") as mock_cls:
            result = asyncio.run(bot.detect_topic_change("อยากกินอาหาร", history))
            mock_cls.assert_not_called()
        assert result is False

    def test_two_pair_history_calls_llm(self):
        """history 2 คู่ (ถึง threshold) → เรียก LLM"""
        history = _make_history(4)  # 2 pairs
        with patch("aiohttp.ClientSession", make_aiohttp_mock("YES")) as mock_cls:
            result = asyncio.run(bot.detect_topic_change("อยากกินก๋วยเตี๋ยว", history))
        assert result is True

    def test_llm_yes_returns_true(self):
        """โมเดลตอบ YES → เปลี่ยนหัวข้อ"""
        history = _make_history(4)  # 2 pairs
        with patch("aiohttp.ClientSession", make_aiohttp_mock("YES")):
            result = asyncio.run(bot.detect_topic_change("อยากกินก๋วยเตี๋ยว", history))
        assert result is True

    def test_llm_no_returns_false(self):
        """โมเดลตอบ NO → หัวข้อเดิม"""
        history = _make_history(4)  # 2 pairs
        with patch("aiohttp.ClientSession", make_aiohttp_mock("NO")):
            result = asyncio.run(bot.detect_topic_change("แนะนำเล่มอื่นได้ไหม", history))
        assert result is False

    def test_exception_returns_false(self):
        """เรียก LLM ไม่ได้ → False (ไม่บล็อก ไม่ throw)"""
        history = _make_history(4)  # 2 pairs
        broken = MagicMock()
        broken.__aenter__ = AsyncMock(side_effect=RuntimeError("network error"))
        broken.__aexit__ = AsyncMock(return_value=None)
        with patch("aiohttp.ClientSession", return_value=broken):
            result = asyncio.run(bot.detect_topic_change("ข้อความ", history))
        assert result is False


# ── summarize_and_verify ──────────────────────────────────────────────────────

class TestSummarizeAndVerify:
    def setup_method(self):
        bot._user_locks.clear()

    def test_empty_pairs_saves_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 20
        _init_mem(tmp_path, user_id)
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(bot.summarize_and_verify(user_id, []))
            mock_cls.assert_not_called()
        assert _load_saved(tmp_path, user_id)["summaries"] == []

    def test_verify_ok_saves_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 21
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "คุยเรื่องอาหาร"}]
        with patch("aiohttp.ClientSession",
                   make_aiohttp_mock_sequence("สรุปเรื่องอาหาร", "OK")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == 1
        entry = saved["summaries"][0]
        assert isinstance(entry, dict)
        assert "date" in entry and "text" in entry
        assert "อาหาร" in entry["text"]

    def test_verify_fix_saves_corrected_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 22
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "คุยเรื่องอาหาร"}]
        with patch("aiohttp.ClientSession",
                   make_aiohttp_mock_sequence("สรุปแต่งรายละเอียดมั่ว", "FIX: สรุปที่ถูกต้อง")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == 1
        assert "สรุปที่ถูกต้อง" in saved["summaries"][0]["text"]

    def test_verify_discard_saves_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 23
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "ทดสอบ"}]
        with patch("aiohttp.ClientSession",
                   make_aiohttp_mock_sequence("สรุปผิดพลาด", "DISCARD")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        assert _load_saved(tmp_path, user_id)["summaries"] == []

    def test_strips_think_tag_from_summary(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 24
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "ทดสอบ"}]
        with patch("aiohttp.ClientSession",
                   make_aiohttp_mock_sequence("<think>กำลังคิด</think>\nสรุปถูกต้อง", "OK")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        saved = _load_saved(tmp_path, user_id)
        assert saved["summaries"][0]["text"].endswith("สรุปถูกต้อง")
        assert "<think>" not in saved["summaries"][0]["text"]

    def test_empty_summary_saves_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 25
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "ทดสอบ"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence("", "OK")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        assert _load_saved(tmp_path, user_id)["summaries"] == []

    def test_exception_does_not_propagate(self):
        broken = MagicMock()
        broken.__aenter__ = AsyncMock(side_effect=RuntimeError("network error"))
        broken.__aexit__ = AsyncMock(return_value=None)
        with patch("aiohttp.ClientSession", return_value=broken):
            asyncio.run(bot.summarize_and_verify(999, [{"role": "user", "content": "ทดสอบ"}]))

    def test_does_not_overwrite_existing_facts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 26
        _init_mem(tmp_path, user_id, facts=["อยู่ชุมพร"])
        pairs = [{"role": "user", "content": "ทดสอบ"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence("สรุปบท", "OK")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        assert "อยู่ชุมพร" in _load_saved(tmp_path, user_id)["facts"]

    def test_caps_summaries_at_max(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 27
        existing = [{"date": "2026-06-01", "text": f"บทที่ {i}"}
                    for i in range(memory.MAX_SUMMARIES)]
        _init_mem(tmp_path, user_id, summaries=existing)
        pairs = [{"role": "user", "content": "ทดสอบ"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence("บทใหม่", "OK")):
            asyncio.run(bot.summarize_and_verify(user_id, pairs))
        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == memory.MAX_SUMMARIES
        assert saved["summaries"][-1]["text"].endswith("บทใหม่")
        assert saved["summaries"][0] != {"date": "2026-06-01", "text": "บทที่ 0"}


# ── flush_user_history ────────────────────────────────────────────────────────

class TestFlushUserHistory:
    def setup_method(self):
        bot._user_locks.clear()

    def test_empty_history_skips_summarize(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 30
        _init_mem(tmp_path, user_id)
        mock_sav = AsyncMock()
        with patch("bot.summarize_and_verify", mock_sav):
            asyncio.run(bot.flush_user_history(user_id))
        mock_sav.assert_not_called()

    def test_non_empty_history_calls_summarize(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 31
        history = _make_history(4)
        _init_mem(tmp_path, user_id, history=history)
        mock_sav = AsyncMock()
        with patch("bot.summarize_and_verify", mock_sav):
            asyncio.run(bot.flush_user_history(user_id))
        mock_sav.assert_called_once_with(user_id, history)

    def test_non_empty_history_clears_after_flush(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 32
        _init_mem(tmp_path, user_id, history=_make_history(4))
        with patch("bot.summarize_and_verify", AsyncMock()):
            asyncio.run(bot.flush_user_history(user_id))
        assert _load_saved(tmp_path, user_id)["history"] == []


# ── summary notice ────────────────────────────────────────────────────────────

class TestSummaryNotice:
    """ทดสอบ _maybe_append_summary_notice — pure function ไม่ต้อง mock IO"""

    def setup_method(self):
        bot._last_had_summary_notice.clear()

    def test_no_summarize_returns_reply_unchanged(self):
        reply, given = bot._maybe_append_summary_notice(1, False, "คำตอบ")
        assert reply == "คำตอบ"
        assert given is False

    def test_will_summarize_appends_phrase(self):
        reply, given = bot._maybe_append_summary_notice(1, True, "คำตอบ")
        assert given is True
        assert reply.startswith("คำตอบ")
        assert "..." in reply  # ทุกประโยคขึ้นต้นด้วย ...
        assert len(reply) > len("คำตอบ")

    def test_two_in_a_row_skips_second(self):
        """รอบก่อนมีแล้ว → รอบนี้ข้าม"""
        bot._last_had_summary_notice.add(1)
        reply, given = bot._maybe_append_summary_notice(1, True, "คำตอบ")
        assert reply == "คำตอบ"
        assert given is False

    def test_different_user_not_affected(self):
        """user อื่นอยู่ใน set ไม่กระทบ user นี้"""
        bot._last_had_summary_notice.add(99)
        reply, given = bot._maybe_append_summary_notice(1, True, "คำตอบ")
        assert given is True

    def test_reply_near_limit_skips_notice(self):
        """reply ใกล้ 2000 ตัว → ข้ามเพื่อไม่ให้เกิน Discord limit"""
        long_reply = "ก" * 1990
        reply, given = bot._maybe_append_summary_notice(1, True, long_reply)
        assert reply == long_reply
        assert given is False
        assert len(reply) <= 2000

    def test_after_silent_round_notice_can_appear_again(self):
        """รอบ N มีแล้ว → รอบ N+1 ไม่มีสรุป (discard) → รอบ N+2 มีได้อีก"""
        bot._last_had_summary_notice.add(1)
        # รอบ N+1: ไม่สรุป → discard จาก set
        _, given = bot._maybe_append_summary_notice(1, False, "คำตอบ")
        assert given is False
        assert 1 not in bot._last_had_summary_notice
        # รอบ N+2: สรุปอีก → notice ได้
        _, given = bot._maybe_append_summary_notice(1, True, "คำตอบ")
        assert given is True

    def test_phrase_uses_separator(self):
        """ประโยคคั่นด้วย newline สองบรรทัด"""
        with patch("random.choice", return_value="...จดไว้แล้วนะคะ"):
            reply, given = bot._maybe_append_summary_notice(1, True, "คำตอบ")
        assert reply == "คำตอบ\n\n...จดไว้แล้วนะคะ"
        assert given is True


# ── condition B trigger ───────────────────────────────────────────────────────

class TestConditionBTrigger:
    """Condition B: buffer ≥ MAX_HISTORY_PAIRS×2 → สรุปทั้งบทแล้วเริ่มใหม่"""
    MAX = bot.MAX_HISTORY_PAIRS * 2

    def test_two_messages_no_trigger(self):
        assert not bot._check_condition_b(_make_history(2))

    def test_twelve_messages_no_trigger(self):
        # 12 msgs = 6 pairs < 8 pairs threshold
        assert not bot._check_condition_b(_make_history(12))

    def test_fourteen_messages_no_trigger(self):
        # 14 msgs = 7 pairs, ยังต่ำกว่า threshold 1 คู่
        assert not bot._check_condition_b(_make_history(14))

    def test_sixteen_messages_triggers(self):
        # 16 msgs = 8 pairs = threshold
        assert bot._check_condition_b(_make_history(16))

    def test_after_clear_stays_under_limit(self):
        # หลัง trigger B บันทึก [] → message ถัดไปเริ่มจาก 2 messages ซึ่งต่ำกว่า limit
        after_clear_then_one_pair = _make_history(2)
        assert not bot._check_condition_b(after_clear_then_one_pair)
