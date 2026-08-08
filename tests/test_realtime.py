"""
Unit tests for realtime data functions — Level 1 (mocked HTTP, no real calls)
ครอบคลุม: น้ำมัน, อากาศ, ตัดไฟ, ค้นเว็บ, หาร้าน, เวลา/วันที่
(routing เดิม — keyword dispatch ที่เคยเทสใน TestGetRealtimeContextRouting — ถูกแทนที่ด้วย
LLM tool calling แล้ว ดูเทส dispatch ใหม่ใน test_bot.py + tools/simulate_toolcalling.py)
Run: pytest test_realtime.py -v
"""
import asyncio
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import bot
import datasources
import websearch


# ── aiohttp session mock ──────────────────────────────────────────────────────

def _make_session_mock(status=200, json_data=None, text_data=None, exception=None):
    """mock สำหรับ aiohttp.ClientSession รองรับ GET/POST, status, json, text, exception"""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data if json_data is not None else {})
    mock_resp.text = AsyncMock(return_value=text_data or "")

    mock_req_ctx = MagicMock()
    if exception is not None:
        mock_req_ctx.__aenter__ = AsyncMock(side_effect=exception)
    else:
        mock_req_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_req_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_req_ctx)
    mock_session.post = MagicMock(return_value=mock_req_ctx)

    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=None)

    return MagicMock(return_value=mock_session_ctx)


# ── Fake HTML สำหรับ parse_oil_html ──────────────────────────────────────────
# โครงสร้างจริงของ Kapook เปลี่ยนมาเป็น Next.js (ราวต้นเดือน ก.ค. 2569) — ไม่มี "(ptt)"
# ห้อยท้ายชื่อแบบเดิมแล้ว แต่ละยี่ห้อกลายเป็น <section id="brand-XXX" class="scroll-mt-28">
# และวันที่ "อัปเดตล่าสุด" กับตัววันที่จริงถูกคั่นด้วย HTML comment (React hydration marker)
# คนละ text node กัน — fixture นี้จำลองโครงสร้างจริงที่ยืนยันแล้วจากการดึงหน้าเว็บสด

_FAKE_OIL_HTML = (
    '<p>อัปเดตล่าสุด <!-- -->22 มิถุนายน 2569</p>'
    '<section id="brand-ptt" class="scroll-mt-28">'
    '<h2>ราคาน้ำมัน ปตท.</h2><p>3 รายการ</p>'
    '<ul>'
    '<li><p>แก๊สโซฮอล 91</p><span>แก๊สโซฮอล์</span><p>42.38</p><p>บาท/ลิตร</p></li>'
    '<li><p>แก๊สโซฮอล 95</p><span>แก๊สโซฮอล์</span><p>43.98</p><p>บาท/ลิตร</p></li>'
    '<li><p>ดีเซล</p><span>ดีเซล</span><p>33.34</p><p>บาท/ลิตร</p></li>'
    '</ul></section>'
    '<section id="brand-bcp" class="scroll-mt-28">'
    '<h2>ราคาน้ำมันบางจาก</h2><p>1 รายการ</p>'
    '<ul>'
    '<li><p>แก๊สโซฮอล 91</p><span>แก๊สโซฮอล์</span><p>40.00</p><p>บาท/ลิตร</p></li>'
    '</ul></section>'
)


# ── 1. get_thai_datetime ──────────────────────────────────────────────────────

class TestThaiDatetime:
    def test_contains_be_year(self):
        result = datasources.get_thai_datetime()
        be_year = datetime.now().year + 543
        assert f"พ.ศ. {be_year}" in result

    def test_contains_time_suffix(self):
        assert "น." in datasources.get_thai_datetime()

    def test_contains_thai_day_name(self):
        days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        assert any(d in datasources.get_thai_datetime() for d in days)

    def test_contains_thai_month(self):
        months = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                  "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
        assert any(m in datasources.get_thai_datetime() for m in months)

    def test_utc_plus_7_offset(self):
        """ปี พ.ศ. ต้องตรงกับเวลา UTC+7 ไม่ใช่ UTC"""
        from datetime import timezone, timedelta
        now_thai = datetime.now(timezone.utc) + timedelta(hours=7)
        be_year = now_thai.year + 543
        assert f"พ.ศ. {be_year}" in datasources.get_thai_datetime()


