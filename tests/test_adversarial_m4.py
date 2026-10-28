"""
Adversarial Stress Test Suite for Milestone 4:
Runner Execution Engine & Exception Hooks (hooks.py, runner.py, cli.py)

Covers:
1. Syntax & Indentation error corner cases (nested brackets, UTF-8 BOM, PEP 263, non-ASCII/Thai, multi-line, TabError, null bytes)
2. Stack & Traceback stress (deep recursion, chained causes/context, cycles, exploding str/repr/doc/name)
3. Multithreading stress (10 concurrent thread crashes, barrier synchronization, thread vs main crash, sys.exit in thread, asyncio)
4. Failsafe isolation (broken normalizer, broken matcher, broken renderer, PYTHAITRACE_DEBUG, sys.stderr=None, degenerate hook args)
"""
import io
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock
import pytest

import pythaitrace
from pythaitrace.hooks import (
    clean_traceback,
    configure_streams,
    install_hooks,
    install_asyncio_hook,
    main_excepthook,
    thread_excepthook,
    _HOOK_LOCK,
)
from pythaitrace.runner import run_script, execute_script
from pythaitrace import cli


# ==============================================================================
# 1. Syntax & Indentation Error Corner Cases
# ==============================================================================

class TestAdversarialSyntaxErrors:
    """Stress tests pre-compilation check against hostile, pathological, or exotic syntax inputs."""

    def test_deeply_nested_unclosed_parentheses(self, run_thpy, tmp_path):
        """Pathological unclosed parentheses must be caught by pre-compile without recursion crash."""
        bad_file = tmp_path / "deep_parens.py"
        bad_file.write_text("x = " + ("(" * 300) + "\n", encoding="utf-8")
        result = run_thpy(str(bad_file))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr

    def test_compiler_bracket_limit_exceeded(self, run_thpy, tmp_path):
        """1000 balanced parentheses triggering compiler nesting limits."""
        bad_file = tmp_path / "limit_parens.py"
        bad_file.write_text("x = " + ("(" * 1000) + ("0" + ")" * 1000) + "\n", encoding="utf-8")
        result = run_thpy(str(bad_file))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr
        assert ("too many nested parentheses" in result.stderr or "SyntaxError" in result.stderr)

    def test_utf8_bom_clean_execution(self, run_thpy, tmp_path):
        """Script starting with UTF-8 BOM (\\xef\\xbb\\xbf) must execute cleanly."""
        bom_clean = tmp_path / "bom_clean.py"
        bom_clean.write_bytes(b"\xef\xbb\xbfprint('BOM_CLEAN_SUCCESS')\n")
        result = run_thpy(str(bom_clean))
        assert result.returncode == 0
        assert "BOM_CLEAN_SUCCESS" in result.stdout

    def test_utf8_bom_with_syntax_error(self, run_thpy, tmp_path):
        """Script with UTF-8 BOM and a syntax error must report syntax error without BOM corruption."""
        bom_bad = tmp_path / "bom_bad.py"
        bom_bad.write_bytes(b"\xef\xbb\xbfdef broken_func(\n")
        result = run_thpy(str(bom_bad))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr
        assert "bom_bad.py" in result.stderr

    def test_pep263_latin1_coding_cookie(self, run_thpy, tmp_path):
        """Script with PEP 263 Latin-1 encoding declaration executes bytes correctly."""
        latin1_file = tmp_path / "latin1_script.py"
        latin1_file.write_bytes(b"# -*- coding: iso-8859-1 -*-\nname = 'caf\xe9'\nprint(f'ENCODED_{name}')\n")
        result = run_thpy(str(latin1_file))
        assert result.returncode == 0
        assert "ENCODED_caf" in result.stdout

    def test_pep263_invalid_encoding_cookie(self, run_thpy, tmp_path):
        """Script with unknown PEP 263 encoding must be intercepted at line 0 without crashing."""
        invalid_enc = tmp_path / "unknown_enc.py"
        invalid_enc.write_bytes(b"# -*- coding: non_existent_charset_999 -*-\nx = 1\n")
        result = run_thpy(str(invalid_enc))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr
        assert "unknown encoding" in result.stderr

    def test_non_ascii_thai_syntax_error(self, run_thpy, tmp_path):
        """Script with Thai variable name and missing operand must produce clean Thai card."""
        thai_err = tmp_path / "thai_syntax.py"
        thai_err.write_text("ตัวแปรยอดรวม = \n", encoding="utf-8")
        result = run_thpy(str(thai_err))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr
        assert "ตัวแปรยอดรวม" in result.stderr

    def test_unclosed_multiline_triple_quote_string(self, run_thpy, tmp_path):
        """Unclosed triple-quote string running to EOF must be intercepted."""
        unclosed_str = tmp_path / "unclosed_str.py"
        unclosed_str.write_text("text = '''This is line 1\nline 2\nline 3 at EOF\n", encoding="utf-8")
        result = run_thpy(str(unclosed_str))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr

    def test_null_byte_in_source_code(self, run_thpy, tmp_path):
        """Source code containing null bytes must be caught as SyntaxError."""
        null_file = tmp_path / "null_byte.py"
        null_file.write_bytes(b"a = 1\x00\nb = 2\n")
        result = run_thpy(str(null_file))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr

    def test_non_utf8_bytes_without_encoding_declaration(self, run_thpy, tmp_path):
        """Raw non-UTF-8 bytes without PEP 263 cookie must raise clean SyntaxError."""
        raw_bytes = tmp_path / "raw_bytes.py"
        raw_bytes.write_bytes(b"\xff\xfe\xfd\n")
        result = run_thpy(str(raw_bytes))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr


