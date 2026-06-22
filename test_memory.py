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

    def test_instruction_asks_for_one_sentence(self):
        result = memory.build_summary_prompt([{"role": "user", "content": "สวัสดี"}])
        assert "1 ประโยค" in result

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

    def test_adds_new_fact_returns_true(self):
        mem = self._mem()
        assert memory.add_fact(mem, "อยู่ชุมพร") is True
        assert "อยู่ชุมพร" in mem["facts"]

    def test_duplicate_returns_false(self):
        mem = self._mem()
        memory.add_fact(mem, "อยู่ชุมพร")
        assert memory.add_fact(mem, "อยู่ชุมพร") is False
        assert mem["facts"].count("อยู่ชุมพร") == 1

    def test_strips_whitespace(self):
        mem = self._mem()
        memory.add_fact(mem, "  อยู่ชุมพร  ")
        assert "อยู่ชุมพร" in mem["facts"]

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
        assert "อันเก่าสุด" not in mem["facts"]


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


# ── parse_extracted_facts ─────────────────────────────────────────────────────

class TestParseExtractedFacts:
    def test_parses_clean_json_array(self):
        assert memory.parse_extracted_facts('["ชื่อจูเลีย", "อยู่ชุมพร"]') == ["ชื่อจูเลีย", "อยู่ชุมพร"]

    def test_strips_think_tag(self):
        output = "<think>กำลังวิเคราะห์...</think>\n[\"อยู่ชุมพร\"]"
        assert memory.parse_extracted_facts(output) == ["อยู่ชุมพร"]

    def test_extracts_array_from_surrounding_text(self):
        output = 'ข้าพเจ้าพบข้อมูลดังนี้ ["ทำงานวิศวกร"] ครับ'
        assert memory.parse_extracted_facts(output) == ["ทำงานวิศวกร"]

    def test_empty_array_returns_empty(self):
        assert memory.parse_extracted_facts("[]") == []

    def test_empty_string_returns_empty(self):
        assert memory.parse_extracted_facts("") == []

    def test_filters_too_long_items(self):
        long_str = "ก" * 61
        assert memory.parse_extracted_facts(f'["{long_str}"]') == []

    def test_invalid_json_returns_empty(self):
        assert memory.parse_extracted_facts("ไม่มี JSON เลยสักนิด") == []

    def test_filters_non_string_items(self):
        result = memory.parse_extracted_facts('[42, "ชื่อจูเลีย", null]')
        assert result == ["ชื่อจูเลีย"]


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
