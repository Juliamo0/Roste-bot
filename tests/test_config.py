"""
Unit tests for config.py — _parse_id_list validation
บั๊กเดิม: พิมพ์ id ผิด (มีตัวอักษรปน) ใน .env จะ crash ตอน start ด้วย ValueError เปล่าๆ
ไม่บอกว่าผิดตรงไหน/ตัวไหน — ตอนนี้ error message บอกชื่อ env var + ค่าที่ผิดชัดเจน

หมายเหตุ: import config ธรรมดาจะได้ fake module จาก conftest.py (sys.modules.setdefault
กันไว้ป้องกัน bot.py SystemExit ตอน import ในเทสไฟล์อื่นที่ต้อง import bot) — โหลดไฟล์ config.py
จริงตรงๆ ผ่าน importlib แทน เพื่อเทส _parse_id_list ของจริง
"""
import importlib.util
import os

import pytest

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.py"
)


def _load_real_config():
    spec = importlib.util.spec_from_file_location("config_real", _CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = _load_real_config()


class TestParseIdList:
    def test_empty_env_var_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("TEST_IDS", "")
        assert config._parse_id_list("TEST_IDS") == []

    def test_missing_env_var_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("TEST_IDS", raising=False)
        assert config._parse_id_list("TEST_IDS") == []

    def test_single_id_parses_correctly(self, monkeypatch):
        monkeypatch.setenv("TEST_IDS", "123456789012345678")
        assert config._parse_id_list("TEST_IDS") == [123456789012345678]

    def test_multiple_ids_comma_separated_with_spaces(self, monkeypatch):
        monkeypatch.setenv("TEST_IDS", "111, 222 ,333")
        assert config._parse_id_list("TEST_IDS") == [111, 222, 333]

    def test_trailing_comma_ignored(self, monkeypatch):
        monkeypatch.setenv("TEST_IDS", "111,222,")
        assert config._parse_id_list("TEST_IDS") == [111, 222]

    def test_invalid_id_raises_value_error_naming_var_and_bad_value(self, monkeypatch):
        """บั๊กเดิม: int('abc') เดิม raise ValueError('invalid literal for int() ...') เฉยๆ
        ไม่บอกว่ามาจาก env var ไหน — ตอนนี้ต้องเห็นทั้งชื่อ env var และค่าที่ผิดในข้อความ error"""
        monkeypatch.setenv("TEST_IDS", "123,abc,456")
        with pytest.raises(ValueError) as exc_info:
            config._parse_id_list("TEST_IDS")
        assert "TEST_IDS" in str(exc_info.value)
        assert "abc" in str(exc_info.value)


class TestMonitorPortParsing:
    """MONITOR_PORT/MONITOR_HOST คำนวณตอน import config.py (module-level) — ต้องโหลดไฟล์จริง
    ใหม่ทุกเคสผ่าน _load_real_config() เพื่อเห็นผลของ env var ที่ตั้งต่างกันในแต่ละเทส"""

    def test_default_port_is_8765_when_unset(self, monkeypatch):
        monkeypatch.delenv("MONITOR_PORT", raising=False)
        mod = _load_real_config()
        assert mod.MONITOR_PORT == 8765

    def test_empty_string_treated_as_unset_not_error(self, monkeypatch):
        """.env.example ใส่ MONITOR_PORT= (ค่าว่าง) ไว้ — ต้องไม่ crash ถ้า user ปล่อยว่างไว้ตามนั้น"""
        monkeypatch.setenv("MONITOR_PORT", "")
        mod = _load_real_config()
        assert mod.MONITOR_PORT == 8765

    def test_custom_port_parses(self, monkeypatch):
        monkeypatch.setenv("MONITOR_PORT", "9000")
        mod = _load_real_config()
        assert mod.MONITOR_PORT == 9000

    def test_zero_means_disabled(self, monkeypatch):
        monkeypatch.setenv("MONITOR_PORT", "0")
        mod = _load_real_config()
        assert mod.MONITOR_PORT == 0

    def test_invalid_port_raises_value_error_naming_var_and_bad_value(self, monkeypatch):
        monkeypatch.setenv("MONITOR_PORT", "abc")
        with pytest.raises(ValueError) as exc_info:
            _load_real_config()
        assert "MONITOR_PORT" in str(exc_info.value)
        assert "abc" in str(exc_info.value)

    def test_default_host_is_localhost(self, monkeypatch):
        monkeypatch.delenv("MONITOR_HOST", raising=False)
        mod = _load_real_config()
        assert mod.MONITOR_HOST == "127.0.0.1"

    def test_empty_host_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("MONITOR_HOST", "")
        mod = _load_real_config()
        assert mod.MONITOR_HOST == "127.0.0.1"

    def test_custom_host_parses(self, monkeypatch):
        monkeypatch.setenv("MONITOR_HOST", "0.0.0.0")
        mod = _load_real_config()
        assert mod.MONITOR_HOST == "0.0.0.0"
