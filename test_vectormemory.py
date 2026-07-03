"""
Unit tests for vectormemory.py — rerank_with_llm 、 Ollama mocked out
เน้นเทสจุดอ่อนเฉพาะของ LLM-as-reranker: output หลุดฟอร์แมต, temperature, edge case คะแนนต่ำหมด
(ดู tools/simulate_vectormemory.py สำหรับเทส end-to-end กับ Ollama/ChromaDB จริง)

Run: pytest test_vectormemory.py -v
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import vectormemory


# ── aiohttp mock helper (เหมือน test_bot.py) ──────────────────────────────────

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


CANDIDATES = ["เกี่ยวข้องมาก", "เกี่ยวข้องน้อย", "ไม่เกี่ยวข้องเลย"]


# ── 1) output หลุดฟอร์แมต — ต้อง fail-safe คืน [] ไม่ใช่ crash หรือปล่อยของมั่วผ่าน ───

class TestRerankMalformedOutput:
    def test_valid_json_array_ranks_and_filters(self):
        with patch("aiohttp.ClientSession", make_aiohttp_mock("[9, 3, 0]")):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == ["เกี่ยวข้องมาก"]  # เฉพาะอันคะแนน >= RERANK_SCORE_MIN(5)

    def test_prose_wrapped_json_still_parses(self):
        text = "แน่นอนค่ะ นี่คือคะแนนที่ขอ: [9, 3, 0] หวังว่าจะช่วยได้นะคะ"
        with patch("aiohttp.ClientSession", make_aiohttp_mock(text)):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == ["เกี่ยวข้องมาก"]

    def test_no_brackets_at_all_returns_empty(self):
        with patch("aiohttp.ClientSession", make_aiohttp_mock("9/10, 3/10, 0/10")):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == []

    def test_wrong_length_array_returns_empty(self):
        # โมเดลตอบแค่ 2 ตัวเลขทั้งที่มี 3 candidates
        with patch("aiohttp.ClientSession", make_aiohttp_mock("[9, 3]")):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == []

    def test_non_numeric_array_returns_empty(self):
        with patch("aiohttp.ClientSession",
                   make_aiohttp_mock('["สูง", "ต่ำ", "ไม่มี"]')):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == []

    def test_malformed_json_syntax_returns_empty(self):
        # bracket เปิดไม่ปิด — json.loads ต้อง raise แล้วโดน catch
        with patch("aiohttp.ClientSession", make_aiohttp_mock("[9, 3, 0")):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == []

    def test_think_tag_stripped_before_parsing(self):
        text = "<think>กำลังพิจารณาคะแนนอยู่...</think>\n[9, 3, 0]"
        with patch("aiohttp.ClientSession", make_aiohttp_mock(text)):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == ["เกี่ยวข้องมาก"]

    def test_http_exception_returns_empty_not_crash(self):
        with patch("aiohttp.ClientSession", side_effect=ConnectionError("ollama down")):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == []

    def test_all_scores_below_threshold_returns_empty(self):
        """คะแนนต่ำหมด (ไม่มีอันไหนเกี่ยวข้องจริง) — ต้องคืน [] ไม่ใช่ปล่อยของมั่วผ่าน
        เพราะไม่มี MAX_DISTANCE คั่นแล้ว ตอนนี้ rerank คือด่านตัดสินสุดท้ายจริงๆ"""
        with patch("aiohttp.ClientSession", make_aiohttp_mock("[3, 2, 1]")):
            result = asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))
        assert result == []

    def test_five_candidates_all_low_score_returns_empty(self):
        """เทส RETRIEVE_K เต็มจำนวน (5) ทุกอันคะแนนต่ำ — จำลองเคส query ที่ไม่เคยคุยมาก่อนเลย"""
        five = ["a", "b", "c", "d", "e"]
        with patch("aiohttp.ClientSession", make_aiohttp_mock("[4, 3, 2, 1, 0]")):
            result = asyncio.run(vectormemory.rerank_with_llm("เรื่องที่ไม่เคยคุย", five))
        assert result == []


# ── 2) temperature ต้องเป็น 0 (นิ่งที่สุด) ────────────────────────────────────

class TestRerankTemperature:
    def test_uses_temperature_zero(self):
        captured_payload = {}

        def capture_and_respond(url, json, timeout):
            captured_payload.update(json)
            mock_resp = MagicMock()
            mock_resp.json = AsyncMock(return_value={"message": {"content": "[9, 3, 0]"}})
            ctx = MagicMock()
            ctx.__aenter__ = AsyncMock(return_value=mock_resp)
            ctx.__aexit__ = AsyncMock(return_value=None)
            return ctx

        mock_session = MagicMock()
        mock_session.post = MagicMock(side_effect=capture_and_respond)
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", MagicMock(return_value=mock_session_ctx)):
            asyncio.run(vectormemory.rerank_with_llm("q", CANDIDATES))

        assert captured_payload["options"]["temperature"] == 0
        assert captured_payload["model"] == vectormemory.RERANK_MODEL


# ── 3) edge cases ที่ไม่ต้องยิง LLM เลย (short-circuit) ──────────────────────

class TestRerankShortCircuit:
    def test_empty_candidates_no_http_call(self):
        with patch("aiohttp.ClientSession") as mock_cls:
            result = asyncio.run(vectormemory.rerank_with_llm("q", []))
            mock_cls.assert_not_called()
        assert result == []

    def test_single_candidate_no_http_call(self):
        with patch("aiohttp.ClientSession") as mock_cls:
            result = asyncio.run(vectormemory.rerank_with_llm("q", ["อันเดียว"]))
            mock_cls.assert_not_called()
        assert result == ["อันเดียว"]


# ── 4) ingest_pdf — cap จำนวนหน้า กัน PDF ที่มีหน้าเยอะผิดปกติทำ extract_text ช้า/ค้าง ──

class TestIngestPdfPageCap:
    def _fake_pages(self, n):
        pages = []
        for i in range(n):
            p = MagicMock()
            p.extract_text.return_value = f"page {i} unique-marker-{i}"
            pages.append(p)
        return pages

    def test_pages_beyond_cap_not_extracted(self, monkeypatch):
        monkeypatch.setattr(vectormemory, "MAX_PDF_PAGES", 2)
        fake_pages = self._fake_pages(5)
        fake_reader = MagicMock()
        fake_reader.pages = fake_pages
        mock_coll = MagicMock()

        with patch("vectormemory.PdfReader", return_value=fake_reader), \
             patch("vectormemory.get_embedding", new=AsyncMock(return_value=[0.1, 0.2, 0.3])), \
             patch("vectormemory._pdf_collection", return_value=mock_coll):
            asyncio.run(vectormemory.ingest_pdf(1, "test.pdf", b"fake bytes"))

        for i in range(2):
            fake_pages[i].extract_text.assert_called_once()
        for i in range(2, 5):
            fake_pages[i].extract_text.assert_not_called()

    def test_under_cap_all_pages_extracted(self, monkeypatch):
        monkeypatch.setattr(vectormemory, "MAX_PDF_PAGES", 200)
        fake_pages = self._fake_pages(3)
        fake_reader = MagicMock()
        fake_reader.pages = fake_pages
        mock_coll = MagicMock()

        with patch("vectormemory.PdfReader", return_value=fake_reader), \
             patch("vectormemory.get_embedding", new=AsyncMock(return_value=[0.1, 0.2, 0.3])), \
             patch("vectormemory._pdf_collection", return_value=mock_coll):
            asyncio.run(vectormemory.ingest_pdf(1, "test.pdf", b"fake bytes"))

        for p in fake_pages:
            p.extract_text.assert_called_once()
