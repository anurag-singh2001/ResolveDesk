"""Behaviour that lands in E2.3b (eligibility + safe execution). Kept in one place so nothing
can accidentally execute before the executor and its checks exist."""

from app.actions.base import ExecutionResult, ValidationResult, VerificationResult


class NotYetExecutable:
    def validate(self, ctx, inp) -> ValidationResult:
        raise NotImplementedError("eligibility rules arrive in E2.3b")

    def execute(self, ctx, inp, idempotency_key) -> ExecutionResult:
        raise NotImplementedError("safe execution arrives in E2.3b")

    def verify(self, ctx, result) -> VerificationResult:
        raise NotImplementedError("verification arrives in E2.3b")
