"""`make llm-smoke` failure output: never echoes third-party error text. No network."""

from app.llm.providers import LLMClient, RateLimited
from scripts import llm_smoke

LEAKY = "https://api.example.test/v1?key=fake-secret-123 prompt=customer text"


class SdkError(Exception):
    pass


def test_foreign_errors_print_only_the_class_name(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise SdkError(LEAKY)

    monkeypatch.setattr(LLMClient, "for_role", boom)
    assert llm_smoke.main() == 1
    out = capsys.readouterr().out
    assert "SdkError" in out and "fake-secret-123" not in out and "customer text" not in out


def test_describe_failure_keeps_our_own_llm_error_messages():
    assert llm_smoke.describe_failure(SdkError(LEAKY)) == "SdkError"
    ours = RateLimited("all LLM providers are rate limited")
    assert llm_smoke.describe_failure(ours) == "RateLimited: all LLM providers are rate limited"
