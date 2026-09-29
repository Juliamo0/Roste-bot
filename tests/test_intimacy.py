"""
Unit tests for intimacy.py — ค่าความสนิทสนม (ร่างตาม docs/roste-plan.md)
Run: pytest tests/test_intimacy.py -v
"""
from datetime import date, timedelta

import intimacy
import memory

USER = 111
OTHER_USER = 222


def _mem():
    return {"name": "", "facts": [], "history": [], "summaries": []}


def _roste_mem():
    return {"name": "", "preferred_name": "", "facts": [], "history": [], "summaries": []}


def _talk_days(mem, days: list[date], messages_per_day: int = 2):
    for d in days:
        for _ in range(messages_per_day):
            intimacy.record_interaction(mem, message_count_today=1, today=d)


def _give_depth(roste_mem, user_id, n_facts: int, chain: bool = False):
    """เติม roste fact ให้ user_id มี depth_component > 0 — chain=True สร้าง parent
    chain ยาวขึ้นเรื่อยๆ (depth เพิ่มทีละชั้น) chain=False สร้าง root แยกกัน n อัน"""
    parent = None
    for i in range(n_facts):
        memory.add_roste_fact(roste_mem, f"เรื่องที่ {i}", user_id, category=None,
                               parent=parent if chain else None)
        if chain:
            parent = roste_mem["facts"][-1]["id"]


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


class TestFrequencyComponent:
    def test_no_history_is_zero(self):
        mem = _mem()
        assert intimacy._frequency_component(mem, today=date(2026, 1, 1)) == 0.0

    def test_full_window_caps_at_one(self):
        mem = _mem()
        today = date(2026, 6, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(intimacy.WINDOW_DAYS + 5)])
        assert intimacy._frequency_component(mem, today=today) == 1.0

    def test_partial_window_is_proportional(self):
        mem = _mem()
        today = date(2026, 3, 1)
        n = 10
        _talk_days(mem, [today - timedelta(days=i) for i in range(n)])
        expected = n / intimacy.WINDOW_DAYS
        assert abs(intimacy._frequency_component(mem, today=today) - expected) < 1e-9


class TestDepthComponent:
    def test_no_facts_for_user_is_zero(self):
        """"ไม่มีข้อมูล = ไม่เปิดเผย" — ตัดสินใจไว้ตรงๆ ตอนออกแบบ"""
        roste_mem = _roste_mem()
        assert intimacy._depth_component(roste_mem, USER) == 0.0

    def test_facts_from_other_user_dont_count(self):
        roste_mem = _roste_mem()
        _give_depth(roste_mem, OTHER_USER, 3)
        assert intimacy._depth_component(roste_mem, USER) == 0.0

    def test_root_only_facts_give_low_depth(self):
        """root ทุกอัน (depth=0 ทั้งหมด) — เฉลี่ย depth = 0 แม้มีหลายเรื่อง (breadth
        อย่างเดียวไม่ได้แปลว่า depth สูง — คนละมิติกัน)"""
        roste_mem = _roste_mem()
        _give_depth(roste_mem, USER, 5, chain=False)
        assert intimacy._depth_component(roste_mem, USER) == 0.0

    def test_deep_chain_gives_higher_depth_than_shallow(self):
        roste_mem = _roste_mem()
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH + 1, chain=True)
        assert intimacy._depth_component(roste_mem, USER) > 0.0

    def test_capped_at_one(self):
        roste_mem = _roste_mem()
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH * 3, chain=True)
        assert intimacy._depth_component(roste_mem, USER) <= 1.0

    def test_superseded_fact_excluded(self):
        """roste facts ไม่ควร superseded เลยตามดีไซน์ (allow_supersede=False เสมอ) แต่
        เผื่อ fact ในระบบ (import จากที่อื่น/แก้มือ) ถูก mark ไว้ — ต้องไม่นับ"""
        roste_mem = _roste_mem()
        memory.add_roste_fact(roste_mem, "เรื่องทดสอบ", USER)
        roste_mem["facts"][0]["superseded"] = True
        assert intimacy._depth_component(roste_mem, USER) == 0.0


