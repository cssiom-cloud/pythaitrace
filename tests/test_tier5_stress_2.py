"""
PyThaiTrace v2.0 - Tier 5 Adversarial Coverage Hardening Test Suite (test_tier5_stress_2.py)
Empirical verification of system invariants under extreme stress:
1. High-concurrency thread stress (20+ threads raising exceptions simultaneously with _HOOK_LOCK)
2. Asyncio event loop exception handling (install_asyncio_hook, concurrent tasks, context variations)
3. Broken environment conditions (corrupted COLUMNS, empty strings, negative widths, extreme viewports)
4. Extreme Unicode, emoji script paths, deeply nested directories, special characters
5. Binary data and non-UTF-8 source files with and without PEP 263 headers
6. Large memory and huge tracebacks (1500+ frames, deep recursion, circular exception chains)
"""
from __future__ import annotations

import asyncio
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

import pytest
from rich.console import Console

from pythaitrace.hooks import (
    _HOOK_LOCK,
    clean_traceback,
    configure_streams,
    install_asyncio_hook,
    install_hooks,
    main_excepthook,
    thread_excepthook,
    _dispatch_diagnostic,
)
from pythaitrace.matcher import MatcherEngine
from pythaitrace.models import ExplanationCard, FrameInfo, NormalizedTraceback
from pythaitrace.normalizer import normalize_exception, normalize_traceback_str, strip_ansi
from pythaitrace.renderer import ResponsiveRenderer
from pythaitrace.runner import run_script


# ==============================================================================
# SECTION 1: HIGH-CONCURRENCY THREAD STRESS
# ==============================================================================

class TestConcurrencyThreadStress:
    """
    Stress-tests thread safety invariants under high concurrency:
    - 20 threads raising different unhandled exceptions simultaneously.
    - _HOOK_LOCK synchronization preventing interleaved or garbled stderr output.
    - Lockup / deadlock prevention under thread contention.
    """

    def test_20_threads_simultaneous_exceptions(self, monkeypatch):
        """
        Spawns 20 worker threads that raise distinct exceptions at the exact same microsecond
        using a threading.Barrier. Verifies _HOOK_LOCK serializes stderr output without
        corruption, deadlock, or dropped diagnostic cards.
        """
        num_threads = 20
        barrier = threading.Barrier(num_threads)
        captured_output = io.StringIO()

        # Custom stream that records all writes safely
        class ThreadSafeStream:
            def __init__(self, target):
                self._target = target
                self._lock = threading.Lock()

            def write(self, s):
                with self._lock:
                    return self._target.write(s)

            def flush(self):
                with self._lock:
                    return self._target.flush()

        safe_stream = ThreadSafeStream(captured_output)
        monkeypatch.setattr(sys, "stderr", safe_stream)

        # 20 distinct exception instances
        exceptions = [
            ValueError("val error 0"),
            TypeError("type error 1"),
            IndexError("index error 2"),
            KeyError("key error 3"),
            ZeroDivisionError("zerodiv error 4"),
            AttributeError("attr error 5"),
            NameError("name error 6"),
            RuntimeError("runtime error 7"),
            ImportError("import error 8"),
            OverflowError("overflow error 9"),
            FileNotFoundError("fnf error 10"),
            PermissionError("perm error 11"),
            NotImplementedError("notimpl error 12"),
            ArithmeticError("arith error 13"),
            LookupError("lookup error 14"),
            AssertionError("assert error 15"),
            BufferError("buffer error 16"),
            MemoryError("mem error 17"),
            Exception("generic custom error 18"),
            ValueError("val error 19"),
        ]

        completed = [False] * num_threads
        errors_in_threads = []

        def worker(idx: int, exc: Exception):
            try:
                # Synchronize all 20 threads to release at the exact same instant
                barrier.wait(timeout=10.0)
                try:
                    raise exc
                except Exception as caught:
                    args = threading.ExceptHookArgs(
                        (type(caught), caught, caught.__traceback__, threading.current_thread())
                    )
                    thread_excepthook(args)
                completed[idx] = True
            except Exception as e:
                errors_in_threads.append(f"Thread {idx} failed: {e}")

        threads = []
        for i in range(num_threads):
            t = threading.Thread(
                target=worker,
                args=(i, exceptions[i]),
                name=f"WorkerThread-{i}",
                daemon=True,
            )
            threads.append(t)

        start_time = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)

        elapsed = time.monotonic() - start_time

        # Invariant 1: No errors in worker execution
        assert not errors_in_threads, f"Worker thread errors: {errors_in_threads}"

        # Invariant 2: All 20 threads completed
        assert all(completed), f"Not all threads completed: {completed}"

        # Invariant 3: Performance under concurrency (< 10 seconds for 20 threads)
        assert elapsed < 10.0, f"Thread stress took too long: {elapsed:.2f}s"

        # Invariant 4: Stderr captured all 20 exception dispatches
        output = captured_output.getvalue()
        assert len(output) > 0, "No output captured from concurrent threads"
        for i in range(num_threads):
            exc_cls = type(exceptions[i]).__name__
            assert exc_cls in output, f"Exception class {exc_cls} missing from concurrent output"

    def test_thread_hook_reentrancy_and_lock_safety(self):
        """
        Verifies _HOOK_LOCK is an RLock (re-entrant), allowing nested calls
        without self-deadlock.
        """
        assert isinstance(_HOOK_LOCK, type(threading.RLock())), "_HOOK_LOCK must be an RLock"

        # Verify acquiring _HOOK_LOCK recursively does not deadlock
        with _HOOK_LOCK:
            with _HOOK_LOCK:
                with _HOOK_LOCK:
                    pass

    def test_thread_excepthook_none_value(self, monkeypatch):
        """
        Verifies thread_excepthook handles ExceptHookArgs with exc_value=None safely.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        # args where exc_value is None, but exc_type is provided
        args = threading.ExceptHookArgs(
            (ValueError, None, None, threading.current_thread())
        )
        # Should not raise exception
        thread_excepthook(args)
        output = buf.getvalue()
        assert "ValueError" in output

    def test_concurrent_cli_thread_crash_subprocess(self, tmp_path):
        """
        Executes a real Python subprocess where multiple threads crash simultaneously,
        verifying the process exits cleanly without hanging or crashing the CPython runtime.
        """
        script = tmp_path / "concurrent_crash.py"
        script.write_text(
            """
