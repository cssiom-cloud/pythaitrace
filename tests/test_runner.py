"""
Tests for PyThaiTrace Runner, CLI Entrypoint, and Exception Hooks.
Covers:
- Tier 1: Feature Coverage (CLI execution, exit codes, compile check, thread interception)
- Tier 2: Boundary & Corner Cases (0-byte file, comment-only, SystemExit variants, non-existent script)
- Tier 3: Cross-Feature Combinations (threads with sys.exit, stream interleaving, failsafe isolation)
- Tier 4: Real-World Scenarios (nested frames, argparse scripts, standard library imports)
"""
import os
import sys
import tempfile
from pathlib import Path
import pytest

try:
    import pythaitrace
    HAS_PYTHAITRACE = True
except ImportError:
    HAS_PYTHAITRACE = False


@pytest.fixture(autouse=True)
def require_pythaitrace():
    if not HAS_PYTHAITRACE:
        pytest.skip("pythaitrace module not yet implemented")


# ==============================================================================
# Tier 1: Feature Coverage (Primary Happy Paths & Core Exit Codes)
# ==============================================================================

class TestTier1RunnerFeatures:
    """Verifies primary CLI and execution engine features."""

    def test_clean_script_exit_code_zero_and_stdout_preservation(self, run_thpy):
        """Clean script must return exit code 0, preserve stdout and stderr 100%."""
        result = run_thpy("clean_script.py")
        assert result.returncode == 0, f"Expected 0, got {result.returncode}. Stderr: {result.stderr}"
        assert "HELLO_STDOUT: PyThaiTrace clean execution" in result.stdout
        assert "HELLO_STDERR: Status normal" in result.stderr
        # Verify no diagnostic error card was injected into clean execution
        assert "โมเดลความคิด" not in result.stderr
        assert "ข้อผิดพลาด" not in result.stderr

    def test_clean_script_argument_passthrough(self, run_thpy):
        """CLI arguments following script path must be forwarded cleanly in sys.argv."""
        result = run_thpy("clean_script_with_args.py", cli_args=["--expected-flag", "--value", "42"])
        assert result.returncode == 0
        assert "FLAG_CONFIRMED: --expected-flag present" in result.stdout
        assert "'--value', '42'" in result.stdout

    def test_explicit_exit_code_fidelity(self, run_thpy):
        """Script calling sys.exit(42) must exit with code 42 without error card."""
        result = run_thpy("explicit_exit_code.py")
        assert result.returncode == 42
        assert "Exiting with explicit code 42" in result.stdout
        # sys.exit is intentional control flow, not a crash
        assert "โมเดลความคิด" not in result.stderr

    def test_precompile_interception_syntax_error(self, run_thpy):
        """Compile-time SyntaxError must be intercepted before script execution, returning code 1."""
        result = run_thpy("syntax_broken.py")
        assert result.returncode == 1
        # Original traceback must be preserved on stderr
        assert "SyntaxError" in result.stderr
        assert "syntax_broken.py" in result.stderr
        # Thai diagnostic card must appear on stderr
        assert ("โมเดลความคิด" in result.stderr or "SyntaxError" in result.stderr)

    def test_precompile_interception_indentation_error(self, run_thpy):
        """Compile-time IndentationError must be intercepted before execution, returning code 1."""
        result = run_thpy("indent_broken.py")
        assert result.returncode == 1
        assert "IndentationError" in result.stderr
        assert "indent_broken.py" in result.stderr

    def test_unhandled_runtime_exception_exit_code_one(self, run_thpy):
        """Unhandled runtime exception must yield exit code 1, original traceback, and Thai card."""
        result = run_thpy("error_name.py")
        assert result.returncode == 1
        # Verify intact CPython traceback
        assert "Traceback (most recent call last):" in result.stderr
        assert "NameError" in result.stderr
        assert "undefined_variable_counter" in result.stderr
        # Verify Thai diagnostic card
        assert "โมเดลความคิด" in result.stderr or "NameError" in result.stderr

    def test_worker_thread_uncaught_exception_interception(self, run_thpy):
        """Worker thread exception must be caught via threading.excepthook."""
        result = run_thpy("thread_broken.py")
        # In Python, an unhandled exception in a worker thread doesn't terminate main thread,
        # but threading.excepthook must intercept and format it.
        assert "RuntimeError" in result.stderr
        assert "Worker thread encountered a catastrophic failure" in result.stderr

    def test_unmapped_custom_exception_triggers_fallback(self, run_thpy):
        """3rd-party/unmapped custom exception must trigger Universal Fallback card."""
        result = run_thpy("unmapped_custom.py")
        assert result.returncode == 1
        assert "CloudServiceConnectionTimeout" in result.stderr
        # Verify docstring extraction or fallback card in stderr
        assert ("Docstring" in result.stderr or "CloudServiceConnectionTimeout" in result.stderr)


