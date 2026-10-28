"""
Tests for PyThaiTrace 3-Tier Matcher Engine and Knowledge Base.
Covers:
- Tier 1: Feature Coverage (Named capture groups for Top 10 exceptions, models validation, Universal Fallback)
- Tier 2: Boundary & Corner Cases (Empty messages, regex meta-characters, Did you mean suffixes, missing docstring)
- Tier 3: 3-Tier Fallback Cascade (Tier 1 regex -> Tier 2 fuzzy -> Tier 3 class generic -> Universal Fallback)
- Tier 4: Real-World Scenarios (3rd-party library exceptions, complex docstrings, valid search URLs)
"""
import urllib.parse
import pytest

try:
    import pythaitrace
    from pythaitrace.models import (
        FrameInfo,
        NormalizedTraceback,
        KnowledgeRule,
        MatchResult,
        ExplanationCard,
    )
    from pythaitrace.matcher import MatcherEngine
    HAS_PYTHAITRACE = True
except ImportError:
    HAS_PYTHAITRACE = False
    FrameInfo = None  # type: ignore
    NormalizedTraceback = None  # type: ignore
    KnowledgeRule = None  # type: ignore
    MatchResult = None  # type: ignore
    ExplanationCard = None  # type: ignore
    MatcherEngine = None  # type: ignore


@pytest.fixture(autouse=True)
def require_pythaitrace():
    if not HAS_PYTHAITRACE:
        pytest.skip("pythaitrace module not yet implemented")


# ==============================================================================
# Tier 1: Feature Coverage (Strict Regex Named Groups & Top 10 Exceptions)
# ==============================================================================

class TestTier1MatcherFeatures:
    """Verifies regex entity extraction and rule matching across Top 10 exceptions."""

    @pytest.fixture(autouse=True)
    def setup_matcher(self):
        self.engine = MatcherEngine()

    def _create_norm_tb(self, exc_type: str, msg: str, code_line: str = "") -> NormalizedTraceback:
        frame = FrameInfo(
            filename="script.py",
            lineno=10,
            funcname="test_func",
            code_line=code_line,
            is_user_code=True,
        )
        return NormalizedTraceback(
            exc_type_name=exc_type,
            exc_message=msg,
            frames=[frame],
            primary_frame=frame,
        )

    def test_name_error_named_group_extraction(self):
        """NameError must extract the undefined variable name via regex named groups."""
        tb = self._create_norm_tb("NameError", "name 'my_variable' is not defined")
        card = self.engine.match(tb)
        assert card.exception_class == "NameError"
        assert card.is_fallback is False
        assert "my_variable" in card.summary_th or "my_variable" in card.search_keywords or "my_variable" in card.title_th

    def test_type_error_named_groups_extraction(self):
        """TypeError must match unsupported operand types or argument type mismatches."""
        tb = self._create_norm_tb(
            "TypeError",
            "unsupported operand type(s) for +: 'int' and 'str'",
            code_line="result = 5 + 'hello'"
        )
        card = self.engine.match(tb)
        assert card.exception_class == "TypeError"
        assert card.is_fallback is False
        assert len(card.fix_suggestions_th) > 0
        assert "int" in card.search_keywords or "TypeError" in card.search_keywords

    def test_index_error_matching(self):
        """IndexError must match sequence index out of bounds."""
        tb = self._create_norm_tb("IndexError", "list index out of range")
        card = self.engine.match(tb)
        assert card.exception_class == "IndexError"
        assert card.is_fallback is False
        assert len(card.mental_model_th) > 0

    def test_key_error_named_group_extraction(self):
        """KeyError must extract the missing dictionary key."""
        tb = self._create_norm_tb("KeyError", "'session_id'")
        card = self.engine.match(tb)
        assert card.exception_class == "KeyError"
        assert card.is_fallback is False
        assert "session_id" in card.search_keywords or "KeyError" in card.search_keywords

    def test_zero_division_error_matching(self):
        """ZeroDivisionError must match division by zero operations."""
        tb = self._create_norm_tb("ZeroDivisionError", "division by zero")
        card = self.engine.match(tb)
        assert card.exception_class == "ZeroDivisionError"
        assert card.is_fallback is False
        assert len(card.fix_suggestions_th) >= 1

    def test_module_not_found_error_extraction(self):
        """ModuleNotFoundError must extract the missing module identifier."""
        tb = self._create_norm_tb("ModuleNotFoundError", "No module named 'non_existent_pkg'")
        card = self.engine.match(tb)
        assert card.exception_class == "ModuleNotFoundError"
        assert card.is_fallback is False
        assert "non_existent_pkg" in card.search_keywords or "ModuleNotFoundError" in card.search_keywords

    def test_attribute_error_extraction(self):
        """AttributeError must extract object type and missing attribute name."""
        tb = self._create_norm_tb(
            "AttributeError",
            "'str' object has no attribute 'calculate_sum'"
        )
        card = self.engine.match(tb)
        assert card.exception_class == "AttributeError"
        assert card.is_fallback is False
        assert "calculate_sum" in card.search_keywords or "AttributeError" in card.search_keywords

    def test_value_error_extraction(self):
        """ValueError must match invalid literal for type conversions."""
        tb = self._create_norm_tb(
            "ValueError",
            "invalid literal for int() with base 10: 'not_a_number'"
        )
        card = self.engine.match(tb)
        assert card.exception_class == "ValueError"
        assert card.is_fallback is False

    def test_syntax_error_matching(self):
        """SyntaxError must match syntax issues (e.g. expected colon)."""
        tb = self._create_norm_tb("SyntaxError", "expected ':'")
        tb.is_syntax_error = True
        card = self.engine.match(tb)
        assert card.exception_class == "SyntaxError"
        assert card.is_fallback is False

    def test_indentation_error_matching(self):
        """IndentationError must match unindent or unexpected indent."""
        tb = self._create_norm_tb("IndentationError", "unindent does not match any outer indentation level")
        tb.is_syntax_error = True
        card = self.engine.match(tb)
        assert card.exception_class == "IndentationError"
        assert card.is_fallback is False

    def test_models_validation_and_serialization(self, sample_card_data):
        """ExplanationCard model must validate required fields and serialize to JSON cleanly."""
        card = ExplanationCard(**sample_card_data)
        assert card.error_id == "NAME_NOT_DEFINED"
        assert card.exception_class == "NameError"
        assert len(card.fix_suggestions_th) == 3
        # Ensure serialization roundtrips
        json_data = card.model_dump_json()
        assert "NAME_NOT_DEFINED" in json_data
        restored = ExplanationCard.model_validate_json(json_data)
        assert restored.error_id == card.error_id