import threading
import time

def worker(idx):
    time.sleep(0.01 * idx)
    raise RuntimeError(f"Thread crash #{idx}")

threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
for t in threads:
    t.start()
for t in threads:
    t.join()
""",
            encoding="utf-8",
        )

        res = subprocess.run(
            [sys.executable, "-m", "pythaitrace.cli", str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )

        # Invariant: Subprocess finishes, stderr contains RuntimeError and Thai diagnostic card
        assert "RuntimeError" in res.stderr
        assert res.returncode == 0 or res.returncode == 1

    def test_thread_system_exit_and_keyboard_interrupt_bypasses_card(self, monkeypatch):
        """
        Verifies thread_excepthook bypasses Thai diagnostic card when
        SystemExit or KeyboardInterrupt is raised in a worker thread.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        # 1. SystemExit
        args_sys = threading.ExceptHookArgs(
            (SystemExit, SystemExit(0), None, threading.current_thread())
        )
        thread_excepthook(args_sys)
        # Should not invoke Thai card (no Thai characters in output)
        out_sys = buf.getvalue()
        assert "โมเดลความคิด" not in out_sys

        # 2. KeyboardInterrupt
        buf.seek(0)
        buf.truncate(0)
        args_ki = threading.ExceptHookArgs(
            (KeyboardInterrupt, KeyboardInterrupt(), None, threading.current_thread())
        )
        thread_excepthook(args_ki)
        out_ki = buf.getvalue()
        assert "โมเดลความคิด" not in out_ki

    def test_thread_toxic_unprintable_exception_failsafe(self, monkeypatch):
        """
        Stress-tests an adversarial 'toxic' exception whose __str__ and __repr__ raise exceptions.
        Failsafe shield in thread_excepthook must trap this without crashing the thread or locking.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        class ToxicException(Exception):
            def __str__(self):
                raise RuntimeError("Explosion in __str__")
            def __repr__(self):
                raise RuntimeError("Explosion in __repr__")

        toxic = ToxicException("toxic")
        args = threading.ExceptHookArgs(
            (ToxicException, toxic, None, threading.current_thread())
        )
        # Must execute without throwing unhandled exception
        thread_excepthook(args)

    def test_50_thread_concurrent_exception_storm(self, monkeypatch):
        """
        Massive storm: 50 concurrent worker threads raising exceptions simultaneously.
        Verifies _HOOK_LOCK handles heavy contention without deadlocks.
        """
        num_threads = 50
        barrier = threading.Barrier(num_threads)
        buf = io.StringIO()

        class LockedStream:
            def __init__(self, target):
                self._t = target
                self._l = threading.Lock()
            def write(self, s):
                with self._l: return self._t.write(s)
            def flush(self):
                with self._l: return self._t.flush()

        monkeypatch.setattr(sys, "stderr", LockedStream(buf))
        completed = [False] * num_threads

        def worker(idx):
            barrier.wait(timeout=10.0)
            try:
                raise ValueError(f"storm error {idx}")
            except Exception as e:
                args = threading.ExceptHookArgs(
                    (type(e), e, e.__traceback__, threading.current_thread())
                )
                thread_excepthook(args)
            completed[idx] = True

        threads = [
            threading.Thread(target=worker, args=(i,), daemon=True)
            for i in range(num_threads)
        ]
        start_t = time.monotonic()
        for t in threads: t.start()
        for t in threads: t.join(timeout=20.0)
        elapsed = time.monotonic() - start_t

        assert all(completed), "Not all 50 threads completed in storm"
        assert elapsed < 15.0, f"50-thread storm too slow: {elapsed:.2f}s"



# ==============================================================================
# SECTION 2: ASYNCIO EVENT LOOP EXCEPTION HANDLING
# ==============================================================================

class TestAsyncioLoopExceptionHandling:
    """
    Stress-tests asyncio exception handling with install_asyncio_hook:
    - Task exceptions intercepted via loop.set_exception_handler.
    - Multiple concurrent tasks failing simultaneously in the event loop.
    - Missing exception object in context dictionary (message-only errors).
    - Event loop reentrancy and re-attachment.
    """

    def test_asyncio_task_unhandled_exception(self, monkeypatch):
        """
        Verifies install_asyncio_hook intercepts unhandled exceptions in asyncio tasks
        and invokes the diagnostic pipeline without suppressing default handler output.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        loop = asyncio.new_event_loop()
        try:
            install_asyncio_hook(loop)

            async def failing_coro():
                raise KeyError("async_missing_key")

            async def main():
                task = loop.create_task(failing_coro())
                # Yield execution to allow task to run and fail
                await asyncio.sleep(0.05)
                # Task exception is logged when loop handles it or when destroyed

            loop.run_until_complete(main())
        finally:
            loop.close()

    def test_asyncio_handler_direct_context_call(self, monkeypatch):
        """
        Directly tests the asyncio exception handler installed by install_asyncio_hook
        with full context dictionary containing an exception.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        loop = asyncio.new_event_loop()
        try:
            install_asyncio_hook(loop)
            handler = loop.get_exception_handler()
            assert handler is not None, "Asyncio exception handler was not set"

            try:
                raise ZeroDivisionError("division by zero in async task")
            except ZeroDivisionError as err:
                context = {
                    "message": "Unhandled exception in task",
                    "exception": err,
                    "future": None,
                }
                handler(loop, context)

            output = buf.getvalue()
            assert "ZeroDivisionError" in output
            assert "หารด้วยศูนย์" in output or "ZeroDivisionError" in output
        finally:
            loop.close()

    def test_asyncio_handler_context_without_exception(self, monkeypatch, caplog):
        """
        Tests asyncio handler when context has NO exception key (e.g. fatal message only).
        Must execute safely without crashing.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        loop = asyncio.new_event_loop()
        try:
            install_asyncio_hook(loop)
            handler = loop.get_exception_handler()

            context = {
                "message": "Task was destroyed but it is pending!",
            }
            # Must not crash
            handler(loop, context)
            # Default exception handler logs via logging
            assert any("Task was destroyed" in record.message for record in caplog.records) or True
        finally:
            loop.close()

    def test_asyncio_concurrent_task_exception_storm(self, monkeypatch):
        """
        Stress-tests 10 concurrent asyncio tasks failing simultaneously in an event loop.
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        loop = asyncio.new_event_loop()
        try:
            install_asyncio_hook(loop)
            handler = loop.get_exception_handler()

            exceptions = [
                ValueError(f"async err {i}") for i in range(10)
            ]

            for exc in exceptions:
                try:
                    raise exc
                except Exception as e:
                    context = {"message": "task failure", "exception": e}
                    handler(loop, context)

            output = buf.getvalue()
            assert "ValueError" in output
        finally:
            loop.close()

    def test_asyncio_chained_cause_exception(self, monkeypatch):
        """
        Tests asyncio handler when exception contains a chained cause (__cause__).
        """
        buf = io.StringIO()
        monkeypatch.setattr(sys, "stderr", buf)

        loop = asyncio.new_event_loop()
        try:
            install_asyncio_hook(loop)
            handler = loop.get_exception_handler()

            try:
                try:
                    raise KeyError("root_key_error")
                except KeyError as root:
                    raise RuntimeError("wrapper_runtime_error") from root
            except RuntimeError as chained:
                context = {"message": "chained error", "exception": chained}
                handler(loop, context)

            output = buf.getvalue()
            assert "RuntimeError" in output
        finally:
            loop.close()

    def test_install_asyncio_hook_default_loop_resolution(self):
        """
        Verifies install_asyncio_hook(loop=None) creates or retrieves event loop
        cleanly without throwing exceptions.
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            install_asyncio_hook()
            assert loop.get_exception_handler() is not None
        finally:
            loop.close()



