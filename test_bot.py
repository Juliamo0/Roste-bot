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
import vectormemory


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


# ── _validate_tool_args — pure function ตรวจ required field ตามที่ TOOLS ประกาศไว้ ─────

class TestValidateToolArgs:
    def test_unknown_tool_returns_error(self):
        assert bot._validate_tool_args("fly_to_moon", {}) is not None

    def test_missing_required_field_returns_error(self):
        assert bot._validate_tool_args("search_web", {}) is not None

    def test_empty_string_required_field_returns_error(self):
        assert bot._validate_tool_args("search_web", {"query": "   "}) is not None

    def test_wrong_type_required_field_returns_error(self):
        assert bot._validate_tool_args("search_web", {"query": 123}) is not None

    def test_valid_required_field_returns_none(self):
        assert bot._validate_tool_args("search_web", {"query": "ข่าววันนี้"}) is None

    def test_no_required_fields_ok_even_with_empty_args(self):
        assert bot._validate_tool_args("get_current_time", {}) is None
        assert bot._validate_tool_args("get_power_outage", {}) is None


# ── _strip_ungrounded_optional_args — กันโมเดลเดา optional param เอง (เช่น province) ──────

class TestStripUngroundedOptionalArgs:
    def test_ungrounded_value_stripped(self):
        """โมเดลเดา province ที่ผู้ใช้ไม่เคยพูดถึงเลย ทั้งใน message/history/facts"""
        args = {"province": "กรุงเทพมหานคร"}
        cleaned = bot._strip_ungrounded_optional_args(
            "get_weather", args, "พรุ่งนี้ฝนตกไหม", [], {"facts": []})
        assert "province" not in cleaned

    def test_value_grounded_in_current_message_kept(self):
        args = {"province": "เชียงใหม่"}
        cleaned = bot._strip_ungrounded_optional_args(
            "get_weather", args, "เชียงใหม่ฝนตกไหม", [], {"facts": []})
        assert cleaned.get("province") == "เชียงใหม่"

    def test_value_grounded_in_history_kept(self):
        """ผู้ใช้บอกเมืองไว้เทิร์นก่อนๆ ไม่ใช่ข้อความปัจจุบัน — ต้องไม่โดนตัด"""
        history = [
            {"role": "user", "content": "อยู่เชียงใหม่นะ"},
            {"role": "assistant", "content": "โอเคค่ะ"},
        ]
        args = {"province": "เชียงใหม่"}
        cleaned = bot._strip_ungrounded_optional_args(
            "get_weather", args, "พรุ่งนี้ฝนตกไหม", history, {"facts": []})
        assert cleaned.get("province") == "เชียงใหม่"

    def test_value_matching_saved_fact_kept(self):
        """ตรงกับ default ที่ผู้ใช้ตั้งไว้เอง (fact) — ต้องแยกจาก 'โมเดลเดาเอง' ไม่ให้โดนตัด"""
        args = {"province": "ชุมพร"}
        cleaned = bot._strip_ungrounded_optional_args(
            "get_weather", args, "ฝนตกไหม", [], {"facts": ["อยู่ชุมพร"]})
        assert cleaned.get("province") == "ชุมพร"

    def test_required_field_never_stripped_even_if_ungrounded(self):
        """query เป็น required — ต้องไม่โดนตัดแม้จะไม่เจอคำนั้นเป๊ะๆ ในข้อความ (โมเดลสรุปคำค้นเองได้)"""
        args = {"query": "ร้านก๋วยเตี๋ยวอร่อย"}
        cleaned = bot._strip_ungrounded_optional_args(
            "search_places", args, "หาของกินหน่อย", [], {"facts": []})
        assert cleaned.get("query") == "ร้านก๋วยเตี๋ยวอร่อย"

    def test_unknown_tool_returns_args_unchanged(self):
        args = {"anything": "value"}
        cleaned = bot._strip_ungrounded_optional_args("fly_to_moon", args, "msg", [], {})
        assert cleaned == args


# ── _tool_* handlers — เรียกตรงๆ (ไม่ผ่าน ask_ollama) mock เฉพาะฟังก์ชันดึงข้อมูลจริงข้างใน ──

