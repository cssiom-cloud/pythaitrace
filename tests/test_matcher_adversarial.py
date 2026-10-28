"""
Adversarial Stress Test Suite for PyThaiTrace 3-Tier Matcher Engine (matcher.py).

Scope & Attack Vectors:
1. Arbitrary 3rd-party exceptions without docstring (docstring=None, non-str, corrupted).
2. Exceptions with exotic names (non-ASCII, Thai, emojis, symbols, empty, null bytes, long names).
3. Long messages (100k characters) for ReDoS safety, catastrophic backtracking resistance, and performance.
4. Chained exceptions (5-level and 10-level deep __cause__ and __context__, circular references, poison __str__, root cause).
5. Fallback search URLs (valid percent-encoding, no raw spaces or newlines, URL safety).
6. Template interpolation attacks (unescaped braces, unknown keys, empty dicts, format specifiers, poison keys/values).
"""

import inspect
import sys
import time
import urllib.parse
import pytest

from pythaitrace.matcher import MatcherEngine, safe_format, build_search_urls
from pythaitrace.models import (
    ExplanationCard,
    FrameInfo,
    KnowledgeRule,
    MatchResult,
    NormalizedTraceback,
)


@pytest.fixture(scope="module")
def engine():
    return MatcherEngine()


def make_norm_tb(
    exc_type: str = "RuntimeError",
    msg: str = "Test message",
    docstring: str | None = None,
    mod: str = "custom_mod",
) -> NormalizedTraceback:
    frame = FrameInfo(filename="test.py", lineno=1, funcname="<module>", code_line="raise ...")
    return NormalizedTraceback(
        exc_type_name=exc_type,
        exc_message=msg,
        frames=[frame],
        primary_frame=frame,
        docstring=docstring,
        exception_module=mod,
    )


# ==============================================================================
# 1. Arbitrary 3rd-Party Exceptions Without Docstring
# ==============================================================================

class TestDocstringAdversarial:
    """Stress tests on docstring extraction and handling."""

    def test_custom_exception_with_none_docstring(self, engine):
        """
        An unmapped 3rd-party exception with __doc__ = None should have docstring=None,
        not inherit 'Common base class for all non-exit exceptions.' from Exception.
        """
        class NoDocError(Exception):
            __doc__ = None

        exc = NoDocError("Custom error with explicitly None docstring")
        tb = make_norm_tb(exc_type="NoDocError", msg=str(exc))
        card = engine.match(tb, exc=exc)

        assert card.is_fallback is True
        assert card.error_id == "__FALLBACK__"
        assert card.exception_class == "NoDocError"
        assert card.docstring is None, (
            f"Expected docstring=None for exception without docstring, "
            f"got inherited base class docstring: {repr(card.docstring)}"
        )

    def test_custom_exception_with_empty_docstring(self, engine):
        class EmptyDocError(Exception):
            """"""

        exc = EmptyDocError("Empty docstring")
        tb = make_norm_tb(exc_type="EmptyDocError", msg=str(exc))
        card = engine.match(tb, exc=exc)

        assert card.is_fallback is True
        assert card.docstring in ("", None)

    def test_custom_exception_without_any_docstring_attribute(self, engine):
        """
        An unmapped 3rd-party exception defined without docstring (class Custom(Exception): pass)
        should have docstring=None, NOT the docstring of builtins.Exception.
        """
        NewErr = type("UndocumentedLibError", (Exception,), {})
        exc = NewErr("No docs anywhere")
        tb = make_norm_tb(exc_type="UndocumentedLibError", msg=str(exc))
        card = engine.match(tb, exc=exc)

        assert card.is_fallback is True
        assert card.docstring is None, (
            f"Expected docstring=None for class without docstring, "
            f"got inherited base docstring: {repr(card.docstring)}"
        )

    def test_custom_exception_with_non_string_docstring(self, engine):
        """
        __doc__ might be an integer, list, or dict in exotic C-extensions or mocked objects.
        MatcherEngine must not crash with a Pydantic ValidationError.
        """
        class NonStrDocError(Exception):
            __doc__ = 12345

        exc = NonStrDocError("Docstring is an integer")
        tb = make_norm_tb(exc_type="NonStrDocError", msg=str(exc))
        card = engine.match(tb, exc=exc)
        assert isinstance(card, ExplanationCard)
        # Must either be None or sanitized str, never crash
        assert card.docstring is None or isinstance(card.docstring, str)

    def test_custom_exception_with_object_docstring(self, engine):
        """__doc__ is an arbitrary object/dict."""
        class ObjectDocError(Exception):
            __doc__ = {"some": "data"}

        exc = ObjectDocError("Docstring is a dict")
        tb = make_norm_tb(exc_type="ObjectDocError", msg=str(exc))
        card = engine.match(tb, exc=exc)
        assert isinstance(card, ExplanationCard)
        assert card.docstring is None or isinstance(card.docstring, str)

    def test_norm_tb_docstring_fallback_when_exc_is_none(self, engine):
        """When exc instance is None, docstring from norm_tb is used."""
        tb = make_norm_tb(
            exc_type="ThirdPartyPaymentError",
            msg="Payment gateway unreachable",
            docstring="Raised when gateway fails to respond within timeout.",
        )
        card = engine.match(tb, exc=None)
        assert card.is_fallback is True
        assert card.docstring == "Raised when gateway fails to respond within timeout."


