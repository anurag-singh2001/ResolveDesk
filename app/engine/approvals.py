"""Whether an approval may still be acted on (PROJECT.md section 10, step 1; hard rule 6).

The executor calls `check_usable` right before reserving money. The database already binds an
approval to its proposal's hash and only lets approved approvals back an execution; this adds
what only code can check at that moment: expiry, and that the proposal still hashes to what
was approved.
"""

from dataclasses import dataclass
from datetime import datetime

from app.core.models import ActionProposal, Approval
from app.engine.proposals import proposal_hash_is_intact


@dataclass(frozen=True)
class Usability:
    ok: bool
    reason: str | None = None


def check_usable(approval: Approval | None, proposal: ActionProposal, now: datetime) -> Usability:
    if approval is None:
        return Usability(False, "no_approval")
    if approval.proposal_id != proposal.id:
        return Usability(False, "approval_for_another_proposal")
    if approval.decision != "approved":
        return Usability(False, "rejected")
    if approval.payload_hash != proposal.payload_hash or not proposal_hash_is_intact(proposal):
        return Usability(False, "payload_changed")
    if now >= approval.expires_at:
        return Usability(False, "expired")
    return Usability(True)
