"""Structured outputs the agents must return (PROJECT.md section 9). Pydantic validates every
reply; LLMClient.invoke_structured gives one repair attempt before failing."""

from typing import Any

from pydantic import BaseModel, Field


class Classification(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)
    needs_info: list[str] = Field(default_factory=list, max_length=3)
    # S7.12: the language of the customer's message, from the same call. Validated in code
    # (app/core/language.py); a wrong or missing value just falls back to the word-list rule.
    language: str = "en"
    language_confidence: float = Field(default=0.0, ge=0, le=1)


class ResolutionDraft(BaseModel):
    """What the resolution agent proposes. `action` is an enabled action name, or "none"
    (nothing to do / apology) or "escalate" (a human must decide)."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)
    citations: list[str] = Field(default_factory=list)  # section_refs it relied on


class BaselineDecision(BaseModel):
    """The single-call baseline (evals): classification and remedy in one reply."""

    category: str
    confidence: float = Field(ge=0, le=1)
    needs_info: list[str] = Field(default_factory=list, max_length=3)
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)
    citations: list[str] = Field(default_factory=list)