# ==============================================================================
# 2. Exceptions with Exotic Names (Non-ASCII, Symbols, Emojis)
# ==============================================================================

class TestExoticExceptionNames:
    """Stress tests on exception class naming and module namespaces."""

    def test_thai_unicode_exception_name(self, engine):
        ThaiError = type("ข้อผิดพลาดทางเทคนิค", (Exception,), {"__module__": "ระบบหลัก"})
        exc = ThaiError("ข้อความทดสอบความผิดพลาด")
        tb = make_norm_tb(exc_type="ข้อผิดพลาดทางเทคนิค", msg=str(exc), mod="ระบบหลัก")
        card = engine.match(tb, exc=exc)

        assert card.exception_class == "ข้อผิดพลาดทางเทคนิค"
        assert "ข้อผิดพลาดทางเทคนิค" in card.title_th
        assert "ข้อผิดพลาดทางเทคนิค" in urllib.parse.unquote(card.google_search_url)

    def test_emoji_exception_name(self, engine):
        EmojiError = type("💥NuclearMeltdownError🔥", (Exception,), {"__module__": "reactor"})
        exc = EmojiError("Core overheating")
        tb = make_norm_tb(exc_type="💥NuclearMeltdownError🔥", msg=str(exc), mod="reactor")
        card = engine.match(tb, exc=exc)

        assert card.exception_class == "💥NuclearMeltdownError🔥"
        assert "💥NuclearMeltdownError🔥" in card.title_th
        assert "💥NuclearMeltdownError🔥" in urllib.parse.unquote(card.google_search_url)

    def test_symbols_and_brackets_in_class_name(self, engine):
        WeirdError = type("Custom<T>[Invalid]::Error!", (Exception,), {"__module__": "weird/pkg"})
        exc = WeirdError("Template instantiation failed")
        tb = make_norm_tb(exc_type="Custom<T>[Invalid]::Error!", msg=str(exc), mod="weird/pkg")
        card = engine.match(tb, exc=exc)

        assert card.exception_class == "Custom<T>[Invalid]::Error!"
        assert "Custom<T>[Invalid]::Error!" in card.title_th
        assert "<" not in card.google_search_url
        assert ">" not in card.google_search_url

    def test_empty_string_exception_name(self, engine):
        EmptyNameError = type("", (Exception,), {})
        exc = EmptyNameError("Error with empty class name")
        tb = make_norm_tb(exc_type="", msg=str(exc))
        card = engine.match(tb, exc=exc)

        assert card.exception_class == ""
        assert isinstance(card.title_th, str)
        assert len(card.title_th) > 0

    def test_exception_name_with_control_chars_and_null_bytes(self, engine):
        """Pass NormalizedTraceback with null bytes and ANSI sequences directly."""
        tb = make_norm_tb(exc_type="Error\x00\x1b[31mRed\x1b[0m\t\n", msg="Control chars in name")
        card = engine.match(tb, exc=None)

        assert isinstance(card, ExplanationCard)
        # Search URLs must not contain raw null bytes, newlines, or unencoded ESC
        assert "\x00" not in card.google_search_url
        assert "\n" not in card.google_search_url
        assert "\x1b" not in card.google_search_url

    def test_exception_module_is_none(self, engine):
        """When exception class __module__ is None, summary_th should not format as 'None.Error'."""
        NoModError = type("NoModError", (Exception,), {})
        NoModError.__module__ = None
        exc = NoModError("No module")
        tb = make_norm_tb(exc_type="NoModError", msg="No module", mod="custom_mod")
        card = engine.match(tb, exc=exc)
        # Should cleanly synthesize card
        assert isinstance(card, ExplanationCard)

    def test_extremely_long_class_name_5000_chars(self, engine):
        huge_name = "Super" * 1000 + "Exception"
        HugeError = type(huge_name, (Exception,), {})
        exc = HugeError("Long name test")
        tb = make_norm_tb(exc_type=huge_name, msg=str(exc))
        t0 = time.perf_counter()
        card = engine.match(tb, exc=exc)
        duration = time.perf_counter() - t0

        assert card.exception_class == huge_name
        assert duration < 0.5


