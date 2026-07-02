"""
Unit tests for memory.py
Run: pytest test_memory.py -v
"""
import json
import pytest
import memory


# ── build_summary_prompt ──────────────────────────────────────────────────────

class TestBuildSummaryPrompt:
    def test_formats_user_role(self):
        pairs = [{"role": "user", "content": "อยากกินก๋วยเตี๋ยว"}]
        assert "ผู้ใช้: อยากกินก๋วยเตี๋ยว" in memory.build_summary_prompt(pairs)

    def test_formats_assistant_role(self):
        pairs = [{"role": "assistant", "content": "แถวไหนดีคะ"}]
        assert "รอสเต้: แถวไหนดีคะ" in memory.build_summary_prompt(pairs)

    def test_includes_both_roles(self):
        pairs = [
            {"role": "user", "content": "อยากกินก๋วยเตี๋ยว"},
            {"role": "assistant", "content": "แถวไหนดีคะ"},
        ]
        result = memory.build_summary_prompt(pairs)
        assert "ผู้ใช้: อยากกินก๋วยเตี๋ยว" in result
        assert "รอสเต้: แถวไหนดีคะ" in result

    def test_instruction_asks_for_one_line(self):
        result = memory.build_summary_prompt([{"role": "user", "content": "สวัสดี"}])
        assert "1 บรรทัด" in result

    def test_missing_content_key_does_not_crash(self):
        result = memory.build_summary_prompt([{"role": "user"}])
        assert isinstance(result, str)


# ── should_try_extract ────────────────────────────────────────────────────────

class TestShouldTryExtract:
    # Fix #2 — "มี" เดี่ยวต้องไม่ trigger อีกต่อไป
    def test_bare_mi_does_not_trigger(self):
        assert memory.should_try_extract("มีวิธีไหมบ้าง") is False
        assert memory.should_try_extract("มีหรือเปล่า") is False       # ไม่มี hint อื่นซ่อน
        assert memory.should_try_extract("มีประโยชน์ไหม") is False

    def test_pronoun_paired_mi_triggers(self):
        assert memory.should_try_extract("ผมมีแมวอยู่ตัวหนึ่ง") is True
        assert memory.should_try_extract("ฉันมีบ้านอยู่ชุมพร") is True
        assert memory.should_try_extract("เรามีงานทำแล้วนะ") is True
        assert memory.should_try_extract("หนูมีความสนใจเรื่องนี้") is True

    def test_other_self_reference_hints_trigger(self):
        assert memory.should_try_extract("ผมทำงานเป็นวิศวกร") is True
        assert memory.should_try_extract("ฉันชอบอ่านหนังสือ") is True
        assert memory.should_try_extract("ชื่อของฉันคือจูเลีย") is True
        assert memory.should_try_extract("ฉันเรียนอยู่ที่มหาวิทยาลัย") is True

    def test_short_text_skipped(self):
        assert memory.should_try_extract("ผม") is False
        assert memory.should_try_extract("") is False

    def test_generic_questions_do_not_trigger(self):
        assert memory.should_try_extract("อากาศวันนี้เป็นยังไง") is False
        assert memory.should_try_extract("ราคาน้ำมันเท่าไหร่วันนี้") is False


# ── add_fact ──────────────────────────────────────────────────────────────────

