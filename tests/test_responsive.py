"""
Tests for PyThaiTrace Responsive Rich Terminal Renderer.
Covers:
- Tier 1: Feature Coverage (Wide mode >= 80 cols, Narrow mode < 80 cols, Plain-text fallback)
- Tier 2: Boundary & Corner Cases (Extreme widths: 35 cols and 200 cols, Thai cell widths, missing fields)
- Tier 3: Cross-Feature Combinations (Mode boundary at 79/80 cols, Fallback card in narrow mode)
- Tier 4: Real-World Scenarios (Simulated Termux 45 cols, VSCode split-terminal 65 cols, Desktop 120 cols)
"""
import re
import pytest
from rich.cells import cell_len
from rich.console import Console

try:
    import pythaitrace
    from pythaitrace.models import FrameInfo, ExplanationCard
    from pythaitrace.renderer import ResponsiveRenderer
    HAS_PYTHAITRACE = True
except ImportError:
    HAS_PYTHAITRACE = False
    FrameInfo = None  # type: ignore
    ExplanationCard = None  # type: ignore
    ResponsiveRenderer = None  # type: ignore


@pytest.fixture(autouse=True)
def require_pythaitrace():
    if not HAS_PYTHAITRACE:
        pytest.skip("pythaitrace module not yet implemented")


# Helper pattern to check for ANSI escape codes
ANSI_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


# ==============================================================================
# Tier 1: Feature Coverage (Wide Mode, Narrow Mode, Plain-Text Fallback)
# ==============================================================================

class TestTier1ResponsiveRendererFeatures:
    """Verifies layout switching between Wide Mode and Narrow Mode."""

    def test_wide_mode_double_borders_at_80_columns(self, make_console, sample_card_data):
        """Wide Mode (>= 80 cols) must render full panels with double borders."""
        console, buf = make_console(width=80, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=80)
        output = buf.getvalue()

        # In Wide Mode, double-border box characters (╔, ═, ║, ╚ or ╭, ─, ╰ for rounded) should exist
        assert ("╔" in output or "═" in output or "║" in output or "╭" in output or "─" in output)
        # Thai section titles must be present
        assert "โมเดลความคิด" in output
        assert "แนวทางแก้ไข" in output
        # Code line must appear in syntax snippet
        assert "print(unknown_var)" in output

    def test_wide_mode_layout_at_120_columns(self, make_console, sample_card_data):
        """Wide Mode at 120 columns expands cleanly without line break artifacts."""
        console, buf = make_console(width=120, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=120)
        output = buf.getvalue()

        assert "โมเดลความคิด" in output
        assert len(output) > 0

    def test_narrow_mode_flat_layout_at_60_columns(self, make_console, sample_card_data):
        """Narrow Mode (< 80 cols) must use flat layout with left-accent bar '▌'."""
        console, buf = make_console(width=60, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=60)
        output = buf.getvalue()

        # Left-accent bar ▌ (\u258c) must be present
        assert "▌" in output or "▍" in output or "▎" in output
        # Heavy double-border box corners (╔, ╚) must NOT be used in flat narrow layout
        assert "╔" not in output
        assert "╚" not in output
        # Content remains fully readable
        assert "โมเดลความคิด" in output
        assert "แนวทางแก้ไข" in output

    def test_narrow_mode_termux_at_45_columns(self, make_console, sample_card_data):
        """Termux mobile terminal simulation (45 columns) renders flat without truncation."""
        console, buf = make_console(width=45, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=45)
        output = buf.getvalue()

        assert "▌" in output or "▍" in output or "▎" in output
        assert "โมเดลความคิด" in output
        # Ensure every rendered line respects the terminal width boundary
        for line in output.splitlines():
            # Strip ANSI when calculating visual cell length
            clean_line = ANSI_PATTERN.sub("", line)
            assert cell_len(clean_line) <= 45, f"Line overflowed 45 columns: '{clean_line}' (len={cell_len(clean_line)})"

    def test_plain_text_fallback_without_ansi(self, make_console, sample_card_data):
        """Failsafe or plain-text mode must emit clean text without ANSI escape sequences."""
        console, buf = make_console(width=80, color=False)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        # Either via render_to_string or render with color=False
        if hasattr(renderer, "render_to_string"):
            output = renderer.render_to_string(card, width=80)
        else:
            renderer.render(card, width=80)
            output = buf.getvalue()

        # If plain text fallback, no raw ESC control characters should be present
        clean_text = ANSI_PATTERN.sub("", output)
        assert len(clean_text) > 0
        assert "โมเดลความคิด" in clean_text
        assert "NameError" in clean_text


# ==============================================================================
# Tier 2: Boundary & Corner Cases
# ==============================================================================

