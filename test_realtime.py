"""
Unit tests for realtime data functions — Level 1 (mocked HTTP, no real calls)
ครอบคลุม: น้ำมัน, อากาศ, ตัดไฟ, ค้นเว็บ, หาร้าน, routing, เวลา/วันที่
Run: pytest test_realtime.py -v
"""
import asyncio
import sys
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import bot


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

_FAKE_OIL_HTML = (
    "<a>อัปเดตล่าสุด 22/06/2569</a>"
    "<span>(ptt)</span>"
    "<span>แก๊สโซฮอล 91</span><span>42.38</span>"
    "<span>แก๊สโซฮอล 95</span><span>43.98</span>"
    "<span>ดีเซล</span><span>33.34</span>"
    "<span>(bcp)</span>"
    "<span>แก๊สโซฮอล 91</span><span>40.00</span>"
)


# ── 1. get_thai_datetime ──────────────────────────────────────────────────────

class TestThaiDatetime:
    def test_contains_be_year(self):
        result = bot.get_thai_datetime()
        be_year = datetime.now().year + 543
        assert f"พ.ศ. {be_year}" in result

    def test_contains_time_suffix(self):
        assert "น." in bot.get_thai_datetime()

    def test_contains_thai_day_name(self):
        days = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
        assert any(d in bot.get_thai_datetime() for d in days)

    def test_contains_thai_month(self):
        months = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                  "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
        assert any(m in bot.get_thai_datetime() for m in months)

    def test_utc_plus_7_offset(self):
        """ปี พ.ศ. ต้องตรงกับเวลา UTC+7 ไม่ใช่ UTC"""
        from datetime import timezone, timedelta
        now_thai = datetime.now(timezone.utc) + timedelta(hours=7)
        be_year = now_thai.year + 543
        assert f"พ.ศ. {be_year}" in bot.get_thai_datetime()


# ── 2. parse_oil_html ─────────────────────────────────────────────────────────

class TestParseOilHtml:
    def test_default_brand_ptt_shows_prices(self):
        result = bot.parse_oil_html(_FAKE_OIL_HTML)
        assert "ปตท." in result
        assert "42.38" in result
        assert "33.34" in result

    def test_specific_brand_bcp(self):
        result = bot.parse_oil_html(_FAKE_OIL_HTML, "bcp")
        assert "บางจาก" in result
        assert "40.00" in result
        assert "ปตท." not in result

    def test_unknown_brand_falls_back_to_first(self):
        result = bot.parse_oil_html(_FAKE_OIL_HTML, "unknown")
        assert "ปตท." in result

    def test_date_in_output(self):
        assert "22/06/2569" in bot.parse_oil_html(_FAKE_OIL_HTML)

    def test_source_tag_in_output(self):
        assert "Kapook" in bot.parse_oil_html(_FAKE_OIL_HTML)

    def test_empty_html_returns_error(self):
        result = bot.parse_oil_html("<html><body>no brand data</body></html>")
        assert "ไม่สำเร็จ" in result


# ── 3. get_oil_price ──────────────────────────────────────────────────────────

class TestGetOilPrice:
    def test_success_parses_html(self):
        mock = _make_session_mock(text_data=_FAKE_OIL_HTML)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_oil_price("ptt"))
        assert "ปตท." in result
        assert "42.38" in result

    def test_network_exception_returns_error_string(self):
        mock = _make_session_mock(exception=Exception("connection refused"))
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_oil_price())
        assert "ดึงราคาน้ำมันไม่สำเร็จ" in result


# ── 4. _parse_pea_date ────────────────────────────────────────────────────────

