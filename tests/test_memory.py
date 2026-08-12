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

    def test_free_form_category_is_stored(self):
        """หมวดที่โมเดลตั้งเอง — ตั้งแต่เปิด open schema ต้อง *เก็บชื่อหมวดไว้* ไม่ใช่ทิ้งเป็น None

        ⚠️ พฤติกรรมนี้เปลี่ยนโดยตั้งใจ (11 ส.ค. 2569): เดิมทิ้งทุกหมวดนอก closed set 7 หมวด
        วัดแล้วทำให้ข้อมูล 9 ใน 10 กลุ่มจำไม่ได้ (8% vs 62%) — ดู TestOpenSchemaExtraction
        """
        mem = self._mem()
        assert memory.add_fact(mem, "แพ้กุ้ง", category="สุขภาพ") is True
        assert mem["facts"][0]["category"] == "สุขภาพ"

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

    def test_free_form_category_is_kept(self):
        """หมวดที่โมเดลตั้งเองต้องถูกเก็บไว้ (open schema) — เปลี่ยนโดยตั้งใจ ดู TestOpenSchemaExtraction"""
        output = '[{"category": "สุขภาพ", "text": "แพ้กุ้ง"}]'
        result = memory.parse_extracted_facts(output)
        assert result == [{"category": "สุขภาพ", "text": "แพ้กุ้ง"}]

    def test_absurdly_long_category_becomes_none(self):
        """หมวดยาวผิดปกติ = โมเดลเขียนประโยคมาแทนชื่อหมวด → ไม่รับ"""
        output = '[{"category": "' + "ก" * 40 + '", "text": "อยู่ชุมพร"}]'
        assert memory.parse_extracted_facts(output) == [{"category": None, "text": "อยู่ชุมพร"}]

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


# ============================================================
#  keyword recall กับภาษาไทย — _keywords / recall_summaries
#
#  ทำไมต้องมีชุดนี้: เดิมทั้ง recall_facts และ recall_summaries ใช้ user_message.split()
#  ซึ่งใช้กับภาษาไทยไม่ได้เลย เพราะไทยไม่เขียนเว้นวรรคระหว่างคำ — ทั้งประโยคกลายเป็น token
#  เดียว แล้วไม่มีวันตรงกับ fact/summary ใดๆ วัดจริงบนคำถามจากบทสนทนา Discord: 0/5 เคส
#  (บอทตอบว่า "ไม่เคยคุย" ทั้งที่ summary ที่ตรงมีอยู่ในไฟล์) หลังแก้เป็น 5/5
# ============================================================