# ── 2. parse_oil_html ─────────────────────────────────────────────────────────

class TestParseOilHtml:
    def test_default_brand_ptt_shows_prices(self):
        result = datasources.parse_oil_html(_FAKE_OIL_HTML)
        assert "ปตท." in result
        assert "42.38" in result
        assert "33.34" in result

    def test_specific_brand_bcp(self):
        result = datasources.parse_oil_html(_FAKE_OIL_HTML, "bcp")
        assert "บางจาก" in result
        assert "40.00" in result
        assert "ปตท." not in result

    def test_unknown_brand_falls_back_to_first(self):
        result = datasources.parse_oil_html(_FAKE_OIL_HTML, "unknown")
        assert "ปตท." in result

    def test_date_in_output(self):
        assert "22 มิถุนายน 2569" in datasources.parse_oil_html(_FAKE_OIL_HTML)

    def test_source_tag_in_output(self):
        assert "Kapook" in datasources.parse_oil_html(_FAKE_OIL_HTML)

    def test_empty_html_returns_error(self):
        result = datasources.parse_oil_html("<html><body>no brand data</body></html>")
        assert "ไม่สำเร็จ" in result


# ── 3. get_oil_price ──────────────────────────────────────────────────────────

class TestGetOilPrice:
    def test_success_parses_html(self):
        mock = _make_session_mock(text_data=_FAKE_OIL_HTML)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_oil_price("ptt"))
        assert "ปตท." in result
        assert "42.38" in result

    def test_network_exception_returns_error_string(self):
        mock = _make_session_mock(exception=Exception("connection refused"))
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_oil_price())
        assert "ดึงราคาน้ำมันไม่สำเร็จ" in result


# ── 4. _parse_pea_date ────────────────────────────────────────────────────────

class TestParsePeaDate:
    def test_epoch_zero_gives_1970_utc7(self):
        result = datasources._parse_pea_date("/Date(0)/")
        assert result is not None
        assert result.year == 1970
        assert result.hour == 7  # UTC+7

    def test_known_epoch(self):
        # 1751302800000 ms = 2025-07-01 00:00 UTC+7
        result = datasources._parse_pea_date("/Date(1751302800000)/")
        assert result is not None
        assert result.year == 2025
        assert result.month == 7
        assert result.day == 1

    def test_empty_string_returns_none(self):
        assert datasources._parse_pea_date("") is None

    def test_none_returns_none(self):
        assert datasources._parse_pea_date(None) is None

    def test_no_digits_returns_none(self):
        # "abc" has no digits — regex won't match
        assert datasources._parse_pea_date("/Date(abc)/") is None

    def test_plain_number_parses(self):
        assert datasources._parse_pea_date("0") is not None


# ── 5. get_power_outage ───────────────────────────────────────────────────────

_FUTURE = "/Date(4000000000000)/"   # ปี ~2096 (อนาคต)
_PAST   = "/Date(1000000000000)/"   # ปี 2001 (อดีต)