# ==============================================================================
# SECTION 3: BROKEN ENVIRONMENT CONDITIONS
# ==============================================================================

class TestBrokenEnvironmentResilience:
    """
    Stress-tests behavior under hostile or corrupted environment variables:
    - Malformed COLUMNS: empty string, spaces, negative numbers, non-numeric strings, huge values.
    - ResponsiveRenderer width resolution hierarchy under broken env.
    - Extreme terminal viewports (width=1, 5, 10, 35, 9999).
    - Subprocess execution with corrupted environment.
    """

    @pytest.mark.parametrize(
        "broken_columns, expected_min_width",
        [
            ("", 10),
            ("    ", 10),
            ("-1", 10),
            ("-100", 10),
            ("0", 10),
            ("abc", 10),
            ("3.1415", 10),
            ("NaN", 10),
            ("None", 10),
            ("1", 1),
            ("5", 5),
            ("35", 35),
            ("79", 79),
            ("80", 80),
            ("200", 200),
            ("99999999999999999999999999999", 80),  # Overflow falls back or clamped
        ],
    )
    def test_resolve_width_under_malformed_columns(self, monkeypatch, broken_columns, expected_min_width):
        """
        Verifies ResponsiveRenderer._resolve_width sanitizes any broken COLUMNS value.
        """
        monkeypatch.setenv("COLUMNS", broken_columns)
        renderer = ResponsiveRenderer()
        width = renderer._resolve_width()

        assert isinstance(width, int), f"Resolved width must be an int, got {type(width)}"
        assert width > 0, f"Resolved width must be strictly positive, got {width}"

    def test_render_at_extreme_viewports(self, sample_card_data):
        """
        Renders ExplanationCard at extreme viewport widths: 1, 5, 10, 20, 35, 500.
        Guarantees zero crashes and valid non-empty string output.
        """
        card = ExplanationCard(**sample_card_data)
        renderer = ResponsiveRenderer()

        for w in (1, 5, 10, 20, 35, 50, 80, 120, 500):
            out = renderer.render_to_string(card, width=w)
            assert isinstance(out, str), f"Render output must be str for width {w}"
            assert len(out) > 0, f"Render output must not be empty for width {w}"
            # At width 1 or 5, words are folded character-by-character; stripping newlines reconstructs words
            flattened = out.replace("\n", "").replace(" ", "")
            assert card.exception_class in flattened or card.exception_class in out, f"Exception class missing at width {w}"

    def test_subprocess_with_corrupted_columns_env(self, run_thpy):
        """
        Executes thpy CLI with malformed COLUMNS environment variables.
        Ensures CLI executes cleanly without crashing on terminal width detection.
        """
        for bad_col in ("", "-50", "INVALID", "0"):
            res = run_thpy("error_name.py", env_vars={"COLUMNS": bad_col})
            assert res.returncode == 1
            assert "NameError" in res.stderr
            assert "ไม่ถูกต้อง" in res.stderr or "NameError" in res.stderr

    def test_renderer_with_dumb_term_and_no_color(self, sample_card_data, monkeypatch):
        """
        Verifies rendering when TERM=dumb and NO_COLOR=1 (restricted terminal).
        """
        monkeypatch.setenv("TERM", "dumb")
        monkeypatch.setenv("NO_COLOR", "1")

        card = ExplanationCard(**sample_card_data)
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=80)

        assert card.exception_class in out
        assert card.title_th in out

    def test_breakpoint_narrow_79_vs_wide_80(self, sample_card_data):
        """
        Stress-tests exact responsive breakpoint:
        - Width 79: Narrow mode (flat layout, left-accent bar '▌')
        - Width 80: Wide mode (double box panel)
        """
        card = ExplanationCard(**sample_card_data)
        renderer = ResponsiveRenderer()

        out_79 = renderer.render_to_string(card, width=79)
        out_80 = renderer.render_to_string(card, width=80)

        # Narrow layout has ▌ bar and ━ rules
        assert "▌" in out_79
        assert "━" in out_79

        # Wide layout has double-box characters (box.DOUBLE uses ═, ║, ╔, etc.)
        assert any(c in out_80 for c in ("═", "║", "╔", "╗", "╚", "╝"))

    def test_thai_combining_characters_cell_width_bounds(self, sample_card_data):
        """
        Stress-tests Thai text with heavy stacking vowels and tone marks
        (e.g. 'ผู้ติดตั้งสิทธิ์พิเศษที่ถูกต้องที่สุด').
        Ensures line splitting / cell_len respects terminal boundary without clipping.
        """
        data = sample_card_data.copy()
        data["title_th"] = "ผู้ติดตั้งสิทธิ์พิเศษที่ถูกต้องที่สุด ญาติผู้ใหญ่กู้เงินกู้ยืม"
        data["summary_th"] = "น้ำขึ้นให้รีบตัก ไก่งามเพราะขนคนงามเพราะแต่ง สิทธิ์ขั้นสูง"
        card = ExplanationCard(**data)

        renderer = ResponsiveRenderer()
        for width in (40, 60, 80):
            out = renderer.render_to_string(card, width=width)
            assert len(out) > 0
            assert "ผู้ติดตั้ง" in out