class TestThaiKeywordRecall:

    SUMMARIES = [
        {"date": "2026-07-22", "text": "22 ก.ค.: คุยเรื่องนิยายและแนะนำหนังสือที่มีเนื้อหาลึกลับ"},
        {"date": "2026-07-21", "text": "21 ก.ค.: คุยเรื่องอากาศและของหวานที่ชอบ"},
        {"date": "2026-07-08", "text": "8 ก.ค.: คุยเรื่องราคาน้ำมันและร้านอาหาร"},
    ]

    def test_thai_sentence_is_tokenized_not_split_on_space(self):
        """หัวใจของบั๊ก: ประโยคไทยไม่มีช่องว่าง split() จึงคืนก้อนเดียว ใช้จับคู่ไม่ได้

        ใช้คำที่ *ไม่มี* ในตาราง _SYNONYMS ("แมว") เพื่อวัดผลของการตัดคำล้วนๆ —
        ถ้าใช้คำที่มีคำพ้อง การขยายแบบ substring จะช่วยกลบไว้จนเทสไม่จับ regression
        """
        q = "เคยคุยเรื่องแมวกันไหม"
        assert len([w for w in q.split() if len(w) >= 2]) == 1   # พฤติกรรมเดิมที่พัง
        assert memory._keywords(q) == ["แมว"]                     # หลังแก้ต้องแยกคำได้จริง

    def test_recall_depends_on_tokenizer_for_unlisted_words(self):
        """คำที่ไม่มีคำพ้องช่วย ต้องพึ่งการตัดคำอย่างเดียว — regression guard ตัวจริง"""
        summaries = [{"date": "2026-07-22", "text": "22 ก.ค.: คุยเรื่องแมวที่บ้าน"}]
        got = memory.recall_summaries({"summaries": summaries}, "เคยคุยเรื่องแมวกันไหม")
        assert any("แมว" in s for s in got)

    def test_stopwords_removed(self):
        """คำที่โผล่ในทุกคำถามถึงอดีตต้องถูกตัด ไม่งั้นไปแมตช์ summary ทุกอันเท่าๆ กัน"""
        kws = memory._keywords("เราเคยคุยเรื่องอะไรกันบ้างไหม")
        assert "เคย" not in kws and "คุย" not in kws and "เรื่อง" not in kws

    def test_synonym_expansion_bridges_vocabulary_gap(self):
        """ผู้ใช้ถาม 'การอ่าน' แต่ summary เขียน 'นิยาย/หนังสือ' — ไม่มีคำร่วมกันเลย"""
        kws = memory._keywords("เคยคุยเรื่องการอ่านไหม")
        assert "หนังสือ" in kws or "นิยาย" in kws

    def test_compound_word_still_expands(self):
        """newmm รวมคำประสมเป็น token เดียว ('อ่านหนังสือ') — ต้องยังจับคำพ้องได้

        เจอจริงตอนแก้: เคสนี้พลาดอยู่เคสเดียวจาก 5 เคส จนต้องเช็ค substring เพิ่ม
        """
        kws = memory._keywords("เรื่องเกี่ยวกับการอ่านหนังสือนะพอจำได้ไหม")
        assert "นิยาย" in kws

    @pytest.mark.parametrize("question,expect", [
        ("ว่าแต่รอสเต้เราเคยคุยเรื่องการอ่านอะไรพวกนั้นด้วยไหมก่อนหน้านี้", "นิยาย"),
        ("เรื่องเกี่ยวกับการอ่านหนังสือนะพอจำได้ไหมตอนนั้นคุยอะไรกัน", "นิยาย"),
        ("เราเคยคุยเรื่องของหวานกันไหม", "ของหวาน"),
        ("จำได้ไหมว่าเคยคุยเรื่องน้ำมันอะไรบ้าง", "น้ำมัน"),
        ("เคยคุยเรื่องอากาศกันหรือเปล่า", "อากาศ"),
    ])
    def test_recalls_matching_summary(self, question, expect):
        """5 เคสจริงจาก Discord ที่เดิมพลาดทั้งหมด"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES}, question)
        assert any(expect in s for s in got), f"ไม่เจอ {expect!r} ใน {got}"

    @pytest.mark.parametrize("question", [
        "วันนี้อากาศเป็นไง", "ราคาน้ำมันวันนี้", "สวัสดีค่ะ",
    ])
    def test_does_not_inject_when_not_asking_about_past(self, question):
        """ไม่ได้ถามอดีต → ต้องไม่ inject summary (เปลือง context + ทำโมเดลสับสน)

        สำคัญหลังเพิ่มคำพ้อง: 'อากาศ'/'น้ำมัน' ตรงกับ summary เต็มๆ ถ้าด่าน hint พัง
        จะ inject ทุกข้อความที่พูดถึงหัวข้อพวกนี้
        """
        assert memory.recall_summaries({"summaries": self.SUMMARIES}, question) == []

    def test_tokenizer_failure_falls_back_to_split(self, monkeypatch):
        """pythainlp พังต้องไม่ทำให้ recall ล้มทั้งระบบ — ถอยไป split() แบบเดิม"""
        import pythainlp.tokenize as tk
        monkeypatch.setattr(
            tk, "word_tokenize",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert memory._keywords("อยู่ ชุมพร") != []


class TestParseSingleObjectOutput:
    """รองรับ format:json ที่ทำให้โมเดลคืน object เดี่ยว ไม่ใช่ array

    🚨 ที่มา: qwen3:4b แม่นที่สุดในการสกัด (89%) แต่ช้า 13-30s เพราะ *คิดออกเสียงก่อนเสมอ*
    ไล่หาสาเหตุแล้วพบว่า:
        think:False   -> 4b เขียนการคิดลง content เลย (3,252 ตัวอักษร / 1,022 tokens)
        /no_think     -> ย้ายไปช่อง thinking (2,932 ตัวอักษร) แต่ยังช้าเท่าเดิม
        num_predict   -> ตัดกลางการคิด JSON ไม่เคยออกมา
        **format:json -> บังคับออก JSON ตั้งแต่ token แรก ข้ามการคิดทั้งหมด = 0.8s**

    แต่ constrained decoding ทำให้โมเดลคืน object เดี่ยว `{"category":...,"text":...}`
    ไม่ใช่ array `[{...}]` — parser เดิมหาแค่ `[...]` จึงได้ [] ทั้งที่สกัดถูก

    วัดกับชุด 80 เคส: qwen3:4b + format:json + parser นี้ = 71/80 (89%) แต่งเรื่อง 0%
    latency 0.8s — เท่า gemma3:12b แต่เล็กกว่า 2.5 เท่า (3.2GB vs 8.1GB)
    """

    def test_single_object_is_parsed(self):
        """object เดี่ยวต้อง parse ได้ (format:json คืนแบบนี้)"""
        out = memory.parse_extracted_facts('{"category": "สุขภาพ", "text": "แพ้กุ้ง"}')
        assert out == [{"category": "สุขภาพ", "text": "แพ้กุ้ง"}]

    def test_array_still_works(self):
        """⚠️ regression guard: array แบบเดิมต้องยังใช้ได้ (โมเดลอื่นคืนแบบนี้)"""
        out = memory.parse_extracted_facts(
            '[{"category": "ที่อยู่", "text": "อยู่ชุมพร"},'
            ' {"category": "งาน", "text": "เป็นครู"}]')
        assert len(out) == 2 and out[0]["text"] == "อยู่ชุมพร"

    def test_object_with_prose_around_it(self):
        """โมเดลพูดนำหน้า/ตามหลัง — ต้องดึงเฉพาะ JSON ออกมาได้"""
        out = memory.parse_extracted_facts(
            'นี่คือผลลัพธ์: {"category": "ทักษะ", "text": "พูดญี่ปุ่นได้"} จบแล้วครับ')
        assert out == [{"category": "ทักษะ", "text": "พูดญี่ปุ่นได้"}]

    def test_array_preferred_when_both_present(self):
        """ถ้ามีทั้ง array และ object ต้องเลือก array (ได้ข้อมูลครบกว่า)"""
        out = memory.parse_extracted_facts(
            '[{"category":"ก","text":"หนึ่ง"},{"category":"ข","text":"สอง"}]')
        assert len(out) == 2

    def test_object_without_text_key_ignored(self):
        """object ที่ไม่มี key text = ไม่ใช่ fact ต้องข้าม ไม่ crash"""
        assert memory.parse_extracted_facts('{"foo": "bar"}') == []

    def test_empty_array_still_empty(self):
        assert memory.parse_extracted_facts("[]") == []


class TestOpenSchemaExtraction:
    """หมวด fact เปิดให้โมเดลตั้งชื่อเองได้ — ไม่ใช่ closed set 7 หมวด

    🚨 วัดกับชุดทดสอบ 80 เคส 10 กลุ่มข้อมูล (tools/memory_coverage_fixture.py):
        baseline (closed set)  จำได้ 11/80 = 14%   [8-23%]
        open schema + ตัดด่าน1 จำได้ 45/80 = 56%   [45-67%]   ← ช่วงไม่ซ้อนทับ
    แยกดู: กลุ่มที่ *มีหมวดรองรับ* จำได้ 62% แต่กลุ่มที่ไม่มีหมวด 8% (ต่างกัน 8 เท่า)
    → พิสูจน์ว่าคอขวดคือ closed set ไม่ใช่คุณภาพโมเดล

    ตรงกับงานวิจัย arXiv 2604.11610 (self-evolving schema ชนะ fixed taxonomy) และ
    mem0 ("LLM เป็น filter ที่ดีกว่า pre-computed structure")

    ⚠️ ข้อควรระวัง: SINGLE_VALUE_CATEGORIES (ชื่อ/ที่อยู่/งาน) ยังต้อง supersede ได้
    เหมือนเดิม — เปิด schema แต่ไม่ทิ้งกลไกที่วัดแล้วว่าทำงานดี
    """

    def test_free_form_category_is_kept(self):
        """หมวดที่โมเดลตั้งเอง (นอก 7 หมวดเดิม) ต้องถูกเก็บ ไม่ใช่ทิ้งเป็น None"""
        out = memory.parse_extracted_facts(
            '[{"category":"สุขภาพ","text":"แพ้กุ้ง"},'
            '{"category":"ครอบครัว","text":"มีลูกสาว 2 คน"}]')
        cats = {f["category"] for f in out}
        assert "สุขภาพ" in cats and "ครอบครัว" in cats, f"หมวดอิสระถูกทิ้ง: {out}"

    def test_single_value_categories_still_supersede(self):
        """⚠️ regression guard: ชื่อ/ที่อยู่/งาน ต้องยัง supersede ได้เหมือนเดิม"""
        mem = {"facts": []}
        memory.add_fact(mem, "อยู่ชุมพร", "ที่อยู่")
        memory.add_fact(mem, "ย้ายมาอยู่เชียงใหม่", "ที่อยู่")
        old = [f for f in mem["facts"] if f["text"] == "อยู่ชุมพร"][0]
        assert old["superseded"], "ที่อยู่ต้องยัง supersede ของเก่า"

    def test_free_form_category_does_not_supersede(self):
        """หมวดอิสระต้องสะสมได้ ไม่ลบของเก่าทิ้ง (ปลอดภัยไว้ก่อน)

        เพราะเราไม่รู้ล่วงหน้าว่าหมวดที่โมเดลตั้งเองเป็น single-value หรือ multi-value
        — เดาผิดแล้วลบข้อมูลจริงทิ้งแย่กว่าเก็บซ้ำ
        """
        mem = {"facts": []}
        memory.add_fact(mem, "แพ้กุ้ง", "สุขภาพ")
        memory.add_fact(mem, "แพ้ถั่ว", "สุขภาพ")
        assert all(not f["superseded"] for f in mem["facts"]), \
            "หมวดอิสระไม่ควร supersede กันเอง"
        assert len(mem["facts"]) == 2

    def test_extract_prompt_has_no_closed_list(self):
        """prompt ต้องไม่บังคับเลือกจากลิสต์ปิดอีกต่อไป"""
        p = memory.build_extract_prompt("ผมแพ้กุ้ง")
        assert "เฉพาะหมวดเหล่านี้เท่านั้น" not in p
        assert "ตั้งชื่อเอง" in p or "ตั้งชื่อหมวด" in p

    def test_extract_prompt_mentions_negation(self):
        """baseline วัดได้ว่าปฏิเสธจำไม่ได้เลย 0/12 — prompt ต้องสั่งเรื่องนี้ตรงๆ"""
        p = memory.build_extract_prompt("x")
        assert "ปฏิเสธ" in p

    def test_should_try_extract_no_longer_blocks_by_pronoun(self):
        """ตัดด่านกรองด้วยคำใบ้ทิ้ง — ประโยคไม่มีสรรพนามต้องผ่านได้

        baseline: ประโยคทั่วไปผ่านแค่ 47/80 = 59% (ตกไป 33 เคสโดยไม่ถึงโมเดล)
        """
        for t in ["แพ้กุ้ง", "ขับรถไม่เป็น", "นับถือพุทธ", "ตื่นตี 5 ทุกวัน"]:
            assert memory.should_try_extract(t), f"{t!r} ควรผ่านไปให้โมเดลตัดสิน"

    @pytest.mark.parametrize("text", ["ครับ", "ค่ะ", "555", "?", "อืม"])
    def test_still_skips_trivial_messages(self, text):
        """⚠️ แต่ข้อความสั้น/ไร้เนื้อหา ต้องยังข้าม — ไม่งั้นเปลือง LLM call ทุกข้อความ"""
        assert not memory.should_try_extract(text)


class TestMetaSummaryTagGuard:
    """tag ที่พูดถึง "การสนทนา" เอง ไม่ใช่ข้อเท็จจริงของใคร ต้องไม่ถูกเก็บ

    🚨 บั๊กที่เจอตอนคุยจริง 15 เทิร์น: ผู้ใช้ถาม "เราเคยคุยเรื่องอะไรกันบ้าง"
    รอสเต้ตอบว่า "เคยคุยเรื่องงาน ความชอบเกม และอาหาร" แล้วรอบสรุปถัดมาเก็บว่า

        user_fact:เคยคุยเรื่องงาน ความชอบเกม และอาหาร

    ซึ่งเป็น *คำตอบของรอสเต้เอง* ไม่ใช่ข้อเท็จจริงของผู้ใช้ = attribution error ตอนเขียน
    (ต่างจาก B1 ที่แก้ตอนอ่าน) และจะสะสมทุกครั้งที่ผู้ใช้ถามเรื่องความจำ —
    ความทรงจำจะค่อยๆ เต็มไปด้วย "บันทึกว่าเคยบันทึกอะไร" แทนข้อมูลจริง
    """

    @pytest.mark.parametrize("tag_value", [
        "เคยคุยเรื่องงาน ความชอบเกม และอาหาร",
        "คุยกันเรื่องหนังสือ",
        "พูดคุยเกี่ยวกับการทำงาน",
        "สนทนาเรื่องอาหาร",
        "ถามเรื่องความจำ",
    ])
    def test_meta_conversation_tag_rejected(self, tag_value):
        assert memory.is_meta_summary_tag(tag_value), f"{tag_value!r} ควรถูกกรองทิ้ง"

    @pytest.mark.parametrize("tag_value", [
        "ทำงานเป็นช่างซ่อมแอร์", "ชอบกินส้มตำเผ็ดๆ", "อยู่ขอนแก่น",
        "เบื่อเกมยิงปืน หันมาเล่นเกมปลูกผัก", "ชอบเล่นเกม Valorant",
    ])
    def test_real_facts_kept(self, tag_value):
        """⚠️ regression guard: ข้อเท็จจริงจริงต้องไม่โดนตัด"""
        assert not memory.is_meta_summary_tag(tag_value)

    def test_parse_drops_meta_tag_keeps_others(self):
        """ด่านตรวจตอน parse — ตัดเฉพาะ meta tag ที่เหลือต้องอยู่ครบ"""
        raw = ('{"summary":"คุยเรื่องงาน",'
               '"tags":["user_fact:เคยคุยเรื่องงาน ความชอบเกม",'
               '"user_fact:ทำงานเป็นช่างซ่อมแอร์"]}')
        out = memory.parse_summary_json(raw)
        assert "ทำงานเป็นช่างซ่อมแอร์" in out
        assert "เคยคุยเรื่องงาน" not in out


class TestMiscategorizedFactGuard:
    """fact ที่โมเดลจัดหมวดผิด ต้องไม่ไป supersede ข้อมูลจริงทิ้ง

    🚨 บั๊กที่เจอตอนคุยกับรอสเต้จริง 15 เทิร์น (11 ส.ค. 2569) — เทส 626 ตัวจับไม่ได้เลย:

        ผู้ใช้: "เกมที่ชอบที่สุดคือ Valorant เล่นมา 3 ปีแล้ว"
        โมเดลสกัดได้: [งาน] "เล่นเกมมา 3 ปีแล้ว"   ← จัดหมวดผิด
        ผลลัพธ์: ไป supersede "ทำงานเป็นช่างซ่อมแอร์" ทิ้ง

    "งาน" อยู่ใน SINGLE_VALUE_CATEGORIES (มีค่าจริงได้ค่าเดียว) การเพิ่มค่าใหม่จึงลบค่าเก่า
    ถ้าผู้ใช้ไม่บังเอิญพูดเรื่องอาชีพซ้ำอีก **ข้อมูลอาชีพจริงจะหายถาวร**

    ทำซ้ำได้: "…มา N ปีแล้ว" ทำให้โมเดลเดาว่าเป็นหมวด "งาน" แม้เนื้อหาจะเป็นเรื่องเกม

    ⚠️ แก้ที่ prompt ไม่พอ (MEMORY_EXPERIMENTS §4 เตือนซ้ำ 3 ครั้งแล้ว) — ต้องมี
    validation layer ที่ตรวจว่า "เนื้อหาเข้ากับหมวดที่โมเดลบอกจริงไหม" ก่อนให้ supersede
    """

    @pytest.mark.parametrize("text,claimed", [
        ("เล่นเกมมา 3 ปีแล้ว", "งาน"),
        ("ชอบเล่นเกม Valorant", "งาน"),
        ("อ่านหนังสือมา 5 ปี", "งาน"),
    ])
    def test_game_hobby_not_accepted_as_job(self, text, claimed):
        """เนื้อหาเรื่องเกม/งานอดิเรก ห้ามรับเป็นหมวด "งาน" """
        assert not memory.category_matches_text(claimed, text), \
            f"{text!r} ไม่ควรผ่านเป็นหมวด {claimed!r}"

    @pytest.mark.parametrize("text", [
        "ทำงานเป็นช่างซ่อมแอร์", "เป็นโปรแกรมเมอร์", "ทำงานสายไอที",
        "อาชีพครู", "ทำงานที่โรงพยาบาล",
    ])
    def test_real_job_still_accepted(self, text):
        """⚠️ regression guard: อาชีพจริงต้องยังผ่านได้ (อย่าเหวี่ยงตัด)"""
        assert memory.category_matches_text("งาน", text)

    @pytest.mark.parametrize("text", ["อยู่ขอนแก่น", "ย้ายมาอยู่เชียงใหม่", "บ้านอยู่ภูเก็ต"])
    def test_real_address_still_accepted(self, text):
        assert memory.category_matches_text("ที่อยู่", text)

    def test_multi_value_category_never_blocked(self):
        """หมวด multi-value ไม่ supersede อะไรอยู่แล้ว → ไม่ต้องตรวจ ปล่อยผ่านหมด

        กันไม่ให้ guard นี้ไปตัดข้อมูลที่ไม่มีความเสี่ยง
        """
        assert memory.category_matches_text("ความชอบ", "เล่นเกมมา 3 ปีแล้ว")
        assert memory.category_matches_text("ของที่มี", "อะไรก็ได้")

    def test_add_fact_downgrades_instead_of_dropping(self):
        """fact ที่หมวดไม่ตรง ต้อง *ไม่หาย* — เก็บต่อแบบไม่มีหมวด (ไม่ supersede ใคร)

        ทิ้งข้อมูลผู้ใช้ไปเลยแย่กว่าเก็บไว้แบบไม่มีหมวด
        """
        mem = {"facts": []}
        memory.add_fact(mem, "ทำงานเป็นช่างซ่อมแอร์", "งาน")
        memory.add_fact(mem, "เล่นเกมมา 3 ปีแล้ว", "งาน")   # หมวดผิด

        job = [f for f in mem["facts"] if f["text"] == "ทำงานเป็นช่างซ่อมแอร์"][0]
        assert not job["superseded"], "อาชีพจริงต้องไม่ถูกลบด้วย fact ที่จัดหมวดผิด"
        game = [f for f in mem["facts"] if f["text"] == "เล่นเกมมา 3 ปีแล้ว"][0]
        assert game["category"] is None, "fact ที่หมวดไม่ตรงต้องถูกลดเป็นไม่มีหมวด"

    def test_genuine_job_change_still_supersedes(self):
        """⚠️ สำคัญ: เปลี่ยนงานจริงต้องยัง supersede ได้เหมือนเดิม"""
        mem = {"facts": []}
        memory.add_fact(mem, "ทำงานเป็นช่างซ่อมแอร์", "งาน")
        memory.add_fact(mem, "เป็นโปรแกรมเมอร์", "งาน")
        old = [f for f in mem["facts"] if f["text"] == "ทำงานเป็นช่างซ่อมแอร์"][0]
        assert old["superseded"], "เปลี่ยนอาชีพจริงต้อง supersede ของเก่า"


class TestTagDeduplication:
    """tag ที่ผู้ใช้พูดซ้ำไม่ควรกลายเป็นหลาย record (กรอบ LTM ข้อ 2: Deduplication)

    วัดกับความจำจริง (หลังกันของลอกจาก prompt แล้ว): tag ซ้ำ 31/144 = 22%
        4x user_pref:ต้องการคำพูดเป็นทางการ
        4x me_fact:แนะนำวิธีจัดการงาน
        3x user_fact:ทำงานหนัก
    เปลืองโควตา context (attention cliff ~3,700c) และทำให้ recall คืนของซ้ำๆ

    ต้นเหตุ: chat.py เขียน summary ด้วย `summaries.append(entry)` ตรงๆ
    ไม่เคยเทียบกับของเดิมเลย — ต่างจาก facts ที่มี add_fact() กันซ้ำอยู่แล้ว

    ⚠️ ระวัง: ห้ามลบ summary ทั้งบรรทัดเพราะ tag ซ้ำบางตัว — บรรทัดเดียวมีหลาย tag
    และหัวเรื่องต่างกัน (เป็นคนละบทสนทนา) จึงกันซ้ำ *ระดับ tag* ไม่ใช่ระดับบรรทัด
    """

    def test_exact_duplicate_tag_removed_from_new_summary(self):
        """tag ที่มีอยู่แล้วในความจำ ไม่ต้องเก็บซ้ำในบรรทัดใหม่"""
        old = ["6 ส.ค.: คุยเรื่องงาน | user_fact:ทำงานหนัก me_fact:แนะนำวิธีจัดการงาน"]
        new = "7 ส.ค.: คุยเรื่องงานอีกครั้ง | user_fact:ทำงานหนัก user_pref:ชอบทำงานดึก"
        out = memory.dedupe_tags_against(new, old)
        assert "ชอบทำงานดึก" in out, "tag ใหม่ต้องอยู่"
        assert "ทำงานหนัก" not in out, "tag ที่ซ้ำของเดิมต้องถูกตัด"

    def test_keeps_summary_when_all_tags_duplicate(self):
        """ถ้า tag ซ้ำหมด ยังต้องเก็บบรรทัดไว้ (หัวเรื่องยังมีค่า เป็นคนละบทสนทนา)"""
        old = ["6 ส.ค.: คุยเรื่องงาน | user_fact:ทำงานหนัก"]
        new = "7 ส.ค.: คุยเรื่องงานอีกครั้ง | user_fact:ทำงานหนัก"
        out = memory.dedupe_tags_against(new, old)
        assert out.startswith("7 ส.ค.: คุยเรื่องงานอีกครั้ง")

    def test_same_value_different_kind_is_not_duplicate(self):
        """user_pref:อ่านหนังสือ กับ me_pref:อ่านหนังสือ = คนละคน ไม่ใช่ของซ้ำ"""
        old = ["6 ส.ค.: คุย | user_pref:ชอบอ่านหนังสือ"]
        new = "7 ส.ค.: คุย | me_pref:ชอบอ่านหนังสือ"
        out = memory.dedupe_tags_against(new, old)
        assert "ชอบอ่านหนังสือ" in out, "ฝั่งรอสเต้ยังไม่เคยเก็บ ต้องไม่ถูกตัด"

    def test_no_old_summaries_keeps_everything(self):
        """ความจำว่าง → ไม่ต้องตัดอะไร"""
        new = "7 ส.ค.: คุยเรื่องงาน | user_fact:ทำงานหนัก"
        assert memory.dedupe_tags_against(new, []) == new

    def test_summary_without_tags_passes_through(self):
        """summary แบบเก่าที่ไม่มี tag ต้องไม่พัง"""
        new = "7 ส.ค.: คุยเรื่องงาน"
        assert memory.dedupe_tags_against(new, ["6 ส.ค.: อะไรสักอย่าง"]) == new


class TestProvenanceFactVsPref:
    """แยก "สิ่งที่รอสเต้ทำให้" (fact) ออกจาก "สิ่งที่รอสเต้เป็น" (pref)

    🚨 attribution error ที่วัดได้กับความจำจริง (11 ส.ค. 2569):
    ถาม "รอสเต้ชอบอะไร" (ถามความชอบ) แล้วได้ "แนะนำร้านให้" ปนมาด้วยทุกครั้ง
    ทั้งที่นั่นคือ *สิ่งที่รอสเต้ทำให้ผู้ใช้* ไม่ใช่ *ความชอบของรอสเต้*

    ต้นเหตุ: split_owner_tags ทิ้งความต่างระหว่าง pref/fact ทั้งหมด เหลือแค่ user/me
    แล้ว filter_by_owner ยัดรวมกันเป็น "รอสเต้: แนะนำร้านให้, ชอบหนังสือเก่า"
    โมเดลจึงแยกไม่ออกว่าอันไหนคือความชอบ อันไหนคือการกระทำ

    ตรงกับ "attribution error" ในกรอบ LTM ข้อ 7 — สับสนระหว่างสิ่งที่ผู้ใช้พูด
    กับสิ่งที่โมเดลเคยเสนอ (ที่นี่คือสับสนระหว่างสิ่งที่รอสเต้เป็น กับสิ่งที่รอสเต้ทำ)
    """

    SUMMARIES = [
        {"date": "2026-08-06",
         "text": "6 ส.ค.: คุยเรื่องหนังสือ | me_pref:ชอบหนังสือเก่า me_fact:แนะนำร้านหนังสือให้"},
        {"date": "2026-08-07",
         "text": "7 ส.ค.: คุยเรื่องงาน | me_fact:แนะนำวิธีจัดการงาน user_fact:ทำงานหนัก"},
    ]

    def test_split_keeps_pref_and_fact_separate(self):
        """split_owner_tags ต้องเก็บความต่าง pref/fact ไว้ ไม่ใช่ยุบรวม"""
        parts = memory.split_owner_tags(self.SUMMARIES[0]["text"])
        assert parts["me_pref"] == ["ชอบหนังสือเก่า"]
        assert parts["me_fact"] == ["แนะนำร้านหนังสือให้"]

    def test_backward_compatible_me_key_still_works(self):
        """⚠️ ของเดิมต้องไม่พัง — key 'me'/'user' ยังต้องคืนทุกอันรวมกันเหมือนเดิม

        มีที่เรียกใช้อยู่หลายจุด (filter_by_owner, recall_summaries, conflict_proto)
        """
        parts = memory.split_owner_tags(self.SUMMARIES[0]["text"])
        assert set(parts["me"]) == {"ชอบหนังสือเก่า", "แนะนำร้านหนังสือให้"}

    def test_preference_question_excludes_actions(self):
        """ถาม "ชอบอะไร" ต้องไม่ได้ "แนะนำร้านให้" (สิ่งที่ทำ) ปนมา"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES}, "รอสเต้ชอบอะไร")
        blob = "\n".join(got)
        assert "ชอบหนังสือเก่า" in blob, "ความชอบจริงต้องยังอยู่"
        assert "แนะนำร้าน" not in blob, "สิ่งที่รอสเต้ *ทำ* ไม่ควรตอบคำถามว่า *ชอบ* อะไร"

    def test_action_question_still_gets_actions(self):
        """แต่ถามว่า "ทำอะไรให้" ต้องได้ me_fact ตามปกติ"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES},
                                      "รอสเต้เคยแนะนำอะไรให้ผมบ้าง")
        assert any("แนะนำ" in s for s in got)

    def test_user_side_unaffected(self):
        """ฝั่งผู้ใช้ต้องทำงานเหมือนเดิม (ไม่ได้แก้ฝั่งนี้)"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES}, "ผมทำงานอะไร")
        assert any("ทำงานหนัก" in s for s in got)


