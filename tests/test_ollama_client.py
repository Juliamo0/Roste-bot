"""
Unit tests for ollama_client.py — circuit breaker
บั๊กเดิม: Ollama ล่ม/รีสตาร์ท → ทุกข้อความค้างรอ timeout เต็ม 300 วิ ก่อนตอบ error
ตอนนี้ล้มติดกันครบ threshold แล้ว breaker เปิด raise OllamaUnavailable ทันทีไม่ยิง HTTP เลย

หมายเหตุ: โปรเจกต์นี้ไม่ได้ติดตั้ง pytest-asyncio — เทส async ทั้งหมดในโปรเจกต์เรียกผ่าน
asyncio.run(...) ข้างใน def test_ ธรรมดา (ดู tests/test_bot.py) ไฟล์นี้ตามรูปแบบเดียวกัน
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ollama_client


@pytest.fixture(autouse=True)
def _reset_breaker():
    """breaker เป็น module-level state — ต้อง reset ก่อน/หลังทุกเทส กันเทสอื่นเห็นผลค้าง"""
    ollama_client._consecutive_failures = 0
    ollama_client._breaker_open_until = 0.0
    yield
    ollama_client._consecutive_failures = 0
    ollama_client._breaker_open_until = 0.0


def _broken_session():
    """ClientSession ที่ throw ConnectionError ตอน post/get — จำลอง Ollama ล่ม"""
    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=ConnectionError("refused"))
    mock_session.get = MagicMock(side_effect=ConnectionError("refused"))

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_session_ctx)


def _ok_session(content="สวัสดีค่ะ"):
    mock_resp = MagicMock()
    mock_resp.json = AsyncMock(return_value={"message": {"content": content}})
    mock_resp.status = 200

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_ctx)
    mock_session.get = MagicMock(return_value=mock_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_session_ctx)


async def _drain(agen):
    async for _ in agen:
        pass


class TestBreakerState:
    def test_closed_initially(self):
        ollama_client._check_breaker()  # ไม่ raise = ผ่าน

    def test_opens_after_threshold_failures(self):
        for _ in range(ollama_client._FAILURE_THRESHOLD):
            ollama_client._record_failure()
        with pytest.raises(ollama_client.OllamaUnavailable):
            ollama_client._check_breaker()

    def test_stays_closed_below_threshold(self):
        for _ in range(ollama_client._FAILURE_THRESHOLD - 1):
            ollama_client._record_failure()
        ollama_client._check_breaker()  # ยังไม่ raise

    def test_success_resets_counter(self):
        for _ in range(ollama_client._FAILURE_THRESHOLD - 1):
            ollama_client._record_failure()
        ollama_client._record_success()
        assert ollama_client._consecutive_failures == 0

    def test_cooldown_allows_retry_after_expiry(self):
        import time
        for _ in range(ollama_client._FAILURE_THRESHOLD):
            ollama_client._record_failure()
        with pytest.raises(ollama_client.OllamaUnavailable):
            ollama_client._check_breaker()
        # จำลองเวลาผ่านไปเกิน cooldown แทนการ sleep จริง
        ollama_client._breaker_open_until = time.monotonic() - 1
        ollama_client._check_breaker()  # ไม่ raise แล้ว


class TestGetJsonPost:
    def test_breaker_open_raises_without_http_call(self):
        for _ in range(ollama_client._FAILURE_THRESHOLD):
            ollama_client._record_failure()
        with patch("aiohttp.ClientSession") as mock_cls:
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(ollama_client._get_json_post({"model": "x"}))
            mock_cls.assert_not_called()  # breaker เปิด = ไม่ยิง HTTP เลย

    def test_connection_error_raises_ollama_unavailable(self):
        with patch("aiohttp.ClientSession", _broken_session()):
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(ollama_client._get_json_post({"model": "x"}))
        assert ollama_client._consecutive_failures == 1

    def test_repeated_failures_open_breaker(self):
        with patch("aiohttp.ClientSession", _broken_session()):
            for _ in range(ollama_client._FAILURE_THRESHOLD):
                with pytest.raises(ollama_client.OllamaUnavailable):
                    asyncio.run(ollama_client._get_json_post({"model": "x"}))
        # ครบ threshold แล้ว breaker ต้องเปิด — เรียกอีกทีต้อง raise ทันทีไม่แตะ session เลย
        with patch("aiohttp.ClientSession") as mock_cls:
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(ollama_client._get_json_post({"model": "x"}))
            mock_cls.assert_not_called()

    def test_success_resets_failure_count(self):
        with patch("aiohttp.ClientSession", _broken_session()):
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(ollama_client._get_json_post({"model": "x"}))
        assert ollama_client._consecutive_failures == 1
        with patch("aiohttp.ClientSession", _ok_session()):
            data = asyncio.run(ollama_client._get_json_post({"model": "x"}))
        assert data["message"]["content"] == "สวัสดีค่ะ"
        assert ollama_client._consecutive_failures == 0


class TestChatOnce:
    def test_breaker_open_raises_before_http(self):
        for _ in range(ollama_client._FAILURE_THRESHOLD):
            ollama_client._record_failure()
        with patch("aiohttp.ClientSession") as mock_cls:
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(ollama_client._chat_once([{"role": "user", "content": "hi"}]))
            mock_cls.assert_not_called()

    def test_success_returns_message(self):
        with patch("aiohttp.ClientSession", _ok_session("ตอบแล้วค่ะ")):
            msg = asyncio.run(ollama_client._chat_once([{"role": "user", "content": "hi"}]))
        assert msg["content"] == "ตอบแล้วค่ะ"


class TestStreamChatChunks:
    def test_breaker_open_raises_before_yielding(self):
        for _ in range(ollama_client._FAILURE_THRESHOLD):
            ollama_client._record_failure()
        with patch("aiohttp.ClientSession") as mock_cls:
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(_drain(ollama_client._stream_chat_chunks({"model": "x"})))
            mock_cls.assert_not_called()

    def test_connection_error_mid_stream_raises_and_records_failure(self):
        with patch("aiohttp.ClientSession", _broken_session()):
            with pytest.raises(ollama_client.OllamaUnavailable):
                asyncio.run(_drain(ollama_client._stream_chat_chunks({"model": "x"})))
        assert ollama_client._consecutive_failures == 1


class TestProbeHealth:
    def test_returns_true_on_200(self):
        with patch("aiohttp.ClientSession", _ok_session()):
            assert asyncio.run(ollama_client.probe_health()) is True

    def test_returns_false_on_connection_error(self):
        with patch("aiohttp.ClientSession", _broken_session()):
            assert asyncio.run(ollama_client.probe_health()) is False

    def test_does_not_touch_breaker(self):
        with patch("aiohttp.ClientSession", _broken_session()):
            asyncio.run(ollama_client.probe_health())
        assert ollama_client._consecutive_failures == 0  # probe ไม่นับเป็นความล้มเหลวของ breaker
