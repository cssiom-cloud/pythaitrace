"""
Adversarial Stress Test Suite for PyThaiTrace Responsive Rich Terminal Renderer (renderer.py).

Scope & Attack Vectors:
1. Micro-viewports (widths 10, 20, 30, 35 columns) & pathological micro-widths (1 to 8 cols).
2. Huge viewports (widths 300, 500, 1000, 5000 columns).
3. Zero, negative, and invalid width values (including COLUMNS="0").
4. Extreme Thai Unicode: deep stacking diacritics, Sara Am, ZWJ/ZWNJ, rare symbols.
5. High-complexity emojis: ZWJ family sequences, skin tones, flags, variation selectors.
6. Hostile ExplanationCard objects: 50,000+ character strings, massive continuous tokens.
7. Extreme FrameInfo coordinates: negative lines, massive carets, inverted columns.
8. ANSI and control character injection (\x00, \r, \b, \a, raw escape sequences).
9. Broken / crashing console streams (OSError, BrokenPipeError, closed files).
10. Ultimate Failsafe Shielding: poison descriptors, None card, non-card objects, zero-crash guarantees.
11. Wide Mode Thai truncation vs Narrow Mode fold wrapping.
"""

import io
import os
import re
import sys
import time
from typing import Any, Optional
import pytest
from rich.cells import cell_len
from rich.console import Console

from pythaitrace.models import ExplanationCard, FrameInfo
from pythaitrace.renderer import ResponsiveRenderer

ANSI_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


@pytest.fixture
def base_card():
    """Provides a baseline valid ExplanationCard for mutation testing."""
    frame = FrameInfo(
        filename="d:/project/app.py",
        lineno=42,
        funcname="process_data",
        code_line="result = calculate_tax(salary, rate)",
        colno=10,
        end_colno=23,
        is_user_code=True,
    )
    return ExplanationCard(
        error_id="TYPE_ERROR_CALC",
        exception_class="TypeError",
        title_th="ชนิดข้อมูลไม่ถูกต้องในการคำนวณ",
        summary_th="พยายามนำสตริงมารวมกับตัวเลขจำนวนเต็ม",
        mental_model_th="เหมือนพยายามเอา 'ข้อความ' ไปบวกกับ 'ตัวเลข' ในเครื่องคิดเลข",
        fix_suggestions_th=[
            "แปลงชนิดข้อมูลด้วย int() หรือ float()",
            "ตรวจสอบค่าของตัวแปรก่อนส่งเข้าฟังก์ชัน",
        ],
        search_keywords="Python TypeError unsupported operand types",
        google_search_url="https://www.google.com/search?q=Python+TypeError",
        stackoverflow_search_url="https://stackoverflow.com/search?q=Python+TypeError",
        primary_frame=frame,
        is_fallback=False,
        docstring="Inappropriate argument type.",
    )


# ==============================================================================
# 1. Micro-viewports, Pathological Widths & Huge Viewports
# ==============================================================================