class TestSummaryPromptExampleLeak:
    """ตัวอย่างใน build_summary_prompt ต้องไม่ถูกโมเดลลอกมาเป็นความทรงจำจริง

    🚨 วัดกับความจำจริง (11 ส.ค. 2569) — โมเดลลอกตัวอย่างใน prompt มาใส่ tag:
        "me_fact:แนะนำร้านให้"    โผล่ 17/55 ครั้ง  ← ตัวอย่างใน prompt เป๊ะๆ
        "me_pref:ชอบหนังสือเก่า"  โผล่ 14/55 ครั้ง  ← ตัวอย่างใน prompt เป๊ะๆ
        "user_pref:ชอบนิยายสืบสวน" โผล่ 0 ครั้ง     ← ตัวอย่างฝั่ง user ไม่หลุด
        "user_fact:กินเผ็ดไม่ได้"  โผล่ 0 ครั้ง

    ทำไมหลุดเฉพาะฝั่ง me: กฎในprompt บอกว่า "รอสเต้จำความชอบของตัวเองได้ ให้ใส่ me_pref:"
    ซึ่งกดดันให้โมเดล *ต้องหา* อะไรมาใส่ฝั่ง me ทุกครั้ง พอในบทไม่มีจริงก็ลอกตัวอย่างมาแทน
    วัดได้: tag ฝั่งรอสเต้ว่าง 0/55 (ต้องมีเสมอ) แต่ฝั่งผู้ใช้ว่าง 17/55 (31%)

    เป็นบั๊กตระกูลเดียวกับที่ persona.py:92-97 บันทึกไว้ — few-shot ที่มีข้อมูลปลอม
    ทำให้โมเดลลอกข้อมูลนั้นแทนที่จะใช้ของจริง
    """

    def test_prompt_examples_are_marked_as_placeholders(self):
        """ตัวอย่างใน prompt ต้องดูออกชัดว่าเป็นตัวอย่าง ไม่ใช่ข้อมูลจริงที่ลอกได้

        แก้โดยเปลี่ยนตัวอย่างให้เป็น placeholder แบบ <...> ซึ่งลอกมาใส่ตรงๆ ไม่ได้
        """
        prompt = memory.build_summary_prompt([
            {"role": "user", "content": "สวัสดี"},
            {"role": "assistant", "content": "สวัสดีค่ะ"},
        ])
        leaked = [s for s in ("ชอบหนังสือเก่า", "แนะนำร้านให้") if s in prompt]
        assert not leaked, (
            f"prompt ยังมีตัวอย่างที่ลอกได้: {leaked} — วัดแล้วโมเดลลอกไปใช้จริง 17/55 ครั้ง")

    def test_prompt_does_not_force_me_tags(self):
        """ต้องไม่มีกฎที่กดดันให้ใส่ tag ฝั่งรอสเต้ทุกครั้ง

        กฎเดิม "รอสเต้จำความชอบของตัวเองได้ ให้ใส่ me_pref:" ทำให้โมเดลเติมมั่วเมื่อไม่มีของจริง
        (ฝั่ง me ว่าง 0/55 = ไม่เคยว่างเลย ซึ่งผิดธรรมชาติ)
        """
        prompt = memory.build_summary_prompt([{"role": "user", "content": "x"}])
        assert "ถ้าไม่มีอย่าใส่" in prompt or "เท่าที่มีจริง" in prompt

    def test_parse_rejects_known_placeholder_leak(self):
        """ด่านสุดท้าย: ถ้าโมเดลยังลอกตัวอย่างมา ต้องกรองทิ้งตอน parse

        MEMORY_EXPERIMENTS §4: "prompt แก้พฤติกรรมโมเดลไม่ได้ ต้องมี validation layer"
        — แก้ prompt อย่างเดียวไม่พอ ต้องมีด่านตรวจด้วย
        """
        raw = ('{"summary":"คุยเรื่องหนังสือ",'
               '"tags":["me_fact:แนะนำร้านให้","user_pref:ชอบอ่านนิยาย"]}')
        out = memory.parse_summary_json(raw)
        assert "แนะนำร้านให้" not in out, "tag ที่ลอกจากตัวอย่างต้องถูกกรองทิ้ง"
        assert "ชอบอ่านนิยาย" in out, "tag จริงต้องยังอยู่"


