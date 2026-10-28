"""
PyThaiTrace v2.0 - Adversarial Stress Test Suite for normalizer.py
Empirical Challenger verification: malformed tracebacks, deep recursion,
PEP 657 caret variations, missing traceback objects, malformed SyntaxErrors,
and embedded ANSI escape codes.
"""

import inspect
import sys
import pytest

from pythaitrace.normalizer import (
    strip_ansi,
    is_user_frame,
    extract_frames_from_exception,
    normalize_exception,
    normalize_traceback_str,
    ANSI_ESCAPE_PATTERN,
)
from pythaitrace.models import FrameInfo, NormalizedTraceback


# ============================================================================
# Category 1: Malformed / Corrupted String Tracebacks
# ============================================================================

class TestMalformedStringTracebacks:
    """Stress testing normalize_traceback_str with corrupted, truncated, and empty inputs."""

    def test_empty_string(self):
        norm = normalize_traceback_str("")
        assert isinstance(norm, NormalizedTraceback)
        assert norm.exc_type_name == "Exception"
        assert norm.exc_message == ""
        assert norm.frames == []
        assert norm.primary_frame is None
        assert norm.is_syntax_error is False
        assert norm.clean_text == ""

    def test_whitespace_and_newlines_only(self):
        norm = normalize_traceback_str("   \n\t\n  \r\n   ")
        assert isinstance(norm, NormalizedTraceback)
        assert norm.exc_type_name == "Exception"
        assert norm.exc_message == ""
        assert norm.frames == []
        assert norm.primary_frame is None

    def test_zero_frames_single_exception_line(self):
        tb_str = "ZeroDivisionError: division by zero"
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "ZeroDivisionError"
        assert norm.exc_message == "division by zero"
        assert norm.frames == []
        assert norm.primary_frame is None
        assert norm.is_syntax_error is False

    def test_exception_line_without_colon(self):
        tb_str = "ValueError"
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "ValueError"
        assert norm.exc_message == ""

    def test_exception_line_with_qualname_module(self):
        tb_str = "builtins.ValueError: bad value"
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "ValueError"
        assert norm.exc_message == "bad value"

    def test_syntax_error_type_detection(self):
        tb_str = "SyntaxError: invalid syntax"
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "SyntaxError"
        assert norm.is_syntax_error is True

        tb_indent = "IndentationError: unexpected indent"
        norm_indent = normalize_traceback_str(tb_indent)
        assert norm_indent.exc_type_name == "IndentationError"
        assert norm_indent.is_syntax_error is True

    def test_truncated_frames_no_in_clause(self):
        """Frame header missing ', in <func>' should still parse correctly."""
        tb_str = """Traceback (most recent call last):
  File "myscript.py", line 42
    result = compute()
ValueError: calculation error"""
        norm = normalize_traceback_str(tb_str)
        assert len(norm.frames) == 1
        frame = norm.frames[0]
        assert frame.filename == "myscript.py"
        assert frame.lineno == 42
        assert frame.funcname == "<module>"
        assert frame.code_line == "result = compute()"
        assert norm.primary_frame == frame
        assert norm.exc_type_name == "ValueError"
        assert norm.exc_message == "calculation error"

    def test_corrupted_frame_missing_line_number(self):
        """Corrupted frame headers without a valid line number should not crash parser."""
        tb_str = """Traceback (most recent call last):
  File "corrupt.py"
  File "valid.py", line 15, in foo
    return x + 1
KeyError: 'missing'"""
        norm = normalize_traceback_str(tb_str)
        # corrupt.py cannot match FRAME_HEADER_PATTERN, valid.py should match
        assert len(norm.frames) == 1
        assert norm.frames[0].filename == "valid.py"
        assert norm.frames[0].lineno == 15
        assert norm.exc_type_name == "KeyError"
        assert norm.exc_message == "'missing'"

    def test_chained_exceptions_extracts_innermost_last_exception(self):
        """Chained traceback with 'During handling...' should parse the final raised exception."""
        tb_str = """Traceback (most recent call last):
  File "first.py", line 10, in a
    int('abc')
ValueError: invalid literal for int() with base 10: 'abc'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "second.py", line 20, in b
    raise RuntimeError('Wrapper error')
RuntimeError: Wrapper error"""
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "RuntimeError"
        assert norm.exc_message == "Wrapper error"
        assert len(norm.frames) >= 2

    def test_non_ascii_unicode_in_traceback_string(self):
        """Thai characters and emojis in filenames, function names, and error messages."""
        tb_str = """Traceback (most recent call last):
  File "แอป/หลัก.py", line 8, in คำนวณยอด
    ยอด = เงิน / 0
ZeroDivisionError: ตัวหารเป็นศูนย์ 🚫"""
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "ZeroDivisionError"
        assert "ตัวหารเป็นศูนย์" in norm.exc_message
        assert len(norm.frames) == 1
        assert norm.frames[0].filename == "แอป/หลัก.py"
        assert norm.frames[0].funcname == "คำนวณยอด"
        assert norm.frames[0].code_line == "ยอด = เงิน / 0"

    def test_bug_frame_without_code_swallows_exception_line(self):
        """
        FIXED: When a traceback has frames without source code lines,
        the parser does NOT consume the exception line as the frame's code_line.
        """
        tb_str = """Traceback (most recent call last):
  File "worker.py", line 25, in run
RuntimeError: worker crashed"""
        norm = normalize_traceback_str(tb_str)
        assert len(norm.frames) == 1
        assert norm.frames[0].code_line == ""
        assert norm.exc_type_name == "RuntimeError"
        assert norm.exc_message == "worker crashed"