class TestAddFact:
    @staticmethod
    def _mem():
        return {"facts": []}

    @staticmethod
    def _texts(mem):
        return [memory._fact_text(f) for f in mem["facts"]]

    def test_adds_new_fact_returns_true(self):
        mem = self._mem()
        assert memory.add_fact(mem, "อยู่ชุมพร") is True
        assert "อยู่ชุมพร" in self._texts(mem)

    def test_duplicate_returns_false(self):
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร")
        assert memory.add_fact(mem, "อยู่ชุมพร") is False
        assert self._texts(mem).count("อยู่ชุมพร") == 1

    def test_strips_whitespace(self):
        mem = self._mem()
        memory.add_fact(mem, "  อยู่ชุมพร  ")
        assert "อยู่ชุมพร" in self._texts(mem)

    def test_empty_fact_ignored(self):
        mem = self._mem()
        assert memory.add_fact(mem, "   ") is False
        assert mem["facts"] == []

    def test_caps_at_max_facts(self):
        mem = self._mem()
        for i in range(memory.MAX_FACTS + 5):
            memory.add_fact(mem, f"fact {i}")
        assert len(mem["facts"]) == memory.MAX_FACTS

    def test_cap_removes_oldest(self):
        mem = self._mem()
        memory.add_fact(mem, "อันเก่าสุด")
        for i in range(memory.MAX_FACTS):
            memory.add_fact(mem, f"fact {i}")
        assert "อันเก่าสุด" not in self._texts(mem)

    def test_no_category_stored_as_none(self):
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร")
        assert mem["facts"][0]["category"] is None
        assert mem["facts"][0]["superseded"] is False

    def test_unknown_category_falls_back_to_none(self):
        """category ที่หลุด FACT_CATEGORIES (โมเดลเผลอสร้างหมวดใหม่เอง) ต้องไม่ crash — เก็บเป็น None"""
        mem = self._mem()
        assert memory.add_fact(mem, "ชอบกาแฟ", category="หมวดที่ไม่มีอยู่จริง") is True
        assert mem["facts"][0]["category"] is None

    def test_valid_category_stored(self):
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        assert mem["facts"][0]["category"] == "ที่อยู่"


# ── add_fact — supersede (single-value category) ───────────────────────────────

class TestAddFactSupersede:
    @staticmethod
    def _mem():
        return {"facts": []}

    def test_single_value_category_supersedes_old_same_category(self):
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        old, new = mem["facts"][0], mem["facts"][1]
        assert old["superseded"] is True
        assert old["superseded_by"] == "อยู่กรุงเทพ"
        assert old["superseded_at"] is not None
        assert new["superseded"] is False

    def test_superseded_fact_not_deleted(self):
        """หัวใจของ supersede-not-delete — fact เก่าต้องยังอยู่ในลิสต์เสมอ กู้คืน/query ย้อนหลังได้"""
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        texts = [f["text"] for f in mem["facts"]]
        assert "อยู่ชุมพร" in texts  # ยังอยู่ ไม่ถูกลบ
        assert len(mem["facts"]) == 2

    def test_multi_value_category_does_not_supersede(self):
        """หมวดสะสมได้ (เช่น ความชอบ) — ของเก่าต้องไม่โดน mark superseded เลย"""
        mem = self._mem()
        memory.add_fact(mem, "ชอบกาแฟ", category="ความชอบ")
        memory.add_fact(mem, "ชอบชา", category="ความชอบ")
        assert all(not f["superseded"] for f in mem["facts"])
        assert len(mem["facts"]) == 2

    def test_different_single_value_categories_do_not_interfere(self):
        """ที่อยู่ vs งาน เป็นคนละหมวด single-value — ไม่ควรไปลบล้างกันเอง"""
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "ทำงานเป็นโปรแกรมเมอร์", category="งาน")
        assert all(not f["superseded"] for f in mem["facts"])

    def test_uncategorized_fact_never_superseded(self):
        """fact เก่าที่ไม่มีหมวด (category=None) — ยกเว้นจาก supersede logic ถาวรตามดีไซน์"""
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร")  # ไม่ระบุ category
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        assert mem["facts"][0]["superseded"] is False  # อันไม่มีหมวดไม่โดนแตะ

    def test_legacy_plain_string_fact_never_touched_by_new_supersede(self):
        """fact แบบเก่าสุด (บันทึกไว้ก่อนมี schema นี้ — เป็น str ล้วนไม่ใช่ dict) ต้องไม่ถูกแตะ
        โดย supersede logic ใหม่เลย (ไม่มี category ให้เทียบ, isinstance check กันไว้)"""
        mem = {"facts": ["อยู่ชุมพร"]}  # รูปแบบเก่าก่อน migration
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        assert mem["facts"][0] == "อยู่ชุมพร"  # ไม่ถูกแปลง/แตะต้องเลย ยังเป็น str เดิม
        assert mem["facts"][1]["superseded"] is False

    def test_re_adding_previously_superseded_text_becomes_current_again(self):
        """ผู้ใช้ย้ายกลับที่เดิม — ข้อความเดียวกับที่เคยถูก supersede ต้องเพิ่มใหม่ได้ ไม่ถูกมองเป็นซ้ำ"""
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        assert memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่") is True
        current = [f for f in mem["facts"] if not f["superseded"]]
        assert len(current) == 1
        assert current[0]["text"] == "อยู่ชุมพร"

    def test_wrong_supersede_is_recoverable(self):
        """เคส supersede ผิด (ระบบ mark ผิดทั้งที่ไม่ได้ขัดกันจริง) — ต้องกู้ได้ เพราะไม่เคยลบข้อมูลจริง
        กู้คืนโดยแก้ flag กลับตรงๆ (ข้อมูลเดิมยังอยู่ครบ ไม่ต้องพึ่งการสร้างใหม่จากศูนย์)"""
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        wrongly_superseded = mem["facts"][0]
        assert wrongly_superseded["text"] == "อยู่ชุมพร"
        # จำลองการกู้คืน — ข้อมูลเดิม (text/created) ยังอยู่ครบ แค่ปลด flag กลับ
        wrongly_superseded["superseded"] = False
        wrongly_superseded["superseded_at"] = None
        wrongly_superseded["superseded_by"] = None
        assert wrongly_superseded["text"] == "อยู่ชุมพร"  # ข้อมูลเดิมไม่หายไปไหน กู้ได้จริง


