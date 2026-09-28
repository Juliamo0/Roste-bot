"""
Unit tests for intimacy.py — ค่าความสนิทสนม (ร่างตาม docs/roste-plan.md)
Run: pytest tests/test_intimacy.py -v
"""
from datetime import date, timedelta

import intimacy


def _mem():
    return {"name": "", "facts": [], "history": [], "summaries": []}


def _talk_days(mem, days: list[date], messages_per_day: int = 2):
    for d in days:
        for _ in range(messages_per_day):
            intimacy.record_interaction(mem, message_count_today=1, today=d)


class TestRecordInteraction:
    def test_creates_intimacy_state_on_first_call(self):
        mem = _mem()
        intimacy.record_interaction(mem, message_count_today=1, today=date(2026, 1, 1))
        assert "intimacy" in mem
        assert mem["intimacy"]["daily_counts"]["2026-01-01"] == 1

    def test_accumulates_count_within_same_day(self):
        mem = _mem()
        d = date(2026, 1, 1)
        intimacy.record_interaction(mem, message_count_today=1, today=d)
        intimacy.record_interaction(mem, message_count_today=1, today=d)
        intimacy.record_interaction(mem, message_count_today=1, today=d)
        assert mem["intimacy"]["daily_counts"]["2026-01-01"] == 3

    def test_prunes_entries_older_than_double_window(self):
        mem = _mem()
        today = date(2026, 6, 1)
        very_old = today - timedelta(days=intimacy.WINDOW_DAYS * 3)
        intimacy.record_interaction(mem, message_count_today=1, today=very_old)
        intimacy.record_interaction(mem, message_count_today=1, today=today)
        assert very_old.isoformat() not in mem["intimacy"]["daily_counts"]
        assert today.isoformat() in mem["intimacy"]["daily_counts"]


class TestGetTier:
    def test_no_history_is_tier_1(self):
        mem = _mem()
        assert intimacy.get_tier(mem) == 1

    def test_single_day_below_min_messages_stays_tier_1(self):
        """1 ข้อความในวันเดียว ไม่ถึงเกณฑ์กันสแปม (MIN_MESSAGES_PER_DAY=2) — ไม่นับ"""
        mem = _mem()
        today = date(2026, 1, 5)
        intimacy.record_interaction(mem, message_count_today=1, today=today)
        assert intimacy.get_tier(mem, today=today) == 1

    def test_few_days_within_threshold_is_experimenting(self):
        mem = _mem()
        today = date(2026, 1, 10)
        _talk_days(mem, [today - timedelta(days=i) for i in range(5)])
        assert intimacy.get_tier(mem, today=today) == 2

    def test_many_days_is_intensifying(self):
        mem = _mem()
        today = date(2026, 3, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(20)])
        assert intimacy.get_tier(mem, today=today) == 3

    def test_very_many_days_is_integrating(self):
        mem = _mem()
        today = date(2026, 6, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(61)])   # 61 วัน > threshold 60
        assert intimacy.get_tier(mem, today=today) == 4

    def test_days_outside_window_dont_count(self):
        """คุยถี่มากแต่ 61+ วันก่อน (นอก WINDOW_DAYS=60) ไม่ควรถูกนับเข้ามาช่วยดันระดับปัจจุบัน"""
        mem = _mem()
        today = date(2026, 6, 1)
        old_days = [today - timedelta(days=70 + i) for i in range(20)]
        _talk_days(mem, old_days)
        # peak_tier ที่เคยได้จากรอบเก่าจะยังให้พื้นอยู่ (tier 3 - 1 = 2) แต่ไม่ใช่ tier 3
        # ของ "ตอนนี้" ตรงๆ — ทดสอบว่า raw computed ปัจจุบัน (ไม่มีวันคุยใน window เลย)
        # ไม่ถูกดันขึ้นไปเป็น tier 3 ทั้งที่ไม่มีการคุยใน 60 วันหลังสุดเลย
        assert intimacy.get_tier(mem, today=today) <= 3