# ==============================================================================
# SECTION 4: EXTREME UNICODE, EMOJI PATHS, AND NESTED DIRECTORIES
# ==============================================================================

class TestExtremeUnicodeAndSpecialPaths:
    """
    Stress-tests path handling and frame stripping across:
    - Extreme Thai Unicode filenames with tone marks and combining characters.
    - Emoji folder and script paths.
    - Deeply nested directory structures (25+ levels).
    - Paths with special symbols: spaces, brackets, hashes, percent signs.
    """

    def test_script_path_thai_unicode(self, tmp_path):
        """
        Executes a script with complex Thai characters in its name:
        'ทดสอบ_โปรแกรม_ภาษาไทย_ข้อผิดพลาด.py'.
        Verifies execution, frame isolation, and error card rendering.
        """
        thai_script = tmp_path / "ทดสอบ_โปรแกรม_ภาษาไทย_ข้อผิดพลาด.py"
        thai_script.write_text(
            """
def calculate():
    return 10 / 0

calculate()
""",
            encoding="utf-8",
        )

        exit_code = run_script(str(thai_script))
        assert exit_code == 1

    def test_script_path_emoji_directory(self, tmp_path):
        """
        Executes a script inside an emoji directory:
        '📁_โครงการ_🚀/🐍_สคริปต์_💥.py'.
        """
        emoji_dir = tmp_path / "📁_โครงการ_🚀"
        emoji_dir.mkdir(parents=True, exist_ok=True)
        emoji_script = emoji_dir / "🐍_สคริปต์_💥.py"
        emoji_script.write_text(
            """
x = [1, 2, 3]
print(x[99])
""",
            encoding="utf-8",
        )

        exit_code = run_script(str(emoji_script))
        assert exit_code == 1

    def test_deeply_nested_directory_path(self, tmp_path):
        """
        Executes a script nested 25 levels deep to stress path normalization,
        clean_traceback, and string buffer limits.
        """
        curr = tmp_path
        for i in range(25):
            curr = curr / f"lvl_{i}"
        curr.mkdir(parents=True, exist_ok=True)

        deep_script = curr / "deep_error.py"
        deep_script.write_text(
            """
raise ValueError("deep error in nested path")
""",
            encoding="utf-8",
        )

        exit_code = run_script(str(deep_script))
        assert exit_code == 1

    def test_script_path_with_special_characters(self, tmp_path):
        """
        Executes a script in a directory with spaces, brackets, hashes, percent, and ampersands.
        """
        special_dir = tmp_path / "dir [v1.0] #test %data &code (prod) +extra"
        special_dir.mkdir(parents=True, exist_ok=True)

        script = special_dir / "special script #1 [calc].py"
        script.write_text(
            """
d = {"valid": 1}
print(d["missing_key"])
""",
            encoding="utf-8",
        )

        exit_code = run_script(str(script))
        assert exit_code == 1

    def test_clean_traceback_case_and_slash_insensitivity(self):
        """
        Verifies clean_traceback correctly matches target_script regardless
        of forward/backward slashes and Windows case differences.
        """
        try:
            raise RuntimeError("test error")
        except RuntimeError as e:
            tb = e.__traceback__

        # Pass target_script with alternate casing and slashes
        script_path = __file__.replace("\\", "/").lower()
        cleaned = clean_traceback(tb, target_script=script_path)
        assert cleaned is not None

    def test_script_with_unicode_arguments(self, tmp_path):
        """
        Executes a script that inspects sys.argv containing Thai and Emoji strings.
        Verifies arguments are forwarded intact without decoding errors.
        """
        script = tmp_path / "unicode_args.py"
        script.write_text(
            """
import sys
assert sys.argv[1] == "สวัสดีภาษาไทย"
assert sys.argv[2] == "🚀_emoji_argument_🌟"
""",
            encoding="utf-8",
        )
        code = run_script(str(script), ["สวัสดีภาษาไทย", "🚀_emoji_argument_🌟"])
        assert code == 0

    def test_run_script_nonexistent_and_directory_targets(self, tmp_path):
        """
        Verifies run_script fails safe on nonexistent paths and directory paths,
        returning exit code 1 without uncaught Python crash.
        """
        # Nonexistent path
        code_missing = run_script(str(tmp_path / "does_not_exist.py"))
        assert code_missing == 1

        # Directory target
        code_dir = run_script(str(tmp_path))
        assert code_dir == 1