# ── remove_fact ───────────────────────────────────────────────────────────────

class TestRemoveFact:
    def test_removes_by_keyword(self):
        mem = {"facts": ["อยู่ชุมพร", "ชอบอ่านหนังสือ"]}
        removed = memory.remove_fact(mem, "ชุมพร")
        assert removed == ["อยู่ชุมพร"]
        assert mem["facts"] == ["ชอบอ่านหนังสือ"]

    def test_removes_multiple_matching_facts(self):
        mem = {"facts": ["อยู่ชุมพร", "บ้านที่ชุมพร", "ชอบแมว"]}
        removed = memory.remove_fact(mem, "ชุมพร")
        assert len(removed) == 2
        assert "ชอบแมว" in mem["facts"]

    def test_no_match_returns_empty(self):
        mem = {"facts": ["อยู่ชุมพร"]}
        assert memory.remove_fact(mem, "กรุงเทพ") == []
        assert len(mem["facts"]) == 1

    def test_empty_keyword_does_nothing(self):
        mem = {"facts": ["อยู่ชุมพร"]}
        assert memory.remove_fact(mem, "") == []
        assert len(mem["facts"]) == 1

    def test_works_with_structured_dict_facts(self):
        mem = {"facts": []}
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        removed = memory.remove_fact(mem, "ชุมพร")
        assert removed == ["อยู่ชุมพร"]
        assert mem["facts"] == []


# ── recall_facts ──────────────────────────────────────────────────────────────