# ============================================================================
# Category 2: Deeply Recursive Stack Traces (500+ frames)
# ============================================================================

class TestDeeplyRecursiveStackTraces:
    """Stress testing with RecursionError exceeding 500+ frames."""

    def test_deep_recursion_exception_normalization(self):
        """Trigger actual RecursionError with 600+ frames and normalize."""
        def recursive_func(depth: int):
            if depth > 0:
                recursive_func(depth - 1)
            else:
                recursive_func(0)

        exc = None
        old_limit = sys.getrecursionlimit()
        try:
            sys.setrecursionlimit(1000)
            try:
                recursive_func(700)
            except RecursionError as e:
                exc = e
        finally:
            sys.setrecursionlimit(old_limit)

        assert exc is not None
        assert isinstance(exc, RecursionError)

        # Normalize exception object
        norm = normalize_exception(exc)
        assert isinstance(norm, NormalizedTraceback)
        assert norm.exc_type_name == "RecursionError"
        assert len(norm.frames) >= 500
        assert norm.primary_frame is not None
        assert norm.primary_frame.is_user_code is True

    def test_deep_recursion_traceback_string_normalization(self):
        """Format 600+ frame traceback into string and stress test normalize_traceback_str."""
        frame_lines = []
        for i in range(1, 601):
            frame_lines.append(f'  File "recursion_test.py", line {i}, in recurse')
            frame_lines.append(f'    recurse({i})')

        tb_str = (
            "Traceback (most recent call last):\n"
            + "\n".join(frame_lines)
            + "\nRecursionError: maximum recursion depth exceeded while calling a Python object"
        )

        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "RecursionError"
        assert len(norm.frames) == 600
        assert norm.primary_frame is not None
        assert norm.primary_frame.lineno == 600
        assert norm.primary_frame.code_line == "recurse(600)"


# ============================================================================
# Category 3: Multiline PEP 657 Caret Blocks with Mixed Tildes
# ============================================================================

class TestPEP657CaretBlocks:
    """Stress testing PEP 657 caret and tilde variations."""

    def test_mixed_tildes_and_carets_single_line(self):
        tb_str = """Traceback (most recent call last):
  File "math_ops.py", line 5, in add
    result = a.val + b.val
             ~~~~~^~~~~~~~
TypeError: unsupported operand type(s) for +: 'NoneType' and 'int'"""
        norm = normalize_traceback_str(tb_str)
        assert len(norm.frames) == 1
        frame = norm.frames[0]
        assert frame.code_line == "result = a.val + b.val"
        assert frame.colno is not None
        assert frame.end_colno is not None
        assert frame.colno == 14
        assert frame.end_colno == 27
        assert frame.caret_pointer is not None

    def test_caret_pointer_generation_from_frame(self):
        frame = FrameInfo(
            filename="test.py",
            lineno=1,
            funcname="test",
            code_line="return x[0]",
            colno=8,
            end_colno=12,
        )
        pointer = frame.caret_pointer
        assert pointer == "       ^^^^"  # 7 spaces + 4 carets

    def test_caret_line_with_only_carets(self):
        tb_str = """Traceback (most recent call last):
  File "call.py", line 12, in run
    do_something()
    ^^^^^^^^^^^^^^
RuntimeError: fail"""
        norm = normalize_traceback_str(tb_str)
        assert len(norm.frames) == 1
        frame = norm.frames[0]
        assert frame.colno == 5
        assert frame.end_colno == 19

    def test_multiline_expression_traceback(self):
        """Python 3.11+ multiline expression traceback containing multiple carets/tildes."""
        tb_str = """Traceback (most recent call last):
  File "multi.py", line 10, in combine
    'hello'
    ~~~~~~~
    +
    ^
    42
    ~~
TypeError: can only concatenate str (not "int") to str"""
        norm = normalize_traceback_str(tb_str)
        assert norm.exc_type_name == "TypeError"
        # Must not crash on multiline caret blocks
        assert len(norm.frames) >= 1
        assert norm.frames[0].filename == "multi.py"


