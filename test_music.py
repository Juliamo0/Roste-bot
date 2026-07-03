"""
Unit tests for music.py — song_requests.json entry cap
Run: pytest test_music.py -v
"""
import json

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