class TestRecallFacts:
    def test_returns_all_when_below_cap(self):
        mem = {"facts": ["อยู่ชุมพร", "ชอบแมว"]}
        result = memory.recall_facts(mem, "สวัสดี")
        assert set(result) == {"อยู่ชุมพร", "ชอบแมว"}

    def test_prioritizes_relevant_facts(self):
        facts = [f"ข้อมูล {i}" for i in range(memory.MAX_FACTS_IN_CONTEXT + 5)]
        facts.append("อยู่ชุมพร")
        mem = {"facts": facts}
        result = memory.recall_facts(mem, "ชุมพร")
        assert "อยู่ชุมพร" in result
        assert len(result) <= memory.MAX_FACTS_IN_CONTEXT

    def test_result_capped_at_max(self):
        facts = [f"ข้อมูลที่ {i}" for i in range(memory.MAX_FACTS_IN_CONTEXT * 2)]
        mem = {"facts": facts}
        assert len(memory.recall_facts(mem, "สวัสดี")) <= memory.MAX_FACTS_IN_CONTEXT

    def test_empty_facts_returns_empty(self):
        assert memory.recall_facts({"facts": []}, "อะไรก็ได้") == []

    def test_superseded_fact_excluded_current_returned(self):
        """จุดที่งานวิจัยเตือนว่าพลาดกันบ่อยที่สุด — ต้องเลือกอันล่าสุดที่ valid ไม่ใช่ทั้งคู่
        (กันโมเดลเห็น 'อยู่ชุมพร' กับ 'อยู่กรุงเทพ' พร้อมกันแล้วสับสนว่าอันไหนจริง)"""
        mem = {"facts": []}
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        result = memory.recall_facts(mem, "ตอนนี้อยู่ไหน")
        assert "อยู่กรุงเทพ" in result
        assert "อยู่ชุมพร" not in result

    def test_superseded_fact_excluded_even_when_over_cap(self):
        """เทสเดียวกันแต่ผ่าน scoring path (facts เกิน MAX_FACTS_IN_CONTEXT) — ต้อง filter
        superseded ออกก่อนเข้า scoring ไม่ใช่แค่ตอน facts น้อยกว่า cap"""
        mem = {"facts": []}
        for i in range(memory.MAX_FACTS_IN_CONTEXT + 5):
            memory.add_fact(mem, f"ข้อมูล {i}", category="ความชอบ")
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        result = memory.recall_facts(mem, "ตอนนี้อยู่จังหวัดไหน")
        assert "อยู่กรุงเทพ" in result
        assert "อยู่ชุมพร" not in result

    def test_superseded_fact_still_present_in_raw_mem_for_future_query(self):
        """ของเก่าต้องยัง query ได้จากตัว mem โดยตรง (ไม่ถูกลบ) แค่ไม่โผล่ใน recall_facts ปกติ
        — เป็นวัตถุดิบให้ฟีเจอร์อื่น (เช่น คาแรกเตอร์ผูกความจำ) ใช้ต่อได้"""
        mem = {"facts": []}
        memory.add_fact(mem, "อยู่ชุมพร", category="ที่อยู่")
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        memory.recall_facts(mem, "ตอนนี้อยู่ไหน")
        all_texts = [f["text"] for f in mem["facts"]]
        assert "อยู่ชุมพร" in all_texts  # ยังอยู่ใน mem จริง แค่ไม่ถูก recall เป็นค่าปัจจุบัน

    def test_multi_value_category_all_returned_not_superseded(self):
        mem = {"facts": []}
        memory.add_fact(mem, "ชอบกาแฟ", category="ความชอบ")
        memory.add_fact(mem, "ชอบชา", category="ความชอบ")
        result = memory.recall_facts(mem, "สวัสดี")
        assert "ชอบกาแฟ" in result
        assert "ชอบชา" in result

    def test_works_with_legacy_plain_string_facts(self):
        """fact แบบเก่า (str ล้วน ไม่มี superseded flag) ต้องยังทำงานถูกต้องเหมือนเดิมทุกอย่าง"""
        mem = {"facts": ["อยู่ชุมพร", "ชอบแมว"]}
        result = memory.recall_facts(mem, "สวัสดี")
        assert set(result) == {"อยู่ชุมพร", "ชอบแมว"}


# ── parse_extracted_facts / add_fact — category ไม่ถูก consolidation แตะถ้าไม่มีหมวด ──

class TestUncategorizedFactsExemptFromConsolidation:
    def test_manual_remember_command_has_no_category_and_never_superseded(self):
        """คำสั่ง "จำไว้ว่า" ของผู้ใช้ไม่ผ่าน LLM extraction จึงไม่มี category —
        ต้องไม่ถูก auto-supersede แม้จะเพิ่ม fact หมวด single-value ตามมาทีหลัง"""
        mem = {"facts": []}
        memory.add_fact(mem, "อยู่ชุมพรมาตั้งแต่เด็ก")  # เหมือนพิมพ์ "จำไว้ว่า..." ตรงๆ ไม่มี category
        memory.add_fact(mem, "อยู่กรุงเทพ", category="ที่อยู่")
        assert mem["facts"][0]["superseded"] is False


# ── parse_extracted_facts ─────────────────────────────────────────────────────