class TestToolHandlers:
    def test_get_current_time_uses_real_clock(self):
        with patch.object(bot, "get_thai_datetime", return_value="วันจันทร์ บ่ายสามโมง"):
            result = asyncio.run(bot._tool_get_current_time({}, {}))
        assert "วันจันทร์" in result

    def test_get_weather_defaults_to_home_province_when_missing(self):
        with patch.object(bot, "get_weather_tmd", AsyncMock(return_value=None)), \
             patch.object(bot, "get_weather", AsyncMock(return_value="ร้อน 35°C")) as mw:
            result = asyncio.run(bot._tool_get_weather({}, {}))
        mw.assert_called_once_with(bot.HOME_PROVINCE_NAME)
        assert "ร้อน 35" in result

    def test_get_weather_prefers_tmd_over_open_meteo(self):
        with patch.object(bot, "get_weather_tmd", AsyncMock(return_value="TMD data")), \
             patch.object(bot, "get_weather", AsyncMock(return_value="OpenMeteo data")) as mow:
            result = asyncio.run(bot._tool_get_weather({"province": "เชียงใหม่"}, {}))
        mow.assert_not_called()
        assert "TMD data" in result

    def test_get_oil_price_defaults_to_ptt(self):
        with patch.object(bot, "get_oil_price", AsyncMock(return_value="ปตท. 33.34")) as mo:
            asyncio.run(bot._tool_get_oil_price({}, {}))
        mo.assert_called_once_with("ptt")

    def test_get_oil_price_accepts_code_directly(self):
        with patch.object(bot, "get_oil_price", AsyncMock(return_value="เชลล์ 34")) as mo:
            asyncio.run(bot._tool_get_oil_price({"brand": "shell"}, {}))
        mo.assert_called_once_with("shell")

    def test_get_oil_price_maps_thai_name_to_code(self):
        with patch.object(bot, "get_oil_price", AsyncMock(return_value="บางจาก 32")) as mo:
            asyncio.run(bot._tool_get_oil_price({"brand": "บางจาก"}, {}))
        mo.assert_called_once_with("bcp")

    def test_search_places_missing_province_asks_back_not_crash(self):
        result = asyncio.run(bot._tool_search_places({"query": "ก๋วยเตี๋ยว"}, {"facts": []}))
        assert "จังหวัด" in result

    def test_search_places_falls_back_to_saved_location(self):
        with patch.object(bot, "_search_places", AsyncMock(return_value="ผลลัพธ์")) as msp:
            asyncio.run(bot._tool_search_places({"query": "ก๋วยเตี๋ยว"}, {"facts": ["อยู่ชุมพร"]}))
        msp.assert_called_once_with("ก๋วยเตี๋ยว", "ชุมพร")

    def test_search_web_returns_failure_message_when_empty(self):
        with patch.object(bot, "search_web", return_value=""):
            result = asyncio.run(bot._tool_search_web({"query": "ทดสอบ"}, {}))
        assert "ไม่พบข้อมูล" in result or "ห้ามเดา" in result


# ── tool loop fail-safe (ผ่าน ask_ollama เต็ม) — โมเดลเรียกมั่ว/ฟอร์แมตเพี้ยน/handler พัง ──
#    ต้องไม่ crash ask_ollama ทั้งฟังก์ชัน ไม่ว่าเกิดอะไรขึ้นกับ tool call