# ==============================================================================
# 3. Long Messages (100k characters) & ReDoS Resistance
# ==============================================================================

class TestReDoSAndLargeMessages:
    """Stress tests on massive error messages and regular expression performance."""

    def test_type_error_100k_chars_redos_safety(self, engine):
        crafted_msg = "unsupported operand type(s) for +: " + ("'WeirdType' and " * 10000) + "'int'"
        assert len(crafted_msg) > 100000
        tb = make_norm_tb(exc_type="TypeError", msg=crafted_msg)

        t0 = time.perf_counter()
        card = engine.match(tb)
        duration = time.perf_counter() - t0

        assert card.exception_class == "TypeError"
        assert duration < 1.0, f"TypeError 100k matching took {duration:.3f}s (possible ReDoS!)"

    def test_name_error_100k_chars_with_repetitive_quotes(self, engine):
        crafted_var = "x" * 100000
        msg = f"name '{crafted_var}' is not defined"
        tb = make_norm_tb(exc_type="NameError", msg=msg)

        t0 = time.perf_counter()
        card = engine.match(tb)
        duration = time.perf_counter() - t0

        assert card.exception_class == "NameError"
        assert duration < 1.0, f"NameError 100k matching took {duration:.3f}s"

    def test_syntax_error_100k_unclosed_parenthesis_redos(self, engine):
        msg = "'(' was never closed" + ("(" * 100000)
        tb = make_norm_tb(exc_type="SyntaxError", msg=msg)

        t0 = time.perf_counter()
        card = engine.match(tb)
        duration = time.perf_counter() - t0

        assert card.exception_class == "SyntaxError"
        assert duration < 1.0, f"SyntaxError 100k matching took {duration:.3f}s"

    def test_key_error_100k_chars(self, engine):
        crafted_key = "K" * 100000
        msg = f"'{crafted_key}'"
        tb = make_norm_tb(exc_type="KeyError", msg=msg)

        t0 = time.perf_counter()
        card = engine.match(tb)
        duration = time.perf_counter() - t0

        assert card.exception_class == "KeyError"
        assert duration < 1.0

    def test_all_10_exceptions_with_100k_random_payload(self, engine):
        garbage = "abc def !@#$%^&*()_+~` \n\t " * 3500
        exc_classes = [
            "SyntaxError", "IndentationError", "NameError", "TypeError",
            "IndexError", "KeyError", "ZeroDivisionError", "ModuleNotFoundError",
            "AttributeError", "ValueError"
        ]
        for exc_name in exc_classes:
            tb = make_norm_tb(exc_type=exc_name, msg=garbage)
            t0 = time.perf_counter()
            card = engine.match(tb)
            duration = time.perf_counter() - t0
            assert card.exception_class == exc_name
            assert duration < 0.5, f"{exc_name} took {duration:.3f}s with 100k payload"


# ==============================================================================
# 4. Chained Exceptions (Deep Cause/Context, Circularity, Poison __str__)
# ==============================================================================

