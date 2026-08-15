"""
Unit tests for music.py — song_requests.json entry cap
Run: pytest test_music.py -v
"""
import json

import pytest

import music


def _use_tmp_log(tmp_path, monkeypatch):
    log_path = tmp_path / "song_requests.json"
    monkeypatch.setattr(music, "SONG_REQUESTS_LOG", str(log_path))
    return log_path


class TestSongRequestCap:
    """log_song_request — จำกัดจำนวน entries กัน song_requests.json โตไม่จำกัด
    เกิน cap แล้วตัดคำขอที่ถูกขอน้อยสุดทิ้งก่อน (เก็บเพลงยอดฮิตไว้)"""

    def test_under_cap_all_entries_kept(self, tmp_path, monkeypatch):
        log_path = _use_tmp_log(tmp_path, monkeypatch)
        monkeypatch.setattr(music, "MAX_SONG_REQUESTS", 5)
        for i in range(3):
            music.log_song_request("user", f"song{i}", found=True)
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data) == 3

    def test_exceeding_cap_keeps_highest_count_entry(self, tmp_path, monkeypatch):
        log_path = _use_tmp_log(tmp_path, monkeypatch)
        monkeypatch.setattr(music, "MAX_SONG_REQUESTS", 2)
        music.log_song_request("user", "popular", found=True)
        music.log_song_request("user", "popular", found=True)
        music.log_song_request("user", "popular", found=True)   # count=3
        music.log_song_request("user", "onehit-a", found=True)  # count=1
        music.log_song_request("user", "onehit-b", found=True)  # count=1 -> เกิน cap(2) ตอนนี้

        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert "popular" in data
        assert data["popular"]["count"] == 3

    def test_repeated_request_updates_existing_key_not_new_entry(self, tmp_path, monkeypatch):
        log_path = _use_tmp_log(tmp_path, monkeypatch)
        monkeypatch.setattr(music, "MAX_SONG_REQUESTS", 5)
        music.log_song_request("user", "same song", found=True)
        music.log_song_request("user", "same song", found=True)
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data["same song"]["count"] == 2

    def test_never_exceeds_cap_over_many_requests(self, tmp_path, monkeypatch):
        log_path = _use_tmp_log(tmp_path, monkeypatch)
        monkeypatch.setattr(music, "MAX_SONG_REQUESTS", 10)
        for i in range(50):
            music.log_song_request("user", f"song{i}", found=True)
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(data) <= 10


# ── extract_song_query — tokenize คำไทยจริงแทน substring replace ────────────────
#    บั๊กจริงที่เจอ (code review ภายนอกชี้จุด): SONG_STRIP มีคำสั้นอย่าง "ขอ" อยู่ในลิสต์
#    ตัว substring replace เดิมจะตัด "ขอ" ออกจากกลางชื่อเพลงที่บังเอิญมีคำนี้ปนอยู่ เช่น "ขอโทษ"

class TestExtractSongQuery:
    def test_song_name_containing_ko_not_mangled(self):
        # เพลงชื่อ "ขอโทษ" ต้องไม่โดนตัดคำว่า "ขอ" ออกจากกลางคำ
        assert music.extract_song_query("ร้องเพลงขอโทษ") == "ขอโทษ"

    def test_strips_common_trigger_words(self):
        assert music.extract_song_query("ร้องเพลง Monster หน่อยค่ะ") == "Monster"

    def test_song_name_containing_kob_khun_not_mangled(self):
        # "ขอบคุณ" มีคำว่า "ขอ" ซ่อนอยู่เหมือนกัน (แม้ไม่ใช่คำเดียวกันเป๊ะ) ต้องรอดเหมือนกัน
        assert music.extract_song_query("เปิดเพลงขอบคุณให้ฟังหน่อย") == "ขอบคุณ"

    def test_english_song_name_with_trigger_word_kept(self):
        assert music.extract_song_query("ขอเพลง Blinding Lights หน่อย") == "Blinding Lights"

    def test_pythainlp_failure_falls_back_to_substring_replace(self, monkeypatch):
        # ถ้า tokenize พังไม่ว่าเหตุผลอะไร ต้องยัง extract ได้ (ผลอาจไม่แม่นเท่า แต่ไม่ crash)
        import pythainlp.tokenize
        monkeypatch.setattr(pythainlp.tokenize, "word_tokenize",
                             lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        result = music.extract_song_query("ร้องเพลง Monster หน่อย")
        assert "Monster" in result


class TestLooksLikePureStop:
    """คำสั่งหยุด **ล้วนๆ** — ทางลัด keyword ที่ตอบได้เลยโดยไม่ต้องยิงโมเดล

    ⚠️ ตั้งใจให้ **แคบ** เพราะสำนวนที่กว้างกว่านี้ให้ tool stop_voice จัดการแทน
    (§4: "กริยาไม่มีวันครบ" · วัดได้ว่าลิสต์คำจับได้แค่ 6/35 สำนวนที่ผู้ใช้น่าจะพิมพ์
    -> เลิกไล่เก็บคำ เปลี่ยนไปให้โมเดลตัดสิน)

    ครึ่งหนึ่งของเทสคือ **ของที่ต้องไม่โดน** — ตีความผิดตอนคุยปกติเสียหายจริง
    (บอทหยุดเสียงและตอบ "หยุดแล้วนะคะ" แทนที่จะตอบคำถามที่ถาม)
    """

    @pytest.mark.parametrize("text", [
        "เงียบหน่อย", "พอแล้ว", "หยุดก่อน", "หยุดเลย", "เงียบๆ",
        "เลิกร้อง", "ไม่ต้องร้อง", "ไม่ต้องพูด",
        "หยุด", "พอ", "เงียบ",
        "stop", "shut up",
    ])
    def test_detects_pure_stop(self, text):
        assert music.looks_like_pure_stop(text)

    @pytest.mark.parametrize("text", [
        "ร้องเพลงให้ฟังหน่อย",       # ขอเพลง ไม่ใช่สั่งหยุด
        "ขอเพลง monster",
        "วันนี้หยุดงานไหม",           # "หยุด" คนละความหมาย
        "รถหยุดตรงไหน",
        "วันหยุดนี้ไปไหนดี",
        "เพลงนี้เพราะจัง",
        "ผมชอบฟังเพลงร็อค",
        "เพลงนี้ชื่ออะไร",
        "ผมเลิกงานแล้วเมื่อกี้นี้เอง",
        "ช่วยอธิบายเรื่องการหยุดพักสมองระหว่างทำงานหน่อยว่าควรทำยังไง",
    ])
    def test_normal_message_not_pure_stop(self, text):
        assert not music.looks_like_pure_stop(text)

    def test_empty_safe(self):
        assert not music.looks_like_pure_stop("")
        assert not music.looks_like_pure_stop(None)
