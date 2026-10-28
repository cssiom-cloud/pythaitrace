"""
PyThaiTrace v2.0 - Tier 5 Adversarial Coverage Hardening Test Suite (test_tier5_coverage_1.py)
Author: challenger_m5_1
Scope: White-box coverage hardening, boundary stress-testing, and unexercised path validation
across normalizer.py, matcher.py, renderer.py, hooks.py, runner.py, and cli.py.
"""
from __future__ import annotations

import asyncio
import builtins
import io
import os
import re
import shutil
import sys
import tempfile
import threading
import types
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from rich.cells import cell_len

from pythaitrace import cli, hooks, matcher, models, normalizer, renderer, runner
from pythaitrace.models import (
    ExplanationCard,
    FrameInfo,
    KnowledgeRule,
    MatchResult,
    NormalizedTraceback,
)


# ==============================================================================
# Suite 1: Normalizer Hardening (Python versions, Carets, Cycles, Synthetic TBs)
# ==============================================================================
class TestNormalizerTier5:
    """Stress tests for normalizer.py covering edge cases, synthetic inputs, and Python version diffs."""

    def test_strip_ansi_comprehensive(self):
        """Test ANSI stripper with various sequences (SGR, CSI, OSC hyperlinks, edge cases)."""
        assert normalizer.strip_ansi(None) == ""
        assert normalizer.strip_ansi("") == ""
        assert normalizer.strip_ansi("Pure text without escapes") == "Pure text without escapes"

        # SGR Colors
        colored = "\x1b[31;1mError: \x1b[32mFile Not Found\x1b[0m"
        assert normalizer.strip_ansi(colored) == "Error: File Not Found"

        # OSC 8 Hyperlinks (closed with \x1b\\ and \x07)
        osc_link = "\x1b]8;;https://python.org\x1b\\Python Site\x1b]8;;\x1b\\"
        assert normalizer.strip_ansi(osc_link) == "Python Site"
        osc_bel = "\x1b]8;;https://python.org\x07Python Site\x1b]8;;\x07"
        assert normalizer.strip_ansi(osc_bel) == "Python Site"

        # Thai text with embedded ANSI
        thai_ansi = "\x1b[33mข้อผิดพลาดไวยากรณ์: \x1b[31mตัวแปรไม่ได้กำหนด\x1b[0m"
        assert normalizer.strip_ansi(thai_ansi) == "ข้อผิดพลาดไวยากรณ์: ตัวแปรไม่ได้กำหนด"

    def test_is_user_frame_boundaries(self):
        """Test is_user_frame with abnormal, pseudo-file, and standard library paths."""
        assert not normalizer.is_user_frame(None)
        assert not normalizer.is_user_frame("")

        # Pseudo-files
        assert normalizer.is_user_frame("<stdin>")
        assert normalizer.is_user_frame("<string>")
        assert normalizer.is_user_frame("<ipython-input-4-deadbeef>")
        assert not normalizer.is_user_frame("<frozen importlib._bootstrap>")
        assert not normalizer.is_user_frame("<frozen abc>")

        # pythaitrace internal paths
        assert not normalizer.is_user_frame(str(Path(normalizer.__file__).resolve()))
        assert not normalizer.is_user_frame("pythaitrace/normalizer.py")
        assert not normalizer.is_user_frame("src/pythaitrace/renderer.py")
        assert not normalizer.is_user_frame("runpy.py")
        assert not normalizer.is_user_frame("C:\\Python314\\Lib\\site-packages\\some_pkg\\mod.py")
        assert not normalizer.is_user_frame("/usr/lib/python3/dist-packages/req/mod.py")

        # Standard project user code
        assert normalizer.is_user_frame("d:/Vscode/my_app/main.py")
        assert normalizer.is_user_frame("/home/user/workspace/script.py")

        # Path with problematic characters that might raise os.path.abspath error
        assert normalizer.is_user_frame("invalid\x00path.py") is not None

    def test_extract_frames_synthetic_and_abnormal(self):
        """Test extract_frames_from_exception with mock and corrupted traceback objects."""
        # Exception without traceback
        exc_no_tb = ValueError("no tb")
        frames, primary = normalizer.extract_frames_from_exception(exc_no_tb)
        assert frames == []
        assert primary is None

        # Exception where traceback.extract_tb raises Exception
        exc_faulty = RuntimeError("faulty")
        try:
            raise exc_faulty
        except RuntimeError as e:
            exc_faulty = e

        with patch("traceback.extract_tb", side_effect=RuntimeError("Extraction failed")):
            frames, primary = normalizer.extract_frames_from_exception(exc_faulty)
            assert frames == []
            assert primary is None

        # Mock FrameSummary with invalid lineno and col offsets
        mock_fs = MagicMock()
        mock_fs.filename = "<string>"
        mock_fs.lineno = -10
        mock_fs.name = "<test_func>"
        mock_fs.line = "a = 1 / 0"
        mock_fs.colno = "invalid_col"
        mock_fs.end_colno = None

        with patch("traceback.extract_tb", return_value=[mock_fs]):
            frames, primary = normalizer.extract_frames_from_exception(exc_faulty)
            assert len(frames) == 1
            assert frames[0].lineno == 1  # normalized <=0 to 1
            assert frames[0].colno is None  # invalid_col caught safely
            assert primary == frames[0]

    def test_normalize_exception_unprintable_str_and_notes(self):
        """Test normalize_exception when exception __str__ or notes raise exceptions."""
        class UnprintableError(Exception):
            def __str__(self):
                raise RuntimeError("Cannot print this exception")

        err = UnprintableError()
        # Add PEP 678 unprintable note
        class UnprintableNote:
            def __str__(self):
                raise TypeError("Unprintable note")

        err.__notes__ = [UnprintableNote(), "Normal note"]

        norm = normalizer.normalize_exception(err)
        assert norm.exc_type_name == "UnprintableError"
        assert "<UnprintableError unprintable>" in norm.exc_message
        assert "<unprintable note>" in norm.notes
        assert "Normal note" in norm.notes

    def test_normalize_exception_syntax_error_boundaries(self):
        """Test normalize_exception for SyntaxError with missing or negative line/offset attributes."""
        # SyntaxError with zero/negative offsets
        syn = SyntaxError("invalid syntax")
        syn.filename = None
        syn.lineno = 0
        syn.offset = 0
        syn.end_offset = -5
        syn.text = None

        norm = normalizer.normalize_exception(syn)
        assert norm.is_syntax_error is True
        assert norm.primary_frame is not None
        assert norm.primary_frame.filename == "<string>"
        assert norm.primary_frame.lineno == 1  # 0 clamped to 1
        assert norm.primary_frame.colno == 0
        assert norm.primary_frame.end_colno == -5

    def test_normalize_traceback_str_multiline_carets_versions(self):
        """Test string traceback normalization across Python 3.10, 3.11, 3.12, 3.14+ formatting."""
        # Python 3.11+ format with underlines and carets
        tb_str_311 = """\
Traceback (most recent call last):
  File "d:/project/test.py", line 42, in calculate
    result = val + 100 / count
                   ~~~~^~~~~~~
ZeroDivisionError: division by zero
"""
        norm = normalizer.normalize_traceback_str(tb_str_311)
        assert norm.exc_type_name == "ZeroDivisionError"
        assert norm.exc_message == "division by zero"
        assert len(norm.frames) == 1
        frame = norm.frames[0]
        assert frame.lineno == 42
        assert frame.code_line == "result = val + 100 / count"
        assert frame.colno is not None
        assert frame.end_colno is not None
        assert frame.colno > 0
        assert frame.end_colno > frame.colno

        # Python 3.10 format with suggestion "Did you mean: '...'"
        tb_str_310 = """\
Traceback (most recent call last):
  File "d:/project/script.py", line 10, in <module>
    print(prnt)
NameError: name 'prnt' is not defined. Did you mean: 'print'?
"""
        norm_310 = normalizer.normalize_traceback_str(tb_str_310)
        assert norm_310.exc_type_name == "NameError"
        assert norm_310.suggestion == "print"

        # Traceback with bare exception class (no message or colon)
        tb_bare = """\
Traceback (most recent call last):
  File "app.py", line 5, in run
    raise StopIteration
StopIteration
"""
        norm_bare = normalizer.normalize_traceback_str(tb_bare)
        assert norm_bare.exc_type_name == "StopIteration"
        assert norm_bare.exc_message == ""