class TestGetTier:
    def test_no_history_is_tier_1(self):
        mem = _mem()
        roste_mem = _roste_mem()
        assert intimacy.get_tier(mem, roste_mem, USER) == 1

    def test_frequency_alone_without_depth_stays_tier_1(self):
        """คุย 61 วันติด (frequency=1.0) แต่ไม่มี roste fact เลย (depth=0) —
        score = freq*depth = 0 เสมอ ไม่ว่าจะคุยนานแค่ไหน (SPT: breadth x depth
        ทั้งคู่ต้อง > 0 ถึงจะได้ intimacy จริง)"""
        mem = _mem()
        roste_mem = _roste_mem()
        today = date(2026, 6, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(61)])
        assert intimacy.get_tier(mem, roste_mem, USER, today=today) == 1

    def test_deep_talk_single_day_stays_low_tier(self):
        """เคสที่คุยกันออกแบบไว้: คุยลึกมาก (depth เต็ม) แต่แค่วันเดียว (freq ต่ำมาก)
        — ไม่ควรกระโดดไป tier สูง เพราะ SPT ต้องการทั้งสองมิติพร้อมกัน"""
        mem = _mem()
        roste_mem = _roste_mem()
        today = date(2026, 3, 1)
        _talk_days(mem, [today])   # แค่ 1 วัน
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH + 2, chain=True)
        assert intimacy.get_tier(mem, roste_mem, USER, today=today) == 1

    def test_long_but_shallow_talk_does_not_exceed_tier_2(self):
        """เคสที่คุยกันออกแบบไว้: คุยกันนาน (freq สูง) แต่ตื้นตลอด (depth ต่ำมาก —
        มีแต่ root กว้างๆ หลายเรื่อง ไม่เคยลงลึกเป็นลูกเลยสักครั้ง) — ไม่ควรเกิน tier 2
        (breadth เยอะไม่ได้แปลว่า depth สูง — คนละมิติกันตาม SPT)"""
        mem = _mem()
        roste_mem = _roste_mem()
        today = date(2026, 6, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(90)])
        _give_depth(roste_mem, USER, 5, chain=False)   # 5 root แยกกัน depth=0 ทุกอัน
        tier = intimacy.get_tier(mem, roste_mem, USER, today=today)
        assert tier <= 2

    def test_moderate_frequency_and_depth_reaches_tier_4(self):
        """เคสที่คุยกันออกแบบไว้: freq≈1.0 + depth กลางๆ → tier 4 (ใกล้เคียงพฤติกรรม
        เดิมที่ใช้ days เพียวๆ)"""
        mem = _mem()
        roste_mem = _roste_mem()
        today = date(2026, 6, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(60)])
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH + 1, chain=True)
        tier = intimacy.get_tier(mem, roste_mem, USER, today=today)
        assert tier == 4


class TestPeakFloor:
    def test_tier_never_drops_below_peak_minus_one(self):
        """roste-plan.md: decay ต้องมีพื้น ห้าม reset กลับ tier 1 ทั้งที่เคยสนิทมาก"""
        mem = _mem()
        roste_mem = _roste_mem()
        peak_day = date(2026, 3, 1)
        _talk_days(mem, [peak_day - timedelta(days=i) for i in range(60)])
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH + 1, chain=True)
        peak_tier = intimacy.get_tier(mem, roste_mem, USER, today=peak_day)
        assert peak_tier == 4   # ยืนยันว่าขึ้นถึง tier 4 จริง

        # หายไปนานมาก (เกิน window ไปมาก) ไม่คุยเลย — frequency กลับไป 0
        much_later = peak_day + timedelta(days=200)
        tier_after_absence = intimacy.get_tier(mem, roste_mem, USER, today=much_later)
        assert tier_after_absence >= peak_tier - 1   # ลดได้สูงสุด 1 ขั้นจาก peak

    def test_peak_updates_when_new_high_reached(self):
        mem = _mem()
        roste_mem = _roste_mem()
        d1 = date(2026, 1, 20)
        _talk_days(mem, [d1 - timedelta(days=i) for i in range(5)])
        intimacy.get_tier(mem, roste_mem, USER, today=d1)   # ยังไม่มี depth เลย → tier 1
        assert mem["intimacy"]["peak_tier"] == 1

        d2 = date(2026, 4, 1)
        _talk_days(mem, [d2 - timedelta(days=i) for i in range(60)])
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH + 1, chain=True)
        intimacy.get_tier(mem, roste_mem, USER, today=d2)   # ควรขยับ peak ขึ้น
        assert mem["intimacy"]["peak_tier"] == 4


class TestToneInstruction:
    def test_returns_tier_1_tone_for_new_user(self):
        mem = _mem()
        roste_mem = _roste_mem()
        tone = intimacy.tone_instruction(mem, roste_mem, USER)
        assert tone == intimacy.TIER_TONE[1]

    def test_returns_matching_tone_for_tier(self):
        mem = _mem()
        roste_mem = _roste_mem()
        today = date(2026, 6, 1)
        _talk_days(mem, [today - timedelta(days=i) for i in range(60)])
        _give_depth(roste_mem, USER, intimacy.MAX_MEANINGFUL_DEPTH + 1, chain=True)
        tone = intimacy.tone_instruction(mem, roste_mem, USER, today=today)
        assert tone == intimacy.TIER_TONE[4]

    def test_all_tiers_have_tone_defined(self):
        for tier in intimacy.TIER_NAMES:
            assert tier in intimacy.TIER_TONE
            assert isinstance(intimacy.TIER_TONE[tier], str) and intimacy.TIER_TONE[tier]
