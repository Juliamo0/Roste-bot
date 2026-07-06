"""
Unit tests for printing.py — file cleanup หลังพิมพ์ + วันหมดอายุของ pending_prints
Run: pytest test_printing.py -v
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import printing


def make_message():
    message = MagicMock()
    message.channel.send = AsyncMock()
    return message


class TestRunPrintJobFileCleanup:
    """run_print_job — ลบไฟล์หลังพิมพ์สำเร็จ (เอกสารอาจเป็นเรื่องส่วนตัว ไม่ควรค้างบนดิสก์)
    เก็บไฟล์ไว้ถ้าพิมพ์ไม่สำเร็จ (เผื่อ debug/ลองใหม่โดยไม่ต้องอัปโหลดซ้ำ)"""

    def _job(self, path):
        return {"path": path, "filename": "test.pdf", "copies": 1,
                "pages": 1, "mention": "@user"}

    def test_file_removed_after_successful_print(self, tmp_path, monkeypatch):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-fake")
        monkeypatch.setattr(printing, "PRINT_REAL_MODE", True)
        with patch("printing.print_pdf_windows", return_value=(True, "")):
            asyncio.run(printing.run_print_job(make_message(), self._job(str(pdf_path))))
        assert not pdf_path.exists()

    def test_file_kept_after_failed_print(self, tmp_path, monkeypatch):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(b"%PDF-fake")
        monkeypatch.setattr(printing, "PRINT_REAL_MODE", True)
        with patch("printing.print_pdf_windows", return_value=(False, "PrinterOffline")):
            asyncio.run(printing.run_print_job(make_message(), self._job(str(pdf_path))))
        assert pdf_path.exists()

    def test_missing_file_does_not_crash(self, tmp_path, monkeypatch):
        # ไฟล์ไม่มีอยู่จริงตอนลบ (เช่นถูกลบไปแล้ว) — ต้องไม่ crash การพิมพ์
        pdf_path = tmp_path / "already_gone.pdf"
        monkeypatch.setattr(printing, "PRINT_REAL_MODE", True)
        with patch("printing.print_pdf_windows", return_value=(True, "")):
            asyncio.run(printing.run_print_job(make_message(), self._job(str(pdf_path))))
        # ไม่ raise = ผ่าน


class TestPendingPrintExpiry:
    """pop_pending_if_valid — pending_prints หมดอายุหลัง PENDING_PRINT_EXPIRY_SEC
    กันพิมพ์คำว่า "ยืนยัน" ในบริบทอื่นแล้วดันไปสั่งพิมพ์งานเก่าที่ลืมไปแล้ว"""

    def setup_method(self):
        printing.pending_prints.clear()

    def test_fresh_job_returned(self):
        printing.pending_prints[111] = {"filename": "a.pdf", "queued_at": time.monotonic()}
        job = printing.pop_pending_if_valid(111)
        assert job is not None
        assert job["filename"] == "a.pdf"

    def test_job_removed_from_pending_after_pop(self):
        printing.pending_prints[111] = {"filename": "a.pdf", "queued_at": time.monotonic()}
        printing.pop_pending_if_valid(111)
        assert 111 not in printing.pending_prints

    def test_expired_job_returns_none(self):
        stale = time.monotonic() - printing.PENDING_PRINT_EXPIRY_SEC - 1
        printing.pending_prints[111] = {"filename": "a.pdf", "queued_at": stale}
        assert printing.pop_pending_if_valid(111) is None

    def test_expired_job_removed_from_pending_too(self):
        stale = time.monotonic() - printing.PENDING_PRINT_EXPIRY_SEC - 1
        printing.pending_prints[111] = {"filename": "a.pdf", "queued_at": stale}
        printing.pop_pending_if_valid(111)
        assert 111 not in printing.pending_prints

    def test_no_pending_job_returns_none(self):
        assert printing.pop_pending_if_valid(999) is None

    def test_job_just_under_expiry_still_valid(self):
        almost_stale = time.monotonic() - printing.PENDING_PRINT_EXPIRY_SEC + 5
        printing.pending_prints[111] = {"filename": "a.pdf", "queued_at": almost_stale}
        assert printing.pop_pending_if_valid(111) is not None
