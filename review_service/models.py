"""models.py

Pydantic v2 models that define the exact JSON shape the LLM must return.
These are also used downstream by comment_poster.py to render inline PR comments.
"""

from enum import Enum
from pydantic import BaseModel, Field


class Severity(str, Enum):
    """How serious the issue is."""
    critical = "critical"   # security vulnerability, data-loss risk
    high     = "high"       # likely bug, incorrect logic
    medium   = "medium"     # potential bug, bad practice
    low      = "low"        # style, readability, minor smell


class Category(str, Enum):
    """The kind of problem found."""
    security    = "security"
    bug         = "bug"
    performance = "performance"
    style       = "style"
    other       = "other"


class ReviewIssue(BaseModel):
    """A single finding produced by the LLM for one location in the diff."""

    filename: str = Field(
        description="Relative path of the file being reviewed, e.g. 'src/auth/login.py'."
    )
    line_number: int = Field(
        description="Line number in the *new* file (right side of the diff) where the issue starts."
    )
    severity: Severity = Field(
        description="How serious the issue is: critical | high | medium | low."
    )
    category: Category = Field(
        description="Type of issue: security | bug | performance | style | other."
    )
    message: str = Field(
        description="One-sentence description of the problem."
    )
    suggestion: str = Field(
        description="Concrete, actionable fix or improvement the developer should apply."
    )


class ReviewResponse(BaseModel):
    """Top-level envelope the LLM must return.

    The LLM is instructed to return *only* this JSON object — no prose, no fences.
    An empty `issues` list means the chunk looks clean.
    """

    issues: list[ReviewIssue] = Field(
        default_factory=list,
        description="All issues found in this diff chunk. Empty list if none."
    )
