"""
Adversarial Stress Test Suite for pythaitrace.models
=====================================================
Authored by challenger_m1_1.
Empirically stress-tests edge cases, boundary conditions, immutability,
Unicode roundtrip fidelity, caret calculations, tier boundaries, and forward compatibility.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List
import pytest
from pydantic import ValidationError

from pythaitrace.models import (
    FrameInfo,
    NormalizedTraceback,
    KnowledgeRule,
    MatchResult,
    ExplanationCard,
)


# ==============================================================================
# 1. Extreme Column Offsets & Caret Pointer Calculations
# ==============================================================================
class TestExtremeColumnOffsetsAndCaret:
    """Stress testing column offsets, negative numbers, inverted spans, and caret pointer."""

    def test_colno_greater_than_end_colno_inverted_span(self):
        """
        Adversarial case: colno > end_colno (inverted span).
        Must not crash with negative string multiplication; must fallback to width=1.
        """
        frame = FrameInfo(
            filename="test.py",
            lineno=10,
            funcname="test_func",
            colno=10,
            end_colno=5,
        )
        caret = frame.caret_pointer
        assert caret is not None
        # colno=10 -> 9 leading spaces, width=max(1, 5-10) -> 1 caret
        expected = " " * 9 + "^"
        assert caret == expected
        assert len(caret) == 10

    def test_extreme_inverted_span(self):
        """colno=100, end_colno=1 -> width=max(1, -99)=1, 99 spaces + 1 caret."""
        frame = FrameInfo(
            filename="test.py",
            lineno=10,
            funcname="test_func",
            colno=100,
            end_colno=1,
        )
        caret = frame.caret_pointer
        assert caret == " " * 99 + "^"
        assert len(caret) == 100

    def test_negative_column_offsets(self):
        """
        Adversarial case: negative column offsets.
        Must not crash; max(0, colno - 1) ensures 0 spaces rather than error.
        """
        frame1 = FrameInfo(
            filename="test.py",
            lineno=10,
            funcname="test_func",
            colno=-5,
            end_colno=-2,
        )
        # colno=-5 -> max(0, -6) = 0 spaces; width=max(1, -2 - (-5)) = 3 carets
        assert frame1.caret_pointer == "^^^"

        frame2 = FrameInfo(
            filename="test.py",
            lineno=10,
            funcname="test_func",
            colno=-1,
            end_colno=5,
        )
        # colno=-1 -> 0 spaces; width=max(1, 5 - (-1)) = 6 carets
        assert frame2.caret_pointer == "^^^^^^"

        frame3 = FrameInfo(
            filename="test.py",
            lineno=10,
            funcname="test_func",
            colno=-10,
            end_colno=-20,
        )
        # colno=-10 -> 0 spaces; width=max(1, -20 - (-10)) = 1 caret
        assert frame3.caret_pointer == "^"

    def test_zero_column_offsets(self):
        """
        Adversarial case: 0 offsets.
        In 0-indexed scenarios, colno=0 must produce 0 leading spaces (max(0, -1) = 0).
        """
        frame1 = FrameInfo(
            filename="test.py",
            lineno=1,
            funcname="root",
            colno=0,
            end_colno=0,
        )
        assert frame1.caret_pointer == "^"

        frame2 = FrameInfo(
            filename="test.py",
            lineno=1,
            funcname="root",
            colno=0,
            end_colno=5,
        )
        assert frame2.caret_pointer == "^^^^^"

        frame3 = FrameInfo(
            filename="test.py",
            lineno=1,
            funcname="root",
            colno=0,
            end_colno=None,
        )
        assert frame3.caret_pointer == "^"

    def test_none_column_offsets(self):
        """Test combinations with None offsets."""
        # Both None -> None
        frame_both_none = FrameInfo(filename="test.py", lineno=1, funcname="f")
        assert frame_both_none.caret_pointer is None

        # Only end_colno provided -> None (cannot point without starting position)
        frame_end_only = FrameInfo(filename="test.py", lineno=1, funcname="f", colno=None, end_colno=10)
        assert frame_end_only.caret_pointer is None

        # Only colno provided -> points at single column
        frame_start_only = FrameInfo(filename="test.py", lineno=1, funcname="f", colno=5, end_colno=None)
        assert frame_start_only.caret_pointer == "    ^"

    def test_single_character_spans(self):
        """Single character spans (colno == end_colno or end_colno == colno + 1)."""
        frame1 = FrameInfo(filename="test.py", lineno=1, funcname="f", colno=1, end_colno=1)
        assert frame1.caret_pointer == "^"

        frame2 = FrameInfo(filename="test.py", lineno=1, funcname="f", colno=1, end_colno=2)
        assert frame2.caret_pointer == "^"

        frame3 = FrameInfo(filename="test.py", lineno=1, funcname="f", colno=12, end_colno=12)
        assert frame3.caret_pointer == " " * 11 + "^"

        frame4 = FrameInfo(filename="test.py", lineno=1, funcname="f", colno=12, end_colno=13)
        assert frame4.caret_pointer == " " * 11 + "^"

    def test_multiline_span_simulation(self):
        """
        PEP 657 multiline AST expressions:
        e.g., expression starts at line 1, col 14, and ends at line 4, col 2.
        When represented on line 1, end_colno might be recorded as 2 (< colno).
        """
        frame = FrameInfo(
            filename="multiline.py",
            lineno=1,
            funcname="call_multi",
            code_line="result = complex_func(",
            colno=10,
            end_colno=2,
        )
        # Must safely yield a 1-character caret at column 10
        caret = frame.caret_pointer
        assert caret == " " * 9 + "^"

    def test_code_line_with_tabs_and_newlines(self):
        """FrameInfo containing tabs or trailing newlines in code_line."""
        frame = FrameInfo(
            filename="tab_script.py",
            lineno=5,
            funcname="with_tab",
            code_line="\tdef foo():\n",
            colno=5,
            end_colno=8,
        )
        caret = frame.caret_pointer
        assert caret == "    ^^^"
        # Verify code_line retains exact content
        assert frame.code_line == "\tdef foo():\n"


# ==============================================================================
# 2. Pydantic Immutability Enforcement (frozen=True)
# ==============================================================================
class TestPydanticImmutability:
    """Ensure frozen models strictly reject mutations with ValidationError."""

    def test_frame_info_hashable_in_set(self):
        """FrameInfo has frozen=True and only immutable fields, making it hashable."""
        f1 = FrameInfo(filename="a.py", lineno=1, funcname="f")
        f2 = FrameInfo(filename="a.py", lineno=1, funcname="f")
        f3 = FrameInfo(filename="b.py", lineno=2, funcname="g")
        s = {f1, f2, f3}
        assert len(s) == 2
        assert f1 in s


    def test_frame_info_frozen_fields(self):
        frame = FrameInfo(
            filename="immutable.py",
            lineno=42,
            funcname="safe_func",
            code_line="x = 100",
            colno=5,
            end_colno=10,
            is_user_code=True,
        )

        with pytest.raises(ValidationError):
            frame.filename = "hacked.py"

        with pytest.raises(ValidationError):
            frame.lineno = 99

        with pytest.raises(ValidationError):
            frame.funcname = "other_func"

        with pytest.raises(ValidationError):
            frame.code_line = "x = 999"

        with pytest.raises(ValidationError):
            frame.colno = 1

        with pytest.raises(ValidationError):
            frame.end_colno = 20

        with pytest.raises(ValidationError):
            frame.is_user_code = False

    def test_frame_info_frozen_extra_assignment(self):
        """Adding extra attributes post-initialization must also raise ValidationError."""
        frame = FrameInfo(filename="immutable.py", lineno=1, funcname="f")
        with pytest.raises(ValidationError):
            frame.new_runtime_attr = "not_allowed"

    def test_knowledge_rule_frozen_fields(self):
        rule = KnowledgeRule(
            error_id="TYPE_ERROR_TEST",
            exception_class="TypeError",
            pattern=r"cannot concatenate",
            summary_th="ข้อความสรุป",
            mental_model_th="คำอธิบายมโนทัศน์",
            fix_suggestions_th=["วิธีแก้ที่ 1"],
            search_keywords="python type error",
        )

        with pytest.raises(ValidationError):
            rule.error_id = "CHANGED_ID"

        with pytest.raises(ValidationError):
            rule.exception_class = "ValueError"

        with pytest.raises(ValidationError):
            rule.summary_th = "เปลี่ยนแปลง"

        with pytest.raises(ValidationError):
            rule.mental_model_th = "เปลี่ยนมโนทัศน์"

        with pytest.raises(ValidationError):
            rule.fix_suggestions_th = ["วิธีใหม่"]

        with pytest.raises(ValidationError):
            rule.search_keywords = "new keywords"

        with pytest.raises(ValidationError):
            rule.pattern = r"new pattern"

    def test_knowledge_rule_frozen_extra_assignment(self):
        rule = KnowledgeRule(
            error_id="TEST",
            exception_class="TestError",
            summary_th="ส",
            mental_model_th="ม",
        )
        with pytest.raises(ValidationError):
            rule.custom_injected_field = 12345

    def test_mutable_models_allow_in_place_updates(self):
        """Verify that NormalizedTraceback, MatchResult, ExplanationCard ARE mutable as designed."""
        tb = NormalizedTraceback(exc_type_name="TypeError", exc_message="old msg")
        tb.exc_message = "new msg"
        assert tb.exc_message == "new msg"

        rule = KnowledgeRule(
            error_id="TEST",
            exception_class="TestError",
            summary_th="ส",
            mental_model_th="ม",
        )
        match_res = MatchResult(rule=rule, tier=1)
        match_res.tier = 2
        assert match_res.tier == 2


# ==============================================================================
# 3. MatchResult Tier Boundaries
# ==============================================================================
class TestMatchResultTierBoundaries:
    """Stress test the 1 <= tier <= 4 boundary validation."""

    @pytest.fixture
    def dummy_rule(self) -> KnowledgeRule:
        return KnowledgeRule(
            error_id="DUMMY_RULE",
            exception_class="DummyError",
            summary_th="สรุปข้อผิดพลาดจำลอง",
            mental_model_th="มโนทัศน์จำลอง",
            fix_suggestions_th=["ทดสอบ"],
            search_keywords="dummy error",
        )

    def test_tier_zero_raises_validation_error(self, dummy_rule):
        """tier=0 must raise ValidationError (ge=1)."""
        with pytest.raises(ValidationError) as exc_info:
            MatchResult(rule=dummy_rule, tier=0)
        assert "greater than or equal to 1" in str(exc_info.value)

    def test_tier_five_raises_validation_error(self, dummy_rule):
        """tier=5 must raise ValidationError (le=4)."""
        with pytest.raises(ValidationError) as exc_info:
            MatchResult(rule=dummy_rule, tier=5)
        assert "less than or equal to 4" in str(exc_info.value)

    def test_tier_negative_raises_validation_error(self, dummy_rule):
        """tier=-1 must raise ValidationError."""
        with pytest.raises(ValidationError):
            MatchResult(rule=dummy_rule, tier=-1)

    def test_tier_valid_range_all_tiers_accepted(self, dummy_rule):
        """Tiers 1, 2, 3, 4 must all be valid."""
        for t in (1, 2, 3, 4):
            res = MatchResult(rule=dummy_rule, tier=t)
            assert res.tier == t
            assert res.matched is True

    def test_tier_invalid_types_raise_validation_error(self, dummy_rule):
        """Non-integer types must raise ValidationError."""
        with pytest.raises(ValidationError):
            MatchResult(rule=dummy_rule, tier="one")  # type: ignore

        with pytest.raises(ValidationError):
            MatchResult(rule=dummy_rule, tier=[1])  # type: ignore


# ==============================================================================
# 4. Unicode & Emoji Roundtrip Serialization
# ==============================================================================
class TestUnicodeRoundtripSerialization:
    """Stress testing serialization with Thai characters, combining vowels, and emojis."""

    THAI_TEXT_CORPUS = (
        "ตรวจพบข้อผิดพลาด: 'ตัวแปร' ไม่ได้ถูกนิยามไว้ในขอบเขตปัจจุบัน "
        "สระลอย: ที่ น้ำ ก้ เก่ง ญ์ ฤๅ ฃ ฅ "
        "สัญลักษณ์ทางคณิตศาสตร์: ∑(x) ≥ 0 ≠ ∞ ± π"
    )
    EMOJI_CORPUS = "🚨 💡 🔍 ⚡ 💥 🎯 📦 🐍 🇹🇭"

    def test_frame_info_unicode_roundtrip(self):
        frame = FrameInfo(
            filename="d:/โปรเจกต์/ภาษาไทย/สคริปต์_🐍.py",
            lineno=15,
            funcname="คำนวณ_ยอดรวม_🎯",
            code_line=f"ราคา_สุทธิ = คำนวณ(100) # {self.EMOJI_CORPUS}",
            colno=5,
            end_colno=25,
            extra_comment=self.THAI_TEXT_CORPUS,
        )
        json_data = frame.model_dump_json()
        restored = FrameInfo.model_validate_json(json_data)
        assert restored == frame
        assert restored.filename == frame.filename
        assert "🐍" in restored.filename
        assert "คำนวณ_ยอดรวม_🎯" in restored.funcname
        assert restored.caret_pointer == "    " + "^" * 20

    def test_normalized_traceback_unicode_roundtrip(self):
        primary_frame = FrameInfo(
            filename="app_🇹🇭.py",
            lineno=1,
            funcname="รัน",
            code_line="raise ValueError('ผิดพลาด')",
        )
        norm_tb = NormalizedTraceback(
            exc_type_name="ข้อผิดพลาดจำลองError",
            exc_message=f"{self.THAI_TEXT_CORPUS} {self.EMOJI_CORPUS}",
            frames=[primary_frame],
            primary_frame=primary_frame,
            notes=[f"บันทึกช่วยจำ: {self.EMOJI_CORPUS}"],
            clean_text="ข้อความที่ล้าง ANSI แล้ว",
            suggestion="คุณหมายถึง 'ชื่อตัวแปรนี้' ใช่หรือไม่?",
        )
        json_data = norm_tb.model_dump_json()
        restored = NormalizedTraceback.model_validate_json(json_data)
        assert restored == norm_tb
        assert "สระลอย" in restored.exc_message
        assert "🇹🇭" in restored.exc_message

    def test_knowledge_rule_unicode_roundtrip(self):
        rule = KnowledgeRule(
            error_id="THAI_RULE_ID_01",
            exception_class="TypeError",
            pattern=r"^ไม่สามารถบวก (?P<type1>\w+) กับ (?P<type2>\w+) ได้$",
            summary_th=self.THAI_TEXT_CORPUS,
            mental_model_th=f"คำอธิบายเชิงเปรียบเทียบ: {self.EMOJI_CORPUS}",
            fix_suggestions_th=[
                "ข้อที่ 1: ตรวจสอบชนิดข้อมูลด้วย type()",
                "ข้อที่ 2: แปลงชนิดตัวแปรก่อนดำเนินการ เช่น int('123')",
            ],
            search_keywords="python type error thai",
        )
        json_data = rule.model_dump_json()
        restored = KnowledgeRule.model_validate_json(json_data)
        assert restored == rule
        assert restored.summary_th == self.THAI_TEXT_CORPUS

    def test_explanation_card_unicode_roundtrip(self):
        card = ExplanationCard(
            error_id="TYPE_ERROR_UNSUPPORTED",
            exception_class="TypeError",
            title_th="พบข้อผิดพลาด: ชนิดข้อมูลไม่สามารถทำงานร่วมกันได้ 🚨",
            summary_th=self.THAI_TEXT_CORPUS,
            mental_model_th=f"การเปรียบเทียบเสมือนนำน้ำกับน้ำมันมาผสมกัน {self.EMOJI_CORPUS}",
            fix_suggestions_th=[
                "1. ตรวจสอบชนิดตัวแปร",
                "2. ทำ Type Casting เช่น str(x)",
            ],
            search_keywords="python type error unsupported operand",
            google_search_url="https://www.google.com/search?q=python+type+error",
            stackoverflow_search_url="https://stackoverflow.com/search?q=python+type+error",
            primary_frame=FrameInfo(filename="main.py", lineno=10, funcname="foo"),
            docstring="คำอธิบายคลาสแบบละเอียดภาษาไทย",
        )
        json_data = card.model_dump_json()
        restored = ExplanationCard.model_validate_json(json_data)
        assert restored == card
        assert "🚨" in restored.title_th
        assert "น้ำกับน้ำมัน" in restored.mental_model_th

    def test_json_dumps_preserves_utf8_unscrambled(self):
        """Ensure standard json.loads parses the Pydantic dump as exact Thai strings."""
        rule = KnowledgeRule(
            error_id="THAI_01",
            exception_class="ValueError",
            summary_th="ค่าที่ส่งเข้ามาไม่ถูกต้อง",
            mental_model_th="กล่องขนาดเล็กใส่ของขนาดใหญ่ไม่ได้",
        )
        parsed = json.loads(rule.model_dump_json())
        assert parsed["summary_th"] == "ค่าที่ส่งเข้ามาไม่ถูกต้อง"
        assert parsed["mental_model_th"] == "กล่องขนาดเล็กใส่ของขนาดใหญ่ไม่ได้"


# ==============================================================================
# 5. Extra Fields Forward-Compatibility (extra="allow")
# ==============================================================================
class TestExtraFieldsForwardCompatibility:
    """Verify that all models accept and preserve unknown future schema fields."""

    def test_frame_info_extra_fields(self):
        frame = FrameInfo(
            filename="test.py",
            lineno=5,
            funcname="worker",
            future_git_commit="a1b2c3d4",
            ast_node_type="BinOp",
            nested_meta={"thread_id": 1042},
        )
        assert getattr(frame, "future_git_commit") == "a1b2c3d4"
        assert getattr(frame, "ast_node_type") == "BinOp"
        assert getattr(frame, "nested_meta") == {"thread_id": 1042}

        # Verify extra fields survive serialization roundtrip
        dumped = frame.model_dump()
        assert dumped["future_git_commit"] == "a1b2c3d4"
        restored = FrameInfo.model_validate_json(frame.model_dump_json())
        assert getattr(restored, "future_git_commit") == "a1b2c3d4"

    def test_normalized_traceback_extra_fields(self):
        norm_tb = NormalizedTraceback(
            exc_type_name="RuntimeError",
            exc_message="crash",
            process_id=9876,
            memory_usage_mb=45.2,
            v3_future_field=[1, 2, 3],
        )
        assert getattr(norm_tb, "process_id") == 9876
        assert getattr(norm_tb, "memory_usage_mb") == 45.2

        dumped = norm_tb.model_dump()
        assert dumped["process_id"] == 9876
        assert dumped["v3_future_field"] == [1, 2, 3]

    def test_knowledge_rule_extra_fields(self):
        rule = KnowledgeRule(
            error_id="CUSTOM_RULE",
            exception_class="CustomError",
            summary_th="ข้อความ",
            mental_model_th="มโนทัศน์",
            author_email="dev@pythaitrace.org",
            severity_level="CRITICAL",
        )
        assert getattr(rule, "author_email") == "dev@pythaitrace.org"
        assert getattr(rule, "severity_level") == "CRITICAL"

        restored = KnowledgeRule.model_validate_json(rule.model_dump_json())
        assert getattr(restored, "author_email") == "dev@pythaitrace.org"

    def test_match_result_extra_fields(self):
        rule = KnowledgeRule(
            error_id="TEST",
            exception_class="TestError",
            summary_th="ส",
            mental_model_th="ม",
        )
        match_res = MatchResult(
            rule=rule,
            tier=2,
            match_duration_ms=1.45,
            confidence_score=0.99,
        )
        assert getattr(match_res, "match_duration_ms") == 1.45
        assert getattr(match_res, "confidence_score") == 0.99

        restored = MatchResult.model_validate_json(match_res.model_dump_json())
        assert getattr(restored, "confidence_score") == 0.99

    def test_explanation_card_extra_fields(self):
        card = ExplanationCard(
            error_id="ERR_1",
            exception_class="KeyError",
            title_th="คีย์ไม่ถูกต้อง",
            summary_th="ไม่พบคีย์ในดิกชันนารี",
            mental_model_th="ค้นหาลิ้นชักที่ไม่มีป้ายชื่อ",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
            ai_assisted_explanation="AI summary text",
            render_theme="dark_mode",
        )
        assert getattr(card, "ai_assisted_explanation") == "AI summary text"
        assert getattr(card, "render_theme") == "dark_mode"

        restored = ExplanationCard.model_validate_json(card.model_dump_json())
        assert getattr(restored, "render_theme") == "dark_mode"


# ==============================================================================
# 6. Aliases and Cross-Compatibility Properties
# ==============================================================================
class TestAliasesAndCrossCompatibility:
    """Verify alias choices and property getters provide 100% backward/cross compatibility."""

    def test_frame_info_aliases(self):
        # Instantiate using alternative aliases
        frame = FrameInfo(
            filename="app.py",
            lineno=20,
            name="compute_stats",
            line="total = sum(items)",
            col_offset=9,
            end_col_offset=19,
        )
        assert frame.funcname == "compute_stats"
        assert frame.code_line == "total = sum(items)"
        assert frame.colno == 9
        assert frame.end_colno == 19

        # Property getters
        assert frame.name == "compute_stats"
        assert frame.line == "total = sum(items)"
        assert frame.col_offset == 9
        assert frame.end_col_offset == 19

    def test_normalized_traceback_aliases(self):
        frame = FrameInfo(filename="test.py", lineno=1, funcname="main")
        norm_tb = NormalizedTraceback(
            exception_class="IndexError",
            message="list index out of range",
            relevant_frame=frame,
        )
        assert norm_tb.exc_type_name == "IndexError"
        assert norm_tb.exc_message == "list index out of range"
        assert norm_tb.primary_frame == frame

        # Property getters
        assert norm_tb.exception_class == "IndexError"
        assert norm_tb.message == "list index out of range"
        assert norm_tb.relevant_frame == frame

    def test_match_result_aliases(self):
        rule = KnowledgeRule(
            error_id="RULE_01",
            exception_class="ZeroDivisionError",
            summary_th="หารด้วยศูนย์",
            mental_model_th="แบ่งของให้คนศูนย์คน",
        )
        res = MatchResult(
            rule=rule,
            tier=1,
            captured_params={"divisor": "0"},
        )
        assert res.extracted_entities == {"divisor": "0"}
        assert res.captured_params == {"divisor": "0"}
        assert res.matched is True

    def test_explanation_card_aliases(self):
        frame = FrameInfo(filename="script.py", lineno=5, funcname="run")
        card = ExplanationCard(
            error_id="ERR_ZERODIV",
            exception_class="ZeroDivisionError",
            title="พบการหารด้วยศูนย์",
            summary_th="สรุป",
            mental_model_th="มโนทัศน์",
            google_search_url="https://google.com/search?q=zerodiv",
            stackoverflow_search_url="https://stackoverflow.com/search?q=zerodiv",
            code_context=frame,
            docstring_summary="Second argument to a division was zero.",
        )
        assert card.title_th == "พบการหารด้วยศูนย์"
        assert card.primary_frame == frame
        assert card.docstring == "Second argument to a division was zero."

        # Properties
        assert card.title == "พบการหารด้วยศูนย์"
        assert card.code_context == frame
        assert card.docstring_summary == "Second argument to a division was zero."
        assert card.search_links["google"] == "https://google.com/search?q=zerodiv"
        assert card.search_links["stackoverflow"] == "https://stackoverflow.com/search?q=zerodiv"


# ==============================================================================
# 7. Knowledge Base Schema Integrity Verification (rules.json)
# ==============================================================================
class TestRulesJsonSchemaIntegrity:
    """Stress test the real rules.json against KnowledgeRule schema."""

    def test_rules_json_loads_and_validates_cleanly(self):
        rules_path = Path(__file__).resolve().parent.parent / "src" / "pythaitrace" / "rules.json"
        assert rules_path.is_file(), f"rules.json not found at {rules_path}"

        with open(rules_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        assert isinstance(raw_data, list), "rules.json root must be a list"
        assert len(raw_data) > 0, "rules.json must not be empty"

        rules: List[KnowledgeRule] = []
        error_ids = set()

        for item in raw_data:
            # Validate with KnowledgeRule
            rule = KnowledgeRule.model_validate(item)
            rules.append(rule)

            # Ensure unique error_id
            assert rule.error_id not in error_ids, f"Duplicate error_id: {rule.error_id}"
            error_ids.add(rule.error_id)

            # Verify pattern compilation if pattern exists
            if rule.pattern is not None:
                try:
                    compiled = re.compile(rule.pattern)
                    assert compiled is not None
                except re.error as e:
                    pytest.fail(f"Invalid regex pattern in rule {rule.error_id}: {e}")

            # Verify Thai fields are non-empty
            assert len(rule.summary_th.strip()) > 0, f"Empty summary_th in {rule.error_id}"
            assert len(rule.mental_model_th.strip()) > 0, f"Empty mental_model_th in {rule.error_id}"

        # Ensure __FALLBACK__ rule exists
        fallback_rules = [r for r in rules if r.exception_class == "__FALLBACK__"]
        assert len(fallback_rules) >= 1, "Missing __FALLBACK__ rule in rules.json"