# ============================================================================
# Category 4: Exceptions with No Traceback
# ============================================================================

class TestExceptionsWithNoTraceback:
    """Stress testing exceptions where exc.__traceback__ is None."""

    def test_unraised_exception_instance(self):
        exc = ValueError("This exception was never raised")
        assert exc.__traceback__ is None

        norm = normalize_exception(exc)
        assert norm.exc_type_name == "ValueError"
        assert norm.exc_message == "This exception was never raised"
        assert norm.frames == []
        assert norm.primary_frame is None
        assert norm.is_syntax_error is False
        assert len(norm.raw_lines) > 0
        assert "ValueError" in norm.clean_text

    def test_raised_then_cleared_traceback(self):
        try:
            1 / 0
        except ZeroDivisionError as e:
            e.__traceback__ = None
            norm = normalize_exception(e)
            assert norm.exc_type_name == "ZeroDivisionError"
            assert norm.frames == []
            assert norm.primary_frame is None

    def test_custom_exception_subclass_no_traceback(self):
        class MyCustomError(Exception):
            """A custom exception documentation."""
            pass

        exc = MyCustomError("custom failure")
        exc.__traceback__ = None
        norm = normalize_exception(exc)
        assert norm.exc_type_name == "MyCustomError"
        assert norm.exc_message == "custom failure"
        assert norm.docstring == "A custom exception documentation."
        assert norm.primary_frame is None


# ============================================================================
# Category 5: SyntaxError Variations (Missing Filename, None lineno, Negative Offsets)
# ============================================================================

class TestSyntaxErrorEdgeCases:
    """Stress testing compile-time SyntaxError edge cases."""

    def test_syntax_error_with_none_fields(self):
        exc = SyntaxError("invalid syntax")
        exc.filename = None
        exc.lineno = None
        exc.offset = None
        exc.text = None

        norm = normalize_exception(exc)
        assert norm.is_syntax_error is True
        assert norm.exc_type_name == "SyntaxError"
        assert norm.primary_frame is not None
        assert norm.primary_frame.filename == "<string>"
        assert norm.primary_frame.lineno == 1
        assert norm.primary_frame.colno is None
        assert norm.primary_frame.code_line == ""

    def test_syntax_error_with_negative_offset(self):
        exc = SyntaxError("weird offset", ("bad.py", 5, -3, "def func():\n"))
        norm = normalize_exception(exc)
        assert norm.primary_frame is not None
        assert norm.primary_frame.lineno == 5
        assert norm.primary_frame.colno == -3
        # Ensure caret_pointer property does not raise ValueError with negative offset
        pointer = norm.primary_frame.caret_pointer
        assert isinstance(pointer, str)

    def test_syntax_error_with_zero_offset_and_zero_lineno(self):
        exc = SyntaxError("zero coordinates")
        exc.filename = "zero.py"
        exc.lineno = 0
        exc.offset = 0
        exc.text = "x = "

        norm = normalize_exception(exc)
        assert norm.primary_frame is not None
        # 0 or 1 -> 1
        assert norm.primary_frame.lineno == 1
        assert norm.primary_frame.colno == 0
        assert norm.primary_frame.caret_pointer == "^"

    def test_indentation_error_handling(self):
        exc = IndentationError("unindent does not match any outer indentation level", ("indent.py", 10, 4, "    x = 1\n"))
        norm = normalize_exception(exc)
        assert norm.exc_type_name == "IndentationError"
        assert norm.is_syntax_error is True
        assert norm.primary_frame is not None
        assert norm.primary_frame.filename == "indent.py"
        assert norm.primary_frame.lineno == 10
        assert norm.primary_frame.colno == 4


# ============================================================================
# Category 6: ANSI Sequences Embedded in Messages and Filenames
# ============================================================================

