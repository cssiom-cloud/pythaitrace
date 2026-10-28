# Project: PyThaiTrace v2.0

## Architecture
PyThaiTrace v2.0 is a zero-crash, bilingual developer diagnostic CLI tool (`thpy <script.py>`) that intercepts Python errors with universal exception capture, responsive terminal output (Rich), and humanized Thai mental model explanations for VSCode and Termux.

### Architecture Diagram & Data Flow
```
 CLI Entrypoint (`thpy script.py [args...]`)
   │
   ├── Stream Reconfiguration: sys.stderr.reconfigure(encoding='utf-8', errors='replace')
   │
   ▼
 Pre-execution Compilation Check (`runner.py`)
   │ ──(SyntaxError / IndentationError)──► Normalizer ──► Matcher ──► Renderer ──► sys.exit(1)
   │
   ▼ (Compile OK)
 Install Exception Hooks (`hooks.py`)
   ├── sys.excepthook (Main Thread)
   ├── threading.excepthook (Worker Threads + threading.RLock)
   └── loop.set_exception_handler (Asyncio Loop)
   │
   ▼
 Script Execution Engine (`runner.py`)
   ├── Set types.ModuleType('__main__'), sys.argv, sys.path[0]
   ├── exec(code_obj, main_mod.__dict__)
   └── Clean exit code preservation (SystemExit, clean 0, unhandled 1/N)
   │
   ▼ (On Uncaught Exception)
 Original English Traceback
   └── sys.__excepthook__ / threading.__excepthook__ printed 100% INTACT to stderr
   │
   ▼
 Traceback Normalizer (`normalizer.py`)
   ├── Strip ANSI sequences
   ├── Parse PEP 657 caret coordinates (col_offset, end_col_offset, lineno)
   └── Separate user script frames from stdlib / runner frames
   │
   ▼
 3-Tier Matcher Engine (`matcher.py`)
   ├── Tier 1: Strict Regex with Named Groups (`rules.json`)
   ├── Tier 2: Fuzzy Token Extraction
   ├── Tier 3: Class Generic Fallback
   └── Universal `__FALLBACK__`: 3rd-party libs (docstring, search query)
   │
   ▼
 Responsive Rich Terminal Renderer (`renderer.py`)
   ├── Dynamic Width Detection (`shutil.get_terminal_size()`)
   ├── Wide Mode (>= 80 cols): Double-bordered Panel + Syntax Snippet
   ├── Narrow / Termux Mode (< 80 cols, 40-60 cols): Flat layout + ▌ bar + fold wrap
   └── Failsafe Shield: catch BaseException, fallback to plain text if Rich fails
```

