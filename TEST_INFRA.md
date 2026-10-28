# PyThaiTrace v2.0: Test Infrastructure & Verification Architecture (TEST_INFRA.md)

This document specifies the comprehensive test infrastructure, methodology, fixture inventory, and verification procedures for **PyThaiTrace v2.0**.

---

## 1. Testing Philosophy & 4-Tier Methodology

PyThaiTrace is designed with a **Zero-Crash Guarantee**: it must execute scripts transparently, preserve authentic CPython English tracebacks untouched on `stderr`, and render helpful, responsive Thai diagnostic mental model cards. It must never mask the original error or crash during diagnosis.

To verify this robustness across Python 3.10–3.14+, Windows PowerShell, Command Prompt, VSCode terminals, and Termux (Android), testing follows a **4-Tier Testing Methodology**:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 4: Real-World Scenarios & Terminal Environments                  │
│  - Real scripts with imports, argparse, multi-frame stacks             │
│  - Simulated Termux (40-60 cols) & VSCode split screens                │
│  - 3rd-party library exceptions (requests, pydantic, numpy)            │
├────────────────────────────────────────────────────────────────────────┤
│  Tier 3: Cross-Feature Integration Scenarios                           │
│  - Pre-compilation interception + CLI arg handling                     │
│  - Multi-threaded exceptions (threading.excepthook) + lock safety      │
│  - Custom exception + narrow width fallback card rendering             │
│  - Stream interleaving (stdout & stderr concurrent outputs)            │
├────────────────────────────────────────────────────────────────────────┤
│  Tier 2: Boundary, Adversarial & Corner Cases                          │
│  - Empty scripts (0 bytes), comments-only, binary files                │
│  - Extreme widths (35-40 cols ultra-narrow, 200+ cols ultra-wide)      │
│  - Complex caret offsets, unclosed parens at EOF, TabError vs spaces   │
│  - Thai Unicode tone marks (สระ/วรรณยุกต์) & emoji visual cell lengths │
│  - Internal crash failsafe isolation (monkeypatched engine failure)    │
├────────────────────────────────────────────────────────────────────────┤
│  Tier 1: Feature & Contract Coverage (>=5 cases per feature)          │
│  - Runner & CLI execution: exit codes 0, 1, custom SystemExit(N)       │
│  - Matcher 3-tier resolution: Tier 1 regex, Tier 2 fuzzy, Tier 3 class │
│  - Universal __FALLBACK__: docstring, module, search URLs              │
│  - Responsive renderer: Wide mode (>=80 cols), Narrow mode (<80 cols)  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Test Fixtures Catalogue (`tests/fixtures/`)

All test scripts are self-contained, reproducible, and isolated inside `tests/fixtures/`:

| Fixture File | Target Exception / Behavior | Description & Expected Outcome |
| :--- | :--- | :--- |
| `clean_script.py` | None (Success) | Prints to `stdout` and `stderr`, inspects `sys.argv`, exits with code `0`. Original stdout/stderr preserved. |
| `clean_script_with_args.py` | None (Success) | Validates CLI argument forwarding; asserts `sys.argv[1:]` contains flags and values. |
| `explicit_exit_code.py` | `SystemExit(42)` | Calls `sys.exit(42)`; PyThaiTrace runner must exit with code `42` without triggering diagnostic card. |
| `syntax_broken.py` | `SyntaxError` | Compile-time syntax error (missing colon in `if True\n  print(1)`). Caught before execution by `precompile_check`. |
| `indent_broken.py` | `IndentationError` | Compile-time indentation mismatch. Caught before execution by `precompile_check`. |
| `thread_broken.py` | `threading.excepthook` | Worker thread raising uncaught `RuntimeError`. Intercepted by `threading.excepthook` without deadlock. |
| `unmapped_custom.py` | `__FALLBACK__` | Custom 3rd-party exception (`DatabaseConnectionTimeout`) with docstring. Triggers Universal Fallback card. |
| `error_name.py` | `NameError` | Accesses undefined identifier (`print(undefined_variable_xyz)`). Regex extracts variable name. |
| `error_type.py` | `TypeError` | Adds unsupported types (`"text" + 123`). Regex extracts operand types `'str'` and `'int'`. |
| `error_index.py` | `IndexError` | Accesses out-of-bounds list element (`[1, 2][99]`). Regex extracts list/index info. |
| `error_key.py` | `KeyError` | Accesses missing dictionary key (`{"user_id": 101}["email"]`). Regex extracts missing key `'email'`. |
| `error_zerodiv.py` | `ZeroDivisionError` | Evaluates integer division by zero (`10 / 0`). Regex extracts division operation. |
| `error_module.py` | `ModuleNotFoundError` | Imports non-existent module (`import fake_package_xyz_999`). Regex extracts module name. |
| `error_attr.py` | `AttributeError` | Accesses non-existent attribute (`"sample".calculate()`). Regex extracts attribute and object type. |
| `error_value.py` | `ValueError` | Passes invalid literal to `int("invalid_string_literal")`. Regex extracts value and function. |

