"""
PyThaiTrace v2.0 - Traceback Normalizer (normalizer.py)
Sanitizes raw tracebacks, strips ANSI sequences, extracts PEP 657 coordinates,
isolates primary culprit user frames, and normalizes SyntaxError attributes.
"""

from __future__ import annotations
import inspect
import linecache
import os
import re
import sys
import sysconfig
import traceback
from typing import List, Optional, Tuple

from pythaitrace.models import FrameInfo, NormalizedTraceback

# ANSI escape sequence regex covering SGR, CSI, OSC, and 8-bit escape codes.
# OSC sequences take precedence over 2-char escapes to avoid clipping at \x1b]
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1B(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-Z\\-_])"
)

# Caret line pattern in Python 3.11+ tracebacks (e.g. '    ~~~~~^^^^^~~~~')
CARET_LINE_PATTERN = re.compile(r"^\s*[\^~]+\s*$")

# Suggestion pattern for Python 3.10+ "Did you mean: '...'?"
DID_YOU_MEAN_PATTERN = re.compile(r"\.\s+Did you mean:\s+'(?P<sug>[^']+)'\?")

# Frame header pattern in formatted tracebacks
FRAME_HEADER_PATTERN = re.compile(
    r'^\s*File\s+"(?P<fn>[^"]+)",\s+line\s+(?P<ln>\d+)(?:,\s+in\s+(?P<name>.*))?$'
)


def strip_ansi(text: Optional[str]) -> str:
    """
    Strips all ANSI escape codes (colors, cursor movements, hyperlinks)
    from text safely. Returns empty string if input is None or empty.
    """
    if not text:
        return ""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def is_user_frame(filename: Optional[str]) -> bool:
    """
    Determines whether a stack frame originates from user project code
    versus Python standard library, site-packages, or pythaitrace internals.
    """
    if not filename:
        return False

    # Pseudo-files / dynamic code
    if filename.startswith("<") and filename.endswith(">"):
        # <stdin> or <string> or <ipython-input...> can be user code
        if "frozen" in filename:
            return False
        return True

    try:
        norm_path = os.path.normcase(os.path.abspath(filename))
    except Exception:
        norm_path = os.path.normcase(filename)

    # Ignore pythaitrace internal package files
    try:
        pkg_dir = os.path.normcase(os.path.abspath(os.path.dirname(__file__)))
        if norm_path.startswith(pkg_dir):
            return False
    except Exception:
        pass

    # Also check relative module paths for pythaitrace internals
    raw_norm = os.path.normcase(filename)
    rel_patterns = (
        "pythaitrace" + os.sep,
        "pythaitrace/",
        "src" + os.sep + "pythaitrace" + os.sep,
        "src/pythaitrace/",
    )
    if any(raw_norm.startswith(p) or (os.sep + "pythaitrace" + os.sep) in norm_path or "/pythaitrace/" in norm_path.replace("\\", "/") for p in rel_patterns):
        return False

    # Ignore standard runner entrypoints
    if norm_path.endswith(os.path.normcase("runpy.py")):
        return False

    # Ignore third-party packages (site-packages / dist-packages)
    if "site-packages" in norm_path or "dist-packages" in norm_path:
        return False

    # Ignore Python standard library files
    try:
        stdlib_path = os.path.normcase(os.path.abspath(sysconfig.get_path("stdlib")))
        if norm_path.startswith(stdlib_path):
            return False
    except Exception:
        pass

    try:
        base_lib = os.path.normcase(
            os.path.abspath(getattr(sys, "base_prefix", sys.prefix) + os.sep + "Lib")
        )
        if norm_path.startswith(base_lib):
            return False
    except Exception:
        pass

    return True