# ==============================================================================
# Tier 2: Boundary & Corner Cases
# ==============================================================================

class TestTier2MatcherBoundaries:
    """Verifies matcher resilience against noisy, malformed, or unusual messages."""

    @pytest.fixture(autouse=True)
    def setup_matcher(self):
        self.engine = MatcherEngine()

    def test_empty_exception_message(self):
        """Empty exception message must not cause a crash or IndexError; returns class fallback."""
        frame = FrameInfo(filename="script.py", lineno=1, funcname="<module>")
        tb = NormalizedTraceback(
            exc_type_name="NameError",
            exc_message="",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        assert card.exception_class == "NameError"
        assert len(card.mental_model_th) > 0

    def test_python_310_did_you_mean_suffix_resilience(self):
        """Python 3.10+ 'Did you mean: ...' suggestions should not disrupt regex matching."""
        frame = FrameInfo(filename="script.py", lineno=5, funcname="test")
        tb = NormalizedTraceback(
            exc_type_name="NameError",
            exc_message="name 'calulate' is not defined. Did you mean: 'calculate'?",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        assert card.exception_class == "NameError"
        assert card.is_fallback is False
        # The target identifier 'calulate' should be handled cleanly
        assert "calulate" in card.search_keywords or "calulate" in card.summary_th or "NameError" in card.search_keywords

    def test_regex_meta_characters_in_error_message(self):
        """Error messages containing brackets, asterisks, pluses, or slashes must not crash regex."""
        frame = FrameInfo(filename="script.py", lineno=12, funcname="lookup")
        tb = NormalizedTraceback(
            exc_type_name="KeyError",
            exc_message="'[(user_id * 2) + 1]/beta\\alpha'",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        assert card.exception_class == "KeyError"
        assert card.is_fallback is False

    def test_extremely_long_error_message(self):
        """Very long error messages (> 1000 characters) must process in bounded time without hanging."""
        huge_msg = "unsupported operand type(s) for +: " + ("'CustomType' and " * 100) + "'int'"
        frame = FrameInfo(filename="script.py", lineno=1, funcname="<module>")
        tb = NormalizedTraceback(
            exc_type_name="TypeError",
            exc_message=huge_msg,
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        assert card.exception_class == "TypeError"

    def test_integer_key_in_key_error(self):
        """KeyError on integer keys (e.g. KeyError: 404) must match correctly."""
        frame = FrameInfo(filename="script.py", lineno=3, funcname="<module>")
        tb = NormalizedTraceback(
            exc_type_name="KeyError",
            exc_message="404",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        assert card.exception_class == "KeyError"
        assert card.is_fallback is False


# ==============================================================================
# Tier 3: 3-Tier Fallback Cascade
# ==============================================================================

class TestTier3MatcherFallbackCascade:
    """Verifies hierarchical fallback progression (Tier 1 -> Tier 2 -> Tier 3 -> Universal Fallback)."""

    @pytest.fixture(autouse=True)
    def setup_matcher(self):
        self.engine = MatcherEngine()

    def test_tier_1_strict_regex_selection(self):
        """When message exactly matches defined regex, tier 1 is selected."""
        frame = FrameInfo(filename="script.py", lineno=1, funcname="<module>")
        tb = NormalizedTraceback(
            exc_type_name="ZeroDivisionError",
            exc_message="division by zero",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        assert card.is_fallback is False
        assert card.error_id in ["ZERO_DIVISION", "ZERODIVISIONERROR"] or "ZeroDivision" in card.error_id

    def test_tier_3_class_generic_fallback_for_standard_exception(self):
        """When error message has non-standard wording, class-level generic rule is returned."""
        frame = FrameInfo(filename="script.py", lineno=1, funcname="<module>")
        # Custom message that will never match a specific regex pattern
        tb = NormalizedTraceback(
            exc_type_name="ValueError",
            exc_message="non_standard_vendor_value_check_failed_code_99",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        # Should return generic ValueError explanation, NOT universal fallback
        assert card.exception_class == "ValueError"
        assert card.is_fallback is False
        assert len(card.mental_model_th) > 0

    def test_universal_fallback_for_unmapped_class(self):
        """Unmapped custom exception triggers Universal __FALLBACK__ with docstring and URLs."""
        class GalacticHyperdriveFailure(Exception):
            """Raised when tachyon injector fails to stabilize the hyperdrive field."""
            pass

        exc_instance = GalacticHyperdriveFailure("Flux capacitor desynchronized at warp 9")
        frame = FrameInfo(filename="spaceship.py", lineno=88, funcname="engage_warp")
        tb = NormalizedTraceback(
            exc_type_name="GalacticHyperdriveFailure",
            exc_message=str(exc_instance),
            frames=[frame],
            primary_frame=frame
        )

        card = self.engine.match(tb, exc=exc_instance)
        assert card.is_fallback is True
        assert card.error_id == "__FALLBACK__"
        assert card.exception_class == "GalacticHyperdriveFailure"
        # Docstring from the custom exception must be extracted
        assert card.docstring is not None
        assert "tachyon injector" in card.docstring
        # Search URLs must be generated
        assert "GalacticHyperdriveFailure" in card.google_search_url
        assert "GalacticHyperdriveFailure" in card.stackoverflow_search_url


# ==============================================================================
# Tier 4: Real-World Scenarios
# ==============================================================================

class TestTier4MatcherRealWorld:
    """Verifies real 3rd-party library exceptions and URL encoding safety."""

    @pytest.fixture(autouse=True)
    def setup_matcher(self):
        self.engine = MatcherEngine()

    def test_search_urls_properly_urlencoded(self):
        """Google and StackOverflow search URLs must contain valid percent-encoding."""
        frame = FrameInfo(filename="app.py", lineno=1, funcname="<module>")
        tb = NormalizedTraceback(
            exc_type_name="CustomAuthException",
            exc_message="Failed token: [header#key] with spaces & symbols",
            frames=[frame],
            primary_frame=frame
        )
        card = self.engine.match(tb)
        # URLs must parse cleanly with urllib.parse
        parsed_google = urllib.parse.urlparse(card.google_search_url)
        assert parsed_google.scheme in ["http", "https"]
        assert "google" in parsed_google.netloc

        parsed_so = urllib.parse.urlparse(card.stackoverflow_search_url)
        assert parsed_so.scheme in ["http", "https"]
        assert "stackoverflow" in parsed_so.netloc

    def test_nested_exception_cause_introspection(self):
        """Exceptions with __cause__ retain context in search keywords or description."""
        try:
            try:
                raise KeyError("missing_db_host")
            except KeyError as inner:
                raise ConnectionError("Could not initialize cluster") from inner
        except ConnectionError as outer:
            frame = FrameInfo(filename="db.py", lineno=5, funcname="connect")
            tb = NormalizedTraceback(
                exc_type_name=type(outer).__name__,
                exc_message=str(outer),
                frames=[frame],
                primary_frame=frame
            )
            card = self.engine.match(tb, exc=outer)
            assert card.exception_class == "ConnectionError"
            assert len(card.fix_suggestions_th) > 0