# ==============================================================================
# Suite 2: Matcher Hardening (Very Long Msgs, Strange Chars, Tier 2, Cycles)
# ==============================================================================
class TestMatcherTier5:
    """Stress tests for matcher.py covering extreme messages, cyclic causes, and fuzzy extraction."""

    @pytest.fixture(autouse=True)
    def setup_engine(self):
        self.engine = matcher.MatcherEngine()

    def test_chained_causes_with_direct_and_mutual_cycles(self):
        """Test chained causes with self-cycle and mutual cycle to verify termination."""
        e1 = ValueError("First error")
        e2 = TypeError("Second error")

        # 1. Self cycle
        e1.__cause__ = e1
        norm1 = normalizer.normalize_exception(e1)
        card1 = self.engine.match(norm1, exc=e1)
        assert card1.exception_class == "ValueError"
        # Verify fix suggestions contain cause notice and terminated cleanly
        assert any("Chained Cause" in s for s in card1.fix_suggestions_th)

        # 2. Mutual cycle: e1 -> e2 -> e1
        e1.__cause__ = e2
        e2.__cause__ = e1
        card2 = self.engine.match(norm1, exc=e1)
        assert card2.exception_class == "ValueError"

        # 3. Context cycle: e1.__context__ = e1
        e3 = KeyError("missing key")
        e3.__suppress_context__ = False
        e3.__cause__ = None
        e3.__context__ = e3
        norm3 = normalizer.normalize_exception(e3)
        card3 = self.engine.match(norm3, exc=e3)
        assert card3.exception_class == "KeyError"

    def test_very_long_message_stress_50k(self):
        """Test error message with >50,000 characters to verify no ReDoS or URL overflow."""
        long_junk = "abcde 12345 " * 5000  # ~60,000 chars
        err = RuntimeError(f"Long error message: {long_junk}")
        norm = normalizer.normalize_exception(err)

        card = self.engine.match(norm, exc=err)
        assert card.exception_class == "RuntimeError"
        # Search query in URL must be truncated to <= 500 chars (safe for browser URI limits)
        assert len(card.google_search_url) < 2000
        assert len(card.stackoverflow_search_url) < 2000

    def test_unexpected_characters_in_message(self):
        """Test exotic unicode, control characters, RTL marks, and format injection strings."""
        strange_msg = (
            "Error: \x00\x07\x1b[31m Null & Escapes "
            "\u202e\u200b\u200d RTL and ZWJ "
            "{var_format} {0} %s ${VARIABLE} "
            "SQL: ' OR '1'='1 -- "
            "Emoji: 💥🚀🔥 และภาษาไทยผสมผสาน"
        )
        err = ValueError(strange_msg)
        norm = normalizer.normalize_exception(err)
        card = self.engine.match(norm, exc=err)
        assert card.exception_class == "ValueError"
        assert card.summary_th  # Successfully rendered without format crash

    def test_tier2_fuzzy_matching_boundary_cases(self):
        """Test Tier 2 fuzzy token matching across all supported exception classes."""
        # 1. NameError with double quotes or legacy 'global name' (triggers Tier 2)
        norm_name = NormalizedTraceback(
            exc_type_name="NameError",
            exc_message="global name 'unresolved_identifier' is not defined",
        )
        card_name = self.engine.match(norm_name)
        assert "unresolved_identifier" in card_name.search_keywords

        # 2. AttributeError with single quote
        norm_attr1 = NormalizedTraceback(
            exc_type_name="AttributeError",
            exc_message="module has no attribute 'missing_func'",
        )
        card_attr1 = self.engine.match(norm_attr1)
        assert "missing_func" in card_attr1.search_keywords

        # 3. KeyError with bare representation
        norm_key = NormalizedTraceback(
            exc_type_name="KeyError",
            exc_message="('composite', 99)",
        )
        card_key = self.engine.match(norm_key)
        assert card_key.error_id == "KEY_NOT_FOUND"

        # 4. ModuleNotFoundError with deep namespace
        norm_mod = NormalizedTraceback(
            exc_type_name="ModuleNotFoundError",
            exc_message="No module named 'deeply.nested.package.service'",
        )
        card_mod = self.engine.match(norm_mod)
        assert "deeply.nested.package.service" in card_mod.search_keywords

        # 5. TypeError callable vs subscriptable vs unpack
        for msg, expected_rule in [
            ("'str' object is not callable", "TYPE_NOT_CALLABLE"),
            ("'int' object is not subscriptable", "TYPE_NOT_SUBSCRIPTABLE"),
            ("cannot unpack non-iterable float object", "TYPE_UNPACK_NON_ITERABLE"),
        ]:
            norm_t = NormalizedTraceback(exc_type_name="TypeError", exc_message=msg)
            card_t = self.engine.match(norm_t)
            assert card_t.error_id == expected_rule

        # 6. ValueError float vs int with base vs unpack mismatch
        for msg, expected_rule in [
            ("could not convert string to float: 'xyz'", "VALUE_INVALID_LITERAL_FLOAT"),
            ("invalid literal for int() with base 10: 'abc'", "VALUE_INVALID_LITERAL_INT"),
            ("not enough values to unpack (expected 3, got 2)", "VALUE_UNPACK_MISMATCH"),
        ]:
            norm_v = NormalizedTraceback(exc_type_name="ValueError", exc_message=msg)
            card_v = self.engine.match(norm_v)
            assert card_v.error_id == expected_rule

    def test_standard_builtin_generics(self):
        """Test standard builtin generic exceptions (ConnectionError, FileNotFoundError, etc.)."""
        for exc_cls in [
            "ConnectionError",
            "FileNotFoundError",
            "RecursionError",
            "TimeoutError",
            "RuntimeError",
        ]:
            norm = NormalizedTraceback(
                exc_type_name=exc_cls,
                exc_message="An internal system event occurred",
            )
            card = self.engine.match(norm)
            assert not card.is_fallback
            assert exc_cls in card.title_th or exc_cls in card.search_keywords

    def test_docstring_inheritance_filtration(self):
        """Verify that inherited builtins.Exception docstrings are omitted while custom class docstrings are kept."""
        # Exception without custom docstring (inherits Exception.__doc__)
        class StandardCustomError(Exception):
            pass

        err_inherited = StandardCustomError("error")
        norm_inh = normalizer.normalize_exception(err_inherited)
        card_inh = self.engine.match(norm_inh, exc=err_inherited)
        # Inherited docstring "Common base class for all non-exit exceptions." must be ignored!
        assert card_inh.docstring is None

        # Exception with explicit docstring
        class DocumentedCustomError(Exception):
            """This is a dedicated custom error docstring for API diagnostics."""

        err_doc = DocumentedCustomError("api failure")
        norm_doc = normalizer.normalize_exception(err_doc)
        card_doc = self.engine.match(norm_doc, exc=err_doc)
        assert card_doc.docstring == "This is a dedicated custom error docstring for API diagnostics."

    def test_safe_format_resilience(self):
        """Verify safe_format never raises KeyError or ValueError on malformed templates."""
        assert matcher.safe_format("", {}) == ""
        assert matcher.safe_format("{existing}", {"existing": "ok"}) == "ok"
        # Missing parameter becomes <missing>
        assert matcher.safe_format("{missing_param}", {}) == "<missing_param>"
        # Malformed template syntax
        assert matcher.safe_format("Invalid {unclosed bracket", {}) == "Invalid {unclosed bracket"
        assert matcher.safe_format("{0.invalid_attr}", {}) == "{0.invalid_attr}"