def extract_frames_from_exception(
    exc: BaseException,
) -> Tuple[List[FrameInfo], Optional[FrameInfo]]:
    """
    Extracts structured FrameInfo models from an exception's __traceback__,
    preserving PEP 657 fine-grained column positions, and isolating the
    primary culprit user frame.
    """
    frames: List[FrameInfo] = []
    tb = exc.__traceback__
    if not tb:
        return frames, None

    try:
        extracted = traceback.extract_tb(tb)
    except Exception:
        extracted = []

    for fs in extracted:
        fn = fs.filename or "<unknown>"
        try:
            lno = int(fs.lineno) if fs.lineno is not None else 1
            if lno <= 0:
                lno = 1
        except (TypeError, ValueError):
            lno = 1
        name = fs.name or "<module>"
        code_line = fs.line or ""

        # Fallback to linecache if source line is empty and file exists
        if not code_line and fn and not (fn.startswith("<") and fn.endswith(">")):
            try:
                code_line = linecache.getline(fn, lno).rstrip("\r\n")
            except Exception:
                code_line = ""

        # PEP 657 column coordinates
        try:
            raw_col = getattr(fs, "colno", None)
            colno = int(raw_col) if raw_col is not None else None
        except (TypeError, ValueError):
            colno = None

        try:
            raw_end = getattr(fs, "end_colno", None)
            end_colno = int(raw_end) if raw_end is not None else None
        except (TypeError, ValueError):
            end_colno = None

        user_code = is_user_frame(fn)

        frame = FrameInfo(
            filename=fn,
            lineno=lno,
            funcname=name,
            code_line=code_line.strip(),
            colno=colno,
            end_colno=end_colno,
            is_user_code=user_code,
        )
        frames.append(frame)

    # Primary culprit frame determination:
    # 1. Last frame marked as user code
    # 2. If no user frame exists (e.g. crash entirely in stdlib), last frame overall
    primary_frame: Optional[FrameInfo] = None
    user_frames = [f for f in frames if f.is_user_code]
    if user_frames:
        primary_frame = user_frames[-1]
    elif frames:
        primary_frame = frames[-1]

    return frames, primary_frame


def normalize_exception(exc: BaseException) -> NormalizedTraceback:
    """
    Converts any Python exception into a structured NormalizedTraceback.
    Handles SyntaxError/IndentationError coordinates directly from the exception
    instance, captures runtime traceback frames with PEP 657 positions, extracts
    PEP 678 notes, Python 3.10+ suggestions, and cleans ANSI sequences.
    """
    exc_type_name = type(exc).__name__
    try:
        exc_module = getattr(type(exc), "__module__", "builtins") or "builtins"
    except Exception:
        exc_module = "builtins"

    # Clean error message extraction
    if isinstance(exc, SyntaxError) and getattr(exc, "msg", None):
        raw_msg = exc.msg
    else:
        try:
            raw_msg = str(exc)
        except Exception:
            raw_msg = f"<{exc_type_name} unprintable>"

    clean_msg = strip_ansi(raw_msg).strip()

    # Did you mean suggestion extraction
    suggestion: Optional[str] = None
    sug_match = DID_YOU_MEAN_PATTERN.search(clean_msg)
    if sug_match:
        suggestion = sug_match.group("sug")

    # Notes (PEP 678)
    notes: List[str] = []
    try:
        raw_notes = getattr(exc, "__notes__", []) or []
        for n in raw_notes:
            try:
                notes.append(str(n))
            except Exception:
                notes.append("<unprintable note>")
    except Exception:
        notes = []

    # Docstring
    docstring: Optional[str] = None
    try:
        docstring = inspect.getdoc(type(exc)) or getattr(type(exc), "__doc__", None)
        if docstring and not isinstance(docstring, str):
            docstring = None
    except Exception:
        docstring = None

    # Branch for compile-time SyntaxError / IndentationError
    if isinstance(exc, SyntaxError):
        fn = getattr(exc, "filename", None) or "<string>"
        try:
            lno = int(exc.lineno) if getattr(exc, "lineno", None) is not None else 1
            if lno <= 0:
                lno = 1
        except (TypeError, ValueError):
            lno = 1

        try:
            colno = int(exc.offset) if getattr(exc, "offset", None) is not None else None
        except (TypeError, ValueError):
            colno = None

        try:
            raw_end = getattr(exc, "end_offset", None)
            end_colno = int(raw_end) if raw_end is not None else None
        except (TypeError, ValueError):
            end_colno = None

        text = (getattr(exc, "text", None) or "").rstrip("\r\n")

        if not text and fn and not (fn.startswith("<") and fn.endswith(">")):
            try:
                text = linecache.getline(fn, lno).rstrip("\r\n")
            except Exception:
                text = ""

        primary = FrameInfo(
            filename=fn,
            lineno=lno,
            funcname="<syntax_check>",
            code_line=text.strip(),
            colno=colno,
            end_colno=end_colno,
            is_user_code=True,
        )

        try:
            raw_lines = traceback.format_exception_only(type(exc), exc)
        except Exception:
            raw_lines = [f"{exc_type_name}: {clean_msg}\n"]

        return NormalizedTraceback(
            exc_type_name=exc_type_name,
            exc_message=clean_msg,
            frames=[primary],
            primary_frame=primary,
            is_syntax_error=True,
            raw_lines=raw_lines,
            clean_text="".join(strip_ansi(line) for line in raw_lines),
            suggestion=suggestion,
            notes=notes,
            docstring=docstring,
            exception_module=exc_module,
        )

    # Runtime exception branch
    frames, primary_frame = extract_frames_from_exception(exc)

    try:
        raw_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    except Exception:
        raw_lines = [f"{exc_type_name}: {clean_msg}\n"]

    clean_text = "".join(strip_ansi(line) for line in raw_lines)

    return NormalizedTraceback(
        exc_type_name=exc_type_name,
        exc_message=clean_msg,
        frames=frames,
        primary_frame=primary_frame,
        is_syntax_error=False,
        raw_lines=raw_lines,
        clean_text=clean_text,
        suggestion=suggestion,
        notes=notes,
        docstring=docstring,
        exception_module=exc_module,
    )