class TestToolLoopFailSafe:
    def setup_method(self):
        bot._user_locks.clear()

    def _patch_no_op_recall(self, monkeypatch):
        """กัน ask_ollama ยิง Ollama/ChromaDB จริงตอน semantic recall/RAG (ไม่เกี่ยวกับสิ่งที่เทสนี้)"""
        monkeypatch.setattr(vectormemory, "query_pdf", AsyncMock(return_value=[]))
        monkeypatch.setattr(vectormemory, "query_conversation_memory", AsyncMock(return_value=[]))

    def test_valid_tool_call_flows_through_normally(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        self._patch_no_op_recall(monkeypatch)
        user_id = 601
        _init_mem(tmp_path, user_id)

        tool_call = {"function": {"name": "get_current_time", "arguments": {}}}
        responses = [
            {"content": "", "tool_calls": [tool_call]},
            {"content": "ตอนนี้บ่ายสามโมงค่ะ", "tool_calls": None},
        ]
        with patch.object(bot, "_chat_once", AsyncMock(side_effect=responses)), \
             patch.object(bot, "get_thai_datetime", return_value="บ่ายสามโมง"):
            reply = asyncio.run(bot.ask_ollama(user_id, "ผู้ทดสอบ", "ตอนนี้กี่โมง"))
        assert "บ่ายสามโมง" in reply

    def test_hallucinated_tool_name_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        self._patch_no_op_recall(monkeypatch)
        user_id = 602
        _init_mem(tmp_path, user_id)

        tool_call = {"function": {"name": "fly_to_moon", "arguments": {}}}
        responses = [
            {"content": "", "tool_calls": [tool_call]},
            {"content": "ขอโทษค่ะ ทำแบบนั้นไม่ได้นะคะ", "tool_calls": None},
        ]
        with patch.object(bot, "_chat_once", AsyncMock(side_effect=responses)):
            reply = asyncio.run(bot.ask_ollama(user_id, "ผู้ทดสอบ", "บินไปดวงจันทร์หน่อย"))
        assert reply  # ไม่ crash — ได้ reply กลับมาตามปกติ

    def test_missing_required_param_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        self._patch_no_op_recall(monkeypatch)
        user_id = 603
        _init_mem(tmp_path, user_id)

        # search_web ต้องมี query แต่โมเดลส่งมาว่างเปล่า
        tool_call = {"function": {"name": "search_web", "arguments": {"query": ""}}}
        responses = [
            {"content": "", "tool_calls": [tool_call]},
            {"content": "หืม ขอโทษค่ะ ลองถามใหม่อีกทีนะคะ", "tool_calls": None},
        ]
        with patch.object(bot, "_chat_once", AsyncMock(side_effect=responses)):
            reply = asyncio.run(bot.ask_ollama(user_id, "ผู้ทดสอบ", "ค้นเว็บหน่อย"))
        assert reply

    def test_handler_exception_does_not_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        self._patch_no_op_recall(monkeypatch)
        # mock handler ตัวจริงใน TOOL_HANDLERS ให้ raise (จำลอง network error/bug ข้างใน)
        monkeypatch.setitem(bot.TOOL_HANDLERS, "get_weather",
                             AsyncMock(side_effect=RuntimeError("weather api down")))
        user_id = 604
        _init_mem(tmp_path, user_id)

        tool_call = {"function": {"name": "get_weather", "arguments": {"province": "ชุมพร"}}}
        responses = [
            {"content": "", "tool_calls": [tool_call]},
            {"content": "ขอโทษค่ะ ระบบอากาศมีปัญหาตอนนี้", "tool_calls": None},
        ]
        with patch.object(bot, "_chat_once", AsyncMock(side_effect=responses)):
            reply = asyncio.run(bot.ask_ollama(user_id, "ผู้ทดสอบ", "พรุ่งนี้ฝนตกไหม"))
        assert reply  # exception ข้างใน handler ต้องไม่หลุดขึ้นไป crash ask_ollama

    def test_multiple_tool_calls_in_one_round_all_processed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        self._patch_no_op_recall(monkeypatch)
        user_id = 605
        _init_mem(tmp_path, user_id)

        calls = [
            {"function": {"name": "get_current_time", "arguments": {}}},
            {"function": {"name": "get_oil_price", "arguments": {}}},
        ]
        responses = [
            {"content": "", "tool_calls": calls},
            {"content": "ตอนนี้บ่ายสามโมง น้ำมันปตท. 33 บาทค่ะ", "tool_calls": None},
        ]
        with patch.object(bot, "_chat_once", AsyncMock(side_effect=responses)), \
             patch.object(bot, "get_thai_datetime", return_value="บ่ายสามโมง"), \
             patch.object(bot, "get_oil_price", AsyncMock(return_value="ปตท. 33 บาท")) as mo:
            reply = asyncio.run(bot.ask_ollama(user_id, "ผู้ทดสอบ", "กี่โมงแล้ว น้ำมันราคาเท่าไหร่"))
        mo.assert_called_once_with("ptt")
        assert reply

    def test_hallucinated_optional_arg_stripped_before_handler_runs(self, tmp_path, monkeypatch):
        """โมเดลเดา province='กรุงเทพมหานคร' ทั้งที่ผู้ใช้ไม่เคยพูดถึง — handler ต้องได้ province ว่าง
        (ไม่ใช่ค่าที่เดามา) แล้ว fallback เป็นจังหวัดบ้านเองตามดีไซน์ของ _tool_get_weather"""
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        self._patch_no_op_recall(monkeypatch)
        user_id = 606
        _init_mem(tmp_path, user_id)

        tool_call = {"function": {"name": "get_weather", "arguments": {"province": "กรุงเทพมหานคร"}}}
        responses = [
            {"content": "", "tool_calls": [tool_call]},
            {"content": "พรุ่งนี้ฝนตกช่วงบ่ายค่ะ", "tool_calls": None},
        ]
        with patch.object(bot, "_chat_once", AsyncMock(side_effect=responses)), \
             patch.object(bot, "get_weather_tmd", AsyncMock(return_value=None)), \
             patch.object(bot, "get_weather", AsyncMock(return_value="ฝนตกบ่าย")) as mw:
            reply = asyncio.run(bot.ask_ollama(user_id, "ผู้ทดสอบ", "พรุ่งนี้ต้องพกร่มไหม"))
        # ต้องเรียก get_weather ด้วยจังหวัดบ้าน (fallback) ไม่ใช่ "กรุงเทพมหานคร" ที่โมเดลเดามา
        mw.assert_called_once_with(bot.HOME_PROVINCE_NAME)
        assert reply