class TestANSIEscapeSequences:
    """Stress testing ANSI sequence stripping across normalizer functions."""

    def test_strip_ansi_basic(self):
        sgr = "\x1b[31;1mRed Bold\x1b[0m"
        assert strip_ansi(sgr) == "Red Bold"

        csi_cursor = "\x1b[2J\x1b[HClean Screen"
        assert strip_ansi(csi_cursor) == "Clean Screen"

        none_input = strip_ansi(None)
        assert none_input == ""

    def test_bug_osc_hyperlink_not_stripped_due_to_regex_range(self):
        """
        FIXED: OSC sequences are cleanly stripped by ANSI_ESCAPE_PATTERN.
        """
        osc_hyperlink = "\x1b]8;;https://example.com\x1b\\Click Here\x1b]8;;\x1b\\"
        stripped = strip_ansi(osc_hyperlink)
        assert stripped == "Click Here"
        assert "8;;https://example.com" not in stripped

    def test_ansi_in_exception_message(self):
        colored_msg = "\x1b[31mCritical:\x1b[0m Failed with code \x1b[33m404\x1b[0m"
        exc = RuntimeError(colored_msg)
        norm = normalize_exception(exc)
        assert "\x1b" not in norm.exc_message
        assert norm.exc_message == "Critical: Failed with code 404"

    def test_ansi_in_string_traceback(self):
        ansi_tb = """\x1b[1mTraceback (most recent call last):\x1b[0m
  \x1b[34mFile "\x1b[32mmy_code.py\x1b[34m", line \x1b[33m10\x1b[34m, in \x1b[35mprocess\x1b[0m
    \x1b[37mval = 1 / 0\x1b[0m
    \x1b[31m~~~~~~^~~~~\x1b[0m
\x1b[31;1mZeroDivisionError\x1b[0m: \x1b[31mdivision by zero\x1b[0m"""
        norm = normalize_traceback_str(ansi_tb)
        assert norm.exc_type_name == "ZeroDivisionError"
        assert norm.exc_message == "division by zero"
        assert len(norm.frames) == 1
        frame = norm.frames[0]
        assert frame.filename == "my_code.py"
        assert frame.lineno == 10
        assert frame.funcname == "process"
        assert frame.code_line == "val = 1 / 0"
        assert "\x1b" not in norm.clean_text


# ============================================================================
# Category 7: Robustness & Unhandled Exception Bugs in normalize_exception
# ============================================================================

class TestRobustnessVulnerabilities:
    """Stress testing edge cases that can crash normalize_exception."""

    def test_bug_broken_str_crashes_normalize_exception(self):
        """
        FIXED: If an exception's __str__ raises an exception,
        normalize_exception falls back safely without crashing.
        """
        class BrokenStrException(Exception):
            def __str__(self):
                raise RuntimeError("broken __str__ implementation")

        exc = BrokenStrException("payload")
        norm = normalize_exception(exc)
        assert norm.exc_type_name == "BrokenStrException"
        assert "<BrokenStrException unprintable>" in norm.exc_message

    def test_bug_broken_doc_property_crashes_normalize_exception(self):
        """
        FIXED: If an exception's class has a broken __doc__ descriptor,
        normalize_exception handles it safely and sets docstring to None.
        """
        class BrokenDocMeta(type):
            @property
            def __doc__(cls):
                raise RuntimeError("broken __doc__ descriptor")

        class BrokenDocException(Exception, metaclass=BrokenDocMeta):
            pass

        exc = BrokenDocException("test")
        norm = normalize_exception(exc)
        assert norm.exc_type_name == "BrokenDocException"
        assert norm.docstring is None

    def test_bug_broken_notes_crashes_normalize_exception(self):
        """
        FIXED: If an exception's __notes__ contains an object whose __str__ raises,
        normalize_exception converts it safely to '<unprintable note>'.
        """
        class BrokenNote:
            def __str__(self):
                raise ValueError("cannot format note")

        exc = ValueError("test")
        exc.__notes__ = [BrokenNote()]
        norm = normalize_exception(exc)
        assert norm.exc_type_name == "ValueError"
        assert norm.notes == ["<unprintable note>"]

    def test_bug_syntax_error_non_int_lineno_raises_validation_error(self):
        """
        FIXED: If SyntaxError has a non-int lineno (e.g. str),
        normalize_exception defensively sanitizes it to 1 without validation error.
        """
        exc = SyntaxError("syntax error")
        exc.filename = "test.py"
        exc.lineno = "invalid_lineno"
        norm = normalize_exception(exc)
        assert norm.is_syntax_error is True
        assert norm.primary_frame is not None
        assert norm.primary_frame.lineno == 1