class TestGetPowerOutage:
    def test_no_matching_province_returns_no_announcement(self):
        data = {"data": [
            {"PROVINCE_ID": 10, "PROVINCE": "กรุงเทพมหานคร", "AREA": "ลาดกระบัง",
             "END_DATE": _FUTURE, "START_DATE": _FUTURE,
             "START_DATE_DISPLAY": "01/07/2568 09:00", "END_DATE_DISPLAY": "01/07/2568 17:00"}
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage(69, "ชุมพร"))
        assert "ยังไม่มีประกาศ" in result

    def test_future_matching_item_shows_in_output(self):
        data = {"data": [
            {"PROVINCE_ID": 69, "PROVINCE": "ชุมพร", "AREA": "อำเภอเมือง",
             "END_DATE": _FUTURE, "START_DATE": _FUTURE,
             "START_DATE_DISPLAY": "01/07/2568 09:00", "END_DATE_DISPLAY": "01/07/2568 17:00"}
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage(69, "ชุมพร"))
        assert "อำเภอเมือง" in result

    def test_past_items_filtered_out(self):
        data = {"data": [
            {"PROVINCE_ID": 69, "PROVINCE": "ชุมพร", "AREA": "อำเภอเมือง",
             "END_DATE": _PAST, "START_DATE": _PAST,
             "START_DATE_DISPLAY": "09/09/2544 09:00", "END_DATE_DISPLAY": "09/09/2544 17:00"}
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage(69, "ชุมพร"))
        assert "ยังไม่มีประกาศ" in result

    def test_filters_by_requested_province_not_home(self):
        # multi-province: ขอจังหวัดอื่น (ไม่ใช่จังหวัดบ้าน) ต้องได้ของจังหวัดนั้น ไม่ปนจังหวัดบ้าน
        # เจอจริงตอนเทสสด: ถามนครศรีฯ แต่โค้ดเดิมกรองเหลือแค่ชุมพร (จังหวัดบ้าน) เสมอ
        data = {"data": [
            {"PROVINCE_ID": 69, "PROVINCE": "ชุมพร", "AREA": "อ.เมืองชุมพร",
             "END_DATE": _FUTURE, "START_DATE": _FUTURE,
             "START_DATE_DISPLAY": "01/07/2568 09:00", "END_DATE_DISPLAY": "01/07/2568 17:00"},
            {"PROVINCE_ID": 80, "PROVINCE": "นครศรีธรรมราช", "AREA": "อ.ทุ่งสง",
             "END_DATE": _FUTURE, "START_DATE": _FUTURE,
             "START_DATE_DISPLAY": "01/07/2568 09:00", "END_DATE_DISPLAY": "01/07/2568 17:00"},
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage(province_name="นครศรีธรรมราช"))
        assert "อ.ทุ่งสง" in result           # ได้ของนครศรีฯ
        assert "อ.เมืองชุมพร" not in result    # ไม่ปนของชุมพร (จังหวัดบ้าน)

    def test_province_name_prefix_normalized(self):
        # "จังหวัดนครศรีธรรมราช" ต้อง match "นครศรีธรรมราช" ในข้อมูล + ไม่โชว์ prefix ซ้ำ (จังหวัดจังหวัด)
        data = {"data": [
            {"PROVINCE_ID": 80, "PROVINCE": "นครศรีธรรมราช", "AREA": "อ.ทุ่งสง",
             "END_DATE": _FUTURE, "START_DATE": _FUTURE,
             "START_DATE_DISPLAY": "01/07/2568 09:00", "END_DATE_DISPLAY": "01/07/2568 17:00"},
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage(province_name="จังหวัดนครศรีธรรมราช"))
        assert "อ.ทุ่งสง" in result
        assert "จังหวัดจังหวัด" not in result

    def test_http_non_200_returns_status_message(self):
        mock = _make_session_mock(status=500)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage())
        assert "500" in result or "ดึงข้อมูลตัดไฟไม่ได้" in result

    def test_network_exception_returns_error_message(self):
        mock = _make_session_mock(exception=Exception("timeout"))
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_power_outage())
        assert "เชื่อมต่อ" in result or "ไม่ได้" in result


# ── 6. get_weather_tmd ────────────────────────────────────────────────────────

_TMD_DAILY = {
    "WeatherForecasts": [{
        "location": {"province": "ชุมพร"},
        "forecasts": [
            {"time": "2025-07-01", "data": {"tc_max": 35, "tc_min": 25, "rh": 70, "cond": 5, "rain": 10}},
            {"time": "2025-07-02", "data": {"tc_max": 34, "tc_min": 24, "rh": 65, "cond": 2, "rain": 0}},
        ]
    }]
}


class TestGetWeatherTmd:
    def test_no_token_returns_none(self):
        with patch.object(datasources, "TMD_TOKEN", ""):
            assert asyncio.run(datasources.get_weather_tmd("ชุมพร")) is None

    def test_placeholder_token_returns_none(self):
        with patch.object(datasources, "TMD_TOKEN", "วาง_token"):
            assert asyncio.run(datasources.get_weather_tmd("ชุมพร")) is None

    def test_with_token_formats_output(self):
        mock = _make_session_mock(json_data=_TMD_DAILY)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock), \
             patch.object(datasources, "get_weather_tmd_hourly_today", AsyncMock(return_value="")):
            result = asyncio.run(datasources.get_weather_tmd("ชุมพร"))
        assert result is not None
        assert "ชุมพร" in result
        assert "ฝนตกเล็กน้อย" in result   # cond=5

    def test_with_token_shows_temp(self):
        mock = _make_session_mock(json_data=_TMD_DAILY)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock), \
             patch.object(datasources, "get_weather_tmd_hourly_today", AsyncMock(return_value="")):
            result = asyncio.run(datasources.get_weather_tmd("ชุมพร"))
        assert "35" in result and "25" in result   # tc_max, tc_min

    def test_http_401_returns_none(self):
        mock = _make_session_mock(status=401)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            assert asyncio.run(datasources.get_weather_tmd("ชุมพร")) is None

    def test_rain_time_appended_if_present(self):
        mock = _make_session_mock(json_data=_TMD_DAILY)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock), \
             patch.object(datasources, "get_weather_tmd_hourly_today",
                          AsyncMock(return_value="14:00-16:00 น.")):
            result = asyncio.run(datasources.get_weather_tmd("ชุมพร"))
        assert "14:00-16:00 น." in result