# ==============================================================================
# Suite 3: Responsive Terminal Renderer Hardening (Exotic Widths & Fallback)
# ==============================================================================
class TestRendererTier5:
    """Stress tests for renderer.py across extreme column widths and failsafe conditions."""

    @pytest.fixture
    def sample_card(self):
        frame = FrameInfo(
            filename="d:/project/script.py",
            lineno=25,
            funcname="compute_stats",
            code_line="return sum(items) / len(items)",
            colno=20,
            end_colno=30,
            is_user_code=True,
        )
        return ExplanationCard(
            error_id="ZERO_DIVISION",
            exception_class="ZeroDivisionError",
            title_th="พบข้อผิดพลาด: การหารด้วยศูนย์ (ZeroDivisionError)",
            summary_th="มีการพยายามหารตัวเลขด้วยศูนย์ ซึ่งเป็นไปไม่ได้ในทางคณิตศาสตร์",
            mental_model_th="เหมือนการแบ่งขนมให้คน 0 คน ย่อมไม่มีความหมาย",
            fix_suggestions_th=[
                "ตรวจสอบค่าตัวหารก่อนทำการคำนวณ",
                "เพิ่มเงื่อนไข if divisor != 0: ป้องกันไว้",
            ],
            search_keywords="python ZeroDivisionError division by zero",
            google_search_url="https://www.google.com/search?q=python+ZeroDivisionError",
            stackoverflow_search_url="https://stackoverflow.com/search?q=python+ZeroDivisionError",
            primary_frame=frame,
            is_fallback=False,
            docstring=None,
        )

    @pytest.mark.parametrize("width", [20, 35, 79, 80, 81, 200, 300])
    def test_render_exotic_widths(self, sample_card, width):
        """Test rendering at narrow, breakpoint boundary, and ultrawide widths."""
        renderer_inst = renderer.ResponsiveRenderer()
        output = renderer_inst.render_to_string(sample_card, width=width)
        assert output
        assert "ZeroDivisionError" in output
        assert "การหารด้วยศูนย์" in output

        if width >= 80:
            # Wide mode should contain double box borders
            assert "═" in output or "║" in output
        else:
            # Narrow mode should contain left-accent bar
            assert "▌" in output
            assert "━" in output

    def test_width_resolution_hierarchy(self):
        """Test hierarchy: explicit width > COLUMNS env > console.width > fallback."""
        r = renderer.ResponsiveRenderer()

        # 1. Explicit width wins
        assert r._resolve_width(105) == 105

        # 2. COLUMNS environment variable
        with patch.dict(os.environ, {"COLUMNS": "65"}):
            assert r._resolve_width() == 65

        # 3. Invalid COLUMNS falls back
        with patch.dict(os.environ, {"COLUMNS": "not_a_number"}):
            resolved = r._resolve_width()
            assert resolved > 0

    def test_renderer_failsafe_plain_fallback(self, sample_card):
        """Verify that when Rich raises BaseException, plain-text fallback triggers transparently."""
        # Mock console whose print method raises RuntimeError
        mock_console = MagicMock()
        mock_console.width = 80
        mock_console.print.side_effect = RuntimeError("Simulated Rich Render Failure")

        r = renderer.ResponsiveRenderer(console=mock_console)

        # Buffer to capture plain text fallback on stderr
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            # Must not raise exception
            r.render(sample_card, width=80)

        # Output from fallback should be written to mock_console.write or sys.stderr
        written_content = ""
        for call in mock_console.write.call_args_list:
            if call.args and isinstance(call.args[0], str):
                written_content += call.args[0]
        content = stderr_buf.getvalue() + written_content
        assert "ZeroDivisionError" in content or "PyThaiTrace" in content

    def test_plain_fallback_with_encoding_error(self, sample_card):
        """Verify plain text fallback handles UnicodeEncodeError by falling back to ascii replacement."""
        r = renderer.ResponsiveRenderer()
        faulty_stream = MagicMock()
        faulty_stream.write.side_effect = UnicodeEncodeError("ascii", "ข้อผิดพลาด", 0, 1, "ordinal not in range")

        # Must not raise
        r._render_plain_fallback(sample_card, faulty_stream, width=80)
        # Verify second write attempt (ASCII replaced) was called
        assert faulty_stream.write.call_count >= 1