---

## 3. Test Suites & Verification Scope

### 3.1 `tests/test_runner.py` (CLI & Execution Core)
- **Exit Code Fidelity**:
  - `clean_script.py` -> exit code `0`.
  - `explicit_exit_code.py` -> exit code `42`.
  - Unhandled runtime error -> exit code `1`.
  - Compile-time `SyntaxError` -> exit code `1`.
  - Compile-time `IndentationError` -> exit code `1`.
- **Stream Transparency**:
  - `stdout` from user script is output 100% untouched.
  - `stderr` contains standard Python traceback first, followed by Thai diagnostic card.
- **Pre-execution Compilation Check**:
  - `SyntaxError` and `IndentationError` intercepted before `exec()` is called.
  - Runner frames stripped: `e.__traceback__ = None` so traceback matches native Python.
- **Worker Thread Interception**:
  - `thread_broken.py` intercepted by `threading.excepthook` with thread name and stack.
- **Failsafe Isolation Barrier**:
  - Internal exceptions in matcher or renderer are caught; process never crashes; original traceback preserved.

### 3.2 `tests/test_matcher.py` (3-Tier Matcher & Knowledge Base)
- **Tier 1 (Strict Regex Match with Named Groups)**:
  - Tests extraction of entity tokens (`identifier`, `type1`, `type2`, `key`, `module`, `attribute`) across all 10 core exceptions.
- **Tier 2 (Loose / Fuzzy Token Match)**:
  - Error messages with variations across Python versions (e.g. quote styles, "Did you mean: ...") match and extract candidate identifiers.
- **Tier 3 (Class-Level Generic Fallback)**:
  - Unrecognized message for known class (e.g. `NameError("custom message")`) returns class-level conceptual mental model and fix steps.
- **Universal `__FALLBACK__`**:
  - 3rd-party and custom exceptions extract module namespace, class name, docstring, and generate valid, escaped Google and StackOverflow search URLs.

### 3.3 `tests/test_responsive.py` (Responsive Rich Terminal Renderer)
- **Wide Mode (`width >= 80`)**:
  - Output uses Rich double-box borders (`╔`, `═`, `║`, `╚`).
  - Renders syntax snippet with line numbers and caret highlight.
  - Displays structured Thai sections: โมเดลความคิด, สาเหตุ, แนวทางแก้ไข.
- **Narrow Mode (`width < 80`, specifically 40-60 cols for Termux)**:
  - Flat layout without box borders.
  - Uses left-accent bar `▌` (`\u258c`) and compact vertical spacing.
  - Enforces `soft_wrap=True` / fold wrap so no line exceeds the terminal column boundary (`cell_len(line) <= width`).
- **Thai Typography & Emoji Handling**:
  - Proper Unicode width calculation using `rich.cells.cell_len` for Thai characters, combining vowels/tone marks, and emojis.
- **Plain-Text & Failsafe Fallback**:
  - Fallback plain text renderer emits clean, legible text without ANSI escape sequences when Rich fails or terminal is dumb.

---

## 4. Test Execution & CI Commands

### Running the Test Suite
```powershell
# Run all tests with pytest
python -m pytest tests -v

# Run runner tests only
python -m pytest tests/test_runner.py -v

# Run matcher tests only
python -m pytest tests/test_matcher.py -v

# Run responsive renderer tests only
python -m pytest tests/test_responsive.py -v

# Run with coverage report
python -m pytest tests --cov=pythaitrace --cov-report=term-missing
```

### Direct CLI Verification
```powershell
# Clean script
python -m pythaitrace.cli tests/fixtures/clean_script.py

# Compile-time syntax error
python -m pythaitrace.cli tests/fixtures/syntax_broken.py

# Unmapped custom exception
python -m pythaitrace.cli tests/fixtures/unmapped_custom.py

# Narrow terminal simulation
$env:COLUMNS="45"; python -m pythaitrace.cli tests/fixtures/error_name.py
```