class TestMicroAndExtremeViewports:
    """Stress tests on terminal viewport dimensions (1 col to 5000 cols)."""

    @pytest.mark.parametrize("micro_width", [10, 15, 20, 25, 30, 35])
    def test_micro_viewports_no_crash_or_infinite_loop(self, base_card, micro_width):
        """Micro-viewports (10-35 cols) must render rapidly without hanging or uncaught exceptions."""
        renderer = ResponsiveRenderer()
        t0 = time.perf_counter()
        output = renderer.render_to_string(base_card, width=micro_width)
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, f"Rendering took too long ({elapsed:.3f}s) at width {micro_width}"
        assert len(output) > 0
        assert "TypeError" in output
        assert "▌" in output or "━" in output

    @pytest.mark.parametrize("pathological_width", [1, 2, 3, 5, 8])
    def test_pathological_micro_widths(self, base_card, pathological_width):
        """Pathological widths (1-8 cols) must not crash or trigger ZeroDivisionError, folding character by character."""
        renderer = ResponsiveRenderer()
        output = renderer.render_to_string(base_card, width=pathological_width)
        assert len(output) > 0
        # Text is folded across single/few characters per line; stripped whitespace must preserve tokens
        collapsed = re.sub(r"[\s\n\r]+", "", output)
        assert "TypeError" in collapsed

    @pytest.mark.parametrize("huge_width", [300, 500, 1000, 5000])
    def test_huge_viewports_expand_without_crash(self, base_card, huge_width):
        """Huge viewports (300 to 5000 cols) render wide mode double-box borders cleanly."""
        renderer = ResponsiveRenderer()
        t0 = time.perf_counter()
        output = renderer.render_to_string(base_card, width=huge_width)
        elapsed = time.perf_counter() - t0

        assert elapsed < 1.0, f"Wide rendering took too long ({elapsed:.3f}s) at width {huge_width}"
        assert len(output) > 0
        assert "TypeError" in output
        assert ("╔" in output or "═" in output or "║" in output)

    @pytest.mark.parametrize("invalid_width", [0, -1, -50, -9999])
    def test_zero_and_negative_width_handling(self, base_card, invalid_width):
        """Zero and negative explicit widths must safely fall back without crash."""
        renderer = ResponsiveRenderer()
        output = renderer.render_to_string(base_card, width=invalid_width)
        assert len(output) > 0
        assert "TypeError" in output

    def test_env_columns_zero_fallback(self, base_card, monkeypatch):
        """
        DEFECT CHECK: If COLUMNS='0' is exported in environment, _resolve_width
        must NOT return 0 (which silences all Rich output to 0 bytes).
        """
        monkeypatch.setenv("COLUMNS", "0")
        renderer = ResponsiveRenderer()
        output = renderer.render_to_string(base_card, width=None)
        # Output must not be empty string
        assert len(output) > 0, "COLUMNS='0' caused renderer to emit 0 bytes!"
        assert "TypeError" in output

    def test_cell_length_bounds_at_narrow_viewports(self, base_card):
        """At widths 45 and 60, every rendered line must strictly respect the cell_len bound."""
        renderer = ResponsiveRenderer()
        for width in [45, 60, 75]:
            output = renderer.render_to_string(base_card, width=width)
            for line in output.splitlines():
                clean_line = ANSI_PATTERN.sub("", line)
                assert cell_len(clean_line) <= width, (
                    f"Line overflowed {width} columns: '{clean_line}' (len={cell_len(clean_line)})"
                )


# ==============================================================================
# 2. Extreme Unicode, Thai Diacritics & Emoji Complexity
# ==============================================================================

