"""
pytest conftest — โหลดก่อน test files ทุกตัว
inject fake config เพื่อกัน bot.py raise SystemExit ตอน import
"""
import sys
from types import ModuleType

_fake_config = ModuleType("config")
_fake_config.DISCORD_TOKEN = "fake-test-token-abc123xyz"
_fake_config.TMD_TOKEN = ""
_fake_config.SERPAPI_KEY = ""
sys.modules.setdefault("config", _fake_config)