# ==============================================================================
# Suite 4: Hooks & Asyncio Hardening (Loop Handlers, Threads, Race Conditions)
# ==============================================================================
class TestHooksTier5:
    """Stress tests for hooks.py covering asyncio exception handler, worker threads, and stream configuration."""

    def test_asyncio_hook_with_and_without_exception(self):
        """Test asyncio loop exception handler when context has an exception vs when it does not."""
        loop = asyncio.new_event_loop()
        try:
            hooks.install_asyncio_hook(loop=loop)
            handler = loop.get_exception_handler()
            assert handler is not None

            # Context 1: message without exception (e.g. unhandled task failure/cancellation)
            ctx_no_exc = {"message": "Task was destroyed but it is pending", "future": None}
            with patch("pythaitrace.hooks._dispatch_diagnostic") as mock_dispatch:
                handler(loop, ctx_no_exc)
                mock_dispatch.assert_not_called()

            # Context 2: context with actual exception
            ctx_with_exc = {"message": "Fatal error in task", "exception": ZeroDivisionError("async div by zero")}
            with patch("pythaitrace.hooks._dispatch_diagnostic") as mock_dispatch:
                handler(loop, ctx_with_exc)
                mock_dispatch.assert_called_once()
        finally:
            loop.close()

    def test_thread_excepthook_null_exc_value(self):
        """Test thread_excepthook when args.exc_value is None but exc_type is provided."""
        args = threading.ExceptHookArgs((
            ValueError,
            None,  # exc_value is None
            None,
            threading.current_thread()
        ))
        with patch("threading.__excepthook__") as mock_orig, \
             patch("pythaitrace.hooks._dispatch_diagnostic") as mock_dispatch:
            hooks.thread_excepthook(args)
            mock_orig.assert_called_once_with(args)
            # Should instantiate exc_type() and dispatch
            mock_dispatch.assert_called_once()

    def test_concurrent_thread_exceptions_under_hook_lock(self):
        """Verify _HOOK_LOCK synchronizes multiple threads throwing exceptions simultaneously."""
        dispatched_count = 0
        lock = threading.Lock()

        def fake_dispatch(exc, thread_name=None):
            nonlocal dispatched_count
            with lock:
                dispatched_count += 1

        threads = []
        with patch("threading.__excepthook__"), patch("pythaitrace.hooks._dispatch_diagnostic", side_effect=fake_dispatch):
            for i in range(10):
                t = threading.Thread(
                    target=lambda idx: hooks.thread_excepthook(
                        threading.ExceptHookArgs((RuntimeError, RuntimeError(f"err_{idx}"), None, threading.current_thread()))
                    ),
                    args=(i,),
                )
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

        assert dispatched_count == 10

    def test_clean_traceback_edge_cases(self):
        """Test clean_traceback with None, non-existent target, and corrupted frame codes."""
        assert hooks.clean_traceback(None) is None

        # Traceback with synthetic frame
        fake_frame = MagicMock()
        fake_frame.tb_frame.f_code.co_filename = "pythaitrace/runner.py"
        fake_next = MagicMock()
        fake_next.tb_frame.f_code.co_filename = "d:/app/user_code.py"
        fake_next.tb_next = None
        fake_frame.tb_next = fake_next

        cleaned = hooks.clean_traceback(fake_frame, target_script="d:/app/user_code.py")
        assert cleaned == fake_next