---

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Pydantic Core Schemas | `FrameInfo`, `NormalizedTraceback`, `KnowledgeRule`, `MatchResult`, `ExplanationCard` | M1 | Survey 2 |
| 2 | Seeded Thai Knowledge Base | Top 10 beginner exceptions + `__FALLBACK__` with humanized Thai mental models, causes, fix steps | M1 | Survey 2 / R5 |
| 3 | Traceback Normalization | ANSI stripping, PEP 657 carets, user-frame isolation, SyntaxError coordinate branching | M2 | Survey 2 / R3 |
| 4 | 3-Tier Matcher Engine | Tier 1 strict regex with named groups, Tier 2 fuzzy tokens, Tier 3 class generic | M2 | Survey 2 / R3 |
| 5 | Universal Fallback Handler | 3rd-party exception introspection (module, class, docstring) + search URLs | M2 | Survey 2 / R3 |
| 6 | Responsive Dual-Mode Renderer | Dynamic width detection, Wide double-panel vs Narrow flat ▌ layout | M3 | Survey 3 / R4 |
| 7 | Windows Encoding Failsafe | UTF-8 stream reconfiguration (`reconfigure`) + plain-text fallback | M3 | Survey 3 / Survey 1 |
| 8 | Thai & Emoji Visual Width Alignment | Unicode character width handling using `cell_len` | M3 | Survey 3 |
| 9 | Pre-execution Compilation Check | `compile(source_bytes, filename, 'exec')` with runner frame stripping | M4 | Survey 1 / R1 |
| 10 | Comprehensive Exception Hooks | `sys.excepthook`, `threading.excepthook` (with `RLock`), asyncio hook | M4 | Survey 1 / R2 |
| 11 | Intact Original Traceback | Calling `sys.__excepthook__` / `threading.__excepthook__` untouched first | M4 | Survey 1 / R2 |
| 12 | Transparent Script Execution | `exec(code_obj, main_mod.__dict__)`, setting `sys.argv`, `sys.path[0]`, exit codes | M4 | Survey 1 / R1 |
| 13 | Failsafe Isolation Barrier | Global `try...except BaseException:` ensuring zero internal crashes | M4 | Survey 1 / R2 |
| 14 | CLI Entrypoint & Argument Passthrough | `thpy <script.py> [args...]`, `--help`, `--version`, `argparse.REMAINDER` | M4 | Survey 3 / R1 |
| 15 | Standard PEP 517/621 Packaging | `pyproject.toml` with `setuptools.build_meta`, console script `thpy` | M4 | Survey 3 |
| 16 | E2E Test Infrastructure & Fixtures | Fixtures for 10 exceptions, syntax/indent, threads, 3rd party, clean script | E2E Track | Survey 3 / R6 |
| 17 | Comprehensive Test Verification | `test_runner.py`, `test_matcher.py`, `test_responsive.py` across 40, 80, 120 cols | E2E Track / M5 | Survey 3 / R6 |
| 18 | Adversarial Coverage Hardening | White-box stress testing, edge-case caret blocks, multithread race exceptions | M5 (Phase 2) | Dual Track |

---

## Code Layout
```
ThaiVScodeorother/
├── pyproject.toml                         # Packaging and console script configuration
├── README.md                              # User and developer documentation
├── src/
│   └── pythaitrace/
│       ├── __init__.py                    # Version and public exports
│       ├── cli.py                         # CLI entrypoint and argument parser
│       ├── runner.py                      # Pre-compilation and script execution engine
│       ├── hooks.py                       # sys, threading, and asyncio exception hooks
│       ├── normalizer.py                  # Traceback parser, ANSI stripper, PEP 657 extractor
│       ├── matcher.py                     # 3-Tier Matcher & Universal Fallback engine
│       ├── models.py                      # Pydantic v2 data models
│       ├── renderer.py                    # Responsive Rich terminal renderer (Wide / Narrow)
│       └── rules.json                     # Seeded Thai mental models & error rules
└── tests/
    ├── __init__.py
    ├── conftest.py                        # Common pytest fixtures and helpers
    ├── fixtures/                          # Test scripts
    │   ├── clean_script.py                # Exit code 0 passthrough
    │   ├── syntax_broken.py               # Compile-time SyntaxError
    │   ├── indent_broken.py               # Compile-time IndentationError
    │   ├── thread_broken.py               # Worker thread unhandled exception
    │   ├── unmapped_custom.py             # 3rd-party custom exception
    │   ├── error_name.py                  # NameError
    │   ├── error_type.py                  # TypeError
    │   ├── error_index.py                 # IndexError
    │   ├── error_key.py                   # KeyError
    │   ├── error_zerodiv.py               # ZeroDivisionError
    │   ├── error_module.py                # ModuleNotFoundError
    │   ├── error_attr.py                  # AttributeError
    │   └── error_value.py                 # ValueError
    ├── test_runner.py                     # Execution, exit codes, compilation checks
    ├── test_matcher.py                    # 3-tier matcher, regex named groups, fallback
    └── test_responsive.py                 # UI layouts at 40, 80, 120 columns
```

---

## Milestones

