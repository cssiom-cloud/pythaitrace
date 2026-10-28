"""
PyThaiTrace v2.0 - Core Data Models (src/pythaitrace/models.py)
Robust Pydantic v2 schemas for normalized tracebacks, knowledge rules,
match results, and responsive explanation cards.
"""

from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import (
    BaseModel,
    Field,
    AliasChoices,
    ConfigDict,
)


class FrameInfo(BaseModel):
    """Information regarding a single stack frame."""
    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="allow")

    filename: str = Field(..., description="File path of the executed frame")
    lineno: int = Field(..., description="1-based line number of the frame")
    funcname: str = Field(
        default="<module>",
        validation_alias=AliasChoices("funcname", "name"),
        description="Function, method, or scope name",
    )
    code_line: str = Field(
        default="",
        validation_alias=AliasChoices("code_line", "line"),
        description="Source code line",
    )
    colno: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("colno", "col_offset"),
        description="Starting column offset (PEP 657)",
    )
    end_colno: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("end_colno", "end_col_offset"),
        description="Ending column offset (PEP 657)",
    )
    is_user_code: bool = Field(
        default=True,
        description="True if frame is within user project",
    )

    # Cross-compatibility properties
    @property
    def name(self) -> str:
        return self.funcname

    @property
    def line(self) -> str:
        return self.code_line

    @property
    def col_offset(self) -> Optional[int]:
        return self.colno

    @property
    def end_col_offset(self) -> Optional[int]:
        return self.end_colno

    @property
    def caret_pointer(self) -> Optional[str]:
        """Generate visual caret string (e.g. '   ^^^^^') if column offsets exist."""
        if self.colno is not None and self.end_colno is not None:
            width = max(1, self.end_colno - self.colno)
            return " " * max(0, self.colno - 1) + "^" * width
        elif self.colno is not None:
            return " " * max(0, self.colno - 1) + "^"
        return None


class NormalizedTraceback(BaseModel):
    """Normalized, ANSI-stripped, structured traceback data."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    exc_type_name: str = Field(
        ...,
        validation_alias=AliasChoices("exc_type_name", "exception_class"),
        description="Class name of the exception, e.g. TypeError",
    )
    exc_message: str = Field(
        default="",
        validation_alias=AliasChoices("exc_message", "message"),
        description="Sanitized error message string",
    )
    frames: List[FrameInfo] = Field(
        default_factory=list,
        description="All stack frames in chronological order",
    )
    primary_frame: Optional[FrameInfo] = Field(
        default=None,
        validation_alias=AliasChoices("primary_frame", "relevant_frame"),
        description="Primary user culprit frame",
    )
    is_syntax_error: bool = Field(
        default=False,
        description="True if exception is a compile-time SyntaxError/IndentationError",
    )
    raw_lines: List[str] = Field(
        default_factory=list,
        description="Original raw traceback lines",
    )

    # Optional metadata extensions
    clean_text: str = Field(default="", description="ANSI-stripped traceback text")
    suggestion: Optional[str] = Field(default=None, description="Python 3.10+ Did you mean suggestion")
    notes: List[str] = Field(default_factory=list, description="PEP 678 exception notes")
    docstring: Optional[str] = Field(default=None, description="Class docstring for unmapped exceptions")
    exception_module: str = Field(default="builtins", description="Module namespace of exception")

    @property
    def exception_class(self) -> str:
        return self.exc_type_name

    @property
    def message(self) -> str:
        return self.exc_message

    @property
    def relevant_frame(self) -> Optional[FrameInfo]:
        return self.primary_frame


class KnowledgeRule(BaseModel):
    """Knowledge rule definition stored in rules.json."""
    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="allow")

    error_id: str = Field(..., description="Unique slug for the rule")
    exception_class: str = Field(..., description="Target exception class or __FALLBACK__")
    pattern: Optional[str] = Field(
        default=None,
        description="Regex pattern with named capture groups",
    )
    summary_th: str = Field(
        ...,
        description="Short Thai summary with {param} placeholders",
    )
    mental_model_th: str = Field(
        ...,
        description="Pedagogical Thai mental model / analogy",
    )
    fix_suggestions_th: List[str] = Field(
        default_factory=list,
        description="Actionable Thai fix steps",
    )
    search_keywords: str = Field(
        default="",
        description="English search keywords for queries",
    )


class MatchResult(BaseModel):
    """Result returned by the 3-Tier Matcher Engine."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    rule: KnowledgeRule = Field(..., description="Matched KnowledgeRule reference")
    tier: int = Field(
        ...,
        ge=1,
        le=4,
        description="Tier level: 1=strict regex, 2=fuzzy tokens, 3=class generic, 4=fallback",
    )
    extracted_entities: Dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("extracted_entities", "captured_params"),
        description="Extracted identifier parameters",
    )

    @property
    def captured_params(self) -> Dict[str, str]:
        return self.extracted_entities

    @property
    def matched(self) -> bool:
        return self.rule is not None


class ExplanationCard(BaseModel):
    """Final presentation payload consumed by renderer.py."""
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    error_id: str = Field(..., description="Rule ID matching KnowledgeRule")
    exception_class: str = Field(..., description="Exception class name")
    title_th: str = Field(
        ...,
        validation_alias=AliasChoices("title_th", "title"),
        description="Card header title in Thai",
    )
    summary_th: str = Field(..., description="Interpolated Thai summary")
    mental_model_th: str = Field(..., description="Thai mental model explanation")
    fix_suggestions_th: List[str] = Field(
        default_factory=list,
        description="Numbered Thai fix instructions",
    )
    search_keywords: str = Field(
        default="",
        description="English search query keywords",
    )
    google_search_url: str = Field(..., description="Direct Google search URL")
    stackoverflow_search_url: str = Field(..., description="Direct StackOverflow search URL")
    primary_frame: Optional[FrameInfo] = Field(
        default=None,
        validation_alias=AliasChoices("primary_frame", "code_context"),
        description="Culprit frame with code snippet and caret pointer",
    )
    is_fallback: bool = Field(
        default=False,
        description="True if matched via tier 4 universal fallback",
    )
    docstring: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("docstring", "docstring_summary"),
        description="Docstring for 3rd-party exceptions",
    )

    @property
    def title(self) -> str:
        return self.title_th

    @property
    def code_context(self) -> Optional[FrameInfo]:
        return self.primary_frame

    @property
    def docstring_summary(self) -> Optional[str]:
        return self.docstring

    @property
    def search_links(self) -> Dict[str, str]:
        return {
            "google": self.google_search_url,
            "stackoverflow": self.stackoverflow_search_url,
        }
