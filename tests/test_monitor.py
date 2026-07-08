"""
Unit tests for monitor.py — GPU/Ollama/system stats ต้อง degrade เป็น None เสมอถ้าไม่มี
(บทเรียนจาก CI: runner ไม่มี GPU/nvidia-smi/Ollama เลยสักตัว เทสต้องผ่านบนนั้นได้)
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import monitor


def _make_session_mock(status=200, json_data=None, exception=None):
    """mock สำหรับ aiohttp.ClientSession — ตัด/ปรับจาก tests/test_realtime.py"""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data if json_data is not None else {})

    mock_req_ctx = MagicMock()
    if exception is not None:
        mock_req_ctx.__aenter__ = AsyncMock(side_effect=exception)
    else:
        mock_req_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_req_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_req_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return MagicMock(return_value=mock_session_ctx)


class _FakeProcess:
    def __init__(self, stdout: bytes, returncode: int = 0):
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, b""


class TestGetGpuStats:
    def test_nvidia_smi_missing_returns_none(self):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = asyncio.run(monitor.get_gpu_stats())
        assert result is None

    def test_nvidia_smi_timeout_returns_none(self):
        async def _hang(*a, **kw):
            proc = MagicMock()

            async def _never():
                await asyncio.sleep(10)
            proc.communicate = _never
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=_hang), \
             patch("monitor._NVIDIA_SMI_TIMEOUT_SEC", 0.05):
            result = asyncio.run(monitor.get_gpu_stats())
        assert result is None

    def test_nvidia_smi_nonzero_exit_returns_none(self):
        async def _fake(*a, **kw):
            return _FakeProcess(b"", returncode=1)

        with patch("asyncio.create_subprocess_exec", side_effect=_fake):
            result = asyncio.run(monitor.get_gpu_stats())
        assert result is None

    def test_nvidia_smi_success_parses_csv(self):
        async def _fake(*a, **kw):
            return _FakeProcess(b"23, 1024, 4096, 47\n", returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=_fake):
            result = asyncio.run(monitor.get_gpu_stats())
        assert result == {
            "utilization_pct": 23.0,
            "vram_used_mb": 1024.0,
            "vram_total_mb": 4096.0,
            "temperature_c": 47.0,
        }

    def test_nvidia_smi_malformed_output_returns_none(self):
        async def _fake(*a, **kw):
            return _FakeProcess(b"not,valid,csv\n", returncode=0)

        with patch("asyncio.create_subprocess_exec", side_effect=_fake):
            result = asyncio.run(monitor.get_gpu_stats())
        assert result is None


class TestGetOllamaModels:
    def test_ollama_unreachable_returns_none(self):
        mock = _make_session_mock(exception=ConnectionError("refused"))
        with patch("monitor.ClientSession", mock):
            result = asyncio.run(monitor.get_ollama_models())
        assert result is None

    def test_ollama_non_200_returns_none(self):
        mock = _make_session_mock(status=500)
        with patch("monitor.ClientSession", mock):
            result = asyncio.run(monitor.get_ollama_models())
        assert result is None

    def test_ollama_empty_models_returns_empty_list(self):
        mock = _make_session_mock(json_data={"models": []})
        with patch("monitor.ClientSession", mock):
            result = asyncio.run(monitor.get_ollama_models())
        assert result == []

    def test_ollama_loaded_model_parses_name_and_vram(self):
        mock = _make_session_mock(json_data={
            "models": [{"name": "qwen3:8b", "size_vram": 8 * 1024 * 1024}]
        })
        with patch("monitor.ClientSession", mock):
            result = asyncio.run(monitor.get_ollama_models())
        assert result == [{"name": "qwen3:8b", "size_vram_mb": 8.0}]


class TestGetSystemStats:
    def test_returns_expected_keys(self):
        result = monitor.get_system_stats()
        assert set(result.keys()) == {
            "cpu_pct", "ram_used_mb", "ram_total_mb", "disk_used_gb", "disk_total_gb",
        }
        assert all(isinstance(v, (int, float)) for v in result.values())

    def test_does_not_block_event_loop(self):
        """cpu_percent(interval=None) ต้องไม่ sleep — เรียกซ้ำๆ ต้องเร็วกว่า 1 วิ (กับดัก interval=1)"""
        import time
        t0 = time.monotonic()
        for _ in range(5):
            monitor.get_system_stats()
        assert time.monotonic() - t0 < 1.0


class TestBuildStatsPayload:
    def test_payload_has_expected_top_level_keys(self):
        with patch("monitor.get_gpu_stats", new=AsyncMock(return_value=None)), \
             patch("monitor.get_ollama_models", new=AsyncMock(return_value=None)):
            payload = asyncio.run(monitor.build_stats_payload(lambda: {"ok": True}, 0.0))
        assert set(payload.keys()) == {
            "uptime_sec", "bot", "system", "gpu", "ollama_models",
            "latency_recent", "latency_summary",
        }
        assert payload["bot"] == {"ok": True}
        assert payload["gpu"] is None
        assert payload["ollama_models"] is None


class TestMonitorServerLifecycle:
    def test_start_stop_serves_stats_json(self):
        """สโมคจริง — เปิดเซิร์ฟเวอร์บน localhost port ทดสอบ ยิง GET จริง แล้วปิด"""
        from aiohttp import ClientSession as RealClientSession

        async def scenario():
            server = monitor.MonitorServer(lambda: {"ok": True}, host="127.0.0.1", port=18765)
            await server.start()
            try:
                async with RealClientSession() as s:
                    async with s.get("http://127.0.0.1:18765/stats.json") as r:
                        assert r.status == 200
                        data = await r.json()
                        assert data["bot"] == {"ok": True}
            finally:
                await server.stop()

        asyncio.run(scenario())

    def test_port_zero_does_not_start_server(self):
        async def scenario():
            server = monitor.MonitorServer(lambda: {}, host="127.0.0.1", port=0)
            await server.start()
            assert server._runner is None

        asyncio.run(scenario())

    def test_stop_without_start_does_not_error(self):
        async def scenario():
            server = monitor.MonitorServer(lambda: {}, host="127.0.0.1", port=18766)
            await server.stop()  # ไม่เคย start() มาก่อน — ต้องไม่ error

        asyncio.run(scenario())