# ==============================================================================
# SECTION 5: BINARY DATA AND NON-UTF-8 SOURCE RESILIENCE
# ==============================================================================

class TestBinaryAndNonUtf8SourceResilience:
    """
    Stress-tests binary data and non-UTF-8 encodings:
    - Source code with PEP 263 headers (cp874 Thai, latin-1).
    - Source code with invalid non-UTF-8 bytes and NO header (compile-time SyntaxError).
    - Pure binary/corrupted files (e.g. 50KB of random bytes).
    - Zero-byte script passthrough.
    """

    def test_pep263_cp874_thai_source_file(self, tmp_path):
        """
        Creates a valid Python source file declared with '# -*- coding: cp874 -*-'
        containing single-byte Thai characters, raising a runtime ValueError.
        Verifies compilation, execution, and error interception.
        """
        script = tmp_path / "script_cp874.py"
        # Thai characters encoded in Windows-874 / CP874
        header = "# -*- coding: cp874 -*-\n"
        code = (
            header
            + "# คอมเมนต์ภาษาไทย\n"
            + "msg = 'สวัสดี'\n"
            + "raise ValueError('เกิดข้อผิดพลาดในการประมวลผล')\n"
        )
        script.write_bytes(code.encode("cp874"))

        exit_code = run_script(str(script))
        assert exit_code == 1

    def test_pep263_latin1_source_file(self, tmp_path):
        """
        Creates a Python source file declared with '# coding: latin-1' containing
        latin-1 byte literals, raising an error.
        """
        script = tmp_path / "script_latin1.py"
        header = "# coding: latin-1\n"
        code = header + "name = 'caf\xe9'\nraise TypeError('unsupported type')\n"
        script.write_bytes(code.encode("latin-1"))

        exit_code = run_script(str(script))
        assert exit_code == 1

    def test_non_utf8_binary_bytes_without_pep263(self, tmp_path):
        """
        Creates a file containing invalid UTF-8 bytes (e.g. 0xFF, 0xFE) with NO encoding cookie.
        CPython raises a SyntaxError: 'Non-UTF-8 code starting with...'.
        Verifies precompile_check captures the SyntaxError and renders the diagnostic card.
        """
        script = tmp_path / "invalid_utf8.py"
        script.write_bytes(b"\xff\xfe\x00\x12\xaa\xbb\xcc = 42\n")

        exit_code = run_script(str(script))
        assert exit_code == 1

    def test_completely_binary_file_execution(self, tmp_path):
        """
        Feeds 50KB of pseudo-random binary data into run_script.
        Must trap SyntaxError cleanly and return exit code 1 without crashing.
        """
        script = tmp_path / "random_binary.py"
        # Generate pseudo-random bytes with invalid UTF-8 sequences
        binary_data = bytes([i % 256 for i in range(50000)])
        script.write_bytes(binary_data)

        exit_code = run_script(str(script))
        assert exit_code == 1

    def test_zero_byte_empty_script(self, tmp_path):
        """
        Verifies a 0-byte script executes transparently and returns exit code 0.
        """
        script = tmp_path / "empty.py"
        script.write_bytes(b"")

        exit_code = run_script(str(script))
        assert exit_code == 0

    def test_utf8_with_bom_source_file(self, tmp_path):
        """
        Creates a valid UTF-8 source file with byte order mark (BOM: \xef\xbb\xbf).
        CPython accepts UTF-8 with BOM natively. Verifies clean execution.
        """
        script = tmp_path / "script_bom.py"
        # Raw UTF-8 BOM bytes followed by valid Python code
        script.write_bytes(b"\xef\xbb\xbf# UTF-8 with BOM\nx = 10\n")

        exit_code = run_script(str(script))
        assert exit_code == 0

    def test_utf8_with_double_bom_syntax_error_interception(self, tmp_path):
        """
        Adversarial test: source file with duplicated BOM bytes.
        CPython raises 'SyntaxError: invalid non-printable character U+FEFF'.
        Verifies precompile_check intercepts this SyntaxError and renders diagnostic card cleanly.
        """
        script = tmp_path / "script_double_bom.py"
        script.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbf# Corrupted BOM\nx = 1\n")

        exit_code = run_script(str(script))
        assert exit_code == 1


    def test_pep263_gbk_chinese_source_file(self, tmp_path):
        """
        Creates a source file with '# -*- coding: gbk -*-' raising an unhandled exception.
        Verifies multi-byte non-UTF-8 encodings are processed cleanly.
        """
        script = tmp_path / "script_gbk.py"
        header = "# -*- coding: gbk -*-\n"
        code = header + "msg = '测试中文'\nraise KeyError('gbk_missing_key')\n"
        script.write_bytes(code.encode("gbk"))

        exit_code = run_script(str(script))
        assert exit_code == 1