class TestPeakFloor:
    def test_tier_never_drops_below_peak_minus_one(self):
        """roste-plan.md: decay ต้องมีพื้น ห้าม reset กลับ tier 1 ทั้งที่เคยสนิทมาก"""
        mem = _mem()
        peak_day = date(2026, 3, 1)
        _talk_days(mem, [peak_day - timedelta(days=i) for i in range(20)])
        assert intimacy.get_tier(mem, today=peak_day) == 3   # ยืนยันว่าขึ้นถึง tier 3 จริง

        # หายไปนานมาก (เกิน window ไปมาก) ไม่คุยเลย
        much_later = peak_day + timedelta(days=200)
        tier_after_absence = intimacy.get_tier(mem, today=much_later)
        assert tier_after_absence >= 3 - 1   # ลดได้สูงสุด 1 ขั้นจาก peak

    def test_peak_updates_when_new_high_reached(self):
        mem = _mem()
        d1 = date(2026, 1, 20)
        _talk_days(mem, [d1 - timedelta(days=i) for i in range(5)])
        intimacy.get_tier(mem, today=d1)   # บันทึก peak = 2
        assert mem["intimacy"]["peak_tier"] == 2

        d2 = date(2026, 4, 1)
        _talk_days(mem, [d2 - timedelta(days=i) for i in range(20)])
        intimacy.get_tier(mem, today=d2)   # ควรขยับ peak ขึ้นเป็น 3
        assert mem["intimacy"]["peak_tier"] == 3


class TestToneInstruction:
    def test_returns_tier_1_tone_for_new_user(self):
        mem = _mem()
        tone = intimacy.tone_instruction(mem)
        assert tone == intimacy.TIER_TONE[1]

    def test_returns_matching_tone_for_tier(self):
        """สร้าง tier 3 จริงจาก daily_counts (ไม่ใช่ยัด peak_tier ตรงๆ) — peak_tier บอก
        แค่ "เคยถึงสูงสุดเท่าไหร่" ไม่ใช่ tier ปัจจุบัน คนละความหมายกัน (ดู floor logic
        ใน get_tier: ไม่มีวันคุยเลยแต่ peak=3 จะได้ tier 2 ไม่ใช่ 3 — tested แยกใน
        TestPeakFloor แล้ว)"""
        mem = _mem()
        today = date(2026, 3, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(20)])
        tone = intimacy.tone_instruction(mem, today=today)
        assert tone == intimacy.TIER_TONE[3]

    def test_all_tiers_have_tone_defined(self):
        for tier in intimacy.TIER_NAMES:
            assert tier in intimacy.TIER_TONE
            assert isinstance(intimacy.TIER_TONE[tier], str) and intimacy.TIER_TONE[tier]


class TestBreadthCount:
    def test_no_summaries_is_zero(self):
        mem = _mem()
        assert intimacy.breadth_count(mem) == 0

    def test_counts_me_pref_and_me_fact_from_tagged_summary(self):
        mem = _mem()
        mem["summaries"] = [
            "คุยแนวนิยาย | user_pref:ชอบนิยายสืบสวน me_pref:ชอบแนวแฟนตาซี",
        ]
        assert intimacy.breadth_count(mem) == 1

    def test_ignores_user_pref_and_user_fact(self):
        """breadth นับแค่ฝั่งรอสเต้ (me_*) — ไม่ใช่จำนวนเรื่องที่ user เล่าให้ฟัง"""
        mem = _mem()
        mem["summaries"] = [
            "คุยเรื่องงาน | user_pref:ชอบงานอิสระ user_fact:ทำงานไอที",
        ]
        assert intimacy.breadth_count(mem) == 0

    def test_dedupes_same_me_fact_across_summaries(self):
        mem = _mem()
        mem["summaries"] = [
            "คุยเรื่องหนังสือ | me_pref:ชอบแนวแฟนตาซี",
            "คุยเรื่องเวทมนตร์ | me_pref:ชอบแนวแฟนตาซี",   # พูดซ้ำเรื่องเดิม ไม่ควรนับซ้ำ
        ]
        assert intimacy.breadth_count(mem) == 1

    def test_counts_distinct_topics_separately(self):
        mem = _mem()
        mem["summaries"] = [
            "คุยเรื่องหนังสือ | me_pref:ชอบแนวแฟนตาซี",
            "คุยเรื่องงาน | me_fact:ดูแลห้องสมุดเวทมนตร์",
        ]
        assert intimacy.breadth_count(mem) == 2

    def test_untagged_legacy_summary_contributes_zero(self):
        """summary เก่าไม่มี tag เลย (ก่อนมีระบบแยกเจ้าของ) — ต้องไม่ error ไม่ใช่นับมั่ว"""
        mem = _mem()
        mem["summaries"] = ["23 ก.ค.: คุยเรื่องความแตกต่างระหว่างเจลาโต้และไอศกรีม"]
        assert intimacy.breadth_count(mem) == 0

    def test_handles_dict_shaped_summary_entries(self):
        """summaries บางจุดในระบบเก็บเป็น {"text": ...} ไม่ใช่ string ตรงๆ"""
        mem = _mem()
        mem["summaries"] = [{"text": "คุยเรื่องหนังสือ | me_pref:ชอบแนวแฟนตาซี"}]
        assert intimacy.breadth_count(mem) == 1