class TestSubstringFalseMatches:
    """ภาษาไทยเขียนติดกัน — การเทียบ *สตริงย่อย* จับคำที่ไม่ได้ตั้งใจ

    บทเรียนเดียวกับ _looks_like_hair ใน persona.py: "ผม" (สรรพนาม) vs "สระผม" (เส้นผม)
    แก้ไม่ได้ด้วย blacklist เพราะคำที่เป็นไปได้มีไม่จำกัด — ต้อง *ตัดคำ* แล้วเทียบทั้งโทเคน

    เจอ 2 จุดในระบบความจำ (11 ส.ค. 2569) วัดกับความจำจริงของผู้ใช้:
      A2  "หน้าร้อน" มี "ร้อน" ∈ _LIVE_DATA_SIGNALS → ถูกตัดทิ้งเป็นคำถามข้อมูลสด
          ทั้งที่คะแนนจริง = 2 (หยิบได้) — กระทบ 4/8 เคสที่ oracle พลาด
      A3  "ขอบคุณ" มี "คุณ" → ไปแมตช์เนื้อความ summary แล้ว inject มั่ว 5 อัน
          (ยืนยันด้วย git stash ว่ามีก่อนงานนี้ ไม่ใช่ของใหม่)
    """

    SUMMARIES = [
        {"date": "2026-06-11", "text": "11 มิ.ย.: คุยเรื่องหน้าร้อน | user_pref:หน้าร้อนชอบไปทะเล"},
        {"date": "2026-06-12", "text": "12 มิ.ย.: คุยเรื่องหน้าหนาว | user_pref:หน้าหนาวชอบไปภูเขา"},
        {"date": "2026-06-13", "text": "13 มิ.ย.: คุยเรื่องหนังสือ | user_pref:ชอบอ่านนิยาย"},
    ]

    # ── A2: live-data gate ต้องไม่ตัดคำถามความจำที่บังเอิญมีสตริงย่อยตรงกัน ──
    @pytest.mark.parametrize("question,expect", [
        ("หน้าร้อนผมชอบไปเที่ยวไหน", "ทะเล"),
        ("หน้าหนาวผมชอบไปไหน", "ภูเขา"),
    ])
    def test_season_question_is_not_treated_as_weather(self, question, expect):
        """"หน้าร้อน"/"หน้าหนาว" = ฤดู ไม่ใช่คำถามสภาพอากาศวันนี้"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES}, question)
        assert any(expect in s for s in got), f"{question!r} คืน {got}"

    @pytest.mark.parametrize("question", [
        "วันนี้อากาศเป็นไง", "พรุ่งนี้ฝนตกไหม", "ตอนนี้ร้อนไหม", "อากาศหนาวหรือยัง",
    ])
    def test_real_weather_questions_still_blocked(self, question):
        """⚠️ regression guard: คำถามอากาศจริงต้องยังถูกกันเหมือนเดิม

        MEMORY_EXPERIMENTS §6 บันทึกว่าเคยลบ gate ทิ้งแล้ว inject มั่ว 3/9 — ห้ามซ้ำรอย
        """
        assert memory.recall_summaries({"summaries": self.SUMMARIES}, question) == []

    def test_weather_word_with_past_hint_still_recalls(self):
        """มีคำใบ้อดีตชัดเจน → คำใบ้อดีตต้องชนะสัญญาณข้อมูลสด (พฤติกรรมเดิม ห้ามพัง)"""
        summaries = [{"date": "2026-07-21", "text": "21 ก.ค.: คุยเรื่องอากาศ | user_fact:ไม่ชอบอากาศร้อน"}]
        got = memory.recall_summaries({"summaries": summaries}, "จำได้ไหมว่าเคยคุยเรื่องอากาศ")
        assert got

    # ── A3: คำทักทาย/ขอบคุณ ไม่ใช่คำถาม ต้องไม่ trigger การดึงความทรงจำ ──
    #
    # ⚠️ แก้ความเข้าใจผิดของผมเอง: ตอนแรกวินิจฉัยว่าเป็นบั๊ก substring ("ขอบคุณ" มี "คุณ")
    #    ตรวจจริงแล้ว _keywords("ขอบคุณนะ") = ['ขอบคุณ'] เป็นโทเคนเต็ม ไม่ใช่ substring
    #    ที่มันแมตช์เพราะ summary จริงของผู้ใช้ *มีคำว่า "ขอบคุณ" อยู่จริง*
    #    (ผู้ใช้เคยคุยเรื่องการเขียนคำกล่าวขอบคุณ) — retrieval ทำงานถูกต้องทุกประการ
    #
    #    ปัญหาจริงคือ: "ขอบคุณนะ" เป็น *คำทักทายทางสังคม* ไม่ใช่คำถาม จึงไม่ควรดึงความจำ
    #    ตั้งแต่แรก — เป็นเรื่อง intrusiveness (กรอบ LTM ข้อ 7) ไม่ใช่เรื่องการจับคู่คำ
    SOCIAL_SUMMARIES = [
        {"date": "2026-08-06", "text": "6 ส.ค.: คุยเรื่องคำกล่าวขอบคุณ | user_pref:ต้องการคำพูดเป็นทางการ"},
        {"date": "2026-08-07", "text": "7 ส.ค.: คุยเรื่องสวัสดีทักทาย | me_fact:แนะนำคำทักทาย"},
    ]

    @pytest.mark.parametrize("question", [
        "ขอบคุณนะ", "ขอบคุณมากค่ะ", "สวัสดีครับ", "โอเคครับ", "เยี่ยมเลย",
    ])
    def test_social_pleasantry_does_not_inject_memory(self, question):
        """คำขอบคุณ/ทักทาย ไม่ใช่คำถาม — ยัดความจำใส่ทำให้ UX แย่กว่าไม่มี memory

        วัดกับความจำจริง: "ขอบคุณนะ" ดึงมา 5 อัน เพราะผู้ใช้เคยคุยเรื่องคำกล่าวขอบคุณจริง
        """
        got = memory.recall_summaries({"summaries": self.SOCIAL_SUMMARIES}, question)
        assert got == [], f"{question!r} inject {len(got)} อัน"

    def test_real_question_about_thanks_still_works(self):
        """แต่ถ้าถามเรื่องคำขอบคุณจริงๆ ต้องยังดึงได้ (อย่าเหวี่ยงตัดทั้งคำ)"""
        got = memory.recall_summaries({"summaries": self.SOCIAL_SUMMARIES},
                                      "จำได้ไหมว่าเคยคุยเรื่องคำกล่าวขอบคุณ")
        assert got


class TestBroadRecallQuestions:
    """คำถามทบทวนความจำแบบกว้าง — ไม่ระบุหัวข้อ แต่ขอให้เล่าว่าเคยคุยอะไรกันบ้าง

    ⚠️ บั๊ก production ที่เจอตอนวัดกับความจำจริง (11 ส.ค. 2569):
        "เราเคยคุยเรื่องอะไรกันบ้าง" → _keywords() คืน [] → recall คืน 0 อัน
        ทั้งที่ผู้ใช้คนนั้นมี summary อยู่ 55 อัน

    ต้นเหตุ: ทุกคำในประโยค (เรา/เคย/คุย/เรื่อง/อะไร/บ้าง) อยู่ใน _STOPWORDS ซึ่ง *ถูกต้อง*
    สำหรับการให้คะแนน (คำพวกนี้แมตช์ทุก summary เท่าๆ กัน จึงไม่ช่วยจัดอันดับ) แต่พอไม่เหลือ
    keyword เลย เงื่อนไข `score > 0` ก็เป็นจริงไม่ได้ → คืน [] เสมอ

    วัดแล้ว 4 ใน 8 สำนวนที่คนใช้จริงเจอปัญหานี้ ที่บอทยังดูไม่พังเพราะ vector ครอบให้อยู่
    """

    SUMMARIES = [
        {"date": "2026-08-06", "text": "6 ส.ค.: คุยเรื่องการอ่านหนังสือ | user_pref:สนใจหนังสือเก่า"},
        {"date": "2026-08-07", "text": "7 ส.ค.: คุยเรื่องงานที่ทำ | user_fact:ทำงานหนัก"},
        {"date": "2026-08-08", "text": "8 ส.ค.: คุยเรื่องอาหารเย็น | user_pref:ชอบต้มยำ"},
    ]

    @pytest.mark.parametrize("question", [
        "เราเคยคุยเรื่องอะไรกันบ้าง",
        "เคยคุยอะไรกันบ้าง",
        "เราคุยเรื่องอะไรกัน",
        "มีอะไรที่เราคุยกันบ้าง",
    ])
    def test_broad_recall_returns_something(self, question):
        """ถามกว้างว่าเคยคุยอะไรกันบ้าง ต้องได้ summary กลับมา ไม่ใช่ []"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES}, question)
        assert got, f"{question!r} คืน [] ทั้งที่มี summary อยู่ {len(self.SUMMARIES)} อัน"

    def test_broad_recall_returns_most_recent_first(self):
        """ไม่มี keyword ให้จัดอันดับ → เรียงตามใหม่สุดก่อน (ของล่าสุดเกี่ยวข้องที่สุด)"""
        got = memory.recall_summaries({"summaries": self.SUMMARIES},
                                      "เราเคยคุยเรื่องอะไรกันบ้าง")
        assert "อาหารเย็น" in got[0], f"ควรได้ของใหม่สุดก่อน แต่ได้ {got[0]!r}"

    def test_broad_recall_still_respects_owner_filter(self):
        """ถามกว้างแต่เจาะจงฝั่ง ต้องยังกรองเจ้าของ (กันของอีกฝั่งปน)"""
        summaries = [
            {"date": "2026-08-06", "text": "6 ส.ค.: คุยเรื่องหนังสือ | user_pref:ชอบสืบสวน"},
            {"date": "2026-08-07", "text": "7 ส.ค.: คุยเรื่องเพลง | me_pref:ชอบคลาสสิก"},
        ]
        got = memory.recall_summaries({"summaries": summaries}, "รอสเต้เคยคุยอะไรกับผมบ้าง")
        assert got and all("สืบสวน" not in s for s in got)

    @pytest.mark.parametrize("question", [
        "วันนี้อากาศเป็นไง", "ราคาน้ำมันวันนี้", "สวัสดีค่ะ", "ขอบคุณนะ",
    ])
    def test_still_silent_when_not_asking_about_past(self, question):
        """⚠️ regression guard: การแก้บั๊กนี้ต้องไม่ทำให้ inject มั่วในคำถามทั่วไป

        เดิมเคยพลาดทางนี้มาแล้ว (MEMORY_EXPERIMENTS §6: ลบ PAST_HINTS gate ทิ้งเลย
        ทำให้ inject มั่ว 3/9 ในคำถามข้อมูลสด) — ต้องคืน [] เหมือนเดิม
        """
        assert memory.recall_summaries({"summaries": self.SUMMARIES}, question) == []

    def test_broad_recall_hint_does_not_fire_on_thanks(self):
        """"ขอบคุณนะ" ต้องไม่ตรง _BROAD_RECALL_HINTS

        ⚠️ หมายเหตุ: คำถามนี้ยัง inject อยู่ด้วยเหตุผล *อื่น* — token "ขอบคุณ" มีสตริงย่อย
        "คุณ" ซึ่งไปแมตช์เนื้อความ summary ผ่านการให้คะแนนปกติ (เทียบแบบ substring)
        เป็นบั๊กคนละตัวที่ *มีอยู่ก่อนแล้ว* (ยืนยันด้วย git stash: โค้ดเดิมก็คืน 5 อัน)
        และเป็นบั๊กตระกูลเดียวกับ _looks_like_hair ใน persona.py — ภาษาไทยเขียนติดกัน
        การเทียบ substring จึงจับคำที่ไม่ได้ตั้งใจ

        เทสนี้ล็อกเฉพาะส่วนที่งานนี้เพิ่ม (hint list) ไม่ให้เป็นต้นเหตุซ้ำอีกทาง
        """
        assert not memory.wants_broad_recall("ขอบคุณนะ")
        assert not memory.wants_broad_recall("ขอบคุณมากค่ะ")

    def test_empty_keywords_without_recall_intent_stays_silent(self):
        """keyword ว่าง *และ* ไม่มีสัญญาณทบทวนความจำ → ต้องไม่ inject

        กันการแก้แบบเหวี่ยง "ถ้า keyword ว่างก็คืนทุกอัน" ซึ่งจะ inject ทุกข้อความสั้นๆ
        """
        assert memory._keywords("ค่ะ") == []
        assert memory.recall_summaries({"summaries": self.SUMMARIES}, "ค่ะ") == []