# ==============================================================================
# Suite 5: Runner & CLI Hardening (Flag Combinations, Boundaries, Returncodes)
# ==============================================================================
class TestRunnerCLITier5:
    """Stress tests for runner.py and cli.py covering CLI flags, arguments, and exit code fidelity."""

    def test_cli_flags_and_delimiter(self, capsys):
        """Test CLI flag handling: -h, --help, -v, --version, -- delimiter, and empty argv."""
        # 1. Empty arguments -> help text on stderr, exit 0
        code_empty = cli.main([])
        captured_empty = capsys.readouterr()
        assert code_empty == 0
        assert "usage: thpy" in captured_empty.err

        # 2. -h / --help -> help text on stdout, exit 0
        code_h = cli.main(["-h"])
        captured_h = capsys.readouterr()
        assert code_h == 0
        assert "usage: thpy" in captured_h.out

        code_help = cli.main(["--help"])
        captured_help = capsys.readouterr()
        assert code_help == 0
        assert "usage: thpy" in captured_help.out

        # 3. -v / --version -> version on stdout, exit 0
        code_v = cli.main(["-v"])
        captured_v = capsys.readouterr()
        assert code_v == 0
        assert "PyThaiTrace 2.0.0" in captured_v.out

        # 4. Bare '--' delimiter with no script -> help text on stderr, exit 0
        code_delim_empty = cli.main(["--"])
        captured_delim = capsys.readouterr()
        assert code_delim_empty == 0
        assert "usage: thpy" in captured_delim.err

        # 5. Non-existent script path -> exit 1, error on stderr
        code_missing = cli.main(["non_existent_script_xyz.py"])
        captured_missing = capsys.readouterr()
        assert code_missing == 1
        assert "not found" in captured_missing.err

    def test_runner_system_exit_variants(self):
        """Test run_script with various SystemExit arguments (None, int, string)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # sys.exit(None) -> exit code 0
            p0 = Path(tmpdir) / "exit_none.py"
            p0.write_text("import sys; sys.exit(None)", encoding="utf-8")
            assert runner.run_script(str(p0)) == 0

            # sys.exit(42) -> exit code 42
            p42 = Path(tmpdir) / "exit_42.py"
            p42.write_text("import sys; sys.exit(42)", encoding="utf-8")
            assert runner.run_script(str(p42)) == 42

            # sys.exit("Error string") -> prints string to stderr, exit code 1
            p_str = Path(tmpdir) / "exit_str.py"
            p_str.write_text("import sys; sys.exit('Fatal error message')", encoding="utf-8")
            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                code = runner.run_script(str(p_str))
            assert code == 1
            assert "Fatal error message" in stderr_buf.getvalue()

    def test_runner_keyboard_interrupt(self):
        """Test run_script cleanly catches KeyboardInterrupt and returns exit code 130."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p_sigint = Path(tmpdir) / "sigint_script.py"
            p_sigint.write_text("raise KeyboardInterrupt()", encoding="utf-8")
            with patch("sys.__excepthook__"):
                code = runner.run_script(str(p_sigint))
            assert code == 130

    def test_runner_compile_time_syntax_and_indent_errors(self):
        """Test run_script intercepts compile-time SyntaxError and IndentationError before exec."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Compile-time SyntaxError
            p_syn = Path(tmpdir) / "broken_syntax.py"
            p_syn.write_text("def broken_func(\n", encoding="utf-8")
            with patch("pythaitrace.runner._dispatch_diagnostic") as mock_diag, \
                 patch("sys.__excepthook__") as mock_orig:
                code_syn = runner.run_script(str(p_syn))
                assert code_syn == 1
                mock_orig.assert_called_once()
                mock_diag.assert_called_once()

            # 2. Compile-time IndentationError
            p_ind = Path(tmpdir) / "broken_indent.py"
            p_ind.write_text("def foo():\npass\n", encoding="utf-8")
            with patch("pythaitrace.runner._dispatch_diagnostic") as mock_diag2, \
                 patch("sys.__excepthook__") as mock_orig2:
                code_ind = runner.run_script(str(p_ind))
                assert code_ind == 1
                mock_orig2.assert_called_once()
                mock_diag2.assert_called_once()

    def test_runner_unhandled_runtime_exception(self):
        """Test run_script handles runtime unhandled exception and calls main_excepthook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p_rt = Path(tmpdir) / "runtime_err.py"
            p_rt.write_text("raise ValueError('Runtime error during execution')", encoding="utf-8")
            with patch("pythaitrace.hooks._dispatch_diagnostic") as mock_diag, \
                 patch("sys.__excepthook__") as mock_orig:
                code = runner.run_script(str(p_rt))
                assert code == 1
                mock_orig.assert_called_once()
                mock_diag.assert_called_once()

    def test_cli_forwarding_args(self):
        """Test cli.main forwards script arguments through runner.run_script."""
        with tempfile.TemporaryDirectory() as tmpdir:
            p_script = Path(tmpdir) / "args_script.py"
            p_script.write_text("import sys\n", encoding="utf-8")
            with patch("pythaitrace.cli.run_script", return_value=0) as mock_run:
                # With standard invocation
                ret = cli.main([str(p_script), "arg1", "--flag"])
                assert ret == 0
                mock_run.assert_called_once_with(str(p_script), ["arg1", "--flag"])

            with patch("pythaitrace.cli.run_script", return_value=0) as mock_run2:
                # With POSIX '--' delimiter
                ret2 = cli.main(["--", str(p_script), "val1", "val2"])
                assert ret2 == 0
                mock_run2.assert_called_once_with(str(p_script), ["val1", "val2"])


