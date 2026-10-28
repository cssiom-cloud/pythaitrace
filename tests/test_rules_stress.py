"""
Adversarial Stress Test Suite for pythaitrace Knowledge Base (src/pythaitrace/rules.json).

Validates:
1. Regex compilation across all rules without re.error.
2. Named group safe substitution in summary_th without KeyError or ValueError.
3. 100% uniqueness of error_id values across the entire knowledge base.
4. Top 10 exception message matching across Python 3.10, 3.11, 3.12, 3.13, 3.14.
5. Verification of __FALLBACK__ rule structure and universal fallback logic.
6. Empirical detection of regex pattern discrepancies and format string vulnerabilities.
"""

import json
import re
import string
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

from pythaitrace.models import KnowledgeRule


RULES_PATH = Path(__file__).resolve().parent.parent / "src" / "pythaitrace" / "rules.json"


@pytest.fixture(scope="session")
def rules_data() -> List[Dict[str, Any]]:
    assert RULES_PATH.is_file(), f"rules.json not found at {RULES_PATH}"
    with open(RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def rules_by_class(rules_data) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for r in rules_data:
        grouped.setdefault(r["exception_class"], []).append(r)
    return grouped


def match_exception(rules_by_class: Dict[str, List[Dict[str, Any]]], exc_class: str, msg: str):
    """Helper to evaluate Tier 1 and Tier 3 matching."""
    rules = rules_by_class.get(exc_class, [])
    tier1_matches = []
    tier3_generic = None

    for r in rules:
        pat = r.get("pattern")
        if pat:
            m = re.search(pat, msg)
            if m:
                tier1_matches.append((r, m.groupdict()))
        else:
            if tier3_generic is None:
                tier3_generic = r

    return tier1_matches, tier3_generic


# ==============================================================================
# 1. Regex Compilation & Model Conformance
# ==============================================================================

class TestRuleCompilationAndSchema:
    """Verifies that all rules parse into Pydantic models and regexes compile cleanly."""

    def test_rules_json_loads_and_non_empty(self, rules_data):
        assert isinstance(rules_data, list)
        assert len(rules_data) >= 11, "Must contain at least Top 10 exceptions + fallback"

    def test_all_rules_conform_to_knowledge_rule_schema(self, rules_data):
        for idx, rule_dict in enumerate(rules_data):
            try:
                rule = KnowledgeRule.model_validate(rule_dict)
                assert rule.error_id, f"Rule at index {idx} has empty error_id"
                assert rule.exception_class, f"Rule at index {idx} has empty exception_class"
                assert rule.summary_th, f"Rule at index {idx} has empty summary_th"
                assert rule.mental_model_th, f"Rule at index {idx} has empty mental_model_th"
                assert isinstance(rule.fix_suggestions_th, list)
                assert len(rule.fix_suggestions_th) > 0, f"Rule at index {idx} has empty fix_suggestions_th"
            except Exception as exc:
                pytest.fail(f"Rule at index {idx} ({rule_dict.get('error_id')}) failed Pydantic validation: {exc}")

    def test_every_pattern_compiles_without_re_error(self, rules_data):
        for rule_dict in rules_data:
            pattern = rule_dict.get("pattern")
            error_id = rule_dict.get("error_id")
            if pattern is not None:
                try:
                    compiled = re.compile(pattern)
                    assert compiled is not None
                except re.error as err:
                    pytest.fail(f"Rule '{error_id}' regex pattern failed to compile: {err} | Pattern: {pattern}")


# ==============================================================================
# 2. Error ID Uniqueness
# ==============================================================================

class TestErrorIdUniqueness:
    """Verifies 100% uniqueness of error_ids across the entire rules database."""

    def test_duplicate_error_ids(self, rules_data):
        seen_ids: Dict[str, int] = {}
        duplicates: List[str] = []
        for r in rules_data:
            eid = r.get("error_id")
            assert eid, f"Rule has missing or empty error_id: {r}"
            if eid in seen_ids:
                duplicates.append(eid)
                seen_ids[eid] += 1
            else:
                seen_ids[eid] = 1

        assert not duplicates, f"Found duplicate error_ids in rules.json: {duplicates}"
        assert len(seen_ids) == len(rules_data), "Unique error_ids count must equal total rules count"

    def test_error_id_naming_convention(self, rules_data):
        for r in rules_data:
            eid = r.get("error_id")
            assert re.match(r"^[a-z0-9_]+$", eid), (
                f"error_id '{eid}' does not follow snake_case convention (lowercase alphanumeric and underscores)"
            )


# ==============================================================================
# 3. Named Capture Groups & Safe summary_th Substitution
# ==============================================================================

class TestNamedGroupSubstitution:
    """Verifies safe substitution of named groups in summary_th without KeyError/ValueError."""

    @staticmethod
    def _extract_format_fields(text: str) -> Set[str]:
        formatter = string.Formatter()
        fields: Set[str] = set()
        for _, field_name, _, _ in formatter.parse(text):
            if field_name is not None:
                fields.add(field_name.split(".")[0].split("[")[0])
        return fields

    def test_summary_th_contains_no_unmatched_groups(self, rules_data):
        """Every placeholder in summary_th must correspond to a named group in the pattern (or fallback vars)."""
        fallback_vars = {"exception_module", "exception_class"}
        for r in rules_data:
            eid = r.get("error_id")
            pat = r.get("pattern")
            sth = r.get("summary_th", "")

            named_groups: Set[str] = set()
            if pat:
                compiled = re.compile(pat)
                named_groups = set(compiled.groupindex.keys())

            placeholders = self._extract_format_fields(sth)

            if r.get("exception_class") == "__FALLBACK__":
                allowed = fallback_vars
            else:
                allowed = named_groups

            unmatched = placeholders - allowed
            assert not unmatched, (
                f"Rule '{eid}' summary_th has placeholders {unmatched} that are not in pattern named groups {named_groups}"
            )

    def test_summary_th_safe_substitution_execution(self, rules_data):
        """Simulate substitution with mock captured entities and verify no KeyError or ValueError."""
        for r in rules_data:
            eid = r.get("error_id")
            pat = r.get("pattern")
            sth = r.get("summary_th", "")

            mock_dict: Dict[str, str] = {}
            if pat:
                compiled = re.compile(pat)
                for g in compiled.groupindex.keys():
                    mock_dict[g] = f"test_{g}"

            if r.get("exception_class") == "__FALLBACK__":
                mock_dict["exception_module"] = "test_module"
                mock_dict["exception_class"] = "TestException"

            try:
                formatted = sth.format(**mock_dict)
                assert isinstance(formatted, str)
                assert len(formatted) > 0
            except KeyError as ke:
                pytest.fail(f"Rule '{eid}' summary_th raised KeyError during formatting: {ke}")
            except ValueError as ve:
                pytest.fail(f"Rule '{eid}' summary_th raised ValueError during formatting: {ve}")

    def test_summary_th_resilient_to_partial_or_none_groups(self, rules_data):
        """If optional groups in regex match None, summary_th formatting should still not crash."""
        for r in rules_data:
            eid = r.get("error_id")
            pat = r.get("pattern")
            sth = r.get("summary_th", "")
            if not pat:
                continue

            compiled = re.compile(pat)
            mock_empty_dict = {g: "" for g in compiled.groupindex.keys()}
            try:
                formatted = sth.format(**mock_empty_dict)
                assert isinstance(formatted, str)
            except Exception as e:
                pytest.fail(f"Rule '{eid}' summary_th crashed on empty group substitution: {e}")


# ==============================================================================
# 4. Universal Fallback Rule Verification
# ==============================================================================

class TestUniversalFallbackRule:
    """Verifies that __FALLBACK__ conforms to interface contracts."""

    def test_universal_fallback_exists(self, rules_data):
        fallback_rules = [r for r in rules_data if r.get("exception_class") == "__FALLBACK__"]
        assert len(fallback_rules) == 1, "Must have exactly one __FALLBACK__ rule in rules.json"

    def test_universal_fallback_pattern_is_null(self, rules_data):
        fallback_rule = next(r for r in rules_data if r.get("exception_class") == "__FALLBACK__")
        assert fallback_rule.get("pattern") is None, "__FALLBACK__ rule must have pattern: null"

    def test_universal_fallback_search_keywords_format(self, rules_data):
        fallback_rule = next(r for r in rules_data if r.get("exception_class") == "__FALLBACK__")
        keywords = fallback_rule.get("search_keywords", "")
        assert "{exception_class}" in keywords or "python" in keywords.lower()

    def test_universal_fallback_error_id(self, rules_data):
        fallback_rule = next(r for r in rules_data if r.get("exception_class") == "__FALLBACK__")
        eid = fallback_rule.get("error_id")
        assert eid in ["universal_fallback", "__FALLBACK__"]


# ==============================================================================
# 5. Top 10 Exception Coverage Across Python 3.10–3.14
# ==============================================================================

class TestTop10ExceptionPatternMatching:
    """
    Stress-tests regex patterns against standard exception strings from Python 3.10-3.14.
    """

    # --- 1. SyntaxError ---
    @pytest.mark.parametrize("msg, expected_rule_id", [
        ("'(' was never closed", "syntax_error_unclosed_paren"),
        ("'[' was never closed", "syntax_error_unclosed_paren"),
        ("'{' was never closed", "syntax_error_unclosed_paren"),
        ("closing parenthesis ']' does not match opening parenthesis '('", "syntax_error_mismatched_paren"),
        ("closing parenthesis '}' does not match opening parenthesis '['", "syntax_error_mismatched_paren"),
        ("unterminated string literal (detected at line 1)", "syntax_error_unterminated_string"),
        ("expected ':'", "syntax_error_expected_colon"),
        ("cannot assign to literal here. Maybe you meant '==' instead of '='?", "syntax_error_cannot_assign"),
        ("cannot assign to expression here. Maybe you meant '==' instead of '='?", "syntax_error_cannot_assign"),
        ("invalid syntax", "syntax_error_invalid_syntax"),
        ("invalid syntax. Perhaps you forgot a comma?", "syntax_error_invalid_syntax"),
    ])
    def test_syntax_error_patterns(self, rules_by_class, msg, expected_rule_id):
        t1, t3 = match_exception(rules_by_class, "SyntaxError", msg)
        assert len(t1) > 0, f"SyntaxError '{msg}' failed to match any Tier 1 pattern"
        matched_id = t1[0][0]["error_id"]
        assert matched_id == expected_rule_id

    # --- 2. IndentationError ---
    @pytest.mark.parametrize("msg, expected_rule_id", [
        ("expected an indented block after 'if' statement on line 1", "indent_expected_block"),
        ("expected an indented block after 'for' statement on line 2", "indent_expected_block"),
        ("expected an indented block after 'def' statement on line 5", "indent_expected_block"),
        ("unindent does not match any outer indentation level", "indent_unindent_mismatch"),
        ("unexpected indent", "indent_unexpected"),
    ])
    def test_indentation_error_patterns(self, rules_by_class, msg, expected_rule_id):
        t1, t3 = match_exception(rules_by_class, "IndentationError", msg)
        assert len(t1) > 0, f"IndentationError '{msg}' failed to match Tier 1"
        assert t1[0][0]["error_id"] == expected_rule_id

    # --- 3. NameError ---
    @pytest.mark.parametrize("msg, expected_var", [
        ("name 'my_variable' is not defined", "my_variable"),
        ("name 'calculate' is not defined. Did you mean: 'calculator'?", "calculate"),
        ("name 'foo_bar_123' is not defined. Did you mean: 'bar'?", "foo_bar_123"),
        ("name 'self' is not defined", "self"),
    ])
    def test_name_error_patterns(self, rules_by_class, msg, expected_var):
        t1, t3 = match_exception(rules_by_class, "NameError", msg)
        assert len(t1) > 0, f"NameError '{msg}' failed to match Tier 1"
        rule, groups = t1[0]
        assert rule["error_id"] == "name_not_defined"
        assert groups.get("var") == expected_var

    # --- 4. TypeError ---
    @pytest.mark.parametrize("msg, expected_rule_id", [
        ("unsupported operand type(s) for +: 'int' and 'str'", "type_unsupported_operand"),
        ("unsupported operand type(s) for -: 'str' and 'int'", "type_unsupported_operand"),
        ("unsupported operand type(s) for /: 'list' and 'dict'", "type_unsupported_operand"),
        ('can only concatenate str (not "int") to str', "type_str_concat"),
        ('can only concatenate str (not "list") to str', "type_str_concat"),
        ("'int' object is not callable", "type_not_callable"),
        ("'str' object is not callable", "type_not_callable"),
        ("'NoneType' object is not callable", "type_not_callable"),
        ("'int' object is not subscriptable", "type_not_subscriptable"),
        ("'NoneType' object is not subscriptable", "type_not_subscriptable"),
        ("cannot unpack non-iterable int object", "type_unpack_non_iterable"),
        ("cannot unpack non-iterable float object", "type_unpack_non_iterable"),
        ("my_func() takes 2 positional arguments but 3 were given", "type_wrong_args_count"),
        ("my_func() missing 1 required positional argument: 'x'", "type_missing_required_args"),
        ("my_func() missing 2 required positional arguments: 'a' and 'b'", "type_missing_required_args"),
    ])
    def test_type_error_patterns(self, rules_by_class, msg, expected_rule_id):
        t1, t3 = match_exception(rules_by_class, "TypeError", msg)
        assert len(t1) > 0, f"TypeError '{msg}' failed Tier 1 match"
        assert t1[0][0]["error_id"] == expected_rule_id

    # --- 5. IndexError ---
    @pytest.mark.parametrize("msg, expected_type", [
        ("list index out of range", "list"),
        ("tuple index out of range", "tuple"),
        ("string index out of range", "string"),
        ("deque index out of range", "deque"),
    ])
    def test_index_error_patterns(self, rules_by_class, msg, expected_type):
        t1, t3 = match_exception(rules_by_class, "IndexError", msg)
        assert len(t1) > 0, f"IndexError '{msg}' failed Tier 1"
        assert t1[0][0]["error_id"] == "index_out_of_range"
        assert t1[0][1].get("type") == expected_type

    def test_index_error_non_standard_falls_back_to_generic(self, rules_by_class):
        t1, t3 = match_exception(rules_by_class, "IndexError", "pop from empty list")
        assert t3 is not None, "IndexError must have a Tier 3 generic fallback rule"
        assert t3["error_id"] == "index_generic"

    # --- 6. KeyError ---
    @pytest.mark.parametrize("msg, expected_key", [
        ("'session_id'", "session_id"),
        ("'user_name'", "user_name"),
        ("404", "404"),
        ("0", "0"),
    ])
    def test_key_error_patterns(self, rules_by_class, msg, expected_key):
        t1, t3 = match_exception(rules_by_class, "KeyError", msg)
        assert len(t1) > 0, f"KeyError '{msg}' failed Tier 1"
        assert t1[0][0]["error_id"] == "key_not_found"
        assert t1[0][1].get("key") == expected_key

    # --- 7. ZeroDivisionError ---
    @pytest.mark.parametrize("msg", [
        "division by zero",
        "float division by zero",
        "integer division or modulo by zero",
    ])
    def test_zero_division_error_patterns(self, rules_by_class, msg):
        t1, t3 = match_exception(rules_by_class, "ZeroDivisionError", msg)
        assert len(t1) > 0, f"ZeroDivisionError '{msg}' failed Tier 1"
        assert t1[0][0]["error_id"] == "zero_division"

    # --- 8. ModuleNotFoundError ---
    @pytest.mark.parametrize("msg, expected_mod", [
        ("No module named 'non_existent_pkg'", "non_existent_pkg"),
        ("No module named 'numpy.core._multiarray_umath'", "numpy.core._multiarray_umath"),
        ("No module named 'requests'", "requests"),
    ])
    def test_module_not_found_patterns(self, rules_by_class, msg, expected_mod):
        t1, t3 = match_exception(rules_by_class, "ModuleNotFoundError", msg)
        assert len(t1) > 0, f"ModuleNotFoundError '{msg}' failed Tier 1"
        assert t1[0][0]["error_id"] == "module_not_found"
        assert t1[0][1].get("module") == expected_mod

    # --- 9. AttributeError ---
    @pytest.mark.parametrize("msg, expected_rule_id, expected_type, expected_attr", [
        ("'NoneType' object has no attribute 'items'", "attr_none_type", None, "items"),
        ("'NoneType' object has no attribute 'get'", "attr_none_type", None, "get"),
        ("'str' object has no attribute 'calculate_sum'", "attr_has_no_attribute", "str", "calculate_sum"),
        ("'list' object has no attribute 'upper'", "attr_has_no_attribute", "list", "upper"),
        ("'str' object has no attribute 'uper'. Did you mean: 'upper'?", "attr_has_no_attribute", "str", "uper"),
    ])
    def test_attribute_error_patterns(self, rules_by_class, msg, expected_rule_id, expected_type, expected_attr):
        t1, t3 = match_exception(rules_by_class, "AttributeError", msg)
        assert len(t1) > 0, f"AttributeError '{msg}' failed Tier 1"
        rule, groups = t1[0]
        assert rule["error_id"] == expected_rule_id
        assert groups.get("attr") == expected_attr
        if expected_type is not None:
            assert groups.get("type") == expected_type

    # --- 10. ValueError ---
    @pytest.mark.parametrize("msg, expected_rule_id", [
        ("invalid literal for int() with base 10: 'not_a_number'", "value_invalid_literal_int"),
        ("invalid literal for int() with base 16: 'xyz'", "value_invalid_literal_int"),
        ("could not convert string to float: 'hello'", "value_invalid_literal_float"),
        ("could not convert string to float: ''", "value_invalid_literal_float"),
        ("not enough values to unpack (expected 2, got 1)", "value_unpack_mismatch"),
        ("too many values to unpack (expected 2)", "value_unpack_mismatch"),
        ("math domain error", "value_math_domain"),
    ])
    def test_value_error_patterns(self, rules_by_class, msg, expected_rule_id):
        t1, t3 = match_exception(rules_by_class, "ValueError", msg)
        assert len(t1) > 0, f"ValueError '{msg}' failed Tier 1 pattern"
        assert t1[0][0]["error_id"] == expected_rule_id

    def test_every_top_10_exception_has_generic_fallback_rule(self, rules_by_class):
        top_10 = [
            "SyntaxError",
            "IndentationError",
            "NameError",
            "TypeError",
            "IndexError",
            "KeyError",
            "ZeroDivisionError",
            "ModuleNotFoundError",
            "AttributeError",
            "ValueError",
        ]
        missing_generics = []
        for exc in top_10:
            rules = rules_by_class.get(exc, [])
            generics = [r for r in rules if r.get("pattern") is None]
            if not generics:
                missing_generics.append(exc)

        assert not missing_generics, f"Top 10 exceptions missing Tier 3 generic (pattern=null) rule: {missing_generics}"


# ==============================================================================
# 6. Empirical Adversarial Challenge Probes (Documenting Real Failure Modes)
# ==============================================================================

class TestAdversarialDiscrepancies:
    """
    Regression verification tests confirming that previously identified
    gaps in rules.json are now resolved for modern Python 3.10-3.14 variations.
    """

    def test_challenge_syntax_error_unclosed_paren_has_unescaped_closing_brace(self, rules_data):
        """
        REMEDIATION 1: In syntax_error_unclosed_paren, fix_suggestions_th[0] lone '}' is escaped as '}}',
        so str.format() executes cleanly without ValueError.
        """
        rule = next(r for r in rules_data if r["error_id"] == "syntax_error_unclosed_paren")
        fix_0 = rule["fix_suggestions_th"][0]
        formatted = fix_0.format()
        assert "}" in formatted

    def test_challenge_syntax_error_unterminated_triple_quote_missing_in_tier1(self, rules_by_class):
        """
        REMEDIATION 2: Python 3.12+ 'unterminated triple-quoted string literal (detected at line 1)'
        now cleanly matches Tier 1 rule syntax_error_unterminated_string.
        """
        t1, t3 = match_exception(rules_by_class, "SyntaxError", "unterminated triple-quoted string literal (detected at line 1)")
        assert len(t1) == 1, "Tier 1 should match triple-quoted string"
        assert t1[0][0]["error_id"] == "syntax_error_unterminated_string"

    def test_challenge_value_error_too_many_unpack_got_n_missing_in_tier1(self, rules_by_class):
        """
        REMEDIATION 3: Python 3.10-3.14 'too many values to unpack (expected 2, got 3)'
        now cleanly matches Tier 1 rule value_unpack_mismatch.
        """
        t1, t3 = match_exception(rules_by_class, "ValueError", "too many values to unpack (expected 2, got 3)")
        assert len(t1) == 1, "Tier 1 should match too many values to unpack with got count"
        assert t1[0][0]["error_id"] == "value_unpack_mismatch"
        assert t1[0][1].get("expected_too") == "2"

    def test_challenge_type_error_takes_zero_args_was_given_missing_in_tier1(self, rules_by_class):
        """
        REMEDIATION 4: Python 'f() takes 0 positional arguments but 1 was given'
        now cleanly matches Tier 1 rule type_wrong_args_count.
        """
        t1, t3 = match_exception(rules_by_class, "TypeError", "f() takes 0 positional arguments but 1 was given")
        assert len(t1) == 1, "Tier 1 should match singular 'was given'"
        assert t1[0][0]["error_id"] == "type_wrong_args_count"
        assert t1[0][1].get("expected") == "0"
        assert t1[0][1].get("actual") == "1"

    def test_challenge_attribute_error_module_missing_in_tier1(self, rules_by_class):
        """
        REMEDIATION 5: Python \"module 'math' has no attribute 'foo'\"
        now cleanly matches Tier 1 rule attr_has_no_attribute.
        """
        t1, t3 = match_exception(rules_by_class, "AttributeError", "module 'math' has no attribute 'foo'")
        assert len(t1) == 1, "Tier 1 should match module AttributeError"
        assert t1[0][0]["error_id"] == "attr_has_no_attribute"
        assert t1[0][1].get("module") == "math"
        assert t1[0][1].get("attr") == "foo"