# ── 7. get_weather_tmd_hourly_today ──────────────────────────────────────────

class TestGetWeatherTmdHourlyToday:
    def test_no_token_returns_empty(self):
        with patch.object(datasources, "TMD_TOKEN", ""):
            assert asyncio.run(datasources.get_weather_tmd_hourly_today("ชุมพร")) == ""

    def test_rainy_consecutive_hours_grouped(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "WeatherForecasts": [{
                "forecasts": [
                    {"time": f"{today}T10:00:00+07:00", "data": {"rain": 1.5}},
                    {"time": f"{today}T11:00:00+07:00", "data": {"rain": 2.0}},
                    {"time": f"{today}T16:00:00+07:00", "data": {"rain": 3.0}},
                ]
            }]
        }
        mock = _make_session_mock(json_data=data)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_weather_tmd_hourly_today("ชุมพร"))
        # รูปแบบเปลี่ยนจาก "10:00-11:00 น." เป็น "10 ถึง 11 นาฬิกา" เพราะข้อความนี้
        # ถูกส่งเข้า TTS ด้วย และ F5/VoxCPM อ่าน ":" ไม่ออก (ผู้ใช้เจอจริง)
        assert "10 ถึง 11 นาฬิกา" in result
        assert "16 นาฬิกา" in result
        assert ":" not in result

    def test_below_threshold_rain_not_shown(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "WeatherForecasts": [{
                "forecasts": [
                    {"time": f"{today}T10:00:00+07:00", "data": {"rain": 0.2}},  # < 0.5
                ]
            }]
        }
        mock = _make_session_mock(json_data=data)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_weather_tmd_hourly_today("ชุมพร"))
        assert result == ""

    def test_different_day_data_ignored(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data = {
            "WeatherForecasts": [{
                "forecasts": [
                    {"time": "2000-01-01T14:00:00+07:00", "data": {"rain": 99.0}},  # ไม่ใช่วันนี้
                    {"time": f"{today}T08:00:00+07:00", "data": {"rain": 0.1}},
                ]
            }]
        }
        mock = _make_session_mock(json_data=data)
        with patch.object(datasources, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            result = asyncio.run(datasources.get_weather_tmd_hourly_today("ชุมพร"))
        assert result == ""


# ── 8. get_weather (Open-Meteo) ───────────────────────────────────────────────

_GEO = {"results": [{"name": "Chumphon", "latitude": 10.5, "longitude": 99.2}]}
_FORECAST = {
    "daily": {
        "time": ["2025-07-01", "2025-07-02", "2025-07-03"],
        "weather_code": [61, 2, 0],
        "temperature_2m_max": [35, 34, 33],
        "temperature_2m_min": [25, 24, 23],
        "precipitation_probability_max": [80, 20, 5],
    },
    "hourly": {
        "time": ["2025-07-01T06:00", "2025-07-01T12:00"],
        "precipitation_probability": [40, 90],
    },
}


class TestGetWeather:
    def test_location_found_returns_formatted_output(self):
        with patch.object(datasources, "_get_json", AsyncMock(side_effect=[_GEO, _FORECAST])):
            result = asyncio.run(datasources.get_weather("Chumphon"))
        assert "Chumphon" in result
        assert "ฝนเล็กน้อย" in result   # weather_code=61

    def test_three_days_in_output(self):
        with patch.object(datasources, "_get_json", AsyncMock(side_effect=[_GEO, _FORECAST])):
            result = asyncio.run(datasources.get_weather("Chumphon"))
        assert "วันนี้" in result
        assert "พรุ่งนี้" in result
        assert "มะรืนนี้" in result

    def test_location_not_found_returns_error(self):
        with patch.object(datasources, "_get_json", AsyncMock(return_value={"results": []})):
            result = asyncio.run(datasources.get_weather("NoSuchPlace"))
        assert "หาตำแหน่งของ" in result

    def test_geocoding_exception_returns_error(self):
        with patch.object(datasources, "_get_json", AsyncMock(side_effect=Exception("network"))):
            result = asyncio.run(datasources.get_weather("Chumphon"))
        assert "ดึงข้อมูลอากาศไม่สำเร็จ" in result


# ── 9a. SerpApi quota-ordering (cache hit ไม่ควรเผาโควตา) ──────────────────────

class TestSerpapiQuotaOrdering:
    """บั๊กเดิม: _serpapi_quota_ok() ถูกเรียกที่ caller (search_web/_search_places) ก่อนเช็ค
    cache ทำให้ cache hit ก็ยังเผาโควตาไปด้วย (ถามคำเดิมซ้ำใน 1 ชม. ก็นับเผา 8 ครั้ง/วันอยู่ดี
    ทั้งที่ไม่ได้ยิง API จริง) — แก้โดยย้ายเช็คโควตาเข้าไปใน _serpapi_get (จุดเดียวที่ยิง HTTP จริง)"""

    def setup_method(self):
        websearch._SEARCH_CACHE.clear()
        websearch._serpapi_quota_date = None
        websearch._serpapi_quota_count = 0

    def test_quota_exceeded_skips_http_call(self, monkeypatch):
        from datetime import date
        monkeypatch.setattr(websearch, "_serpapi_quota_date", date.today())
        monkeypatch.setattr(websearch, "_serpapi_quota_count", websearch._SERPAPI_DAILY_LIMIT)
        with patch("requests.get") as mock_get:
            result = websearch._serpapi_get({"q": "test"})
        assert result is None
        mock_get.assert_not_called()

    def test_cache_hit_does_not_burn_quota_again(self):
        """cache hit ต้องไม่เรียก _serpapi_get ซ้ำ (= ไม่เผาโควตาซ้ำ) — ยืนยันด้วย quota counter
        จริง ไม่ mock _serpapi_get ตรงๆ (ต่างจากเทสอื่นด้านล่างที่ mock _serpapi_get เพื่อเทส
        พฤติกรรม parse ผลลัพธ์ — เทสนี้ต้องการดูว่า HTTP call จริงถูกยิงกี่ครั้ง)"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"organic_results": [
            {"title": "X", "snippet": "Y", "link": "https://x.com"}
        ]}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            websearch.search_web_serpapi("same-query")   # cache miss → ยิงจริง 1 ครั้ง
            websearch.search_web_serpapi("same-query")   # cache hit → ไม่ควรยิงซ้ำ
        assert mock_get.call_count == 1
        assert websearch._serpapi_quota_count == 1   # เผาโควตาแค่ครั้งเดียว ไม่ใช่ 2


# ── 9. search_web_serpapi ──────────────────────────────────────────────────────

class TestSearchWebSerpapi:
    """หมายเหตุ: search_web_serpapi ย้ายไป websearch.py แล้ว (bot.py แค่ re-export) —
    patch _serpapi_get ต้องชี้ไป websearch ตรงๆ เพราะฟังก์ชันนี้เรียก _serpapi_get ผ่าน
    __globals__ ของโมดูลที่นิยามมันเอง (websearch) ไม่ใช่ของ bot ที่ import มา"""

    def setup_method(self):
        websearch._SEARCH_CACHE.clear()

    def test_returns_formatted_results(self):
        data = {"organic_results": [
            {"title": "ข่าว AI", "snippet": "AI ล่าสุด", "link": "https://example.com/ai"}
        ]}
        with patch.object(websearch, "_serpapi_get", return_value=data):
            result = websearch.search_web_serpapi("ข่าว AI")
        assert "ข่าว AI" in result
        assert "example.com" in result

    def test_no_organic_results_returns_empty(self):
        with patch.object(websearch, "_serpapi_get", return_value={"organic_results": []}):
            assert websearch.search_web_serpapi("ข่าว") == ""

    def test_serpapi_error_returns_empty(self):
        with patch.object(websearch, "_serpapi_get", return_value=None):
            assert websearch.search_web_serpapi("ข่าว") == ""

    def test_result_is_cached_on_second_call(self):
        data = {"organic_results": [{"title": "X", "snippet": "Y", "link": "https://x.com"}]}
        with patch.object(websearch, "_serpapi_get", return_value=data) as mock_fn:
            websearch.search_web_serpapi("cache-test-query")
            websearch.search_web_serpapi("cache-test-query")
        assert mock_fn.call_count == 1   # ครั้งที่สองใช้ cache


# ── 10. search_places_serpapi ─────────────────────────────────────────────────

class TestSearchPlacesSerpapi:
    def setup_method(self):
        websearch._SEARCH_CACHE.clear()

    def test_filters_low_review_places(self):
        data = {"local_results": [
            {"title": "ร้านดัง", "rating": 4.5, "reviews": 100, "address": "ใจกลางเมือง"},
            {"title": "ร้านใหม่", "rating": 4.0, "reviews": 5},  # < 10 รีวิว → กรองออก
        ]}
        with patch.object(websearch, "_serpapi_get", return_value=data):
            result = websearch.search_places_serpapi("ร้านอาหาร", "ชุมพร")
        assert "ร้านดัง" in result
        assert "ร้านใหม่" not in result

    def test_sorts_by_rating_descending(self):
        data = {"local_results": [
            {"title": "ร้านB", "rating": 3.5, "reviews": 50, "address": "ซอย 2"},
            {"title": "ร้านA", "rating": 4.8, "reviews": 200, "address": "ถนนหลัก"},
        ]}
        with patch.object(websearch, "_serpapi_get", return_value=data):
            result = websearch.search_places_serpapi("ร้านอาหาร", "ชุมพร")
        assert result.index("ร้านA") < result.index("ร้านB")

    def test_empty_local_results_returns_empty(self):
        with patch.object(websearch, "_serpapi_get", return_value={"local_results": []}):
            assert websearch.search_places_serpapi("ร้านอาหาร", "ชุมพร") == ""

    def test_serpapi_error_returns_empty(self):
        with patch.object(websearch, "_serpapi_get", return_value=None):
            assert websearch.search_places_serpapi("ร้านอาหาร", "ชุมพร") == ""

    def test_place_results_fallback_used(self):
        """ถ้าไม่มี local_results แต่มี place_results (สถานที่เดียว) ต้องแสดงได้"""
        data = {
            "local_results": [],
            "place_results": {"title": "สวนสาธารณะ", "rating": 4.2, "reviews": 30}
        }
        with patch.object(websearch, "_serpapi_get", return_value=data):
            result = websearch.search_places_serpapi("สวนสาธารณะ", "ชุมพร")
        assert "สวนสาธารณะ" in result


# ── 11. search_web ────────────────────────────────────────────────────────────

class TestSearchWeb:
    """หมายเหตุ: search_web ย้ายไป websearch.py แล้ว — patch SERPAPI_KEY/search_web_serpapi
    ต้องชี้ไป websearch ตรงๆ ด้วยเหตุผลเดียวกับ TestSearchWebSerpapi ด้านบน"""

    def setup_method(self):
        websearch._SEARCH_CACHE.clear()

    def test_uses_serpapi_when_key_present(self):
        with patch.object(websearch, "SERPAPI_KEY", "fake_key"), \
             patch.object(websearch, "search_web_serpapi", return_value="ผลจาก SerpApi") as mock_sp:
            result = websearch.search_web("ข่าว AI")
        mock_sp.assert_called_once()
        assert "ผลจาก SerpApi" in result

    def test_falls_back_to_ddg_when_no_key(self):
        mock_ddgs_module = MagicMock()
        mock_ddgs_module.DDGS = MagicMock(return_value=MagicMock(
            text=MagicMock(return_value=[
                {"title": "ผล DDG", "body": "เนื้อหา", "href": "https://ddg.com"}
            ])
        ))
        with patch.object(websearch, "SERPAPI_KEY", ""), \
             patch.dict("sys.modules", {"ddgs": mock_ddgs_module}):
            result = websearch.search_web("คำค้น")
        assert "ผล DDG" in result

    def test_ddg_import_error_returns_install_message(self):
        with patch.object(websearch, "SERPAPI_KEY", ""), \
             patch.dict("sys.modules", {"ddgs": None}):
            result = websearch.search_web("ข่าว")
        assert "ยังไม่ได้ติดตั้ง" in result or "ddgs" in result

    def test_serpapi_empty_falls_back_to_ddg(self):
        """SerpApi คืน '' → ต้องลอง ddg สำรอง"""
        mock_ddgs_module = MagicMock()
        mock_ddgs_module.DDGS = MagicMock(return_value=MagicMock(
            text=MagicMock(return_value=[
                {"title": "DDG fallback", "body": "content", "href": "https://x.com"}
            ])
        ))
        with patch.object(websearch, "SERPAPI_KEY", "fake_key"), \
             patch.object(websearch, "search_web_serpapi", return_value=""), \
             patch.dict("sys.modules", {"ddgs": mock_ddgs_module}):
            result = websearch.search_web("ข่าว")
        assert "DDG fallback" in result


# ============================================================
#  ข้อความจาก tool ต้อง "อ่านออกเสียงได้"
#
#  ผลลัพธ์ tool ถูกส่งเข้า TTS ด้วย — F5/VoxCPM อ่าน "/" ":" "|" ไม่ออก
#  ผู้ใช้เจอจริง: "แก๊สโซฮอล์ 95: 35.99 บาท/ลิตร" อ่าน / ไม่ได้
#  แก้ที่ต้นทาง (datasources) แทนการเพิ่มกฎใน f5_preprocess ซึ่งใช้ร่วมกับ
#  ข้อความทุกประเภท (เสี่ยงไปโดน URL/path/วันที่ในบริบทอื่น)
# ============================================================
class TestSpeakableToolOutput:
    UNREADABLE = "/:|"

    def test_oil_price_has_no_unreadable_chars(self):
        out = datasources.parse_oil_html(_FAKE_OIL_HTML, only_brand="ptt")
        body = "\n".join(l for l in out.splitlines() if "ที่มา" not in l)
        assert "บาทต่อลิตร" in body
        for ch in self.UNREADABLE:
            assert ch not in body, f"เหลือ {ch!r} ที่ TTS อ่านไม่ออก: {body!r}"

    def test_speakable_time_basic(self):
        assert datasources._speakable_time("09:00") == "9 นาฬิกา"
        assert datasources._speakable_time("13:30") == "13 นาฬิกา 30 นาที"

    def test_speakable_time_midnight_and_noon(self):
        """0/12 นาฬิกา ฟังแล้วไม่เป็นธรรมชาติ — ใช้คำเรียกปกติแทน"""
        assert datasources._speakable_time("00:00") == "เที่ยงคืน"
        assert datasources._speakable_time("12:00") == "เที่ยง"

    def test_speakable_time_passthrough_on_bad_input(self):
        """รูปแบบไม่ตรง → คืนค่าเดิม ดีกว่าทำข้อมูลเพี้ยน"""
        assert datasources._speakable_time("ไม่ใช่เวลา") == "ไม่ใช่เวลา"
        assert datasources._speakable_time("") == ""
        assert datasources._speakable_time(None) == ""

    def test_speakable_datetime_full(self):
        got = datasources._speakable_datetime("12/05/2569 09:00")
        assert got == "12 พฤษภาคม 2569 9 นาฬิกา"
        for ch in self.UNREADABLE:
            assert ch not in got

    def test_speakable_datetime_date_only(self):
        assert datasources._speakable_datetime("01/12/2569") == "1 ธันวาคม 2569"

    def test_speakable_datetime_passthrough(self):
        assert datasources._speakable_datetime("รูปแบบแปลก") == "รูปแบบแปลก"

    def test_rain_hours_readable(self):
        """ช่วงเวลาฝนตกต้องไม่มี ':' (เดิมเป็น '16:00-19:00 น.')

        ยิงผ่านฟังก์ชันจริงด้วย mock ข้อมูลรายชั่วโมง แทนการอ่าน source
        เพื่อให้เทสจับพฤติกรรม ไม่ใช่รูปแบบการเขียนโค้ด
        """
        today = datetime.now().strftime("%Y-%m-%d")   # ฟังก์ชันกรองเฉพาะวันนี้
        payload = {"WeatherForecasts": [{"forecasts": [
            {"time": f"{today}T{h:02d}:00:00+07:00", "data": {"rain": rain}}
            for h, rain in [(14, 0.0), (16, 2.0), (17, 3.0), (18, 1.0), (20, 0.0)]
        ]}]}
        # _make_session_mock คืน "factory" อยู่แล้ว — patch ทับ ClientSession ตรงๆ
        session_factory = _make_session_mock(json_data=payload)
        with patch.object(datasources.aiohttp, "ClientSession", session_factory), \
             patch.object(datasources, "TMD_TOKEN", "fake-token"):
            got = asyncio.run(datasources.get_weather_tmd_hourly_today("ชุมพร"))

        assert got, "ควรได้ช่วงเวลาฝนตกกลับมา (16-18 น. ฝน >= 0.5)"
        for ch in self.UNREADABLE:
            assert ch not in got, f"เหลือ {ch!r} ที่ TTS อ่านไม่ออก: {got!r}"
        assert "นาฬิกา" in got