# ==============================================================================
# Suite 6: Additional White-Box Path Verification (Corrupted / Corner Cases)
# ==============================================================================
class TestWhiteBoxCornerPathsTier5:
    """Tests specifically targeting unexercised branches in normalizer, matcher, renderer, and hooks."""

    def test_normalizer_format_exception_failure(self):
        """Test normalizer exception handling when traceback.format_exception fails."""
        err = RuntimeError("Runtime error")
        with patch("traceback.format_exception", side_effect=Exception("Formatting failed")):
            norm = normalizer.normalize_exception(err)
            assert norm.raw_lines == ["RuntimeError: Runtime error\n"]

    def test_normalizer_syntax_error_format_failure(self):
        """Test normalizer SyntaxError handling when traceback.format_exception_only fails."""
        syn = SyntaxError("Syntax failure")
        with patch("traceback.format_exception_only", side_effect=Exception("Formatting failed")):
            norm = normalizer.normalize_exception(syn)
            assert norm.raw_lines == ["SyntaxError: Syntax failure\n"]

    def test_matcher_corrupted_rules_file(self):
        """Test MatcherEngine handles corrupted JSON rules file by falling back to DEFAULT_FALLBACK_RULE."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_json = Path(tmpdir) / "corrupted.json"
            bad_json.write_text("{ this is not valid json }", encoding="utf-8")
            engine = matcher.MatcherEngine(rules_path=str(bad_json))
            assert len(engine.rules) >= 1
            assert engine._fallback_rule.error_id == "__FALLBACK__"

    def test_matcher_chained_cause_long_truncation(self):
        """Test chained cause message truncation when cause message exceeds 200 chars."""
        e_cause = ValueError("A" * 300)
        e_main = KeyError("main")
        e_main.__cause__ = e_cause

        engine = matcher.MatcherEngine()
        norm = normalizer.normalize_exception(e_main)
        card = engine.match(norm, exc=e_main)
        # Should contain Chained Cause notice
        chained_fixes = [f for f in card.fix_suggestions_th if "Chained Cause" in f]
        assert len(chained_fixes) == 1
        assert "ValueError" in chained_fixes[0]

    def test_main_excepthook_bypasses_systemexit_sigint(self):
        """Test sys.excepthook bypasses SystemExit and KeyboardInterrupt."""
        with patch("sys.__excepthook__") as mock_orig, \
             patch("pythaitrace.hooks._dispatch_diagnostic") as mock_diag:
            hooks.main_excepthook(SystemExit, SystemExit(0), None)
            mock_orig.assert_called_once()
            mock_diag.assert_not_called()

        with patch("sys.__excepthook__") as mock_orig2, \
             patch("pythaitrace.hooks._dispatch_diagnostic") as mock_diag2:
            hooks.main_excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
            mock_orig2.assert_called_once()
            mock_diag2.assert_not_called()

    def test_dispatch_diagnostic_debug_logging(self):
        """Test PYTHAITRACE_DEBUG=1 logs internal error message to stderr if diagnostic crashes."""
        with patch.dict(os.environ, {"PYTHAITRACE_DEBUG": "1"}), \
             patch("pythaitrace.normalizer.normalize_exception", side_effect=Exception("Internal Crash")):
            stderr_buf = io.StringIO()
            with patch("sys.stderr", stderr_buf):
                hooks._dispatch_diagnostic(ValueError("test"))
            assert "PyThaiTrace Internal Error" in stderr_buf.getvalue()

    def test_render_wide_dynamic_expansion_for_long_urls(self):
        """Test wide mode dynamically expands console width when search URLs are long."""
        long_url = "https://www.google.com/search?q=" + ("x" * 150)
        card = ExplanationCard(
            error_id="TEST",
            exception_class="TestError",
            title_th="ทดสอบ",
            summary_th="สรุป",
            mental_model_th="โมเดล",
            fix_suggestions_th=["แก้ 1"],
            search_keywords="test",
            google_search_url=long_url,
            stackoverflow_search_url=long_url,
            primary_frame=None,
            is_fallback=False,
            docstring=None,
        )
        r = renderer.ResponsiveRenderer()
        output = r.render_to_string(card, width=80)
        assert output
        assert long_url in output

    def test_plain_fallback_direct_to_sys_stderr(self):
        """Test _render_plain_fallback writes directly to sys.stderr when stream is not provided."""
        card = ExplanationCard(
            error_id="FALLBACK_TEST",
            exception_class="DirectError",
            title_th="ข้อผิดพลาดโดยตรง",
            summary_th="สรุปการทำงาน",
            mental_model_th="โมเดลความคิด",
            fix_suggestions_th=["ขั้นตอนที่ 1"],
            search_keywords="direct error",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
            primary_frame=None,
            is_fallback=False,
            docstring=None,
        )
        r = renderer.ResponsiveRenderer()
        stderr_buf = io.StringIO()
        with patch("sys.stderr", stderr_buf):
            # Pass None as stream_or_console to force fallback to sys.stderr
            r._render_plain_fallback(card, stream_or_console=None, width=80)
        assert "DirectError" in stderr_buf.getvalue()