class TestParseExtractedFacts:
    def test_parses_clean_object_array(self):
        output = '[{"category": "ชื่อ", "text": "ชื่อจูเลีย"}, {"category": "ที่อยู่", "text": "อยู่ชุมพร"}]'
        result = memory.parse_extracted_facts(output)
        assert result == [
            {"category": "ชื่อ", "text": "ชื่อจูเลีย"},
            {"category": "ที่อยู่", "text": "อยู่ชุมพร"},
        ]

    def test_unknown_category_becomes_none(self):
        """โมเดลเผลอสร้าง category ใหม่เอง (ไม่อยู่ใน FACT_CATEGORIES) — ต้องไม่ crash เก็บเป็น None"""
        output = '[{"category": "หมวดมั่ว", "text": "อยู่ชุมพร"}]'
        result = memory.parse_extracted_facts(output)
        assert result == [{"category": None, "text": "อยู่ชุมพร"}]

    def test_missing_category_key_becomes_none(self):
        output = '[{"text": "อยู่ชุมพร"}]'
        result = memory.parse_extracted_facts(output)
        assert result == [{"category": None, "text": "อยู่ชุมพร"}]

    def test_legacy_plain_string_array_still_parses(self):
        """เผื่อโมเดลเผลอตอบรูปแบบเก่า (list ของสตริงล้วน) — ต้องทนทาน ไม่ crash แปลงเป็น category=None"""
        result = memory.parse_extracted_facts('["ชื่อจูเลีย", "อยู่ชุมพร"]')
        assert result == [
            {"category": None, "text": "ชื่อจูเลีย"},
            {"category": None, "text": "อยู่ชุมพร"},
        ]

    def test_strips_think_tag(self):
        output = '<think>กำลังวิเคราะห์...</think>\n[{"category": "ที่อยู่", "text": "อยู่ชุมพร"}]'
        result = memory.parse_extracted_facts(output)
        assert result == [{"category": "ที่อยู่", "text": "อยู่ชุมพร"}]

    def test_extracts_array_from_surrounding_text(self):
        output = 'ข้าพเจ้าพบข้อมูลดังนี้ [{"category": "งาน", "text": "ทำงานวิศวกร"}] ครับ'
        result = memory.parse_extracted_facts(output)
        assert result == [{"category": "งาน", "text": "ทำงานวิศวกร"}]

    def test_empty_array_returns_empty(self):
        assert memory.parse_extracted_facts("[]") == []

    def test_empty_string_returns_empty(self):
        assert memory.parse_extracted_facts("") == []

    def test_filters_too_long_items(self):
        long_str = "ก" * 61
        assert memory.parse_extracted_facts(f'[{{"category": "ชื่อ", "text": "{long_str}"}}]') == []

    def test_invalid_json_returns_empty(self):
        assert memory.parse_extracted_facts("ไม่มี JSON เลยสักนิด") == []

    def test_filters_non_dict_non_string_items(self):
        result = memory.parse_extracted_facts('[42, {"category": "ชื่อ", "text": "ชื่อจูเลีย"}, null]')
        assert result == [{"category": "ชื่อ", "text": "ชื่อจูเลีย"}]


# ── load_memory — summaries field ────────────────────────────────────────────

class TestLoadMemorySummaries:
    def test_new_user_has_summaries_field(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        mem = memory.load_memory(999)
        assert "summaries" in mem
        assert mem["summaries"] == []

    def test_old_file_without_summaries_gets_default(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        (tmp_path / "123.json").write_text(
            json.dumps({"name": "Julia", "facts": ["อยู่ชุมพร"], "history": []}),
            encoding="utf-8",
        )
        mem = memory.load_memory(123)
        assert mem["summaries"] == []
        assert mem["name"] == "Julia"
        assert mem["facts"] == ["อยู่ชุมพร"]

    def test_existing_summaries_preserved(self, tmp_path, monkeypatch):
        monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
        existing = {"name": "", "facts": [], "history": [],
                    "summaries": ["22 มิ.ย.: คุยเรื่องก๋วยเตี๋ยว"]}
        (tmp_path / "456.json").write_text(json.dumps(existing), encoding="utf-8")
        mem = memory.load_memory(456)
        assert mem["summaries"] == ["22 มิ.ย.: คุยเรื่องก๋วยเตี๋ยว"]