# ── แยกความทรงจำตามเจ้าของ (วิธี F + P3) ──────────────────────────────────────

class TestOwnerSeparatedMemory:
    """summary เก็บ tag บอกว่าเรื่องไหนของใคร แล้ว recall กรองเหลือเฉพาะฝั่งที่ถูกถาม

    ทำไมสำคัญ: วัดได้ว่าการยัด summary ทั้งบรรทัด (มีทั้ง user_pref และ me_pref) ทำให้
    โมเดลจำสลับเจ้าของ 29% — รอสเต้เชื่อว่าผู้ใช้ชอบสิ่งที่ตัวเองชอบ ซึ่งแย่กว่าจำไม่ได้
    พอกรองฝั่งก่อนส่ง เหลือ 0% (ดู docs/MEMORY_EXPERIMENTS.md)
    """

    SUMMARIES = [
        {"date": "2026-08-01",
         "text": "1 ส.ค.: คุยแนวนิยาย | user_pref:ชอบนิยายสืบสวน me_pref:ชอบแนวแฟนตาซี"},
        {"date": "2026-07-31",
         "text": "31 ก.ค.: คุยเรื่องอาหาร | user_fact:กินเผ็ดไม่ได้ me_pref:ไม่ชอบของหวาน"},
        {"date": "2026-07-30",
         "text": "30 ก.ค.: คุยเรื่องที่ทำงาน | user_fact:ทำงานสายไอที"},
    ]

    # ── split_owner_tags ──
    def test_splits_tags_by_owner(self):
        parts = memory.split_owner_tags(
            "คุยแนวนิยาย | user_pref:ชอบสืบสวน me_pref:ชอบแฟนตาซี")
        assert parts["summary"] == "คุยแนวนิยาย"
        assert parts["user"] == ["ชอบสืบสวน"]
        assert parts["me"] == ["ชอบแฟนตาซี"]

    def test_old_format_without_tags(self):
        """summary แบบเก่าไม่มี tag — ต้องไม่ crash และคืน user/me ว่าง"""
        parts = memory.split_owner_tags("23 ก.ค.: คุยเรื่องเจลาโต้")
        assert parts["summary"] == "23 ก.ค.: คุยเรื่องเจลาโต้"
        assert parts["user"] == [] and parts["me"] == []

    # ── guess_owner ──
    @pytest.mark.parametrize("question,expect", [
        ("จำได้ไหมว่าผมชอบอ่านนิยายแนวไหน", "user"),
        ("รอสเต้ชอบอ่านแนวไหนเหรอ", "me"),
        ("ผมทำอาชีพอะไร", "user"),
        ("รอสเต้ทำงานอะไร", "me"),
        ("เราสองคนชอบกินอะไรต่างกัน", "any"),
        ("เคยคุยอะไรกันบ้าง", "any"),
    ])
    def test_guess_owner(self, question, expect):
        assert memory.guess_owner(question) == expect

    def test_guess_owner_matches_subject_not_verb(self):
        """จับที่ประธานอย่างเดียว ไม่จับคู่กับกริยา

        รุ่นแรกจับ '<ประธาน> + <กริยา>' แล้วพังทันทีที่เจอกริยานอกลิสต์ ('ทำงาน'/'อ่าน')
        การไล่เติมกริยาเป็น whack-a-mole — กริยาไม่มีวันครบ ประธานนับได้
        """
        for q in ("ผมอ่านหนังสือแนวไหน", "ผมทำอาชีพอะไร", "ผมเลี้ยงสัตว์อะไร"):
            assert memory.guess_owner(q) == "user", q
        for q in ("รอสเต้ทำงานอะไร", "รอสเต้ประดิษฐ์อะไร", "รอสเต้ดื่มอะไร"):
            assert memory.guess_owner(q) == "me", q

    def test_ask_both_beats_single_side(self):
        """ถามเทียบสองฝ่ายต้องได้ทั้งคู่ ไม่ใช่ตัดฝั่งใดทิ้ง"""
        assert memory.guess_owner("เราสองคนชอบกินอะไรต่างกันบ้าง") == "any"

    # ── filter_by_owner ──
    def test_filter_keeps_only_asked_side(self):
        got = memory.filter_by_owner(
            [s["text"] for s in self.SUMMARIES], "user")
        joined = " ".join(got)
        assert "สืบสวน" in joined
        assert "แฟนตาซี" not in joined, "ของรอสเต้ต้องไม่ปนมาตอนถามเรื่องผู้ใช้"

    def test_filter_drops_lines_without_that_side(self):
        """บรรทัดที่ไม่มีฝั่งที่ถามต้องถูกตัด — ตอบว่าจำไม่ได้ดีกว่าเอาของอีกฝั่งมาตอบ"""
        got = memory.filter_by_owner(
            ["30 ก.ค.: คุยเรื่องที่ทำงาน | user_fact:ทำงานสายไอที"], "me")
        assert got == []

    def test_filter_any_returns_all(self):
        texts = [s["text"] for s in self.SUMMARIES]
        assert memory.filter_by_owner(texts, "any") == texts

    # ── recall_summaries แบบครบวงจร ──
    @pytest.mark.parametrize("question,must,forbid", [
        ("จำได้ไหมว่าผมชอบอ่านนิยายแนวไหน", "สืบสวน", "แฟนตาซี"),
        ("รอสเต้ชอบอ่านแนวไหนเหรอ จำได้ไหม", "แฟนตาซี", "สืบสวน"),
        ("ผมกินเผ็ดได้ไหม", "เผ็ด", "หวาน"),
        ("รอสเต้ไม่ชอบกินอะไร", "หวาน", "เผ็ด"),
    ])
    def test_recall_does_not_swap_owner(self, question, must, forbid):
        got = " ".join(memory.recall_summaries({"summaries": self.SUMMARIES}, question))
        assert must in got, f"ไม่เจอ {must!r} ใน {got!r}"
        assert forbid not in got, f"ของอีกฝั่ง ({forbid!r}) ปนมาใน {got!r}"

    def test_recall_without_past_hint_still_works(self):
        """คำถามที่ไม่มีคำใบ้อดีต ('ผมชอบอ่านอะไร') ต้องยังค้นได้

        ด่านเดิมเช็ค PAST_HINTS ก่อน ทำให้คำถามแบบนี้คืน [] ทันทีทั้งที่ข้อมูลอยู่ครบ
        """
        got = memory.recall_summaries({"summaries": self.SUMMARIES}, "ผมชอบอ่านอะไร")
        assert any("สืบสวน" in s for s in got)

    @pytest.mark.parametrize("question", [
        "วันนี้อากาศเป็นไง", "ราคาน้ำมันวันนี้", "พรุ่งนี้ฝนตกไหม", "ตอนนี้กี่โมง",
    ])
    def test_live_data_questions_do_not_inject(self, question):
        """คำถามข้อมูลสดต้องไม่ดึง summary มาเปลือง context

        เอาด่าน PAST_HINTS ออกแล้วต้องมีอะไรกันแทน ไม่งั้น inject ทุกครั้งที่พูดถึง
        หัวข้อที่เคยคุย (ขนาดใน context มีราคาจริง: >3,700c ทำให้โมเดลลืม summary)
        """
        assert memory.recall_summaries({"summaries": self.SUMMARIES}, question) == []

    def test_past_hint_beats_live_signal(self):
        """'เมื่อวานคุยเรื่องอากาศไหม' = ถามบทสนทนาเก่า ไม่ใช่ถามพยากรณ์"""
        mem = {"summaries": [{"date": "x", "text": "1 ส.ค.: คุยเรื่องอากาศ | user_pref:ชอบหน้าหนาว"}]}
        assert memory.recall_summaries(mem, "เคยคุยเรื่องอากาศกันไหม") != []

    def test_old_summaries_still_recalled(self):
        """⚠️ ทางถอย: ถ้าไม่มี summary ไหนมี tag เลย ต้องไม่กรองจนหายหมด

        ผู้ใช้ที่มีความจำแบบเก่าอยู่จะเจอบอทลืมทุกอย่างทันทีที่ deploy ถ้าไม่มีข้อนี้
        (เจอจริงตอนรันเทสเดิม: คำถามที่มีคำว่า 'รอสเต้' ถูกเดาเป็น me แล้วกรองทิ้งหมด)
        """
        old = [{"date": "2026-07-22", "text": "22 ก.ค.: คุยเรื่องนิยายและหนังสือลึกลับ"}]
        got = memory.recall_summaries({"summaries": old}, "รอสเต้จำได้ไหมว่าคุยเรื่องนิยาย")
        assert got != [], "summary แบบเก่าต้องยังถูก recall ได้"

    # ── parse_summary_json ──
    def test_parse_json_with_tags(self):
        out = memory.parse_summary_json(
            '{"summary": "คุยแนวนิยาย", "tags": ["user_pref:ชอบสืบสวน"]}')
        assert out == "คุยแนวนิยาย | user_pref:ชอบสืบสวน"

    def test_parse_json_ignores_surrounding_text(self):
        """qwen3:8b ชอบพูดนำหน้า/ตามหลัง JSON — ต้องตัดเอาเฉพาะช่วง {...}"""
        out = memory.parse_summary_json(
            'นี่คือสรุปครับ {"summary": "ก", "tags": []} หวังว่าจะช่วยได้')
        assert out == "ก"

    def test_parse_non_json_returns_empty(self):
        """parse ไม่ได้ = ทิ้งรอบนั้น ไม่เก็บข้อความดิบที่กรองฝั่งไม่ได้"""
        assert memory.parse_summary_json("สรุปเป็นข้อความธรรมดา") == ""
        assert memory.parse_summary_json("") == ""
