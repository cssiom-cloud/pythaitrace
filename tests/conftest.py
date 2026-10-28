"""
Pytest configuration and shared fixtures for PyThaiTrace test suite.
"""
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import pytest
from rich.console import Console

# Ensure src/ is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Returns the absolute Path to the tests/fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def make_console() -> Callable[[int, bool], Tuple[Console, io.StringIO]]:
    """
    Factory fixture creating a virtual Rich Console recording into a StringIO buffer.
    Allows exact verification of terminal layouts at widths 40, 45, 60, 80, 120, etc.
    """
    def _create(width: int = 80, color: bool = True) -> Tuple[Console, io.StringIO]:
        buf = io.StringIO()
        console = Console(
            file=buf,
            width=width,
            color_system="truecolor" if color else None,
            force_terminal=True,
            record=True,
            highlight=False,
            legacy_windows=False
        )
        return console, buf
    return _create


@pytest.fixture
def run_thpy():
    """
    Helper fixture to execute PyThaiTrace CLI as a subprocess.
    Returns subprocess.CompletedProcess with captured stdout, stderr, and returncode.
    """
    def _run(
        fixture_name_or_path: str,
        cli_args: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        cwd: Optional[Path] = None
    ) -> subprocess.CompletedProcess:
        # Resolve target script path
        path_candidate = Path(fixture_name_or_path)
        if not path_candidate.is_file():
            path_candidate = FIXTURES_DIR / fixture_name_or_path

        target_path_str = str(path_candidate.resolve())

        cmd = [
            sys.executable,
            "-m",
            "pythaitrace.cli",
            target_path_str,
            *(cli_args or [])
        ]

        merged_env = os.environ.copy()
        merged_env["PYTHONUNBUFFERED"] = "1"
        merged_env["PYTHONIOENCODING"] = "utf-8"
        # Ensure src is in PYTHONPATH for subprocess execution
        current_pythonpath = merged_env.get("PYTHONPATH", "")
        merged_env["PYTHONPATH"] = (
            str(SRC_DIR) + os.pathsep + current_pythonpath if current_pythonpath else str(SRC_DIR)
        )
        if env_vars:
            merged_env.update(env_vars)

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(cwd or PROJECT_ROOT),
            env=merged_env,
            timeout=15
        )
        return result
    return _run


@pytest.fixture
def sample_frame_info() -> Dict[str, Any]:
    """Sample dictionary conforming to FrameInfo interface contract."""
    return {
        "filename": "d:/project/script.py",
        "lineno": 14,
        "funcname": "calculate_tax",
        "code_line": "total = price + tax_rate",
        "colno": 9,
        "end_colno": 25,
        "is_user_code": True,
    }


@pytest.fixture
def sample_card_data() -> Dict[str, Any]:
    """Sample dictionary conforming to ExplanationCard interface contract."""
    return {
        "error_id": "NAME_NOT_DEFINED",
        "exception_class": "NameError",
        "title_th": "พบข้อผิดพลาด: ชื่อตัวแปรไม่ถูกต้อง (NameError)",
        "summary_th": "มีการเรียกใช้ชื่อตัวแปรที่ยังไม่ได้ถูกสร้างขึ้นในโปรแกรม",
        "mental_model_th": "เปรียบเสมือนการเรียกหาของในกล่องที่ยังไม่เคยวางของชิ้นนั้นลงไป",
        "fix_suggestions_th": [
            "ตรวจสอบการสะกดชื่อตัวแปรให้ตรงกับที่ประกาศไว้",
            "ตรวจสอบว่าได้กำหนดค่าให้กับตัวแปรก่อนเรียกใช้งานหรือไม่",
            "ตรวจสอบขอบเขต (Scope) ของตัวแปรว่าถูกสร้างอยู่ในฟังก์ชันอื่นหรือไม่",
        ],
        "search_keywords": "Python NameError name is not defined",
        "google_search_url": "https://www.google.com/search?q=Python+NameError+name+is+not+defined",
        "stackoverflow_search_url": "https://stackoverflow.com/search?q=Python+NameError+name+is+not+defined",
        "primary_frame": {
            "filename": "d:/project/script.py",
            "lineno": 10,
            "funcname": "main",
            "code_line": "print(unknown_var)",
            "colno": 7,
            "end_colno": 18,
            "is_user_code": True,
        },
        "is_fallback": False,
        "docstring": None,
    }


@pytest.fixture
def sample_fallback_card_data() -> Dict[str, Any]:
    """Sample dictionary conforming to ExplanationCard for unmapped 3rd party exception."""
    return {
        "error_id": "__FALLBACK__",
        "exception_class": "DatabaseConnectionTimeout",
        "title_th": "พบข้อผิดพลาดที่ไม่คุ้นเคย: DatabaseConnectionTimeout",
        "summary_th": "เกิดข้อยกเว้นจากไลบรารีภายนอกหรือคลาสที่กำหนดขึ้นเอง",
        "mental_model_th": "ระบบพบข้อผิดพลาดเฉพาะทางของไลบรารี ซึ่งไม่ได้จัดอยู่ในข้อผิดพลาดพื้นฐานทั่วไป",
        "fix_suggestions_th": [
            "อ่านคำอธิบายใน Docstring ด้านบนเพื่อทำความเข้าใจเงื่อนไขของข้อผิดพลาด",
            "ตรวจสอบเอกสารคู่มือของไลบรารีเกี่ยวกับข้อผิดพลาดนี้",
            "ค้นหาแนวทางแก้ไขจากลิงก์ Google หรือ StackOverflow ด้านล่าง",
        ],
        "search_keywords": "Python DatabaseConnectionTimeout",
        "google_search_url": "https://www.google.com/search?q=Python+DatabaseConnectionTimeout",
        "stackoverflow_search_url": "https://stackoverflow.com/search?q=Python+DatabaseConnectionTimeout",
        "primary_frame": {
            "filename": "d:/project/app.py",
            "lineno": 45,
            "funcname": "connect_db",
            "code_line": "raise DatabaseConnectionTimeout('timeout after 30s')",
            "colno": 5,
            "end_colno": 50,
            "is_user_code": True,
        },
        "is_fallback": True,
        "docstring": "Raised when a remote cloud storage cluster fails to acknowledge handshakes.",
    }