class TestParsePeaDate:
    def test_epoch_zero_gives_1970_utc7(self):
        result = bot._parse_pea_date("/Date(0)/")
        assert result is not None
        assert result.year == 1970
        assert result.hour == 7  # UTC+7

    def test_known_epoch(self):
        # 1751302800000 ms = 2025-07-01 00:00 UTC+7
        result = bot._parse_pea_date("/Date(1751302800000)/")
        assert result is not None
        assert result.year == 2025
        assert result.month == 7
        assert result.day == 1

    def test_empty_string_returns_none(self):
        assert bot._parse_pea_date("") is None

    def test_none_returns_none(self):
        assert bot._parse_pea_date(None) is None

    def test_no_digits_returns_none(self):
        # "abc" has no digits — regex won't match
        assert bot._parse_pea_date("/Date(abc)/") is None

    def test_plain_number_parses(self):
        assert bot._parse_pea_date("0") is not None


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
            result = asyncio.run(bot.get_power_outage(69, "ชุมพร"))
        assert "ยังไม่มีประกาศ" in result

    def test_future_matching_item_shows_in_output(self):
        data = {"data": [
            {"PROVINCE_ID": 69, "PROVINCE": "ชุมพร", "AREA": "อำเภอเมือง",
             "END_DATE": _FUTURE, "START_DATE": _FUTURE,
             "START_DATE_DISPLAY": "01/07/2568 09:00", "END_DATE_DISPLAY": "01/07/2568 17:00"}
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_power_outage(69, "ชุมพร"))
        assert "อำเภอเมือง" in result

    def test_past_items_filtered_out(self):
        data = {"data": [
            {"PROVINCE_ID": 69, "PROVINCE": "ชุมพร", "AREA": "อำเภอเมือง",
             "END_DATE": _PAST, "START_DATE": _PAST,
             "START_DATE_DISPLAY": "09/09/2544 09:00", "END_DATE_DISPLAY": "09/09/2544 17:00"}
        ]}
        mock = _make_session_mock(json_data=data)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_power_outage(69, "ชุมพร"))
        assert "ยังไม่มีประกาศ" in result

    def test_http_non_200_returns_status_message(self):
        mock = _make_session_mock(status=500)
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_power_outage())
        assert "500" in result or "ดึงข้อมูลตัดไฟไม่ได้" in result

    def test_network_exception_returns_error_message(self):
        mock = _make_session_mock(exception=Exception("timeout"))
        with patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_power_outage())
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
        with patch.object(bot, "TMD_TOKEN", ""):
            assert asyncio.run(bot.get_weather_tmd("ชุมพร")) is None

    def test_placeholder_token_returns_none(self):
        with patch.object(bot, "TMD_TOKEN", "วาง_token"):
            assert asyncio.run(bot.get_weather_tmd("ชุมพร")) is None

    def test_with_token_formats_output(self):
        mock = _make_session_mock(json_data=_TMD_DAILY)
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock), \
             patch.object(bot, "get_weather_tmd_hourly_today", AsyncMock(return_value="")):
            result = asyncio.run(bot.get_weather_tmd("ชุมพร"))
        assert result is not None
        assert "ชุมพร" in result
        assert "ฝนตกเล็กน้อย" in result   # cond=5

    def test_with_token_shows_temp(self):
        mock = _make_session_mock(json_data=_TMD_DAILY)
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock), \
             patch.object(bot, "get_weather_tmd_hourly_today", AsyncMock(return_value="")):
            result = asyncio.run(bot.get_weather_tmd("ชุมพร"))
        assert "35" in result and "25" in result   # tc_max, tc_min

    def test_http_401_returns_none(self):
        mock = _make_session_mock(status=401)
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            assert asyncio.run(bot.get_weather_tmd("ชุมพร")) is None

    def test_rain_time_appended_if_present(self):
        mock = _make_session_mock(json_data=_TMD_DAILY)
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock), \
             patch.object(bot, "get_weather_tmd_hourly_today",
                          AsyncMock(return_value="14:00-16:00 น.")):
            result = asyncio.run(bot.get_weather_tmd("ชุมพร"))
        assert "14:00-16:00 น." in result


# ── 7. get_weather_tmd_hourly_today ──────────────────────────────────────────

class TestGetWeatherTmdHourlyToday:
    def test_no_token_returns_empty(self):
        with patch.object(bot, "TMD_TOKEN", ""):
            assert asyncio.run(bot.get_weather_tmd_hourly_today("ชุมพร")) == ""

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
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_weather_tmd_hourly_today("ชุมพร"))
        assert "10:00-11:00 น." in result
        assert "16:00 น." in result

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
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_weather_tmd_hourly_today("ชุมพร"))
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
        with patch.object(bot, "TMD_TOKEN", "real_token"), \
             patch("aiohttp.ClientSession", mock):
            result = asyncio.run(bot.get_weather_tmd_hourly_today("ชุมพร"))
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
        with patch.object(bot, "_get_json", AsyncMock(side_effect=[_GEO, _FORECAST])):
            result = asyncio.run(bot.get_weather("Chumphon"))
        assert "Chumphon" in result
        assert "ฝนเล็กน้อย" in result   # weather_code=61

    def test_three_days_in_output(self):
        with patch.object(bot, "_get_json", AsyncMock(side_effect=[_GEO, _FORECAST])):
            result = asyncio.run(bot.get_weather("Chumphon"))
        assert "วันนี้" in result
        assert "พรุ่งนี้" in result
        assert "มะรืนนี้" in result

    def test_location_not_found_returns_error(self):
        with patch.object(bot, "_get_json", AsyncMock(return_value={"results": []})):
            result = asyncio.run(bot.get_weather("NoSuchPlace"))
        assert "หาตำแหน่งของ" in result

    def test_geocoding_exception_returns_error(self):
        with patch.object(bot, "_get_json", AsyncMock(side_effect=Exception("network"))):
            result = asyncio.run(bot.get_weather("Chumphon"))
        assert "ดึงข้อมูลอากาศไม่สำเร็จ" in result


