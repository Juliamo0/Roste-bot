"""
Security regression tests for chat.summarize_and_verify — sensitive-data filter
ต้องทำงานทั้งสองเส้นทาง (summary_text เดิม และ fixed จาก verify's FIX:)

ที่มา: security review พบว่า strip_sensitive_tags() เรียกแค่ครั้งเดียวก่อนส่งไป verify
— ถ้า verify คืน "FIX: <ข้อความใหม่>" ข้อความนั้นถูกใช้ต่อทั้งใน mem["summaries"] ของ
user และส่งต่อเข้า _promote_roste_facts() (ไฟล์กลาง memory/_roste_self.json ที่ทุก
Discord user เห็นร่วมกัน) โดยไม่เคยผ่าน filter เลย — แก้แล้วให้เรียกซ้ำหลัง FIX:

แยกไฟล์จาก test_bot.py เพราะ chat.py import ได้เดี่ยวๆ โดยไม่ต้องพึ่ง
discord-ext-voice-recv (ต่างจาก bot.py ที่ import ตรงนั้นไว้)
Run: pytest tests/test_chat_security.py -v
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import chat
import memory


def make_aiohttp_mock_sequence(*responses):
    """คืน mock ที่ตอบตามลำดับ — สำเนาจาก tests/test_bot.py"""
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


def _init_mem(tmp_path, user_id, *, summaries=None, facts=None, history=None):
    mem = {"name": "", "facts": facts or [], "history": history or [],
           "summaries": summaries or []}
    (tmp_path / f"{user_id}.json").write_text(json.dumps(mem), encoding="utf-8")


def _load_saved(tmp_path, user_id):
    return json.loads((tmp_path / f"{user_id}.json").read_text(encoding="utf-8"))


class TestVerifyFixSensitiveDataFilter:
    def setup_method(self):
        chat._user_locks.clear()

    def test_fix_with_sensitive_tag_is_stripped(self, tmp_path, monkeypatch):
        """verify คืน FIX: ที่มี tag หนึ่งอันมีเบอร์โทร — ต้องถูกตัด tag นั้นทิ้ง
        เหลือแค่ tag ที่ไม่อ่อนไหว ไม่ใช่เก็บทั้งดุ้นแบบไม่กรอง"""
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(chat, "_promote_roste_facts", AsyncMock())
        user_id = 901
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "คุยเรื่องเบอร์โทร"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence(
                '{"summary": "สรุปแต่งมั่ว", "tags": ["user_pref:xxx"]}',
                "FIX: คุยเรื่องเบอร์ | user_pref:ชอบกาแฟ user_fact:เบอร์โทร 0812345678")):
            asyncio.run(chat.summarize_and_verify(user_id, pairs))

        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == 1
        text = saved["summaries"][0]["text"]
        assert "0812345678" not in text
        assert "ชอบกาแฟ" in text   # tag ที่ไม่อ่อนไหวยังอยู่

    def test_fix_with_sensitive_head_discards_whole_entry(self, tmp_path, monkeypatch):
        """เบอร์โทรอยู่ใน "หัวเรื่อง" (ก่อน tag แรก) — strip_sensitive_tags คืน ""
        (fail-conservative) ต้องไม่บันทึกอะไรเลย ไม่ใช่บันทึกหัวเรื่องที่มีเบอร์โทร"""
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(chat, "_promote_roste_facts", AsyncMock())
        user_id = 902
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "คุยเรื่องเบอร์โทร"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence(
                '{"summary": "สรุปแต่งมั่ว", "tags": ["user_pref:xxx"]}',
                "FIX: โทร 0812345678 ได้เลย | user_pref:ชอบกาแฟ")):
            asyncio.run(chat.summarize_and_verify(user_id, pairs))

        assert _load_saved(tmp_path, user_id)["summaries"] == []

    def test_fix_without_sensitive_data_still_saves_normally(self, tmp_path, monkeypatch):
        """regression guard — FIX: ปกติที่ไม่มีข้อมูลอ่อนไหวต้องยังบันทึกได้เหมือนเดิม
        (ตรงกับ test_bot.py::test_verify_fix_saves_corrected_summary)"""
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        monkeypatch.setattr(chat, "_promote_roste_facts", AsyncMock())
        user_id = 903
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "คุยเรื่องอาหาร"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence(
                '{"summary": "สรุปแต่งมั่ว", "tags": ["user_pref:xxx"]}',
                "FIX: สรุปที่ถูกต้อง | user_pref:ชอบอาหารไทย")):
            asyncio.run(chat.summarize_and_verify(user_id, pairs))
        saved = _load_saved(tmp_path, user_id)
        assert len(saved["summaries"]) == 1
        assert "สรุปที่ถูกต้อง" in saved["summaries"][0]["text"]

    def test_fix_sensitive_data_never_reaches_promote_roste_facts(self, tmp_path, monkeypatch):
        """ยืนยันตรงจุดที่ security review เป็นห่วงที่สุด — ข้อมูลอ่อนไหวจาก FIX:
        ต้องไม่ถูกส่งต่อเข้า _promote_roste_facts เลย (ไฟล์กลางที่ทุก user เห็นร่วมกัน)"""
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        promote_mock = AsyncMock()
        monkeypatch.setattr(chat, "_promote_roste_facts", promote_mock)
        user_id = 904
        _init_mem(tmp_path, user_id)
        pairs = [{"role": "user", "content": "คุยเรื่องเบอร์โทร"}]
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence(
                '{"summary": "สรุปแต่งมั่ว", "tags": ["user_pref:xxx"]}',
                "FIX: คุยเรื่องเบอร์ | me_pref:ชอบกาแฟ me_fact:เบอร์โทร 0812345678")):
            asyncio.run(chat.summarize_and_verify(user_id, pairs))

        promote_mock.assert_called_once()
        promoted_text = promote_mock.call_args[0][0]
        assert "0812345678" not in promoted_text
