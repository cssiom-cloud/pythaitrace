"""
PyThaiTrace v2.0 - Zero-crash, bilingual developer diagnostic CLI tool.
"""

__version__ = "2.0.0"

from pythaitrace.models import (
    FrameInfo,
    NormalizedTraceback,
    KnowledgeRule,
    MatchResult,
    ExplanationCard,
)
from pythaitrace.renderer import ResponsiveRenderer
from pythaitrace.hooks import install_hooks
from pythaitrace.runner import run_script

__all__ = [
    "__version__",
    "FrameInfo",
    "NormalizedTraceback",
    "KnowledgeRule",
    "MatchResult",
    "ExplanationCard",
    "ResponsiveRenderer",
    "install_hooks",
    "run_script",
]
