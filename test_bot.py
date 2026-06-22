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


# ── aiohttp mock helper ───────────────────────────────────────────────────────

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


# ── memory file helpers ───────────────────────────────────────────────────────

def _init_mem(tmp_path, user_id, *, summaries=None, facts=None):
    mem = {"name": "", "facts": facts or [], "history": [],
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


# ── summarize_old_history ─────────────────────────────────────────────────────

class TestSummarizeOldHistory:
    def setup_method(self):
        bot._user_locks.clear()

    def test_empty_pairs_skips_ollama(self):
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(bot.summarize_old_history(999, []))
            mock_cls.assert_not_called()

    def test_saves_summary_to_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 10
        _init_mem(tmp_path, user_id)

        pairs = [
            {"role": "user", "content": "อยากกินก๋วยเตี๋ยว"},
            {"role": "assistant", "content": "แถวไหนดีคะ"},
        ]
        with patch("aiohttp.ClientSession", make_aiohttp_mock("คุยเรื่องร้านก๋วยเตี๋ยว")):
            asyncio.run(bot.summarize_old_history(user_id, pairs))

        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == 1
        assert "ก๋วยเตี๋ยว" in saved["summaries"][0]

    def test_strips_think_tag_from_response(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 11
        _init_mem(tmp_path, user_id)

        raw = "<think>กำลังคิด</think>\nสรุปเรื่องทดสอบ"
        with patch("aiohttp.ClientSession", make_aiohttp_mock(raw)):
            asyncio.run(bot.summarize_old_history(user_id, [{"role": "user", "content": "ทดสอบ"}]))

        saved = _load_saved(tmp_path, user_id)
        entry = saved["summaries"][0]
        assert entry.endswith("สรุปเรื่องทดสอบ")
        assert "<think>" not in entry

    def test_entry_has_date_prefix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 12
        _init_mem(tmp_path, user_id)

        with patch("aiohttp.ClientSession", make_aiohttp_mock("บทสรุป")):
            asyncio.run(bot.summarize_old_history(user_id, [{"role": "user", "content": "ทดสอบ"}]))

        entry = _load_saved(tmp_path, user_id)["summaries"][0]
        # รูปแบบ: "22 มิ.ย.: บทสรุป"
        assert ":" in entry
        assert "บทสรุป" in entry

    def test_caps_summaries_at_max(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 13
        existing = [f"บทที่ {i}" for i in range(memory.MAX_SUMMARIES)]
        _init_mem(tmp_path, user_id, summaries=existing)

        with patch("aiohttp.ClientSession", make_aiohttp_mock("บทใหม่")):
            asyncio.run(bot.summarize_old_history(user_id, [{"role": "user", "content": "ทดสอบ"}]))

        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == memory.MAX_SUMMARIES
        # อันเก่าสุดถูกตัด, อันใหม่อยู่ท้าย
        assert saved["summaries"][-1].endswith("บทใหม่")
        assert saved["summaries"][0] != "บทที่ 0"

    def test_empty_ollama_response_saves_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 14
        _init_mem(tmp_path, user_id)

        with patch("aiohttp.ClientSession", make_aiohttp_mock("")):
            asyncio.run(bot.summarize_old_history(user_id, [{"role": "user", "content": "ทดสอบ"}]))

        assert _load_saved(tmp_path, user_id)["summaries"] == []

    def test_exception_does_not_propagate(self):
        broken_ctx = MagicMock()
        broken_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("network error"))
        broken_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=broken_ctx):
            # ต้องไม่ raise — ควร swallow exception เงียบๆ
            asyncio.run(bot.summarize_old_history(999, [{"role": "user", "content": "ทดสอบ"}]))

    def test_does_not_overwrite_existing_facts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        user_id = 15
        _init_mem(tmp_path, user_id, facts=["อยู่ชุมพร"])

        with patch("aiohttp.ClientSession", make_aiohttp_mock("สรุปบท")):
            asyncio.run(bot.summarize_old_history(user_id, [{"role": "user", "content": "ทดสอบ"}]))

        saved = _load_saved(tmp_path, user_id)
        assert "อยู่ชุมพร" in saved["facts"]  # facts ต้องยังอยู่ครบ


# ── history overflow logic ────────────────────────────────────────────────────

class TestHistoryOverflowLogic:
    """ทดสอบ logic ตัด/คัด pairs_to_summarize + new_history
    ดึงมาเป็น pure function เพื่อไม่ต้อง mock ask_ollama ทั้งตัว"""

    MAX = bot.MAX_HISTORY_PAIRS * 2

    @staticmethod
    def _compute(history, user_msg="ข้อความ", reply="คำตอบ"):
        MAX = bot.MAX_HISTORY_PAIRS * 2
        total = history + [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": reply},
        ]
        pts = total[:-MAX] if len(total) > MAX else []
        nh = total[-MAX:]
        return pts, nh

    def test_empty_history_no_overflow(self):
        pts, nh = self._compute([])
        assert pts == []
        assert len(nh) == 2

    def test_history_at_limit_no_overflow(self):
        history = _make_history(self.MAX - 2)  # ขาดอีก 1 คู่จะเต็ม
        pts, nh = self._compute(history)
        assert pts == []
        assert len(nh) == self.MAX

    def test_full_history_overflows_by_one_pair(self):
        history = _make_history(self.MAX)
        pts, nh = self._compute(history)
        assert len(pts) == 2         # 1 คู่ (user+assistant) ถูก cut
        assert len(nh) == self.MAX

    def test_overflow_cuts_oldest_pair(self):
        history = _make_history(self.MAX)
        pts, _ = self._compute(history)
        assert pts[0]["role"] == "user"
        assert pts[0]["content"] == "u0"    # เก่าสุดคือ u0
        assert pts[1]["content"] == "a0"

    def test_new_history_ends_with_latest_exchange(self):
        history = _make_history(self.MAX)
        _, nh = self._compute(history, "ใหม่", "ตอบใหม่")
        assert nh[-2]["content"] == "ใหม่"
        assert nh[-1]["content"] == "ตอบใหม่"

    def test_new_history_length_always_capped(self):
        history = _make_history(self.MAX)
        _, nh = self._compute(history)
        assert len(nh) == self.MAX
