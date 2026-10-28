"""
PyThaiTrace v2.0 - Core Data Models (src/pythaitrace/models.py)
Robust data schemas for normalized tracebacks, knowledge rules,
match results, and responsive explanation cards.

Supports Pydantic v2 if installed, with a zero-dependency pure-Python
fallback for Termux/Android and lightweight environments without Rust/C compilers.
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional

try:
    from pydantic import (
        BaseModel as _PydanticBaseModel,
        Field,
        AliasChoices,
        ConfigDict,
    )
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False


if HAS_PYDANTIC:
    class FrameInfo(_PydanticBaseModel):
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


    class NormalizedTraceback(_PydanticBaseModel):
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


    class KnowledgeRule(_PydanticBaseModel):
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


    class MatchResult(_PydanticBaseModel):
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


    class ExplanationCard(_PydanticBaseModel):
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

else:
    # =========================================================================
    # Pure Python zero-dependency fallback for Termux / Android without Rust
    # =========================================================================

    class _PureBaseModel:
        def model_dump(self) -> Dict[str, Any]:
            result = {}
            for k, v in self.__dict__.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, _PureBaseModel):
                    result[k] = v.model_dump()
                elif isinstance(v, list):
                    result[k] = [item.model_dump() if isinstance(item, _PureBaseModel) else item for item in v]
                else:
                    result[k] = v
            return result

        def model_dump_json(self) -> str:
            return json.dumps(self.model_dump(), ensure_ascii=False)

        @classmethod
        def model_validate(cls, data: Any):
            if isinstance(data, cls):
                return data
            if isinstance(data, dict):
                return cls(**data)
            raise TypeError(f"Expected dict, got {type(data)}")

        @classmethod
        def model_validate_json(cls, json_str: str):
            return cls.model_validate(json.loads(json_str))


    class FrameInfo(_PureBaseModel):
        def __init__(
            self,
            filename: str,
            lineno: int,
            funcname: str = "<module>",
            code_line: str = "",
            colno: Optional[int] = None,
            end_colno: Optional[int] = None,
            is_user_code: bool = True,
            **extra: Any,
        ):
            self.filename = str(filename)
            self.lineno = int(lineno)
            self.funcname = extra.get("name", funcname)
            self.code_line = extra.get("line", code_line)
            self.colno = extra.get("col_offset", colno)
            self.end_colno = extra.get("end_col_offset", end_colno)
            self.is_user_code = is_user_code
            for k, v in extra.items():
                setattr(self, k, v)

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
            if self.colno is not None and self.end_colno is not None:
                width = max(1, self.end_colno - self.colno)
                return " " * max(0, self.colno - 1) + "^" * width
            elif self.colno is not None:
                return " " * max(0, self.colno - 1) + "^"
            return None


    class NormalizedTraceback(_PureBaseModel):
        def __init__(
            self,
            exc_type_name: str,
            exc_message: str = "",
            frames: Optional[List[Any]] = None,
            primary_frame: Optional[Any] = None,
            is_syntax_error: bool = False,
            raw_lines: Optional[List[str]] = None,
            clean_text: str = "",
            suggestion: Optional[str] = None,
            notes: Optional[List[str]] = None,
            docstring: Optional[str] = None,
            exception_module: str = "builtins",
            **extra: Any,
        ):
            self.exc_type_name = extra.get("exception_class", exc_type_name)
            self.exc_message = extra.get("message", exc_message)
            if frames:
                self.frames = [f if isinstance(f, FrameInfo) else FrameInfo.model_validate(f) for f in frames]
            else:
                self.frames = []
            if primary_frame is not None:
                self.primary_frame = primary_frame if isinstance(primary_frame, FrameInfo) else FrameInfo.model_validate(primary_frame)
            elif "relevant_frame" in extra:
                rf = extra["relevant_frame"]
                self.primary_frame = rf if isinstance(rf, FrameInfo) else (FrameInfo.model_validate(rf) if rf else None)
            else:
                self.primary_frame = None
            self.is_syntax_error = is_syntax_error
            self.raw_lines = raw_lines if raw_lines is not None else []
            self.clean_text = clean_text
            self.suggestion = suggestion
            self.notes = notes if notes is not None else []
            self.docstring = docstring
            self.exception_module = exception_module
            for k, v in extra.items():
                setattr(self, k, v)

        @property
        def exception_class(self) -> str:
            return self.exc_type_name

        @property
        def message(self) -> str:
            return self.exc_message

        @property
        def relevant_frame(self) -> Optional[FrameInfo]:
            return self.primary_frame


    class KnowledgeRule(_PureBaseModel):
        def __init__(
            self,
            error_id: str,
            exception_class: str,
            summary_th: str,
            mental_model_th: str,
            pattern: Optional[str] = None,
            fix_suggestions_th: Optional[List[str]] = None,
            search_keywords: str = "",
            **extra: Any,
        ):
            self.error_id = error_id
            self.exception_class = exception_class
            self.pattern = pattern
            self.summary_th = summary_th
            self.mental_model_th = mental_model_th
            self.fix_suggestions_th = fix_suggestions_th if fix_suggestions_th is not None else []
            self.search_keywords = search_keywords
            for k, v in extra.items():
                setattr(self, k, v)


    class MatchResult(_PureBaseModel):
        def __init__(
            self,
            rule: Any,
            tier: int,
            extracted_entities: Optional[Dict[str, str]] = None,
            **extra: Any,
        ):
            self.rule = rule if isinstance(rule, KnowledgeRule) else KnowledgeRule.model_validate(rule)
            self.tier = int(tier)
            if extracted_entities is not None:
                self.extracted_entities = extracted_entities
            elif "captured_params" in extra:
                self.extracted_entities = extra["captured_params"]
            else:
                self.extracted_entities = {}
            for k, v in extra.items():
                setattr(self, k, v)

        @property
        def captured_params(self) -> Dict[str, str]:
            return self.extracted_entities

        @property
        def matched(self) -> bool:
            return self.rule is not None


    class ExplanationCard(_PureBaseModel):
        def __init__(
            self,
            error_id: str,
            exception_class: str,
            title_th: str,
            summary_th: str,
            mental_model_th: str,
            google_search_url: str,
            stackoverflow_search_url: str,
            fix_suggestions_th: Optional[List[str]] = None,
            search_keywords: str = "",
            primary_frame: Optional[Any] = None,
            is_fallback: bool = False,
            docstring: Optional[str] = None,
            **extra: Any,
        ):
            self.error_id = error_id
            self.exception_class = exception_class
            self.title_th = extra.get("title", title_th)
            self.summary_th = summary_th
            self.mental_model_th = mental_model_th
            self.fix_suggestions_th = fix_suggestions_th if fix_suggestions_th is not None else []
            self.search_keywords = search_keywords
            self.google_search_url = google_search_url
            self.stackoverflow_search_url = stackoverflow_search_url
            if primary_frame is not None:
                self.primary_frame = primary_frame if isinstance(primary_frame, FrameInfo) else FrameInfo.model_validate(primary_frame)
            elif "code_context" in extra:
                cc = extra["code_context"]
                self.primary_frame = cc if isinstance(cc, FrameInfo) else (FrameInfo.model_validate(cc) if cc else None)
            else:
                self.primary_frame = None
            self.is_fallback = is_fallback
            self.docstring = extra.get("docstring_summary", docstring)
            for k, v in extra.items():
                setattr(self, k, v)

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