# ── 9. search_web_serpapi ─────────────────────────────────────────────────────

class TestSearchWebSerpapi:
    def setup_method(self):
        bot._SEARCH_CACHE.clear()

    def test_returns_formatted_results(self):
        data = {"organic_results": [
            {"title": "ข่าว AI", "snippet": "AI ล่าสุด", "link": "https://example.com/ai"}
        ]}
        with patch.object(bot, "_serpapi_get", return_value=data):
            result = bot.search_web_serpapi("ข่าว AI")
        assert "ข่าว AI" in result
        assert "example.com" in result

    def test_no_organic_results_returns_empty(self):
        with patch.object(bot, "_serpapi_get", return_value={"organic_results": []}):
            assert bot.search_web_serpapi("ข่าว") == ""

    def test_serpapi_error_returns_empty(self):
        with patch.object(bot, "_serpapi_get", return_value=None):
            assert bot.search_web_serpapi("ข่าว") == ""

    def test_result_is_cached_on_second_call(self):
        data = {"organic_results": [{"title": "X", "snippet": "Y", "link": "https://x.com"}]}
        with patch.object(bot, "_serpapi_get", return_value=data) as mock_fn:
            bot.search_web_serpapi("cache-test-query")
            bot.search_web_serpapi("cache-test-query")
        assert mock_fn.call_count == 1   # ครั้งที่สองใช้ cache


# ── 10. search_places_serpapi ─────────────────────────────────────────────────

class TestSearchPlacesSerpapi:
    def setup_method(self):
        bot._SEARCH_CACHE.clear()

    def test_filters_low_review_places(self):
        data = {"local_results": [
            {"title": "ร้านดัง", "rating": 4.5, "reviews": 100, "address": "ใจกลางเมือง"},
            {"title": "ร้านใหม่", "rating": 4.0, "reviews": 5},  # < 10 รีวิว → กรองออก
        ]}
        with patch.object(bot, "_serpapi_get", return_value=data):
            result = bot.search_places_serpapi("ร้านอาหาร", "ชุมพร")
        assert "ร้านดัง" in result
        assert "ร้านใหม่" not in result

    def test_sorts_by_rating_descending(self):
        data = {"local_results": [
            {"title": "ร้านB", "rating": 3.5, "reviews": 50, "address": "ซอย 2"},
            {"title": "ร้านA", "rating": 4.8, "reviews": 200, "address": "ถนนหลัก"},
        ]}
        with patch.object(bot, "_serpapi_get", return_value=data):
            result = bot.search_places_serpapi("ร้านอาหาร", "ชุมพร")
        assert result.index("ร้านA") < result.index("ร้านB")

    def test_empty_local_results_returns_empty(self):
        with patch.object(bot, "_serpapi_get", return_value={"local_results": []}):
            assert bot.search_places_serpapi("ร้านอาหาร", "ชุมพร") == ""

    def test_serpapi_error_returns_empty(self):
        with patch.object(bot, "_serpapi_get", return_value=None):
            assert bot.search_places_serpapi("ร้านอาหาร", "ชุมพร") == ""

    def test_place_results_fallback_used(self):
        """ถ้าไม่มี local_results แต่มี place_results (สถานที่เดียว) ต้องแสดงได้"""
        data = {
            "local_results": [],
            "place_results": {"title": "สวนสาธารณะ", "rating": 4.2, "reviews": 30}
        }
        with patch.object(bot, "_serpapi_get", return_value=data):
            result = bot.search_places_serpapi("สวนสาธารณะ", "ชุมพร")
        assert "สวนสาธารณะ" in result


# ── 11. search_web ────────────────────────────────────────────────────────────