class TestUnicodeAndThaiComplexity:
    """Stress tests on complex Thai scripts, combining marks, ZWJ/ZWNJ, and emojis."""

    def test_deep_stacking_thai_combining_diacritics(self):
        """Deep stacking of upper/lower vowels, tone marks, and Than-thakhat."""
        # ก + ุ (lower) + ิ (upper) + ้ (tone) + ์ (than-thakhat)
        deep_thai = "ก" + "\u0E38" + "\u0E34" + "\u0E49" + "\u0E4C"
        stacked_text = f"ข้อความทดสอบสระซ้อน: {deep_thai * 10}"

        card = ExplanationCard(
            error_id="THAI_STACK",
            exception_class="ValueError",
            title_th=f"หัวข้อสระซ้อน {deep_thai}",
            summary_th=stacked_text,
            mental_model_th=f"โมเดล {deep_thai} ซ้อนหลายชั้น",
            fix_suggestions_th=[f"แก้ไขสระ {deep_thai}"],
            search_keywords="thai combining characters",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        out_wide = renderer.render_to_string(card, width=80)
        out_narrow = renderer.render_to_string(card, width=45)

        assert len(out_wide) > 0
        assert len(out_narrow) > 0
        assert "ValueError" in out_wide
        assert "ValueError" in out_narrow

    def test_thai_sara_am_and_rare_punctuation(self):
        """Sara Am (ำ = ํ + า), Paiyannoi (ฯ), Maiyamok (ๆ), Fongman (๏), Khomut (๛)."""
        rare_text = "๏ คำนำการทดลองฯ ไปเรื่อยๆ ๚ จบการทดสอบ๛"
        card = ExplanationCard(
            error_id="THAI_RARE",
            exception_class="SyntaxError",
            title_th=f"สัญลักษณ์โบราณ {rare_text}",
            summary_th=f"สรุป {rare_text}",
            mental_model_th=f"เปรียบเทียบ {rare_text}",
            fix_suggestions_th=[f"ตรวจตรา {rare_text}"],
            search_keywords="thai rare symbols",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=60)
        assert "๏" in out
        assert "๛" in out

    def test_zero_width_characters_and_invisible_separators(self):
        """Zero-width joiner (\u200d), ZWNJ (\u200c), ZWSP (\u200b), BOM (\ufeff), SHY (\u00ad)."""
        zw_text = "คำ\u200Dต่อ\u200Cเนื่อง\u200Bและ\uFEFFตัด\u00ADคำ"
        card = ExplanationCard(
            error_id="ZERO_WIDTH",
            exception_class="NameError",
            title_th=f"ชื่อที่มีตัวอักษรล่องหน: {zw_text}",
            summary_th=f"สรุป {zw_text}",
            mental_model_th=f"โมเดล {zw_text}",
            fix_suggestions_th=[f"ลบตัวอักษรล่องหน {zw_text}"],
            search_keywords="python zero width char",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=50)
        assert "NameError" in out

    def test_bidirectional_and_multilingual_mixed_text(self):
        """Mixed Thai, English, Arabic/Hebrew (RTL), and Python code snippet."""
        bidi_text = "Thai ภาษาไทย mixed with English and RTL: مرحبا بالعالم / שָׁלוֹם"
        frame = FrameInfo(
            filename="mixed_bidi.py",
            lineno=10,
            funcname="שלום_world",
            code_line="greeting = 'مرحبا' + 'สวัสดี'",
            colno=5,
            end_colno=20,
        )
        card = ExplanationCard(
            error_id="BIDI_TEST",
            exception_class="TypeError",
            title_th=f"ข้อผิดพลาดทวิทิศทาง: {bidi_text}",
            summary_th=bidi_text,
            mental_model_th=bidi_text,
            fix_suggestions_th=[bidi_text],
            search_keywords="bidi python",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
            primary_frame=frame,
        )
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=70)
        assert "TypeError" in out
        assert "สวัสดี" in out

    def test_complex_multi_codepoint_emojis(self):
        """Complex emojis: ZWJ family sequences, skin tones, flags, variation selectors."""
        complex_emojis = "👨‍👩‍👧‍👦 👩🏽‍💻 🏳️‍🌈 🇹🇭 ⚠️ ℹ️ 🏴‍☠️ 🧑‍🤝‍🧑"
        card = ExplanationCard(
            error_id="EMOJI_TEST",
            exception_class="RuntimeError",
            title_th=f"อิโมจิซับซ้อน: {complex_emojis}",
            summary_th=f"สรุป {complex_emojis}",
            mental_model_th=f"โมเดล {complex_emojis}",
            fix_suggestions_th=[f"ตรวจดู {complex_emojis}"],
            search_keywords="emoji python error",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        out_narrow = renderer.render_to_string(card, width=45)
        out_wide = renderer.render_to_string(card, width=100)
        assert "RuntimeError" in out_narrow
        assert "RuntimeError" in out_wide


# ==============================================================================
# 3. Hostile ExplanationCard Objects (Massive, Malformed, Poison)
# ==============================================================================

class TestHostileExplanationCard:
    """Stress tests on massive text, pathological frames, and hostile inputs."""

    def test_massive_strings_narrow_mode_folding(self):
        """In narrow mode (<80 cols), massive Thai text is folded without truncation or crash."""
        massive_text = "กิ้" * 5000
        card = ExplanationCard(
            error_id="DOS_TEST",
            exception_class="MemoryError",
            title_th="หัวข้อยักษ์",
            summary_th=massive_text,
            mental_model_th=massive_text,
            fix_suggestions_th=[massive_text[:500]],
            search_keywords="massive string test",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        t0 = time.perf_counter()
        output = renderer.render_to_string(card, width=50)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0, f"Narrow rendering took too long ({elapsed:.3f}s)"
        assert len(output) > 10000
        assert "MemoryError" in output

    def test_wide_mode_thai_truncation_without_spaces(self):
        """
        DEFECT CHECK: In Wide Mode (>=80 cols), Table.grid column must NOT truncate
        continuous Thai sentences (which lack spaces) with an ellipsis ('…').
        The complete sentence must be visible.
        """
        thai_sentence = (
            "ตัวแปรนี้ยังไม่ได้ประกาศใช้งานในฟังก์ชันปัจจุบันหรือขอบเขตภายนอกทำให้อินเทอร์พรีเตอร์ไม่สามารถค้นหาค่าของตัวแปรดังกล่าวได้"
        )
        card = ExplanationCard(
            error_id="THAI_TRUNC",
            exception_class="NameError",
            title_th="ไม่พบตัวแปร",
            summary_th=thai_sentence,
            mental_model_th="คำอธิบายโมเดลความคิด",
            fix_suggestions_th=[],
            search_keywords="test",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        output = renderer.render_to_string(card, width=80)

        # If truncated with ellipsis, the end of the sentence is missing
        assert "ตัวแปรดังกล่าวได้" in output, (
            "Wide mode truncated the Thai summary with '…' because grid column lacks overflow='fold'!"
        )

    def test_wide_mode_long_search_url_truncation(self):
        """
        DEFECT CHECK: In Wide Mode, long Google/StackOverflow search URLs must NOT
        be truncated with '…' so that users can view or copy the entire URL.
        """
        long_url = "https://www.google.com/search?q=Python+TypeError+unsupported+operand+types+for+pow"
        card = ExplanationCard(
            error_id="URL_TRUNC",
            exception_class="TypeError",
            title_th="ชนิดข้อมูลไม่ถูกต้อง",
            summary_th="สรุป",
            mental_model_th="โมเดล",
            fix_suggestions_th=[],
            search_keywords="url test",
            google_search_url=long_url,
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        output = renderer.render_to_string(card, width=80)

        assert long_url in output, (
            "Wide mode truncated search URL with '…'! Users cannot read the full URL."
        )

    def test_massive_unbreakable_token_without_spaces(self):
        """A continuous 10,000-character line with no spaces must fold without hang or width explosion."""
        unbreakable = "A" * 10000
        frame = FrameInfo(
            filename="unbreakable.py",
            lineno=1,
            funcname="token_bomb",
            code_line=unbreakable,
            colno=1,
            end_colno=100,
        )
        card = ExplanationCard(
            error_id="UNBREAKABLE",
            exception_class="SyntaxError",
            title_th="Unbreakable line",
            summary_th=unbreakable,
            mental_model_th="Long token",
            fix_suggestions_th=[unbreakable],
            search_keywords="unbreakable",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
            primary_frame=frame,
        )
        renderer = ResponsiveRenderer()
        output = renderer.render_to_string(card, width=40)
        assert len(output) > 0
        for line in output.splitlines():
            clean = ANSI_PATTERN.sub("", line)
            assert cell_len(clean) <= 40

    def test_pathological_frame_coordinates(self):
        """FrameInfo with negative lineno, astronomical colno, inverted offsets."""
        frame_huge_col = FrameInfo(
            filename="test.py",
            lineno=-999,
            funcname="weird",
            code_line="x = 1",
            colno=10000,
            end_colno=10010,
        )
        card = ExplanationCard(
            error_id="WEIRD_FRAME",
            exception_class="IndexError",
            title_th="พิกัดประหลาด",
            summary_th="สรุป",
            mental_model_th="โมเดล",
            fix_suggestions_th=["แก้"],
            search_keywords="frame",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
            primary_frame=frame_huge_col,
        )
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=80)
        assert "IndexError" in out

        frame_inverted = FrameInfo(
            filename="test.py",
            lineno=0,
            funcname="<module>",
            code_line="print(y)",
            colno=20,
            end_colno=5,
        )
        card.primary_frame = frame_inverted
        out2 = renderer.render_to_string(card, width=80)
        assert "IndexError" in out2

    def test_raw_ansi_injection_in_card_fields(self):
        """Hostile ANSI escape codes injected into fields must not crash or poison terminal."""
        poison_ansi = "\x1B[31;1mINJECTED_RED\x1B[0m\x1B]0;HackedTitle\x07\x1B[2J\x1B[H"
        card = ExplanationCard(
            error_id="ANSI_INJECTION",
            exception_class="SecurityError",
            title_th=f"หัวข้อที่มี ANSI: {poison_ansi}",
            summary_th=f"สรุป {poison_ansi}",
            mental_model_th=f"โมเดล {poison_ansi}",
            fix_suggestions_th=[f"วิธีแก้ {poison_ansi}"],
            search_keywords=poison_ansi,
            google_search_url=f"https://google.com/?q={poison_ansi}",
            stackoverflow_search_url=f"https://stackoverflow.com/?q={poison_ansi}",
        )
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=80)
        assert "SecurityError" in out

    def test_control_characters_in_card_fields(self):
        """Control characters (\x00, \r, \b, \a, \t, \v, \f) must not crash renderer."""
        control_chars = "Null:\x00 CR:\r Bell:\a Backspace:\b Tab:\t FF:\f VT:\v"
        card = ExplanationCard(
            error_id="CONTROL_CHARS",
            exception_class="ValueError",
            title_th=f"ตัวอักษรควบคุม: {control_chars}",
            summary_th=f"สรุป {control_chars}",
            mental_model_th=f"โมเดล {control_chars}",
            fix_suggestions_th=[f"แก้ไข {control_chars}"],
            search_keywords="control chars",
            google_search_url="https://google.com",
            stackoverflow_search_url="https://stackoverflow.com",
        )
        renderer = ResponsiveRenderer()
        out = renderer.render_to_string(card, width=70)
        assert "ValueError" in out


# ==============================================================================
# 4. Console Stream Failures & Failsafe Shielding
# ==============================================================================

class BrokenStreamConsole(Console):
    """A console whose underlying stream raises IO/OS errors upon writing."""
    def __init__(self, error_type=OSError):
        self.error_type = error_type
        super().__init__(file=io.StringIO(), stderr=True)

    def print(self, *args, **kwargs):
        raise self.error_type("Simulated broken console print stream failure")


class TestFailsafeBarrierAndExceptionShielding:
    """Stress tests verifying that zero exceptions ever escape render() or render_to_string()."""

    def test_broken_console_stream_fails_safe(self, base_card):
        """When console.print() raises OSError or BrokenPipeError, fallback is triggered safely."""
        broken_console = BrokenStreamConsole(error_type=BrokenPipeError)
        renderer = ResponsiveRenderer(console=broken_console)

        try:
            renderer.render(base_card, width=80)
        except BrokenPipeError:
            pytest.fail("BrokenPipeError escaped ResponsiveRenderer.render()!")

    def test_console_width_restoration_after_error(self, base_card):
        """Even if rendering encounters an error, the console's original width must be restored."""
        console = Console(width=100, stderr=True)
        renderer = ResponsiveRenderer(console=console)

        renderer.render(base_card, width=45)
        assert console.width == 100, f"console.width was not restored! Found: {console.width}"

    def test_poison_descriptor_card_failsafe(self):
        """
        DEFECT CHECK: A hostile mock card whose property access raises an arbitrary exception
        must NOT crash renderer.render() or renderer.render_to_string().
        """
        class PoisonCard:
            @property
            def exception_class(self):
                raise RuntimeError("Poison exception_class property access!")

            @property
            def title_th(self):
                raise TypeError("Poison title_th property access!")

            @property
            def summary_th(self):
                raise ValueError("Poison summary_th!")

            @property
            def mental_model_th(self):
                raise KeyError("Poison mental_model_th!")

            @property
            def fix_suggestions_th(self):
                raise AttributeError("Poison fix_suggestions_th!")

            @property
            def primary_frame(self):
                return None

            @property
            def docstring(self):
                return None

            @property
            def google_search_url(self):
                return ""

            @property
            def stackoverflow_search_url(self):
                return ""

        poison = PoisonCard()
        renderer = ResponsiveRenderer()

        try:
            renderer.render(poison, width=80)  # type: ignore
        except BaseException as e:
            pytest.fail(f"Exception {type(e).__name__}: {e} escaped renderer.render()!")

        try:
            out = renderer.render_to_string(poison, width=80)  # type: ignore
        except BaseException as e:
            pytest.fail(f"Exception {type(e).__name__}: {e} escaped renderer.render_to_string()!")

    def test_none_card_failsafe(self):
        """
        DEFECT CHECK: Passing None to render() or render_to_string() must fail safely
        without crashing the entire application process.
        """
        renderer = ResponsiveRenderer()
        try:
            renderer.render(None, width=80)  # type: ignore
        except BaseException as e:
            pytest.fail(f"Exception {type(e).__name__}: {e} escaped renderer.render(None)!")

        try:
            out = renderer.render_to_string(None, width=80)  # type: ignore
        except BaseException as e:
            pytest.fail(f"Exception {type(e).__name__}: {e} escaped renderer.render_to_string(None)!")

    def test_non_card_primitive_types_failsafe(self):
        """DEFECT CHECK: Passing string, int, list, or dict must not crash renderer."""
        renderer = ResponsiveRenderer()
        for hostile_input in ["just a string", 12345, [1, 2, 3], {"key": "val"}]:
            try:
                renderer.render(hostile_input, width=80)  # type: ignore
            except BaseException as e:
                pytest.fail(f"Exception {type(e).__name__}: {e} escaped render({type(hostile_input)})!")

            try:
                out = renderer.render_to_string(hostile_input, width=80)  # type: ignore
            except BaseException as e:
                pytest.fail(f"Exception {type(e).__name__}: {e} escaped render_to_string({type(hostile_input)})!")
