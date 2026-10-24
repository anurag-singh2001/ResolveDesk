"""`make llm-smoke`: one classification call to the configured classifier; prints the JSON."""

import sys

from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.llm.providers import LLMClient, MissingAPIKey

CATEGORIES = ["late_delivery", "missing_items", "wrong_item", "quality", "refund_status", "other"]
MESSAGE = "My order came 50 minutes late and one of the two drinks was missing."


class SmokeClassification(BaseModel):
    category: str
    confidence: float = Field(ge=0, le=1)
    needs_info: list[str]


def main() -> int:
    try:
        s = get_settings()
    except ValidationError as exc:
        # Only the messages: pydantic's own text echoes the input, which includes API keys.
        print("Invalid settings: " + "; ".join(e["msg"] for e in exc.errors()))
        return 1
    try:
        client = LLMClient.for_role("classifier", settings=s)
        result = client.invoke_structured(
            [
                ("system", f"Classify the support message. Categories: {', '.join(CATEGORIES)}."),
                ("human", MESSAGE),
            ],
            SmokeClassification,
        )
    except MissingAPIKey as exc:
        print(f"{exc}. Set GROQ_API_KEY/GEMINI_API_KEY in .env (see env.example).")
        return 2
    except Exception as exc:  # a smoke check reports (settings, network, LLMError), no traceback
        print(f"LLM smoke failed: {exc.__class__.__name__}: {exc}")
        return 1
    target = client.targets[0]
    print(f"provider={target.provider} model={target.model}")
    print(result.model_dump_json(indent=2))
    print(f"counters: {client.budget.snapshot()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