class TestSearchWeb:
    def setup_method(self):
        bot._SEARCH_CACHE.clear()

    def test_uses_serpapi_when_key_present(self):
        with patch.object(bot, "SERPAPI_KEY", "fake_key"), \
             patch.object(bot, "search_web_serpapi", return_value="ผลจาก SerpApi") as mock_sp:
            result = bot.search_web("ข่าว AI")
        mock_sp.assert_called_once()
        assert "ผลจาก SerpApi" in result

    def test_falls_back_to_ddg_when_no_key(self):
        mock_ddgs_module = MagicMock()
        mock_ddgs_module.DDGS = MagicMock(return_value=MagicMock(
            text=MagicMock(return_value=[
                {"title": "ผล DDG", "body": "เนื้อหา", "href": "https://ddg.com"}
            ])
        ))
        with patch.object(bot, "SERPAPI_KEY", ""), \
             patch.dict("sys.modules", {"ddgs": mock_ddgs_module}):
            result = bot.search_web("คำค้น")
        assert "ผล DDG" in result

    def test_ddg_import_error_returns_install_message(self):
        with patch.object(bot, "SERPAPI_KEY", ""), \
             patch.dict("sys.modules", {"ddgs": None}):
            result = bot.search_web("ข่าว")
        assert "ยังไม่ได้ติดตั้ง" in result or "ddgs" in result

    def test_serpapi_empty_falls_back_to_ddg(self):
        """SerpApi คืน '' → ต้องลอง ddg สำรอง"""
        mock_ddgs_module = MagicMock()
        mock_ddgs_module.DDGS = MagicMock(return_value=MagicMock(
            text=MagicMock(return_value=[
                {"title": "DDG fallback", "body": "content", "href": "https://x.com"}
            ])
        ))
        with patch.object(bot, "SERPAPI_KEY", "fake_key"), \
             patch.object(bot, "search_web_serpapi", return_value=""), \
             patch.dict("sys.modules", {"ddgs": mock_ddgs_module}):
            result = bot.search_web("ข่าว")
        assert "DDG fallback" in result


# ── 12. get_realtime_context — routing ────────────────────────────────────────

class TestGetRealtimeContextRouting:
    def test_กี่โมง_calls_get_thai_datetime(self):
        with patch.object(bot, "get_thai_datetime", return_value="วันจันทร์ที่ 1") as mock_dt:
            result = asyncio.run(bot.get_realtime_context("ตอนนี้กี่โมงแล้ว"))
        mock_dt.assert_called_once()
        assert "วันจันทร์" in result

    def test_วันอะไร_calls_get_thai_datetime(self):
        with patch.object(bot, "get_thai_datetime", return_value="วันอาทิตย์") as mock_dt:
            asyncio.run(bot.get_realtime_context("วันนี้วันอะไร"))
        mock_dt.assert_called_once()

    def test_อากาศ_calls_extract_city_then_weather(self):
        with patch.object(bot, "extract_city", AsyncMock(return_value="Chumphon")) as mc, \
             patch.object(bot, "get_weather_tmd", AsyncMock(return_value=None)), \
             patch.object(bot, "get_weather", AsyncMock(return_value="อากาศดี 30°C")) as mw:
            result = asyncio.run(bot.get_realtime_context("อากาศวันนี้เป็นยังไง"))
        mc.assert_called_once()
        mw.assert_called_once()
        assert "อากาศดี" in result

    def test_อากาศ_prefers_tmd_over_open_meteo(self):
        """ถ้า TMD คืนข้อมูล ต้องไม่เรียก Open-Meteo"""
        with patch.object(bot, "extract_city", AsyncMock(return_value="Chumphon")), \
             patch.object(bot, "get_weather_tmd", AsyncMock(return_value="TMD data")), \
             patch.object(bot, "get_weather", AsyncMock(return_value="OpenMeteo data")) as mow:
            result = asyncio.run(bot.get_realtime_context("ฝนตกไหม"))
        mow.assert_not_called()
        assert "TMD data" in result

    def test_ตัดไฟ_calls_get_power_outage(self):
        with patch.object(bot, "get_power_outage", AsyncMock(return_value="ไม่มีตัดไฟ")) as mock_po:
            result = asyncio.run(bot.get_realtime_context("วันนี้มีตัดไฟไหม"))
        mock_po.assert_called_once()
        assert "ไม่มีตัดไฟ" in result

    def test_น้ำมัน_calls_get_oil_price_ptt_default(self):
        with patch.object(bot, "get_oil_price", AsyncMock(return_value="ปตท. ดีเซล 33.34")) as mock_oil:
            asyncio.run(bot.get_realtime_context("ราคาน้ำมันวันนี้"))
        mock_oil.assert_called_once_with("ptt")

    def test_น้ำมัน_selects_brand_บางจาก(self):
        with patch.object(bot, "get_oil_price", AsyncMock(return_value="บางจาก")) as mock_oil:
            asyncio.run(bot.get_realtime_context("น้ำมันบางจากราคาเท่าไหร่"))
        mock_oil.assert_called_once_with("bcp")

    def test_ดีเซล_keyword_triggers_oil(self):
        with patch.object(bot, "get_oil_price", AsyncMock(return_value="ดีเซล 33.34")) as mock_oil:
            asyncio.run(bot.get_realtime_context("ดีเซลวันนี้ราคาเท่าไร"))
        mock_oil.assert_called_once()

    def test_no_keyword_returns_none(self):
        result = asyncio.run(bot.get_realtime_context("สวัสดีตอนเช้า"))
        assert result is None

    def test_generic_greeting_returns_none(self):
        result = asyncio.run(bot.get_realtime_context("คุยเรื่องหนังสือการ์ตูน"))
        assert result is None