def normalize_traceback_str(tb_str: str) -> NormalizedTraceback:
    """
    Parses a formatted string traceback (e.g. captured from stderr or logs),
    strips ANSI codes, reconstructs FrameInfo items including caret positions,
    and isolates the culprit frame.
    """
    clean_str = strip_ansi(tb_str)
    lines = clean_str.splitlines()

    # Find the exception line (typically the last non-empty line)
    exc_type_name = "Exception"
    exc_message = ""
    is_syntax_error = False

    # First pass: prioritize lines with ExcClass: message format
    for line in reversed(lines):
        line_s = line.strip()
        if not line_s or line_s.startswith("Traceback") or line_s.startswith("During handling"):
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\.]*):\s*(.*)$", line_s)
        if m:
            exc_type_name = m.group(1).split(".")[-1]
            exc_message = m.group(2) or ""
            if "SyntaxError" in exc_type_name or "IndentationError" in exc_type_name:
                is_syntax_error = True
            break
    else:
        # Fallback pass: bare exception class name
        for line in reversed(lines):
            line_s = line.strip()
            if not line_s or line_s.startswith("Traceback") or line_s.startswith("During handling"):
                continue
            m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_\.]*)$", line_s)
            if m:
                exc_type_name = m.group(1).split(".")[-1]
                exc_message = ""
                if "SyntaxError" in exc_type_name or "IndentationError" in exc_type_name:
                    is_syntax_error = True
                break

    # Parse frames
    frames: List[FrameInfo] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FRAME_HEADER_PATTERN.match(line)
        if m:
            fn = m.group("fn")
            lno = int(m.group("ln"))
            name = m.group("name") or "<module>"
            code_line = ""
            colno: Optional[int] = None
            end_colno: Optional[int] = None

            # Next line may be code line
            if i + 1 < len(lines):
                next_raw = lines[i + 1]
                next_strip = next_raw.strip()
                is_header = bool(FRAME_HEADER_PATTERN.match(next_raw))
                is_caret = bool(CARET_LINE_PATTERN.match(next_raw))
                is_exc = bool(
                    re.match(r"^[A-Za-z_][a-zA-Z0-9_\.]*(?:Error|Exception|Interrupt|Exit|Warning)?(?::|$)", next_strip)
                    or next_strip.startswith("File ")
                    or next_strip.startswith("Traceback")
                    or next_strip.startswith("During handling")
                    or (exc_type_name and (next_strip == exc_type_name or next_strip.startswith(f"{exc_type_name}:")))
                )
                if not is_header and not is_caret and not is_exc:
                    code_line = next_strip
                    i += 1

                # Line after code line may be caret line
                if i + 1 < len(lines) and CARET_LINE_PATTERN.match(lines[i + 1]):
                    caret_line = lines[i + 1]
                    colno = len(caret_line) - len(caret_line.lstrip()) + 1
                    end_colno = len(caret_line.rstrip()) + 1
                    i += 1

            frame = FrameInfo(
                filename=fn,
                lineno=lno,
                funcname=name,
                code_line=code_line,
                colno=colno,
                end_colno=end_colno,
                is_user_code=is_user_frame(fn),
            )
            frames.append(frame)
        i += 1

    primary_frame: Optional[FrameInfo] = None
    user_frames = [f for f in frames if f.is_user_code]
    if user_frames:
        primary_frame = user_frames[-1]
    elif frames:
        primary_frame = frames[-1]

    # Suggestion extraction
    suggestion: Optional[str] = None
    sug_match = DID_YOU_MEAN_PATTERN.search(exc_message)
    if sug_match:
        suggestion = sug_match.group("sug")

    return NormalizedTraceback(
        exc_type_name=exc_type_name,
        exc_message=exc_message,
        frames=frames,
        primary_frame=primary_frame,
        is_syntax_error=is_syntax_error,
        raw_lines=[line + "\n" for line in lines],
        clean_text=clean_str,
        suggestion=suggestion,
        notes=[],
        docstring=None,
        exception_module="builtins",
    )