class TestChainedExceptionsAdversarial:
    """Stress tests on chained causes, contexts, deep nesting, and circularity."""

    def test_5_level_deep_explicit_cause_chain(self, engine):
        """
        Verify that 5-level deep cause chain does not crash and provides useful context.
        """
        try:
            try:
                try:
                    try:
                        try:
                            raise KeyError("RootKeyMissing")
                        except KeyError as e1:
                            raise ValueError("L2: Value error") from e1
                    except ValueError as e2:
                        raise IndexError("L3: Index error") from e2
                except IndexError as e3:
                    raise ConnectionError("L4: Connection error") from e3
            except ConnectionError as e4:
                raise RuntimeError("L5: Top-level runtime failure") from e4
        except RuntimeError as e5:
            tb = make_norm_tb(exc_type="RuntimeError", msg=str(e5))
            card = engine.match(tb, exc=e5)

            assert card.exception_class == "RuntimeError"
            assert any("Chained Cause" in s for s in card.fix_suggestions_th)
            assert "ConnectionError" in card.search_keywords

    def test_10_level_deep_cause_chain(self, engine):
        curr: BaseException = ValueError("Chain seed 0")
        for i in range(1, 11):
            next_exc = RuntimeError(f"Chain level {i}")
            next_exc.__cause__ = curr
            curr = next_exc

        tb = make_norm_tb(exc_type="RuntimeError", msg=str(curr))
        card = engine.match(tb, exc=curr)
        assert card.exception_class == "RuntimeError"
        assert len(card.fix_suggestions_th) > 0

    def test_5_level_deep_implicit_context_chain(self, engine):
        try:
            try:
                try:
                    try:
                        try:
                            raise TypeError("T1")
                        except TypeError:
                            raise ValueError("V2")
                    except ValueError:
                        raise IndexError("I3")
                except IndexError:
                    raise KeyError("K4")
            except KeyError:
                raise AttributeError("A5")
        except AttributeError as e5:
            tb = make_norm_tb(exc_type="AttributeError", msg=str(e5))
            card = engine.match(tb, exc=e5)
            assert card.exception_class == "AttributeError"
            assert any("Chained Cause" in s for s in card.fix_suggestions_th)

    def test_circular_exception_reference_resilience(self, engine):
        """e1.__context__ = e2 and e2.__context__ = e1 must not cause infinite recursion."""
        e1 = ValueError("First error")
        e2 = RuntimeError("Second error")
        e1.__context__ = e2
        e2.__context__ = e1

        tb = make_norm_tb(exc_type="ValueError", msg=str(e1))
        card = engine.match(tb, exc=e1)
        assert card.exception_class == "ValueError"

    def test_poison_cause_whose_str_raises(self, engine):
        """
        If cause.__str__() raises an exception, MatcherEngine must NOT crash.
        Failsafe requirement: must handle broken str(cause) gracefully.
        """
        class PoisonError(Exception):
            def __str__(self):
                raise RuntimeError("Poison __str__ explosion!")

        try:
            p = PoisonError()
            raise ValueError("Outer error") from p
        except ValueError as outer:
            tb = make_norm_tb(exc_type="ValueError", msg="Outer error")
            card = engine.match(tb, exc=outer)
            assert isinstance(card, ExplanationCard)

    def test_cause_with_massive_100k_message(self, engine):
        massive_cause = ValueError("C" * 100000)
        outer = RuntimeError("Outer operation failed")
        outer.__cause__ = massive_cause

        tb = make_norm_tb(exc_type="RuntimeError", msg="Outer operation failed")
        card = engine.match(tb, exc=outer)
        assert card.exception_class == "RuntimeError"
        assert len(card.google_search_url) > 0


# ==============================================================================
# 5. Fallback Search URLs - URL Encoding and Safety
# ==============================================================================

class TestSearchUrlsSafety:
    """Stress tests on search URL generation, percent-encoding, and invalid characters."""

    def test_urls_contain_no_raw_spaces_or_newlines(self):
        query_samples = [
            "python NameError name 'var' is not defined\nLine 2\r\nLine 3",
            "   leading and trailing spaces with \t tabs \n and newlines   ",
            "TypeError: unsupported operand type(s) for +: 'int' and 'str'\n\n",
            "KeyError: '[(user_id * 2) + 1]/beta\\alpha'\r\n\t",
            "ข้อผิดพลาด ฐานข้อมูล ไม่พบไฟล์\n\n",
            "🔥💥 Error: Something blew up! 💥🔥",
        ]
        for q in query_samples:
            g_url, so_url = build_search_urls(q)

            # Check Google URL
            assert " " not in g_url, f"Raw space found in Google URL: {g_url}"
            assert "\n" not in g_url, f"Raw newline found in Google URL: {g_url}"
            assert "\r" not in g_url, f"Raw CR found in Google URL: {g_url}"
            assert "\t" not in g_url, f"Raw tab found in Google URL: {g_url}"

            # Check StackOverflow URL
            assert " " not in so_url, f"Raw space found in SO URL: {so_url}"
            assert "\n" not in so_url, f"Raw newline found in SO URL: {so_url}"
            assert "\r" not in so_url, f"Raw CR found in SO URL: {so_url}"
            assert "\t" not in so_url, f"Raw tab found in SO URL: {so_url}"

            # Verify parseable with urllib.parse
            parsed_g = urllib.parse.urlsplit(g_url)
            assert parsed_g.scheme in ("http", "https")
            assert parsed_g.netloc == "www.google.com"

            parsed_so = urllib.parse.urlsplit(so_url)
            assert parsed_so.scheme in ("http", "https")
            assert parsed_so.netloc == "stackoverflow.com"

    def test_special_characters_in_urls(self):
        special_query = "Error: foo?bar=1&baz=2#frag/path <script>alert('xss')</script>"
        g_url, so_url = build_search_urls(special_query)

        assert "<" not in g_url and ">" not in g_url
        assert "<" not in so_url and ">" not in so_url
        assert "'" not in g_url and '"' not in g_url
        assert "'" not in so_url and '"' not in so_url

    def test_empty_or_whitespace_only_query(self):
        for empty_q in ["", "   ", "\n\t\r", "   \n   "]:
            g_url, so_url = build_search_urls(empty_q)
            assert g_url == "https://www.google.com/search?q="
            assert " " not in so_url and "\n" not in so_url

    def test_url_encoding_in_card_synthesis(self, engine):
        tb = make_norm_tb(
            exc_type="WeirdQueryError",
            msg="Error with raw \n newline and \t tab and 'quotes'",
        )
        card = engine.match(tb)
        assert " " not in card.google_search_url
        assert "\n" not in card.google_search_url
        assert " " not in card.stackoverflow_search_url
        assert "\n" not in card.stackoverflow_search_url