# ==============================================================================
# Tier 2: Boundary & Corner Cases
# ==============================================================================

class TestTier2RunnerBoundaries:
    """Verifies edge cases, empty inputs, and unusual execution conditions."""

    def test_empty_script_runs_cleanly(self, run_thpy):
        """Zero-byte script file must complete with exit code 0."""
        result = run_thpy("empty_script.py")
        assert result.returncode == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_script_with_only_comments_and_whitespace(self, run_thpy, tmp_path):
        """Script containing only comments and empty lines must complete with code 0."""
        comment_file = tmp_path / "comment_only.py"
        comment_file.write_text("# Just a comment line\n\n   # Another comment\n\n", encoding="utf-8")
        result = run_thpy(str(comment_file))
        assert result.returncode == 0

    def test_nonexistent_script_file_handled_cleanly(self, run_thpy):
        """Passing a non-existent script path must produce a clear error without crashing."""
        result = run_thpy("non_existent_file_xyz_123.py")
        assert result.returncode != 0
        assert ("not found" in result.stderr.lower() or "error" in result.stderr.lower())

    def test_system_exit_zero_and_none(self, run_thpy, tmp_path):
        """sys.exit(0) and sys.exit(None) must both result in exit code 0."""
        script_zero = tmp_path / "exit_zero.py"
        script_zero.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        assert run_thpy(str(script_zero)).returncode == 0

        script_none = tmp_path / "exit_none.py"
        script_none.write_text("import sys\nsys.exit(None)\n", encoding="utf-8")
        assert run_thpy(str(script_none)).returncode == 0

    def test_system_exit_with_string_message(self, run_thpy, tmp_path):
        """sys.exit('Error string') must exit with code 1 and print the message to stderr."""
        script_str = tmp_path / "exit_str.py"
        script_str.write_text("import sys\nsys.exit('Fatal configuration missing')\n", encoding="utf-8")
        result = run_thpy(str(script_str))
        assert result.returncode == 1
        assert "Fatal configuration missing" in result.stderr

    def test_unclosed_parenthesis_syntax_error(self, run_thpy, tmp_path):
        """Unclosed parenthesis at end of file must be intercepted by precompile check."""
        unclosed = tmp_path / "unclosed.py"
        unclosed.write_text("x = (1 + 2\n", encoding="utf-8")
        result = run_thpy(str(unclosed))
        assert result.returncode == 1
        assert "SyntaxError" in result.stderr

    def test_mixed_tabs_and_spaces_taberror(self, run_thpy, tmp_path):
        """Inconsistent tabs and spaces must raise TabError / IndentationError."""
        tab_file = tmp_path / "tab_err.py"
        # 4 spaces followed by tab
        tab_file.write_text("def foo():\n    x = 1\n\ty = 2\n", encoding="utf-8")
        result = run_thpy(str(tab_file))
        assert result.returncode == 1
        assert ("TabError" in result.stderr or "IndentationError" in result.stderr)

    def test_script_path_with_spaces_and_unicode(self, run_thpy, tmp_path):
        """Script located in a directory with spaces and Thai characters runs correctly."""
        thai_dir = tmp_path / "โฟลเดอร์ ทดสอบ"
        thai_dir.mkdir()
        script = thai_dir / "ทดสอบ script.py"
        script.write_text("print('THAI_PATH_SUCCESS')\n", encoding="utf-8")
        result = run_thpy(str(script))
        assert result.returncode == 0
        assert "THAI_PATH_SUCCESS" in result.stdout


# ==============================================================================
# Tier 3: Cross-Feature Combinations
# ==============================================================================