# ==============================================================================
# 2. Stack & Traceback Stress
# ==============================================================================

class TestAdversarialTracebackStress:
    """Stress tests traceback cleaning, deep stacks, chained causes, and hostile exceptions."""

    def test_deep_recursion_stack_resolution(self, run_thpy, tmp_path):
        """Call stack 600 frames deep must not crash clean_traceback or normalizer."""
        rec_script = tmp_path / "deep_stack.py"
        rec_script.write_text(
            "def recurse(n):\n"
            "    if n <= 0:\n"
            "        raise ValueError('BOTTOM_OF_RECURSION')\n"
            "    recurse(n - 1)\n"
            "recurse(600)\n",
            encoding="utf-8"
        )
        result = run_thpy(str(rec_script))
        assert result.returncode == 1
        assert "ValueError: BOTTOM_OF_RECURSION" in result.stderr
        assert "recurse" in result.stderr

    def test_system_recursion_limit_hit(self, run_thpy, tmp_path):
        """Infinite recursion triggering RecursionError is captured cleanly."""
        rec_inf = tmp_path / "rec_inf.py"
        rec_inf.write_text("def f(): f()\nf()\n", encoding="utf-8")
        result = run_thpy(str(rec_inf))
        assert result.returncode == 1
        assert "RecursionError" in result.stderr

    def test_chained_exceptions_explicit_and_implicit(self, run_thpy, tmp_path):
        """Multi-level chained exceptions with both __cause__ and __context__."""
        multi_chain = tmp_path / "multi_chain.py"
        multi_chain.write_text(
            "try:\n"
            "    try:\n"
            "        1 / 0\n"
            "    except ZeroDivisionError as e0:\n"
            "        raise ValueError('Level 2 Value') from e0\n"
            "except ValueError as e1:\n"
            "    raise RuntimeError('Level 3 Runtime')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(multi_chain))
        assert result.returncode == 1
        assert "ZeroDivisionError" in result.stderr
        assert "ValueError: Level 2 Value" in result.stderr
        assert "RuntimeError: Level 3 Runtime" in result.stderr

    def test_cycle_in_exception_cause_self(self, run_thpy, tmp_path):
        """Self-referential cause (e.__cause__ = e) must not result in an infinite loop."""
        cycle_self = tmp_path / "cycle_self.py"
        cycle_self.write_text(
            "e = ValueError('SELF_CYCLE_ERROR')\n"
            "e.__cause__ = e\n"
            "raise e\n",
            encoding="utf-8"
        )
        result = run_thpy(str(cycle_self))
        assert result.returncode == 1
        assert "ValueError: SELF_CYCLE_ERROR" in result.stderr

    def test_mutual_cycle_in_exception_causes(self, run_thpy, tmp_path):
        """Mutual cause cycle (e1.__cause__ = e2, e2.__cause__ = e1) must terminate cleanly."""
        cycle_mutual = tmp_path / "cycle_mutual.py"
        cycle_mutual.write_text(
            "e1 = ValueError('E1_CAUSE')\n"
            "e2 = RuntimeError('E2_CAUSE')\n"
            "e1.__cause__ = e2\n"
            "e2.__cause__ = e1\n"
            "raise e1\n",
            encoding="utf-8"
        )
        result = run_thpy(str(cycle_mutual))
        assert result.returncode == 1
        assert "E1_CAUSE" in result.stderr
        assert "E2_CAUSE" in result.stderr

    def test_mutual_cycle_in_exception_context(self, run_thpy, tmp_path):
        """Mutual context cycle (e1.__context__ = e2, e2.__context__ = e1) must terminate cleanly."""
        cycle_context = tmp_path / "cycle_context.py"
        cycle_context.write_text(
            "e1 = KeyError('E1_CONTEXT')\n"
            "e2 = IndexError('E2_CONTEXT')\n"
            "e1.__context__ = e2\n"
            "e2.__context__ = e1\n"
            "raise e1\n",
            encoding="utf-8"
        )
        result = run_thpy(str(cycle_context))
        assert result.returncode == 1
        assert "E1_CONTEXT" in result.stderr

    def test_exploding_str_repr_and_doc_on_exception(self, run_thpy, tmp_path):
        """Custom exception whose __str__, __repr__, and metaclass __doc__ raise must not crash runner."""
        evil_script = tmp_path / "evil_exc.py"
        evil_script.write_text(
            "class EvilMeta(type):\n"
            "    @property\n"
            "    def __doc__(cls):\n"
            "        raise RuntimeError('EXPLODING_DOC')\n\n"
            "class EvilException(Exception, metaclass=EvilMeta):\n"
            "    def __str__(self):\n"
            "        raise RuntimeError('EXPLODING_STR')\n"
            "    def __repr__(self):\n"
            "        raise RuntimeError('EXPLODING_REPR')\n\n"
            "raise EvilException()\n",
            encoding="utf-8"
        )
        result = run_thpy(str(evil_script))
        assert result.returncode == 1
        assert "EvilException" in result.stderr

    def test_exploding_name_property_on_exception_metaclass(self, run_thpy, tmp_path):
        """Custom exception whose type(exc).__name__ raises must be shielded by failsafe."""
        bad_name_script = tmp_path / "bad_name.py"
        bad_name_script.write_text(
            "class BadMeta(type):\n"
            "    @property\n"
            "    def __name__(cls):\n"
            "        raise RuntimeError('EXPLODING_NAME')\n\n"
            "class BrokenClass(Exception, metaclass=BadMeta):\n"
            "    pass\n\n"
            "raise BrokenClass('test_message')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(bad_name_script))
        assert result.returncode == 1
        assert "BrokenClass: test_message" in result.stderr


# ==============================================================================
# 3. Multithreading Stress
# ==============================================================================

class TestAdversarialMultithreading:
    """Stress tests concurrent thread crashes, barrier synchronizations, and race conditions."""

    def test_ten_concurrent_worker_threads_crashing_simultaneously(self, run_thpy, tmp_path):
        """10 threads crashing simultaneously at a barrier must serialize output without deadlock."""
        multi_thread = tmp_path / "ten_threads.py"
        multi_thread.write_text(
            "import threading\n"
            "import time\n\n"
            "barrier = threading.Barrier(10)\n\n"
            "def worker(idx):\n"
            "    barrier.wait()\n"
            "    raise RuntimeError(f'BARRIER_THREAD_FAIL_{idx}')\n\n"
            "threads = []\n"
            "for i in range(10):\n"
            "    t = threading.Thread(target=worker, args=(i,), name=f'Thread-Crash-{i}')\n"
            "    threads.append(t)\n"
            "    t.start()\n\n"
            "for t in threads:\n"
            "    t.join()\n"
            "print('ALL_10_THREADS_DONE')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(multi_thread))
        assert result.returncode == 0
        assert "ALL_10_THREADS_DONE" in result.stdout
        for i in range(10):
            assert f"BARRIER_THREAD_FAIL_{i}" in result.stderr

    def test_worker_thread_and_main_thread_both_crashing(self, run_thpy, tmp_path):
        """Worker thread and main thread both crashing in close timing must both output cleanly."""
        dual_crash = tmp_path / "dual_crash.py"
        dual_crash.write_text(
            "import threading\n"
            "import time\n\n"
            "def worker():\n"
            "    time.sleep(0.02)\n"
            "    raise RuntimeError('WORKER_CRASHED')\n\n"
            "t = threading.Thread(target=worker, name='CrashingWorker')\n"
            "t.start()\n"
            "time.sleep(0.02)\n"
            "raise ValueError('MAIN_CRASHED')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(dual_crash))
        assert result.returncode == 1
        assert "WORKER_CRASHED" in result.stderr
        assert "MAIN_CRASHED" in result.stderr

    def test_worker_thread_calling_sys_exit_zero(self, run_thpy, tmp_path):
        """Worker thread calling sys.exit(0) must terminate thread without error card."""
        thread_exit = tmp_path / "thread_exit.py"
        thread_exit.write_text(
            "import threading\n"
            "import sys\n\n"
            "def worker():\n"
            "    sys.exit(0)\n\n"
            "t = threading.Thread(target=worker)\n"
            "t.start()\n"
            "t.join()\n"
            "print('THREAD_EXIT_ZERO_SUCCESS')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(thread_exit))
        assert result.returncode == 0
        assert "THREAD_EXIT_ZERO_SUCCESS" in result.stdout
        assert "โมเดลความคิด" not in result.stderr

    def test_asyncio_event_loop_unhandled_task_exception(self, run_thpy, tmp_path):
        """Asyncio background task error must be intercepted by install_asyncio_hook."""
        asyncio_script = tmp_path / "asyncio_test.py"
        asyncio_script.write_text(
            "import asyncio\n"
            "from pythaitrace.hooks import install_asyncio_hook\n\n"
            "async def failing_task():\n"
            "    raise ValueError('ASYNCIO_BACKGROUND_CORO_ERROR')\n\n"
            "async def main():\n"
            "    install_asyncio_hook()\n"
            "    asyncio.create_task(failing_task())\n"
            "    await asyncio.sleep(0.05)\n\n"
            "asyncio.run(main())\n"
            "print('ASYNCIO_MAIN_FINISHED')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(asyncio_script))
        assert result.returncode == 0
        assert "ASYNCIO_MAIN_FINISHED" in result.stdout
        assert "ASYNCIO_BACKGROUND_CORO_ERROR" in result.stderr


# ==============================================================================
# 4. Failsafe Isolation & Degenerate Conditions
# ==============================================================================

class TestAdversarialFailsafeIsolation:
    """Stress tests failsafe shield under broken components and degenerate runtime conditions."""

    def test_failsafe_when_normalizer_raises(self, run_thpy, tmp_path):
        """If normalizer crashes internally, authentic traceback must still appear on stderr."""
        script = tmp_path / "broken_norm.py"
        script.write_text(
            "import pythaitrace.normalizer as norm\n"
            "norm.normalize_exception = lambda e: (_ for _ in ()).throw(RuntimeError('FORCED_NORMALIZER_BUG'))\n"
            "raise KeyError('FAILS_SAFE_KEY')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(script))
        assert result.returncode == 1
        assert "KeyError: 'FAILS_SAFE_KEY'" in result.stderr

    def test_failsafe_debug_flag_prints_internal_error(self, run_thpy, tmp_path):
        """When PYTHAITRACE_DEBUG=1 is set, internal errors are noted on stderr alongside authentic trace."""
        script = tmp_path / "broken_norm_debug.py"
        script.write_text(
            "import os\n"
            "os.environ['PYTHAITRACE_DEBUG'] = '1'\n"
            "import pythaitrace.normalizer as norm\n"
            "norm.normalize_exception = lambda e: (_ for _ in ()).throw(RuntimeError('FORCED_NORMALIZER_BUG'))\n"
            "raise IndexError('FAILS_SAFE_INDEX')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(script), env_vars={"PYTHAITRACE_DEBUG": "1"})
        assert result.returncode == 1
        assert "IndexError: FAILS_SAFE_INDEX" in result.stderr
        assert "[PyThaiTrace Internal Error: FORCED_NORMALIZER_BUG]" in result.stderr

    def test_clean_traceback_with_none_co_filename(self):
        """clean_traceback must handle mock/custom frames where co_filename is None or empty."""
        mock_tb = MagicMock()
        mock_tb.tb_frame.f_code.co_filename = None
        mock_tb.tb_next = None

        # Empirical challenge: current code will encounter TypeError if fn is None
        # Verify whether clean_traceback handles or raises
        try:
            res = clean_traceback(mock_tb, target_script="script.py")
        except TypeError as err:
            pytest.fail(f"VULNERABILITY CONFIRMED: clean_traceback raised TypeError on None co_filename: {err}")

    def test_main_excepthook_with_none_exc_type(self):
        """main_excepthook must not crash if exc_type is None (e.g. called outside except block)."""
        # CPython's sys.__excepthook__(None, None, None) prints 'NoneType: None' without crashing
        try:
            main_excepthook(None, None, None)
        except TypeError as err:
            pytest.fail(f"VULNERABILITY CONFIRMED: main_excepthook crashed on None exc_type: {err}")

    def test_thread_excepthook_with_none_exc_type(self):
        """thread_excepthook must not crash if args.exc_type is None."""
        args = threading.ExceptHookArgs((None, None, None, threading.current_thread()))
        try:
            thread_excepthook(args)
        except TypeError as err:
            pytest.fail(f"VULNERABILITY CONFIRMED: thread_excepthook crashed on None args.exc_type: {err}")

    def test_main_excepthook_when_sys_stderr_is_none(self, monkeypatch):
        """main_excepthook must not crash if sys.stderr is None (e.g. GUI/daemon pythonw process)."""
        monkeypatch.setattr(sys, "stderr", None)
        try:
            try:
                raise ValueError("test_none_stderr")
            except ValueError as e:
                main_excepthook(type(e), e, e.__traceback__)
        except AttributeError as err:
            pytest.fail(f"VULNERABILITY CONFIRMED: main_excepthook crashed when sys.stderr is None: {err}")


# ==============================================================================
# 5. CLI Arguments & Boundary Conditions
# ==============================================================================

class TestAdversarialCliBoundaries:
    """Stress tests CLI entrypoint flags, delimiters, and transparent argument forwarding."""

    def test_cli_help_flag_returns_zero(self, run_thpy):
        """thpy --help must print help and return code 0."""
        result = run_thpy("clean_script.py", cli_args=["--help"])
        # Notice: first arg is script, so --help is forwarded to clean_script.py!
        # When calling CLI directly with --help:
        import subprocess
        res = subprocess.run([sys.executable, "-m", "pythaitrace.cli", "--help"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "usage: thpy" in res.stdout

    def test_cli_version_flag_returns_zero(self):
        """thpy --version must print version and return code 0."""
        import subprocess
        res = subprocess.run([sys.executable, "-m", "pythaitrace.cli", "--version"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "PyThaiTrace 2.0.0" in res.stdout

    def test_cli_double_dash_delimiter_alone(self):
        """thpy -- without script must print help and return 0."""
        import subprocess
        res = subprocess.run([sys.executable, "-m", "pythaitrace.cli", "--"], capture_output=True, text=True)
        assert res.returncode == 0
        assert "usage: thpy" in res.stderr

    def test_cli_double_dash_with_script_and_flags(self, run_thpy, tmp_path):
        """thpy -- script.py -v must pass -v to script rather than triggering CLI version."""
        script = tmp_path / "flag_receiver.py"
        script.write_text(
            "import sys\n"
            "assert '-v' in sys.argv\n"
            "print('FLAG_V_RECEIVED_SUCCESS')\n",
            encoding="utf-8"
        )
        import subprocess
        res = subprocess.run(
            [sys.executable, "-m", "pythaitrace.cli", "--", str(script), "-v"],
            capture_output=True,
            text=True
        )
        assert res.returncode == 0
        assert "FLAG_V_RECEIVED_SUCCESS" in res.stdout
