"""Structured outputs the agents must return (PROJECT.md section 9). Pydantic validates every
reply; LLMClient.invoke_structured gives one repair attempt before failing."""

from typing import Any

from pydantic import BaseModel, Field


class Classification(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)
    needs_info: list[str] = Field(default_factory=list, max_length=3)


class ResolutionDraft(BaseModel):
    """What the resolution agent proposes. `action` is an enabled action name, or "none"
    (nothing to do / apology) or "escalate" (a human must decide)."""

    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1, max_length=500)
    citations: list[str] = Field(default_factory=list)  # section_refs it relied on