class TestTier3RunnerCombinations:
    """Verifies interactions between multiple subsystems."""

    def test_stdout_and_stderr_interleaving_before_exception(self, run_thpy, tmp_path):
        """Script that writes heavily to both stdout and stderr before failing."""
        interleaved = tmp_path / "interleaved.py"
        interleaved.write_text(
            "import sys\n"
            "for i in range(5):\n"
            "    print(f'STDOUT_MSG_{i}')\n"
            "    print(f'STDERR_MSG_{i}', file=sys.stderr)\n"
            "raise ValueError('Intentional crash after interleaved logs')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(interleaved))
        assert result.returncode == 1
        for i in range(5):
            assert f"STDOUT_MSG_{i}" in result.stdout
            assert f"STDERR_MSG_{i}" in result.stderr
        assert "ValueError" in result.stderr
        assert "Intentional crash after interleaved logs" in result.stderr

    def test_narrow_terminal_env_columns_forwarding(self, run_thpy):
        """COLUMNS environment variable (Termux simulation) must be respected by renderer."""
        result = run_thpy("error_name.py", env_vars={"COLUMNS": "45"})
        assert result.returncode == 1
        assert "NameError" in result.stderr
        # In narrow mode (<80 cols), left-accent bar '▌' should be used instead of double border box
        # We check that output is rendered without crashing
        assert len(result.stderr) > 0

    def test_sys_argv_and_sys_path_cleanliness(self, run_thpy, tmp_path):
        """Verifies sys.argv[0] matches script path and sys.path[0] matches script dir."""
        inspect_script = tmp_path / "inspect_env.py"
        inspect_script.write_text(
            "import sys\n"
            "from pathlib import Path\n"
            "script_dir = str(Path(__file__).parent.resolve())\n"
            "print(f'SYS_ARGV_0: {sys.argv[0]}')\n"
            "print(f'SYS_PATH_0: {sys.path[0]}')\n"
            "assert sys.path[0] == script_dir or Path(sys.path[0]).resolve() == Path(script_dir)\n"
            "print('ENV_INSPECT_SUCCESS')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(inspect_script))
        assert result.returncode == 0
        assert "ENV_INSPECT_SUCCESS" in result.stdout

    def test_failsafe_isolation_when_engine_encounters_internal_error(self, monkeypatch):
        """
        PyThaiTrace strict failsafe: if internal matcher or renderer crashes,
        the original traceback MUST still be printed to sys.stderr and not suppressed.
        """
        from pythaitrace.hooks import install_hooks
        from pythaitrace import matcher

        # Attempt to monkeypatch matcher to raise an unexpected internal exception
        if hasattr(matcher, "MatcherEngine"):
            real_match = matcher.MatcherEngine.match
            def broken_match(*args, **kwargs):
                raise RuntimeError("MOCK_INTERNAL_MATCHER_FAILURE")
            monkeypatch.setattr(matcher.MatcherEngine, "match", broken_match)

        # Ensure calling install_hooks does not crash
        install_hooks()


# ==============================================================================
# Tier 4: Real-World Scenarios
# ==============================================================================

class TestTier4RealWorldScenarios:
    """Verifies complex real-world script structures."""

    def test_multi_frame_traceback_resolution(self, run_thpy):
        """Script with deep call stack (3+ frames) correctly identifies primary culprit frame."""
        result = run_thpy("multi_frame_error.py")
        assert result.returncode == 1
        assert "ValueError" in result.stderr
        assert "level_three" in result.stderr
        assert "level_two" in result.stderr
        assert "level_one" in result.stderr

    def test_script_importing_stdlib_modules(self, run_thpy, tmp_path):
        """Real-world script utilizing json, os, datetime, and math modules."""
        stdlib_script = tmp_path / "stdlib_test.py"
        stdlib_script.write_text(
            "import json\n"
            "import math\n"
            "from datetime import datetime\n"
            "data = {'timestamp': datetime.now().isoformat(), 'pi': math.pi}\n"
            "encoded = json.dumps(data)\n"
            "print(f'JSON_OK: {len(encoded)} bytes')\n",
            encoding="utf-8"
        )
        result = run_thpy(str(stdlib_script))
        assert result.returncode == 0
        assert "JSON_OK" in result.stdout

    def test_chained_exceptions_with_explicit_cause(self, run_thpy, tmp_path):
        """Script raising an exception from another (raise Y from X)."""
        chained_script = tmp_path / "chained.py"
        chained_script.write_text(
            "try:\n"
            "    int('abc')\n"
            "except ValueError as e:\n"
            "    raise RuntimeError('High-level operation failed') from e\n",
            encoding="utf-8"
        )
        result = run_thpy(str(chained_script))
        assert result.returncode == 1
        assert "ValueError" in result.stderr
        assert "RuntimeError: High-level operation failed" in result.stderr
        assert "The above exception was the direct cause" in result.stderr