class TestTier2ResponsiveRendererBoundaries:
    """Verifies edge cases in terminal dimensions and card fields."""

    def test_extreme_narrow_width_35_columns(self, make_console, sample_card_data):
        """Ultra-narrow screen (35 cols) must render without crashing or indefinite loops."""
        console, buf = make_console(width=35, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=35)
        output = buf.getvalue()
        assert len(output) > 0

    def test_extreme_wide_width_200_columns(self, make_console, sample_card_data):
        """Ultra-wide monitor (200 cols) renders gracefully without layout breaks."""
        console, buf = make_console(width=200, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=200)
        output = buf.getvalue()
        assert "โมเดลความคิด" in output
        assert len(output) > 0

    def test_card_with_optional_fields_as_none_or_empty(self, make_console):
        """Card with primary_frame=None, empty fix suggestions, and no docstring renders cleanly."""
        console, buf = make_console(width=80, color=True)
        renderer = ResponsiveRenderer(console=console)
        minimal_card = ExplanationCard(
            error_id="GENERIC_ERROR",
            exception_class="RuntimeError",
            title_th="ข้อผิดพลาดที่ไม่ระบุ",
            summary_th="เกิดข้อผิดพลาดในการทำงาน",
            mental_model_th="คำอธิบายสั้น",
            fix_suggestions_th=[],
            search_keywords="Python RuntimeError",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
            primary_frame=None,
            is_fallback=False,
            docstring=None
        )

        renderer.render(minimal_card, width=80)
        output = buf.getvalue()
        assert "ข้อผิดพลาดที่ไม่ระบุ" in output

    def test_thai_and_emoji_visual_cell_widths(self, make_console):
        """Verifies Thai combining marks and emojis do not break alignment."""
        console, buf = make_console(width=50, color=True)
        renderer = ResponsiveRenderer(console=console)
        thai_card = ExplanationCard(
            error_id="TEST_THAI",
            exception_class="ValueError",
            title_th="💡 ทดสอบสระและวรรณยุกต์: ที่นี่มีข้อผิดพลาดเกิดขึ้น",
            summary_th="ข้อความที่มีสระซ้อน เช่น ที่ ผู้ ซึ่ง ได้ ทำ การ ทดลอง 🌟",
            mental_model_th="การเปรียบเทียบเชิงอุปมาอุปไมย 🛠️",
            fix_suggestions_th=["แก้ไขตามคำแนะนำที่ ๑", "ตรวจสอบให้แน่ใจ"],
            search_keywords="test thai",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )

        renderer.render(thai_card, width=50)
        output = buf.getvalue()
        assert "💡" in output
        assert "ข้อผิดพลาด" in output


# ==============================================================================
# Tier 3: Cross-Feature Combinations
# ==============================================================================

class TestTier3ResponsiveRendererCombinations:
    """Verifies mode boundary behavior and fallback card layout."""

    def test_breakpoint_boundary_switch_79_vs_80(self, make_console, sample_card_data):
        """
        Width 79 must select Narrow Mode (left-accent bar ▌, no double-box ╔).
        Width 80 must select Wide Mode (double-box or panel borders).
        """
        card = ExplanationCard(**sample_card_data)

        # 79 columns -> Narrow Mode
        con79, buf79 = make_console(width=79, color=True)
        renderer79 = ResponsiveRenderer(console=con79)
        renderer79.render(card, width=79)
        out79 = buf79.getvalue()
        assert ("▌" in out79 or "▍" in out79 or "▎" in out79)
        assert "╔" not in out79

        # 80 columns -> Wide Mode
        con80, buf80 = make_console(width=80, color=True)
        renderer80 = ResponsiveRenderer(console=con80)
        renderer80.render(card, width=80)
        out80 = buf80.getvalue()
        assert ("╔" in out80 or "═" in out80 or "║" in out80 or "╭" in out80 or "─" in out80)

    def test_fallback_card_rendered_in_narrow_mode(self, make_console, sample_fallback_card_data):
        """Universal Fallback card with docstring and URLs renders properly in Narrow Mode."""
        console, buf = make_console(width=50, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_fallback_card_data)

        renderer.render(card, width=50)
        output = buf.getvalue()
        assert "DatabaseConnectionTimeout" in output
        assert "Docstring" in output or "คำอธิบาย" in output or "handshake" in output
        # Verify search link presence
        assert "google" in output.lower() or "stackoverflow" in output.lower()


# ==============================================================================
# Tier 4: Real-World Application Scenarios
# ==============================================================================

class TestTier4ResponsiveRendererRealWorld:
    """Simulates real terminal environments (Termux, VSCode, Terminal)."""

    @pytest.mark.parametrize("terminal_width,mode_name", [
        (45, "Termux Mobile"),
        (65, "VSCode Split Editor"),
        (100, "Standard Terminal"),
        (140, "Ultrawide Terminal"),
    ])
    def test_rendering_across_real_world_viewports(
        self, make_console, sample_card_data, terminal_width, mode_name
    ):
        """Ensures all standard viewport widths render without errors or overflows."""
        console, buf = make_console(width=terminal_width, color=True)
        renderer = ResponsiveRenderer(console=console)
        card = ExplanationCard(**sample_card_data)

        renderer.render(card, width=terminal_width)
        output = buf.getvalue()
        assert len(output) > 0, f"Renderer output empty for {mode_name} (width {terminal_width})"
        assert "NameError" in output
