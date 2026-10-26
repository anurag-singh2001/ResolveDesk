"""Execution and verification are done by app/engine/executor.py (refunds) or land with their
story (vouchers, loyalty, messages: E4). Kept in one place so nothing can execute without
the executor's checks."""

from app.actions.base import ExecutionResult, VerificationResult


class NotYetExecutable:
    def execute(self, ctx, inp, idempotency_key) -> ExecutionResult:
        raise NotImplementedError("run approved proposals through app.engine.executor")

    def verify(self, ctx, result) -> VerificationResult:
        raise NotImplementedError("verification arrives with the verifier (E4)")
