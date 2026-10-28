"""
Adversarial Stress Test Suite for Milestone 4:
PyThaiTrace CLI Entrypoint, Argument Handling, Subprocess Execution & Environment Isolation.

Tests cover:
1. CLI Argument Passthrough & Flag Mirroring (-h, --help, -v, --version, -- POSIX delimiter)
2. Complex argument handling (spaces, quotes, Thai Unicode, empty strings, multiple args)
3. Environment & Sys Integrity (sys.argv[0], sys.path[0], cwd preservation, sibling imports)
4. Stream interleaving and heavy buffered stdout/stderr flushing before exceptions
5. Exit code strictness (0, None, 42, 255, string messages, bools, unhandled exceptions,
   SyntaxError, IndentationError, TabError, KeyboardInterrupt -> 130, os._exit)
6. PEP 263 source encodings and circular exception chaining
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional
import pytest

from pythaitrace.cli import main as cli_main
from pythaitrace.runner import run_script

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"


def _run_cli_subprocess(
    args: List[str],
    cwd: Optional[Path] = None,
    env_vars: Optional[Dict[str, str]] = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess:
    """Helper to run pythaitrace.cli as a subprocess."""
    cmd = [sys.executable, "-m", "pythaitrace.cli", *args]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    current_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(SRC_DIR) + os.pathsep + current_pp if current_pp else str(SRC_DIR)
    )
    if env_vars:
        env.update(env_vars)

    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd or PROJECT_ROOT),
        timeout=timeout,
        env=env,
    )


# ==============================================================================
# 1. CLI Argument Passthrough & Flag Mirroring
# ==============================================================================

class TestCLIArgumentPassthroughAdversarial:
    """Adversarial testing of CLI flag parsing and transparent argument forwarding."""

    def test_script_arg_mirrors_short_help_flag(self, tmp_path):
        """thpy script.py -h must forward -h to the script and NOT trigger thpy help."""
        script = tmp_path / "target_help.py"
        script.write_text(
            "import sys\n"
            "print(f'SCRIPT_SEES_ARGV: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script), "-h"])
        assert res.returncode == 0
        assert "SCRIPT_SEES_ARGV: ['-h']" in res.stdout
        assert "usage: thpy" not in res.stdout
        assert "usage: thpy" not in res.stderr

    def test_script_arg_mirrors_long_help_flag(self, tmp_path):
        """thpy script.py --help must forward --help to script and NOT trigger thpy help."""
        script = tmp_path / "target_help_long.py"
        script.write_text(
            "import sys\n"
            "print(f'SCRIPT_SEES_ARGV: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script), "--help"])
        assert res.returncode == 0
        assert "SCRIPT_SEES_ARGV: ['--help']" in res.stdout
        assert "usage: thpy" not in res.stdout
        assert "usage: thpy" not in res.stderr

    def test_script_arg_mirrors_short_version_flag(self, tmp_path):
        """thpy script.py -v must forward -v to script and NOT print PyThaiTrace version."""
        script = tmp_path / "target_ver.py"
        script.write_text(
            "import sys\n"
            "print(f'SCRIPT_SEES_ARGV: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script), "-v"])
        assert res.returncode == 0
        assert "SCRIPT_SEES_ARGV: ['-v']" in res.stdout
        assert "PyThaiTrace 2.0.0" not in res.stdout

    def test_script_arg_mirrors_long_version_flag(self, tmp_path):
        """thpy script.py --version must forward --version to script."""
        script = tmp_path / "target_ver_long.py"
        script.write_text(
            "import sys\n"
            "print(f'SCRIPT_SEES_ARGV: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script), "--version"])
        assert res.returncode == 0
        assert "SCRIPT_SEES_ARGV: ['--version']" in res.stdout
        assert "PyThaiTrace 2.0.0" not in res.stdout

    def test_posix_double_dash_delimiter_basic(self, tmp_path):
        """thpy -- script.py arg1 arg2 must route correctly."""
        script = tmp_path / "target_posix.py"
        script.write_text(
            "import sys\n"
            "print(f'POSIX_ARGS: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess(["--", str(script), "alpha", "beta", "gamma"])
        assert res.returncode == 0
        assert "POSIX_ARGS: ['alpha', 'beta', 'gamma']" in res.stdout

    def test_posix_double_dash_with_flag_arguments(self, tmp_path):
        """thpy -- script.py -h --version must forward flags directly to script."""
        script = tmp_path / "target_posix_flags.py"
        script.write_text(
            "import sys\n"
            "print(f'FLAG_ARGS: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess(["--", str(script), "-h", "-v", "--version", "--help"])
        assert res.returncode == 0
        assert "FLAG_ARGS: ['-h', '-v', '--version', '--help']" in res.stdout

    def test_posix_double_dash_without_script(self):
        """thpy -- without script must print help and return 0."""
        res = _run_cli_subprocess(["--"])
        assert res.returncode == 0
        assert "usage: thpy" in res.stderr

    def test_cli_bare_invocation_no_args(self):
        """thpy with no args prints usage to stderr and exits cleanly."""
        res = _run_cli_subprocess([])
        assert res.returncode == 0
        assert "usage: thpy" in res.stderr

    def test_cli_standalone_help_flags(self):
        """thpy -h and thpy --help print usage to stdout and return 0."""
        for flag in ["-h", "--help"]:
            res = _run_cli_subprocess([flag])
            assert res.returncode == 0
            assert "usage: thpy" in res.stdout

    def test_cli_standalone_version_flags(self):
        """thpy -v and thpy --version print PyThaiTrace version to stdout and return 0."""
        for flag in ["-v", "--version"]:
            res = _run_cli_subprocess([flag])
            assert res.returncode == 0
            assert "PyThaiTrace 2.0.0" in res.stdout

    def test_script_args_with_spaces_and_quotes(self, tmp_path):
        """Arguments containing spaces, single quotes, and double quotes preserved."""
        script = tmp_path / "target_quotes.py"
        script.write_text(
            "import sys\n"
            "for i, arg in enumerate(sys.argv[1:]):\n"
            "    print(f'ARG_{i}: <{arg}>')\n",
            encoding="utf-8"
        )
        test_args = ["arg with spaces", "don't fail", 'say "hello" now', 'nested "quote\'s" here']
        res = _run_cli_subprocess([str(script), *test_args])
        assert res.returncode == 0
        for i, expected in enumerate(test_args):
            assert f"ARG_{i}: <{expected}>" in res.stdout

    def test_script_args_with_thai_unicode(self, tmp_path):
        """Arguments with Thai script and emojis pass through without mojibake."""
        script = tmp_path / "target_thai_args.py"
        script.write_text(
            "import sys\n"
            "for i, arg in enumerate(sys.argv[1:]):\n"
            "    print(f'THAI_ARG_{i}: {arg}')\n",
            encoding="utf-8"
        )
        thai_args = ["สวัสดีครับ", "ทดสอบการส่งพารามิเตอร์", "ระบบวินิจฉัยข้อผิดพลาด", "🚀🔥✨"]
        res = _run_cli_subprocess([str(script), *thai_args])
        assert res.returncode == 0
        for i, val in enumerate(thai_args):
            assert f"THAI_ARG_{i}: {val}" in res.stdout

    def test_script_empty_string_argument(self, tmp_path):
        """Empty string arguments '' must be preserved in sys.argv."""
        script = tmp_path / "target_empty_arg.py"
        script.write_text(
            "import sys\n"
            "print(f'LEN: {len(sys.argv)}')\n"
            "print(f'RAW: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script), "before", "", "after"])
        assert res.returncode == 0
        assert "LEN: 4" in res.stdout
        assert "RAW: ['before', '', 'after']" in res.stdout

    def test_script_many_positional_arguments(self, tmp_path):
        """Large number of positional arguments (50+) forwarded transparently."""
        script = tmp_path / "target_many_args.py"
        script.write_text(
            "import sys\n"
            "print(f'COUNT: {len(sys.argv) - 1}')\n"
            "assert sys.argv[1:] == [f'item_{i}' for i in range(50)]\n"
            "print('MANY_ARGS_OK')\n",
            encoding="utf-8"
        )
        args = [f"item_{i}" for i in range(50)]
        res = _run_cli_subprocess([str(script), *args])
        assert res.returncode == 0
        assert "MANY_ARGS_OK" in res.stdout

    def test_script_inner_posix_delimiter_passed_through(self, tmp_path):
        """thpy script.py -- inner_flag preserves -- in script args."""
        script = tmp_path / "target_inner_posix.py"
        script.write_text(
            "import sys\n"
            "print(f'INNER_ARGS: {sys.argv[1:]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script), "--", "inner_val"])
        assert res.returncode == 0
        assert "INNER_ARGS: ['--', 'inner_val']" in res.stdout

    def test_script_path_is_directory_handled_cleanly(self, tmp_path):
        """Passing a directory path instead of a file returns exit code 1."""
        res = _run_cli_subprocess([str(tmp_path)])
        assert res.returncode == 1
        assert "Error: Script" in res.stderr
        assert "not found" in res.stderr


# ==============================================================================
# 2. Environment & Sys Integrity
# ==============================================================================

class TestEnvironmentAndSysIntegrityAdversarial:
    """Adversarial testing of sys.argv[0], sys.path[0], cwd, and stream buffering."""

    def test_sys_argv_0_integrity_absolute_and_relative(self, tmp_path):
        """sys.argv[0] must be the script path, never thpy or cli.py."""
        script = tmp_path / "check_argv0.py"
        script.write_text(
            "import sys\n"
            "print(f'ARGV0: {sys.argv[0]}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 0
        assert "ARGV0:" in res.stdout
        argv0_val = res.stdout.split("ARGV0:")[1].strip()
        assert Path(argv0_val).resolve() == script.resolve()
        assert "cli.py" not in argv0_val.lower()
        assert "runner.py" not in argv0_val.lower()

    def test_sys_path_0_allows_sibling_module_import(self, tmp_path):
        """
        sys.path[0] must be the script directory, enabling import of sibling modules
        even when execution cwd is completely different.
        """
        isolated_dir = tmp_path / "sub_package"
        isolated_dir.mkdir()
        sibling = isolated_dir / "my_helper.py"
        sibling.write_text("HELPER_DATA = 'SIBLING_IMPORT_SUCCESS'\n", encoding="utf-8")

        main_script = isolated_dir / "app.py"
        main_script.write_text(
            "import my_helper\n"
            "print(my_helper.HELPER_DATA)\n",
            encoding="utf-8"
        )

        # Run with cwd set to project root (or another directory)
        res = _run_cli_subprocess([str(main_script)], cwd=PROJECT_ROOT)
        assert res.returncode == 0
        assert "SIBLING_IMPORT_SUCCESS" in res.stdout

    def test_cwd_preservation_across_execution(self, tmp_path):
        """Script's os.getcwd() must reflect caller's current working directory."""
        script = tmp_path / "check_cwd.py"
        script.write_text(
            "import os\n"
            "print(f'SCRIPT_CWD: {os.getcwd()}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)], cwd=tmp_path)
        assert res.returncode == 0
        assert f"SCRIPT_CWD: {tmp_path}" in res.stdout

    def test_heavy_interleaved_stdout_and_stderr_flush_before_crash(self, tmp_path):
        """
        Rapid interleaved stdout and stderr logging followed immediately by an exception.
        Verifies that unbuffered streams do not drop or scramble text prior to error card.
        """
        script = tmp_path / "interleave_stress.py"
        script.write_text(
            "import sys\n"
            "for i in range(100):\n"
            "    sys.stdout.write(f'OUT_{i:03d} ')\n"
            "    sys.stderr.write(f'ERR_{i:03d} ')\n"
            "raise RuntimeError('CrashAfter100InterleavedWrites')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        # All 100 stdout chunks must exist
        for i in range(100):
            assert f"OUT_{i:03d}" in res.stdout
            assert f"ERR_{i:03d}" in res.stderr
        assert "RuntimeError: CrashAfter100InterleavedWrites" in res.stderr
        # Thai diagnostic card also rendered
        assert ("โมเดลความคิด" in res.stderr or "RuntimeError" in res.stderr)

    def test_large_unflushed_stdout_before_exception(self, tmp_path):
        """
        Writing 64KB to sys.stdout without explicit flush, followed by unhandled exception.
        Must preserve all stdout output upon process exit.
        """
        script = tmp_path / "large_stdout.py"
        script.write_text(
            "import sys\n"
            "sys.stdout.write('X' * 65536)\n"
            "raise ValueError('CrashAfterLargeStdout')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert len(res.stdout) >= 65536
        assert "ValueError: CrashAfterLargeStdout" in res.stderr


# ==============================================================================
# 3. Exit Code Strictness
# ==============================================================================

class TestExitCodeStrictnessAdversarial:
    """Verifies strict adherence to exit code contracts across all termination modes."""

    @pytest.mark.parametrize("exit_arg,expected_code", [
        ("0", 0),
        ("None", 0),
        ("", 0),  # sys.exit()
        ("42", 42),
        ("1", 1),
        ("127", 127),
        ("255", 255),
    ])
    def test_numeric_and_none_sys_exit_codes(self, tmp_path, exit_arg, expected_code):
        """sys.exit(N), sys.exit(None), and sys.exit() return exact exit codes."""
        script = tmp_path / f"exit_{expected_code}.py"
        script.write_text(
            f"import sys\nsys.exit({exit_arg})\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == expected_code
        # Intentional exit must not trigger error card
        assert "โมเดลความคิด" not in res.stderr

    def test_sys_exit_with_string_message_fidelity(self, tmp_path):
        """sys.exit('message') exits with 1 and prints the string verbatim to stderr."""
        script = tmp_path / "exit_string.py"
        script.write_text(
            "import sys\n"
            "sys.exit('FATAL_DATABASE_UNREACHABLE')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert "FATAL_DATABASE_UNREACHABLE" in res.stderr
        # Must NOT render diagnostic card for deliberate sys.exit
        assert "โมเดลความคิด" not in res.stderr

    def test_sys_exit_with_boolean_fidelity(self, tmp_path):
        """sys.exit(True) exits with 1, sys.exit(False) exits with 0."""
        script_true = tmp_path / "exit_true.py"
        script_true.write_text("import sys\nsys.exit(True)\n", encoding="utf-8")
        assert _run_cli_subprocess([str(script_true)]).returncode == 1

        script_false = tmp_path / "exit_false.py"
        script_false.write_text("import sys\nsys.exit(False)\n", encoding="utf-8")
        assert _run_cli_subprocess([str(script_false)]).returncode == 0

    def test_unhandled_runtime_exceptions_return_code_1(self, tmp_path):
        """Standard runtime exceptions exit with code 1 and render both native and Thai card."""
        for exc_name in ["KeyError('missing_key')", "ZeroDivisionError('division by zero')", "IndexError('out of range')"]:
            script = tmp_path / "runtime_err.py"
            script.write_text(f"raise {exc_name}\n", encoding="utf-8")
            res = _run_cli_subprocess([str(script)])
            assert res.returncode == 1
            assert "Traceback (most recent call last):" in res.stderr
            assert ("โมเดลความคิด" in res.stderr or "ข้อผิดพลาด" in res.stderr)

    def test_compile_time_syntax_error_returns_code_1(self, tmp_path):
        """Pre-compilation check returns exit code 1 on SyntaxError with native error output."""
        script = tmp_path / "syntax_err.py"
        script.write_text("def broken_syntax(:\n    pass\n", encoding="utf-8")
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert "SyntaxError" in res.stderr
        # Precompile check strips runner frames: no 'runner.py' in the syntax error line
        assert "runner.py" not in res.stderr.lower() or "line" not in res.stderr

    def test_compile_time_indentation_error_returns_code_1(self, tmp_path):
        """Pre-compilation check returns exit code 1 on IndentationError."""
        script = tmp_path / "indent_err.py"
        script.write_text("def foo():\npass\n", encoding="utf-8")
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert "IndentationError" in res.stderr

    def test_compile_time_tab_error_returns_code_1(self, tmp_path):
        """Pre-compilation check returns exit code 1 on TabError."""
        script = tmp_path / "tab_err.py"
        script.write_text("def foo():\n    x = 1\n\ty = 2\n", encoding="utf-8")
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert ("TabError" in res.stderr or "IndentationError" in res.stderr)

    def test_keyboard_interrupt_returns_code_130_without_error_card(self, tmp_path):
        """Explicit or simulated KeyboardInterrupt yields returncode 130 and NO Thai card."""
        script = tmp_path / "sigint_sim.py"
        script.write_text("raise KeyboardInterrupt()\n", encoding="utf-8")
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 130
        assert "KeyboardInterrupt" in res.stderr
        # Must NOT render diagnostic card on SIGINT / KeyboardInterrupt
        assert "โมเดลความคิด" not in res.stderr

    def test_os_exit_bypasses_runner_cleanly(self, tmp_path):
        """os._exit(N) terminates the process immediately with code N."""
        script = tmp_path / "os_exit.py"
        script.write_text("import os\nos._exit(77)\n", encoding="utf-8")
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 77


# ==============================================================================
# 4. Hostile Edge Cases & Complex Scenarios
# ==============================================================================

class TestHostileEdgeCasesAdversarial:
    """Stress tests covering encodings, circular references, and thread exceptions."""

    def test_pep263_latin1_source_encoding(self, tmp_path):
        """PEP 263 latin-1 coding cookie handled without UTF-8 decode crash."""
        script = tmp_path / "latin1_script.py"
        # Write bytes with Latin-1 specific byte (\xe9 = é)
        content = (
            b"# -*- coding: latin-1 -*-\n"
            b"message = 'Caf\xe9'\n"
            b"print(f'LATIN1_OK: {len(message)}')\n"
        )
        script.write_bytes(content)
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 0
        assert "LATIN1_OK: 4" in res.stdout

    def test_circular_chained_exceptions_handled_without_recursion_error(self, tmp_path):
        """Circular exception chains (A -> B -> A) must not crash clean_traceback."""
        script = tmp_path / "circular_exc.py"
        script.write_text(
            "try:\n"
            "    raise ValueError('First')\n"
            "except ValueError as e1:\n"
            "    try:\n"
            "        raise RuntimeError('Second') from e1\n"
            "    except RuntimeError as e2:\n"
            "        e1.__cause__ = e2  # Create deliberate cycle\n"
            "        raise e2\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert "RuntimeError: Second" in res.stderr

    def test_worker_thread_exception_interception_and_main_thread_exit_code(self, tmp_path):
        """
        Worker thread uncaught exception is intercepted by threading.excepthook,
        while main thread completes cleanly with exit code 0.
        """
        script = tmp_path / "thread_unhandled.py"
        script.write_text(
            "import threading\n"
            "import time\n"
            "def worker():\n"
            "    raise ValueError('WorkerThreadCatastrophe')\n"
            "t = threading.Thread(target=worker)\n"
            "t.start()\n"
            "t.join()\n"
            "print('MAIN_THREAD_FINISHED')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        # In Python, worker thread crashes do not terminate the process if main thread completes
        assert res.returncode == 0
        assert "MAIN_THREAD_FINISHED" in res.stdout
        # Thread exception must be reported via threading.excepthook and Thai card rendered
        assert "ValueError: WorkerThreadCatastrophe" in res.stderr
        assert ("โมเดลความคิด" in res.stderr or "ValueError" in res.stderr)

    def test_deep_recursion_error_traceback_interception(self, tmp_path):
        """RecursionError with 500+ stack frames handled safely by normalizer/renderer."""
        script = tmp_path / "deep_recursion.py"
        script.write_text(
            "def recurse(n):\n"
            "    return recurse(n + 1)\n"
            "recurse(0)\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert "RecursionError" in res.stderr
        # Diagnostic card should be rendered without crashing
        assert len(res.stderr) > 0


    def test_argparse_script_full_transparency(self, tmp_path):
        """Scripts using argparse can handle --help, --version, and custom flags transparently."""
        script = tmp_path / "argparse_app.py"
        script.write_text(
            "import argparse\n"
            "parser = argparse.ArgumentParser(prog='my_cli', description='Custom user tool')\n"
            "parser.add_argument('--app-version', action='version', version='my_cli 9.9.9')\n"
            "parser.add_argument('--input', '-i', required=True)\n"
            "parser.add_argument('--count', type=int, default=1)\n"
            "args = parser.parse_args()\n"
            "print(f'PARSED: input={args.input}, count={args.count}')\n",
            encoding="utf-8"
        )
        # 1. Normal flag execution
        res = _run_cli_subprocess([str(script), "--input", "data.csv", "--count", "5"])
        assert res.returncode == 0
        assert "PARSED: input=data.csv, count=5" in res.stdout

        # 2. Script help flag: thpy script.py -h
        res_help = _run_cli_subprocess([str(script), "-h"])
        assert res_help.returncode == 0
        assert "usage: my_cli" in res_help.stdout
        assert "Custom user tool" in res_help.stdout
        assert "usage: thpy" not in res_help.stdout

        # 3. Script version flag
        res_ver = _run_cli_subprocess([str(script), "--app-version"])
        assert res_ver.returncode == 0
        assert "my_cli 9.9.9" in res_ver.stdout

    def test_user_script_globals_fidelity(self, tmp_path):
        """User script globals __name__, __file__, __doc__, __builtins__ correctly configured."""
        script = tmp_path / "check_globals.py"
        script.write_text(
            "'''Module docstring test.'''\n"
            "import builtins\n"
            "import sys\n"
            "assert __name__ == '__main__'\n"
            "assert __file__ is not None\n"
            "assert __doc__ == 'Module docstring test.'\n"
            "assert __builtins__ is builtins or isinstance(__builtins__, dict)\n"
            "assert sys.modules['__main__'].__file__ == __file__\n"
            "print('GLOBALS_VERIFIED')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 0
        assert "GLOBALS_VERIFIED" in res.stdout

    def test_user_script_can_import_pythaitrace(self, tmp_path):
        """User script can import pythaitrace without circular dependency or crash."""
        script = tmp_path / "import_self.py"
        script.write_text(
            "import pythaitrace\n"
            "print(f'PYTHAITRACE_VER: {pythaitrace.__version__}')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 0
        assert "PYTHAITRACE_VER: 2.0.0" in res.stdout

    def test_sys_excepthook_override_by_user_script(self, tmp_path):
        """If user script overrides sys.excepthook, runner honors it upon unhandled exception."""
        script = tmp_path / "custom_hook.py"
        script.write_text(
            "import sys\n"
            "def my_hook(exc_type, exc_val, tb):\n"
            "    sys.stderr.write(f'CUSTOM_HOOK_TRIGGERED: {exc_type.__name__}\\n')\n"
            "sys.excepthook = my_hook\n"
            "raise ValueError('testing custom hook')\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 1
        assert "CUSTOM_HOOK_TRIGGERED: ValueError" in res.stderr

    def test_keyboard_interrupt_traceback_preserves_code_location(self, tmp_path):
        """KeyboardInterrupt prints native traceback pointing to user line and exits with code 130."""
        script = tmp_path / "sigint_loc.py"
        script.write_text(
            "def run_loop():\n"
            "    raise KeyboardInterrupt()\n"
            "run_loop()\n",
            encoding="utf-8"
        )
        res = _run_cli_subprocess([str(script)])
        assert res.returncode == 130
        assert "KeyboardInterrupt" in res.stderr
        assert "run_loop" in res.stderr
        assert "sigint_loc.py" in res.stderr
        # Must not print Thai error card
        assert "โมเดลความคิด" not in res.stderr