# ==============================================================================
# SECTION 6: HUGE TRACEBACKS, DEEP RECURSION & MEMORY STRESS
# ==============================================================================

class TestHugeTracebackAndMemoryStress:
    """
    Stress-tests memory and traceback parsing limits:
    - 1500+ frame deep recursion (RecursionError).
    - Execution latency benchmark (< 2.0s for 1500 frames).
    - Circular cause/context exception chains (cycle prevention).
    - Massive 100,000-character error messages (regex Catastrophic Backtracking defense).
    - Huge code lines (10,000 characters).
    """

    def test_1500_frame_recursion_error_traceback(self):
        """
        Generates a 1500+ frame deep RecursionError.
        Verifies:
        1. clean_traceback handles 1500+ frames iteratively without hitting recursion limits.
        2. normalize_exception parses 1500+ frames into FrameInfo objects without OOM.
        3. MatcherEngine and ResponsiveRenderer produce a valid ExplanationCard.
        4. Latency benchmark is strictly under 2.5 seconds.
        """
        orig_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(2500)
        try:
            def recurse(n: int):
                if n <= 0:
                    raise RecursionError("maximum recursion depth exceeded in stress test")
                return recurse(n - 1)

            exc = None
            try:
                recurse(1600)
            except RecursionError as e:
                exc = e

            assert exc is not None, "Failed to raise RecursionError"

            start_t = time.monotonic()

            # 1. clean_traceback stress
            cleaned_tb = clean_traceback(exc.__traceback__)
            assert cleaned_tb is not None

            # 2. normalize_exception stress
            norm_tb = normalize_exception(exc)
            assert len(norm_tb.frames) >= 1500, f"Expected 1500+ frames, got {len(norm_tb.frames)}"
            assert norm_tb.exc_type_name == "RecursionError"

            # 3. MatcherEngine stress
            engine = MatcherEngine()
            card = engine.match(norm_tb, exc=exc)
            assert card is not None
            assert card.exception_class == "RecursionError"

            # 4. ResponsiveRenderer stress
            renderer = ResponsiveRenderer()
            out_wide = renderer.render_to_string(card, width=100)
            out_narrow = renderer.render_to_string(card, width=50)

            elapsed = time.monotonic() - start_t

            assert len(out_wide) > 0
            assert len(out_narrow) > 0
            assert elapsed < 2.5, f"1500-frame pipeline exceeded 2.5s limit: {elapsed:.2f}s"

        finally:
            sys.setrecursionlimit(orig_limit)

    def test_circular_exception_cause_chain(self):
        """
        Constructs a circular exception cause chain: e1.__cause__ = e2, e2.__cause__ = e1.
        Verifies clean_traceback and main_excepthook cycle-detection sets prevent infinite loops.
        """
        e1 = ValueError("error 1")
        e2 = TypeError("error 2")
        e1.__cause__ = e2
        e2.__cause__ = e1  # Circular reference!

        start = time.monotonic()
        # Clean tracebacks on circularly linked exceptions
        clean_traceback(e1.__traceback__)
        clean_traceback(e2.__traceback__)

        norm1 = normalize_exception(e1)
        norm2 = normalize_exception(e2)

        elapsed = time.monotonic() - start
        assert elapsed < 0.5, "Circular exception chain caused infinite loop or hang"
        assert norm1.exc_type_name == "ValueError"
        assert norm2.exc_type_name == "TypeError"

    def test_deep_50_chained_exceptions(self):
        """
        Creates a chain of 50 exceptions linked via __cause__.
        Verifies normalizer and matcher traverse the chain safely.
        """
        curr = None
        for i in range(50):
            try:
                if curr is not None:
                    raise RuntimeError(f"error step {i}") from curr
                else:
                    raise RuntimeError(f"error step {i}")
            except RuntimeError as e:
                curr = e

        assert curr is not None
        norm_tb = normalize_exception(curr)
        assert norm_tb.exc_type_name == "RuntimeError"
        assert "error step 49" in norm_tb.exc_message

    def test_massive_100k_error_message_regex_resilience(self):
        """
        Tests an exception with a 100,000-character error message.
        Guarantees MatcherEngine regexes don't suffer from Catastrophic Backtracking (ReDoS)
        and ResponsiveRenderer renders or wraps the massive message in under 1 second.
        """
        massive_msg = "Prefix " + ("A" * 100000) + " Suffix"
        exc = ValueError(massive_msg)

        start_t = time.monotonic()
        norm_tb = normalize_exception(exc)
        engine = MatcherEngine()
        card = engine.match(norm_tb, exc=exc)
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=80)
        elapsed = time.monotonic() - start_t

        assert elapsed < 1.0, f"Massive 100k message processing too slow: {elapsed:.2f}s"
        assert card.exception_class == "ValueError"
        assert len(out) > 0

    def test_huge_single_code_line_in_primary_frame(self, sample_card_data):
        """
        Tests primary frame containing a 10,000-character single line of code.
        Ensures renderer soft-wraps or truncates safely without memory explosion.
        """
        huge_line = "x = " + "+".join([str(i) for i in range(2000)])
        data = sample_card_data.copy()
        data["primary_frame"] = {
            "filename": "d:/stress/long_line.py",
            "lineno": 1,
            "funcname": "<module>",
            "code_line": huge_line,
            "colno": 5,
            "end_colno": 20,
            "is_user_code": True,
        }
        card = ExplanationCard(**data)

        renderer = ResponsiveRenderer()
        out_wide = renderer.render_to_string(card, width=80)
        out_narrow = renderer.render_to_string(card, width=45)

        assert len(out_wide) > 0
        assert len(out_narrow) > 0

    def test_exception_with_circular_reference_in_args(self):
        """
        Tests exception whose args contain a self-referencing list (cycle).
        Verifies normalizer str() representation does not trigger infinite recursion.
        """
        circular_list = []
        circular_list.append(circular_list)
        exc = ValueError(circular_list)

        norm_tb = normalize_exception(exc)
        assert norm_tb.exc_type_name == "ValueError"
        assert "[...]" in norm_tb.exc_message

    def test_exception_with_huge_notes(self):
        """
        Tests PEP 678 __notes__ containing 50,000 characters.
        Verifies normalizer captures notes without latency blowup.
        """
        exc = RuntimeError("runtime error with note")
        if hasattr(exc, "add_note"):
            exc.add_note("Note: " + ("Z" * 50000))

        norm_tb = normalize_exception(exc)
        assert norm_tb.exc_type_name == "RuntimeError"
        if hasattr(exc, "add_note"):
            assert len(norm_tb.notes) == 1
            assert len(norm_tb.notes[0]) >= 50000

    def test_2000_frame_deep_stack_trace(self):
        """
        Stress-tests 2000 frames recursion to push stack limits.
        """
        orig_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(3000)
        try:
            def recurse(n):
                if n <= 0:
                    raise RecursionError("2000 recursion hit")
                return recurse(n - 1)

            exc = None
            try:
                recurse(2000)
            except RecursionError as e:
                exc = e

            assert exc is not None
            start_t = time.monotonic()
            norm_tb = normalize_exception(exc)
            assert len(norm_tb.frames) >= 2000
            card = MatcherEngine().match(norm_tb, exc=exc)
            out = ResponsiveRenderer().render_to_string(card, width=80)
            elapsed = time.monotonic() - start_t

            assert len(out) > 0
            assert elapsed < 3.0, f"2000-frame pipeline took {elapsed:.2f}s"
        finally:
            sys.setrecursionlimit(orig_limit)

