"""
Unit tests for chat._promote_roste_facts — promote me_pref/me_fact เข้า roste facts
(ตัวตนกลาง เหมือนกันทุก user) แยกไฟล์จาก test_bot.py เพราะ chat.py import ได้เดี่ยวๆ
โดยไม่ต้องพึ่ง discord-ext-voice-recv (ต่างจาก bot.py ที่ import ตรงนั้นไว้)
Run: pytest tests/test_chat_roste_facts.py -v
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import chat
import memory

USER_A = 111
USER_B = 222
USER_C = 333


def make_aiohttp_mock_sequence(*responses):
    """คืน mock ที่ตอบตามลำดับ — สำเนาจาก tests/test_bot.py (ไม่ import ข้ามไฟล์เพราะ
    test_bot.py ดึง bot.py มาด้วยซึ่งต้องพึ่ง voice_recv)"""
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


@pytest.fixture(autouse=True)
def isolated_roste_memory(tmp_path, monkeypatch):
    """แยกไฟล์ roste memory ต่อเทส กันเทสชนกัน/เขียนทับ memory/_roste_self.json จริง"""
    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))


class TestPromoteNoOp:
    def test_no_me_tags_does_nothing(self):
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(chat._promote_roste_facts("คุยเรื่องงาน | user_pref:ชอบงานอิสระ", USER_A))
            mock_cls.assert_not_called()   # ไม่มี me_pref/me_fact เลย — ไม่ควรยิง LLM

    def test_empty_text_does_nothing(self):
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(chat._promote_roste_facts("", USER_A))
            mock_cls.assert_not_called()


class TestPromoteFirstFact:
    def test_first_me_pref_becomes_root(self):
        """fact แรกในระบบ — ไม่มี existing facts ให้เทียบ เลยไม่ควรยิง LLM หา parent เลย"""
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(chat._promote_roste_facts("คุยหนังสือ | me_pref:ชอบแนวแฟนตาซี", USER_A))
            mock_cls.assert_not_called()

        roste_mem = memory.load_roste_memory()
        assert len(roste_mem["facts"]) == 1
        assert roste_mem["facts"][0]["text"] == "ชอบแนวแฟนตาซี"
        assert roste_mem["facts"][0]["parent"] is None
        assert roste_mem["facts"][0]["mentioned_by"] == [USER_A]

    def test_promoted_fact_is_never_superseded(self):
        """ยิงคำที่ปกติจะ trigger negation-supersede (ถ้า allow_supersede=True) —
        roste facts ต้องไม่ superseded เด็ดขาด (ข้อความใหม่ไม่ตรง dedup เป๊ะ จึงยัง
        เรียก LLM หา parent จริง — mock ให้ตอบ null คือไม่เกี่ยวกับอะไรเลย)"""
        asyncio.run(chat._promote_roste_facts("คุยหนังสือ | me_pref:ชอบแนวแฟนตาซี", USER_A))
        with patch("aiohttp.ClientSession", make_aiohttp_mock_sequence('{"parent_id": null}')):
            asyncio.run(chat._promote_roste_facts("คุยหนังสือต่อ | me_pref:ไม่ชอบแนวแฟนตาซี", USER_A))

        roste_mem = memory.load_roste_memory()
        assert len(roste_mem["facts"]) == 2   # เก็บทั้งคู่ ไม่ลบ/mark superseded อันไหนเลย
        assert not roste_mem["facts"][0]["superseded"]
        assert not roste_mem["facts"][1]["superseded"]


class TestPromoteWithParentExtraction:
    def test_second_fact_asks_llm_for_parent(self):
        asyncio.run(chat._promote_roste_facts("คุยหนังสือ | me_pref:ชอบหนังสือ", USER_A))
        root_mem = memory.load_roste_memory()
        root_id = root_mem["facts"][0]["id"]

        with patch("aiohttp.ClientSession",
                    make_aiohttp_mock_sequence(f'{{"parent_id": "{root_id}"}}')):
            asyncio.run(chat._promote_roste_facts("คุยนิยาย | me_pref:ชอบนิยายไซไฟ", USER_A))

        roste_mem = memory.load_roste_memory()
        leaf = next(f for f in roste_mem["facts"] if f["text"] == "ชอบนิยายไซไฟ")
        assert leaf["parent"] == root_id

    def test_llm_says_unrelated_stays_root(self):
        asyncio.run(chat._promote_roste_facts("คุยหนังสือ | me_pref:ชอบหนังสือ", USER_A))

        with patch("aiohttp.ClientSession",
                    make_aiohttp_mock_sequence('{"parent_id": null}')):
            asyncio.run(chat._promote_roste_facts("คุยดนตรี | me_pref:ชอบดนตรีคลาสสิก", USER_A))

        roste_mem = memory.load_roste_memory()
        leaf = next(f for f in roste_mem["facts"] if f["text"] == "ชอบดนตรีคลาสสิก")
        assert leaf["parent"] is None

    def test_llm_hallucinated_parent_id_falls_back_to_root(self):
        """LLM ตอบ id ที่ไม่มีอยู่จริง — parse_parent_response ต้องกรองทิ้ง ไม่ยัดมั่ว"""
        asyncio.run(chat._promote_roste_facts("คุยหนังสือ | me_pref:ชอบหนังสือ", USER_A))

        with patch("aiohttp.ClientSession",
                    make_aiohttp_mock_sequence('{"parent_id": "id-ที่ไม่มีจริง"}')):
            asyncio.run(chat._promote_roste_facts("คุยนิยาย | me_pref:ชอบนิยายไซไฟ", USER_A))

        roste_mem = memory.load_roste_memory()
        leaf = next(f for f in roste_mem["facts"] if f["text"] == "ชอบนิยายไซไฟ")
        assert leaf["parent"] is None

    def test_llm_timeout_falls_back_to_root_not_dropped(self):
        """LLM call พลาด (connection error จำลอง) — เก็บ fact เป็น root แทนทิ้งทั้งอัน"""
        asyncio.run(chat._promote_roste_facts("คุยหนังสือ | me_pref:ชอบหนังสือ", USER_A))

        broken = MagicMock(side_effect=ConnectionError("refused"))
        with patch("aiohttp.ClientSession", broken):
            asyncio.run(chat._promote_roste_facts("คุยนิยาย | me_pref:ชอบนิยายไซไฟ", USER_A))

        roste_mem = memory.load_roste_memory()
        leaf = next(f for f in roste_mem["facts"] if f["text"] == "ชอบนิยายไซไฟ")
        assert leaf["parent"] is None   # ไม่ถูกทิ้ง แค่ไม่ได้ parent


class TestPromoteMentionedBy:
    """user คนละคนพูดถึงเรื่องเดิม — ไม่สร้าง fact ซ้ำ แต่ track ไว้ใน mentioned_by
    (ดู memory.add_roste_fact/roste_fact_credit — เปลี่ยนจากพฤติกรรมเดิมที่แค่ skip
    ไม่ทำอะไรเลย เป็น "skip การหา parent ซ้ำ" แต่ยัง track ผู้พูดใหม่ ให้คำนวณ credit
    ทีหลังได้ว่าใครเป็นคนแรก)"""

    def test_second_user_same_text_appends_to_mentioned_by_no_llm_call(self):
        asyncio.run(chat._promote_roste_facts("คุยกับ user A | me_pref:ชอบแนวแฟนตาซี", USER_A))
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(chat._promote_roste_facts("คุยกับ user B | me_pref:ชอบแนวแฟนตาซี", USER_B))
            # fact มีอยู่แล้ว (ไม่ว่า user ไหนพูดไว้ก่อน) — ไม่ต้องหา parent ใหม่ซ้ำ
            mock_cls.assert_not_called()

        roste_mem = memory.load_roste_memory()
        assert len(roste_mem["facts"]) == 1   # ไม่สร้าง fact ซ้ำอีกอัน
        assert roste_mem["facts"][0]["mentioned_by"] == [USER_A, USER_B]

    def test_same_user_repeats_own_text_no_change(self):
        asyncio.run(chat._promote_roste_facts("รอบแรก | me_pref:ชอบแนวแฟนตาซี", USER_A))
        with patch("aiohttp.ClientSession") as mock_cls:
            asyncio.run(chat._promote_roste_facts("รอบสอง | me_pref:ชอบแนวแฟนตาซี", USER_A))
            mock_cls.assert_not_called()

        roste_mem = memory.load_roste_memory()
        assert roste_mem["facts"][0]["mentioned_by"] == [USER_A]   # ไม่ซ้ำตัวเอง

    def test_three_users_recorded_in_order(self):
        asyncio.run(chat._promote_roste_facts("รอบ A | me_pref:ชอบแนวแฟนตาซี", USER_A))
        asyncio.run(chat._promote_roste_facts("รอบ B | me_pref:ชอบแนวแฟนตาซี", USER_B))
        asyncio.run(chat._promote_roste_facts("รอบ C | me_pref:ชอบแนวแฟนตาซี", USER_C))

        roste_mem = memory.load_roste_memory()
        assert roste_mem["facts"][0]["mentioned_by"] == [USER_A, USER_B, USER_C]
        # first-mover credit: USER_A เป็นคนแรก ได้เครดิตเต็ม
        assert memory.roste_fact_credit(roste_mem["facts"][0], USER_A) == 1.0
        assert memory.roste_fact_credit(roste_mem["facts"][0], USER_C) < 1.0


class TestPromoteBothPrefAndFact:
    def test_me_pref_and_me_fact_both_promoted(self):
        asyncio.run(chat._promote_roste_facts(
            "คุยหลายเรื่อง | me_pref:ชอบแนวแฟนตาซี me_fact:ดูแลห้องสมุดเวทมนตร์", USER_A))
        roste_mem = memory.load_roste_memory()
        texts = {f["text"] for f in roste_mem["facts"]}
        assert texts == {"ชอบแนวแฟนตาซี", "ดูแลห้องสมุดเวทมนตร์"}
        for f in roste_mem["facts"]:
            assert f["mentioned_by"] == [USER_A]