# ==============================================================================
# 6. Template Interpolation Attacks
# ==============================================================================

class TestTemplateInterpolationAttacks:
    """Stress tests on safe_format and template string injection attacks."""

    def test_unescaped_single_braces(self):
        assert safe_format("Single left brace { alone", {"a": "1"}) == "Single left brace { alone"
        assert safe_format("Single right brace } alone", {"a": "1"}) == "Single right brace } alone"
        assert safe_format("Mismatched {a} and {", {"a": "test"}) == "Mismatched {a} and {"

    def test_unknown_keys_default_to_placeholder(self):
        res = safe_format("Hello {unknown_key}!", {})
        assert res == "Hello <unknown_key>!"

    def test_empty_dict_params(self):
        template = "Error in {module}.{class}: {message}"
        res = safe_format(template, {})
        assert res == "Error in <module>.<class>: <message>"

    def test_nested_attribute_access_attack(self):
        res = safe_format("Attack: {0.__class__}", {"0": "safe_val"})
        assert isinstance(res, str)

    def test_indexing_into_missing_or_present_keys(self):
        res1 = safe_format("Value is {var[0]}", {"var": "hello"})
        assert res1 == "Value is h"

        res2 = safe_format("Value is {missing[0]}", {})
        assert isinstance(res2, str)

        res3 = safe_format("Out of bounds {var[999]}", {"var": "short"})
        assert res3 == "Out of bounds {var[999]}"

    def test_format_specifiers(self):
        res1 = safe_format("Padded: {var:>10s}", {"var": "hi"})
        assert res1 == "Padded:         hi"

        res2 = safe_format("Bad spec: {var:invalid_spec_123}", {"var": "hi"})
        assert res2 == "Bad spec: {var:invalid_spec_123}"

    def test_deeply_nested_braces_dos(self):
        deep = "{{{{{" * 500 + "}}}}}" * 500
        res = safe_format(deep, {})
        assert isinstance(res, str)

    def test_poison_object_in_params_whose_str_raises(self):
        class PoisonParam:
            def __str__(self):
                raise RuntimeError("Poison parameter string conversion failed!")

        res = safe_format("Hello {user}", {"user": PoisonParam()})
        assert res == "Hello {user}"

    def test_none_and_empty_template(self):
        assert safe_format("", {"a": "1"}) == ""
        assert safe_format(None, {"a": "1"}) == ""

    def test_non_string_keys_in_params(self):
        """Non-string keys should safely fall back to original template without crashing."""
        params = {123: "number", None: "none", (1, 2): "tuple"}
        res = safe_format("Keys: {123}, {None}, {(1, 2)}", params)
        assert isinstance(res, str)

    def test_indirect_template_injection_via_exception_message(self, engine):
        tb = make_norm_tb(
            exc_type="NameError",
            msg="name '{exploit_token}' is not defined",
        )
        card = engine.match(tb)
        assert card.exception_class == "NameError"
        assert isinstance(card.summary_th, str)
        assert isinstance(card.mental_model_th, str)
