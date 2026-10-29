"""
PyThaiTrace v2.0 - Responsive Rich Terminal Renderer (renderer.py)
Renders structured Thai diagnostic cards optimized for:
- Wide Mode (>= 80 columns): Double-bordered Rich panel (box.DOUBLE) with code snippet
- Narrow Mode (< 80 columns): Flat layout with left-accent bar '▌' and strict cell_len bounds
- Plain-Text Fallback: Pure text without ANSI codes for dumb/restricted terminals or failsafe
"""

from __future__ import annotations
import io
import os
import shutil
import sys
from typing import Any, Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pythaitrace.models import ExplanationCard


def _is_termux() -> bool:
    """Detects whether running in Android Termux environment."""
    return bool(
        os.environ.get("TERMUX_VERSION")
        or "/com.termux/" in os.environ.get("PREFIX", "")
        or os.environ.get("ANDROID_ROOT")
    )


class ResponsiveRenderer:
    """
    Responsive terminal diagnostic card renderer for PyThaiTrace.
    Dynamically switches between Wide Mode (>= 80 cols) and Narrow Mode (< 80 cols).
    """

    def __init__(self, console: Optional[Console] = None) -> None:
        self.console = console or Console(stderr=True)

    def _resolve_width(self, width: Optional[int] = None) -> int:
        """
        Determines the effective terminal column width using hierarchical resolution:
        1. Explicit parameter 'width'
        2. Environment variable 'COLUMNS'
        3. Termux check: Default to 60 in Termux unless terminal is confirmed wide
        4. Console width property
        5. shutil.get_terminal_size()
        6. Default fallback: 80
        """
        if width is not None and width > 0:
            return width

        env_cols = os.environ.get("COLUMNS")
        if env_cols and env_cols.strip().isdigit() and int(env_cols.strip()) > 0:
            return int(env_cols.strip())

        # If running on Android / Termux, prioritize mobile-friendly width
        if _is_termux():
            try:
                import fcntl, termios, struct
                with open("/dev/tty", "r") as tty:
                    cr = struct.unpack("hh", fcntl.ioctl(tty.fileno(), termios.TIOCGWINSZ, "1234"))
                    if cr[1] > 0:
                        return cr[1]
            except Exception:
                pass
            try:
                cols = shutil.get_terminal_size().columns
                if 0 < cols < 80:
                    return cols
            except Exception:
                pass
            return 60

        if self.console and getattr(self.console, "width", None) and self.console.width > 0:
            return self.console.width

        try:
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            return cols if cols > 0 else 80
        except Exception:
            return 80

    def render(self, card: ExplanationCard, width: Optional[int] = None) -> None:
        """
        Renders the diagnostic card to the configured console or stderr.
        Guarantees zero-crash execution via BaseException containment.
        """
        eff_width = self._resolve_width(width)
        orig_width = getattr(self.console, "width", None)
        try:
            if orig_width is not None and orig_width != eff_width:
                self.console.width = eff_width

            if eff_width >= 80:
                self._render_wide(card, self.console, eff_width)
            else:
                self._render_narrow(card, self.console, eff_width)
        except BaseException:
            try:
                self._render_plain_fallback(card, self.console, eff_width)
            except BaseException:
                pass
        finally:
            if orig_width is not None and getattr(self.console, "width", None) != orig_width:
                self.console.width = orig_width

    def render_to_string(self, card: ExplanationCard, width: Optional[int] = None) -> str:
        """
        Renders the diagnostic card into a string buffer for virtual consoles and testing.
        """
        eff_width = self._resolve_width(width)
        buf = io.StringIO()

        color_sys = getattr(self.console, "color_system", None)
        no_color = getattr(self.console, "no_color", False) or (color_sys is None)

        str_console = Console(
            file=buf,
            width=eff_width,
            color_system=color_sys,
            no_color=no_color,
            force_terminal=bool(color_sys),
            highlight=False,
            legacy_windows=False,
        )

        try:
            if eff_width >= 80:
                self._render_wide(card, str_console, eff_width)
            else:
                self._render_narrow(card, str_console, eff_width)
        except BaseException:
            try:
                self._render_plain_fallback(card, str_console, eff_width)
            except BaseException:
                pass

        return buf.getvalue()

    def _render_wide(self, card: ExplanationCard, console: Console, width: int) -> None:
        """
        Renders full double-bordered Rich panel layout for viewports >= 80 columns.
        """
        grid = Table.grid(padding=(0, 1))
        grid.add_column(overflow="fold")

        header_title = f"[ข้อผิดพลาด] {card.exception_class}: {card.title_th}"

        # 1. Summary
        if card.summary_th:
            grid.add_row(Text(card.summary_th, style="white"))
            grid.add_row(Text(""))

        # 2. Mental Model (โมเดลความคิด)
        if card.mental_model_th:
            grid.add_row(Text("[โมเดลความคิด]:", style="bold yellow"))
            grid.add_row(Text(f"   {card.mental_model_th}", style="white"))
            grid.add_row(Text(""))

        # 3. Actionable Fix Suggestions (แนวทางแก้ไข)
        if card.fix_suggestions_th:
            grid.add_row(Text("[แนวทางแก้ไข]:", style="bold green"))
            for idx, step in enumerate(card.fix_suggestions_th, 1):
                grid.add_row(Text(f"   {idx}. {step}", style="white"))
            grid.add_row(Text(""))

        # 4. Code Context Snippet (if primary_frame exists)
        if card.primary_frame and card.primary_frame.code_line:
            frame = card.primary_frame
            grid.add_row(Text("[โค้ดที่เกิดปัญหา]:", style="bold magenta"))
            if frame.filename:
                file_info = f"   File \"{frame.filename}\", line {frame.lineno}, in {frame.funcname}"
                grid.add_row(Text(file_info, style="dim"))

            line_text = Text(f"   > {frame.lineno} | ", style="bold cyan") + Text(
                frame.code_line, style="bold white"
            )
            grid.add_row(line_text)

            if frame.caret_pointer:
                caret_indent = " " * len(f"   > {frame.lineno} | ")
                grid.add_row(Text(f"{caret_indent}{frame.caret_pointer}", style="bold red"))
            grid.add_row(Text(""))

        # 5. Docstring (for fallback cards)
        if card.docstring:
            grid.add_row(Text("[คำอธิบายเพิ่มเติม]:", style="bold cyan"))
            grid.add_row(Text(f"   {card.docstring}", style="white"))
            grid.add_row(Text(""))

        # 6. Search Queries & URLs
        if card.google_search_url or card.stackoverflow_search_url:
            grid.add_row(Text("[ค้นหาเพิ่มเติม]:", style="bold blue"))
            if card.google_search_url:
                grid.add_row(Text(f"   • Google: {card.google_search_url}", style="dim underline"))
            if card.stackoverflow_search_url:
                grid.add_row(
                    Text(f"   • StackOverflow: {card.stackoverflow_search_url}", style="dim underline")
                )

        panel = Panel(
            grid,
            title=Text(header_title, style="bold red"),
            subtitle=Text("PyThaiTrace v2.0 • Bilingual Developer Diagnostics", style="dim"),
            border_style="red",
            box=box.DOUBLE,
            expand=True,
        )

        req_width = width
        for u in (getattr(card, "google_search_url", None), getattr(card, "stackoverflow_search_url", None)):
            if u and isinstance(u, str) and len(u) > width - 4:
                req_width = max(req_width, min(len(u) + 4, 5000))

        orig_w = getattr(console, "width", None)
        try:
            if orig_w is not None and orig_w < req_width:
                console.width = req_width
            console.print(panel)
        finally:
            if orig_w is not None and getattr(console, "width", None) != orig_w:
                console.width = orig_w

    def _render_narrow(self, card: ExplanationCard, console: Console, width: int) -> None:
        """
        Renders flat layout with left-accent bar '▌' for viewports < 80 columns.
        Enforces cell_len(line) <= width across all rendered output.
        Clean, readable, zero emoji, zero broken box wrapping.
        """
        sep_width = max(width - 1, 10)

        # 1. Top separator rule & Header
        console.print(Text("━" * sep_width, style="bold red"))
        header_text = Text("▌ ", style="bold red") + Text(
            f"[ข้อผิดพลาด] {card.exception_class}: {card.title_th}", style="bold red"
        )
        header_text.overflow = "fold"
        console.print(header_text)

        if card.summary_th:
            summary_text = Text("▌ ", style="bold red") + Text(card.summary_th, style="white")
            summary_text.overflow = "fold"
            console.print(summary_text)

        console.print(Text("━" * sep_width, style="dim"))

        # 2. Mental Model (โมเดลความคิด)
        if card.mental_model_th:
            console.print(Text("▌ ", style="bold yellow") + Text("[โมเดลความคิด]:", style="bold yellow"))
            mm_text = Text(f"  {card.mental_model_th}", style="white")
            mm_text.overflow = "fold"
            console.print(mm_text)

        # 3. Actionable Fix Suggestions (แนวทางแก้ไข)
        if card.fix_suggestions_th:
            console.print(Text("▌ ", style="bold green") + Text("[แนวทางแก้ไข]:", style="bold green"))
            for idx, step in enumerate(card.fix_suggestions_th, 1):
                step_text = Text(f"  {idx}. {step}", style="white")
                step_text.overflow = "fold"
                console.print(step_text)

        # 4. Code Context Snippet (if primary_frame exists)
        if card.primary_frame and card.primary_frame.code_line:
            frame = card.primary_frame
            console.print(Text("▌ ", style="bold magenta") + Text("[โค้ดที่เกิดปัญหา]:", style="bold magenta"))
            if frame.filename:
                file_info = f"  File \"{frame.filename}\", line {frame.lineno}, in {frame.funcname}"
                file_text = Text(file_info, style="dim")
                file_text.overflow = "fold"
                console.print(file_text)

            line_text = Text(f"  > {frame.lineno} | ", style="bold cyan") + Text(
                frame.code_line, style="bold white"
            )
            line_text.overflow = "fold"
            console.print(line_text)

            if frame.caret_pointer:
                caret_indent = " " * len(f"  > {frame.lineno} | ")
                caret_text = Text(f"{caret_indent}{frame.caret_pointer}", style="bold red")
                caret_text.overflow = "fold"
                console.print(caret_text)

        # 5. Docstring (for fallback cards)
        if card.docstring:
            console.print(Text("▌ ", style="bold cyan") + Text("[คำอธิบายเพิ่มเติม]:", style="bold cyan"))
            doc_text = Text(f"  {card.docstring}", style="white")
            doc_text.overflow = "fold"
            console.print(doc_text)

        # 6. Search Queries & URLs
        if card.google_search_url or card.stackoverflow_search_url:
            console.print(Text("▌ ", style="bold blue") + Text("[ค้นหาเพิ่มเติม]:", style="bold blue"))
            if card.google_search_url:
                g_text = Text(f"  • Google: {card.google_search_url}", style="dim underline")
                g_text.overflow = "fold"
                console.print(g_text)
            if card.stackoverflow_search_url:
                so_text = Text(
                    f"  • StackOverflow: {card.stackoverflow_search_url}",
                    style="dim underline",
                )
                so_text.overflow = "fold"
                console.print(so_text)

        # 7. Bottom separator rule
        console.print(Text("━" * sep_width, style="bold red"))

    def _render_plain_fallback(self, card: Any, stream_or_console: Any, width: int = 80) -> None:
        """
        Zero-dependency, ASCII/UTF-8 safe plain-text fallback renderer.
        Invoked on dumb terminals or as ultimate failsafe barrier.
        """
        try:
            rule_len = max(10, min(width, 70))
            exc_cls = getattr(card, "exception_class", type(card).__name__)
            title = getattr(card, "title_th", str(card) if card is not None else "Unknown Error")
            lines = [
                "=" * rule_len,
                f"[PyThaiTrace] {exc_cls}: {title}",
            ]
            summary = getattr(card, "summary_th", None)
            if summary:
                lines.append(f"สรุป: {summary}")
            lines.append("-" * rule_len)
            mm = getattr(card, "mental_model_th", None)
            if mm:
                lines.append(f"โมเดลความคิด: {mm}")

            fixes = getattr(card, "fix_suggestions_th", None)
            if fixes and isinstance(fixes, (list, tuple)):
                lines.append("แนวทางแก้ไข:")
                for idx, step in enumerate(fixes, 1):
                    lines.append(f"  {idx}. {step}")

            frame = getattr(card, "primary_frame", None)
            if frame and getattr(frame, "code_line", None):
                lines.append(f"โค้ดที่เกิดปัญหา: {frame.code_line}")

            doc = getattr(card, "docstring", None)
            if doc:
                lines.append(f"คำอธิบาย (Docstring): {doc}")

            g_url = getattr(card, "google_search_url", None)
            so_url = getattr(card, "stackoverflow_search_url", None)
            if g_url or so_url:
                lines.append("ค้นหาเพิ่มเติม:")
                if g_url:
                    lines.append(f"  Google: {g_url}")
                if so_url:
                    lines.append(f"  StackOverflow: {so_url}")

            lines.append("=" * rule_len)
            text = "\n".join(lines) + "\n"
        except BaseException:
            try:
                card_rep = repr(card)
            except BaseException:
                card_rep = type(card).__name__
            text = f"[PyThaiTrace] Unhandled error diagnostic payload: {card_rep}\n"

        try:
            if isinstance(stream_or_console, Console):
                stream_or_console.print(text, highlight=False)
            elif hasattr(stream_or_console, "write"):
                stream_or_console.write(text)
                if hasattr(stream_or_console, "flush"):
                    stream_or_console.flush()
            else:
                sys.stderr.write(text)
                sys.stderr.flush()
        except BaseException:
            try:
                safe_text = text.encode("ascii", errors="replace").decode("ascii")
                if hasattr(stream_or_console, "write"):
                    stream_or_console.write(safe_text)
                    if hasattr(stream_or_console, "flush"):
                        stream_or_console.flush()
                else:
                    sys.stderr.write(safe_text)
                    sys.stderr.flush()
            except BaseException:
                pass