### Implementation Track
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Core Models & Knowledge Base | `models.py`, `rules.json` | None | DONE |
| M2 | Traceback Normalizer & 3-Tier Matcher | `normalizer.py`, `matcher.py` | M1 | DONE |
| M3 | Responsive Rich Terminal Renderer | `renderer.py` | M1 | DONE |
| M4 | Exception Hooks, Runner & CLI | `hooks.py`, `runner.py`, `cli.py`, `pyproject.toml` | M2, M3 | DONE |
| M5 | E2E Test Pass & Adversarial Hardening | Full system E2E verification (Tiers 1-4) + Adversarial hardening (Tier 5) | M4, E2E Track (`TEST_READY.md`) | DONE |



### E2E Testing Track (Parallel)
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Test Suite & Test Infra | `TEST_INFRA.md`, `tests/fixtures/`, `test_runner.py`, `test_matcher.py`, `test_responsive.py`, `TEST_READY.md` | Interface Contracts | DONE |

---

## Interface Contracts

### 1. `models.py`
```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class FrameInfo(BaseModel, frozen=True):
    filename: str
    lineno: int
    funcname: str
    code_line: str = ""
    colno: Optional[int] = None
    end_colno: Optional[int] = None
    is_user_code: bool = True

class NormalizedTraceback(BaseModel):
    exc_type_name: str
    exc_message: str
    frames: List[FrameInfo]
    primary_frame: Optional[FrameInfo] = None
    is_syntax_error: bool = False
    raw_lines: List[str] = Field(default_factory=list)

class KnowledgeRule(BaseModel, frozen=True):
    error_id: str
    exception_class: str
    pattern: Optional[str] = None
    summary_th: str
    mental_model_th: str
    fix_suggestions_th: List[str]
    search_keywords: str

class MatchResult(BaseModel):
    rule: KnowledgeRule
    tier: int  # 1: strict regex, 2: fuzzy tokens, 3: class generic, 4: fallback
    extracted_entities: Dict[str, str] = Field(default_factory=dict)

class ExplanationCard(BaseModel):
    error_id: str
    exception_class: str
    title_th: str
    summary_th: str
    mental_model_th: str
    fix_suggestions_th: List[str]
    search_keywords: str
    google_search_url: str
    stackoverflow_search_url: str
    primary_frame: Optional[FrameInfo] = None
    is_fallback: bool = False
    docstring: Optional[str] = None
```

### 2. `normalizer.py ↔ matcher.py`
```python
def normalize_exception(exc: BaseException) -> NormalizedTraceback:
    """Normalize any Python exception into NormalizedTraceback."""
    ...

def strip_ansi(text: str) -> str:
    """Strip ANSI sequences from traceback strings."""
    ...
```

### 3. `matcher.py ↔ renderer.py`
```python
class MatcherEngine:
    def __init__(self, rules_path: Optional[str] = None): ...
    def match(self, norm_tb: NormalizedTraceback, exc: Optional[BaseException] = None) -> ExplanationCard:
        """Evaluate 3-tier matcher and fallback, returning ExplanationCard."""
        ...
```

### 4. `renderer.py`
```python
class ResponsiveRenderer:
    def __init__(self, console: Optional[Console] = None): ...
    def render(self, card: ExplanationCard, width: Optional[int] = None) -> None:
        """Render diagnostic card to stderr in Wide (>=80) or Narrow (<80) mode."""
        ...
    def render_to_string(self, card: ExplanationCard, width: int = 80) -> str:
        """Render card to string for virtual console testing."""
        ...
```

### 5. `runner.py & hooks.py ↔ cli.py`
```python
def precompile_check(source_bytes: bytes, filename: str) -> None:
    """Pre-compiles source code. If SyntaxError/IndentationError, strips runner frames,
    invokes diagnostic pipeline, and exits with code 1."""
    ...

def execute_script(script_path: str, args: List[str]) -> int:
    """Transparently executes target script, setting sys.argv and sys.path[0].
    Returns script exit code (0 on clean return, 1 or SystemExit code on exit)."""
    ...

def install_hooks() -> None:
    """Installs sys.excepthook, threading.excepthook, with failsafe isolation."""
    ...
```
