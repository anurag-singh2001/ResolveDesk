"""Engine hardening (E2.3a safety review): least privilege + bindings the executor relies on.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24

- App role: proposals/approvals/verifications are insert+read only; executions and
  refund_operations may only change their status columns; no engine row can be deleted by the
  app (reseed and test cleanup use the owner).
- An execution must reference an *approved* approval *of the same proposal*; one per proposal.
- A refund reservation must match its proposal's amount and order; one per proposal.
- A proposal's amount_paise must equal the param it came from; a run must belong to the case.
- Approval expiry capped at 7 days after the decision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "resolvedesk_app"
ENGINE_TABLES = [
    "cases",
    "workflow_runs",
    "action_proposals",
    "approvals",
    "executions",
    "verifications",
    "refund_operations",
    "domain_events",
]


def _grants(sql: str) -> None:
    """Privileges only apply to the app role. Fail loudly if it doesn't exist: a silently
    skipped REVOKE would leave the guarantees above unenforced."""
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; {sql}; END $$"
    )


def upgrade() -> None:
    # --- proposal: amount column must equal the param it was taken from -------------------
    op.add_column("action_proposals", sa.Column("amount_param", sa.String(64)))
    op.create_check_constraint(
        "ck_action_proposals_amount_matches_params",
        "action_proposals",
        "(amount_param IS NULL AND amount_paise IS NULL) OR "
        "(amount_param IS NOT NULL AND (params ->> amount_param)::bigint = amount_paise)",
    )
    # --- proposal.run must belong to the same case ----------------------------------------
    op.create_unique_constraint(
        "uq_workflow_runs_tenant_id_case", "workflow_runs", ["tenant_id", "id", "case_id"]
    )
    op.drop_constraint(
        "action_proposals_tenant_id_run_id_fkey", "action_proposals", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_action_proposals_run_case",
        "action_proposals",
        "workflow_runs",
        ["tenant_id", "run_id", "case_id"],
        ["tenant_id", "id", "case_id"],
    )
    # --- approvals: expiry cap; execution binding target ----------------------------------
    op.create_check_constraint(
        "ck_approvals_expiry_cap", "approvals", "expires_at <= decided_at + interval '7 days'"
    )
    op.create_unique_constraint(
        "uq_approvals_binding", "approvals", ["tenant_id", "id", "proposal_id", "decision"]
    )
    # --- executions: approved approval of THIS proposal, one per proposal ------------------
    op.add_column(
        "executions",
        sa.Column("approval_decision", sa.String(16), nullable=False, server_default="approved"),
    )
    op.create_check_constraint(
        "ck_executions_only_approved", "executions", "approval_decision = 'approved'"
    )
    op.drop_constraint("executions_tenant_id_approval_id_fkey", "executions", type_="foreignkey")
    op.create_foreign_key(
        "fk_executions_approved_approval_of_proposal",
        "executions",
        "approvals",
        ["tenant_id", "approval_id", "proposal_id", "approval_decision"],
        ["tenant_id", "id", "proposal_id", "decision"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_executions_one_per_proposal", "executions", ["tenant_id", "proposal_id"]
    )
    # --- refund ledger: one reservation per proposal, matching it ---------------------------
    op.create_unique_constraint(
        "uq_refund_operations_one_per_proposal", "refund_operations", ["tenant_id", "proposal_id"]
    )
    op.execute(
        """
        CREATE FUNCTION refund_matches_proposal() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE p action_proposals%ROWTYPE;
        BEGIN
            SELECT * INTO p FROM action_proposals
             WHERE tenant_id = NEW.tenant_id AND id = NEW.proposal_id;
            IF p.id IS NULL OR p.action <> 'refund'
               OR (p.params ->> 'amount_paise')::bigint IS DISTINCT FROM NEW.amount_paise
               OR (p.params ->> 'transaction_id')::uuid IS DISTINCT FROM NEW.transaction_id THEN
                RAISE EXCEPTION 'refund operation does not match its refund proposal'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_refund_operations_match BEFORE INSERT OR UPDATE OF amount_paise, "
        "transaction_id, proposal_id ON refund_operations "
        "FOR EACH ROW EXECUTE FUNCTION refund_matches_proposal()"
    )
    # Approvals are decisions: never edited (defence in depth on top of the privileges).
    op.execute(
        "CREATE TRIGGER trg_approvals_immutable BEFORE UPDATE ON approvals "
        "FOR EACH ROW EXECUTE FUNCTION reject_update()"
    )
    # --- least privilege for the app role --------------------------------------------------
    tables = ", ".join(ENGINE_TABLES)
    _grants(
        f"REVOKE DELETE, TRUNCATE ON {tables} FROM {APP_ROLE}; "
        f"REVOKE UPDATE ON action_proposals, approvals, verifications, executions, "
        f"refund_operations FROM {APP_ROLE}; "
        f"GRANT UPDATE (status, provider_reference, error) ON executions TO {APP_ROLE}; "
        f"GRANT UPDATE (status, provider_reference) ON refund_operations TO {APP_ROLE}; "
        f"REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM {APP_ROLE}"
    )


def downgrade() -> None:
    tables = ", ".join(ENGINE_TABLES)
    _grants(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {APP_ROLE}")
    op.execute("DROP TRIGGER IF EXISTS trg_approvals_immutable ON approvals")
    op.execute("DROP TRIGGER IF EXISTS trg_refund_operations_match ON refund_operations")
    op.execute("DROP FUNCTION IF EXISTS refund_matches_proposal()")
    op.drop_constraint("uq_refund_operations_one_per_proposal", "refund_operations", type_="unique")
    op.drop_constraint("uq_executions_one_per_proposal", "executions", type_="unique")
    op.drop_constraint(
        "fk_executions_approved_approval_of_proposal", "executions", type_="foreignkey"
    )
    op.create_foreign_key(
        "executions_tenant_id_approval_id_fkey",
        "executions",
        "approvals",
        ["tenant_id", "approval_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("ck_executions_only_approved", "executions", type_="check")
    op.drop_column("executions", "approval_decision")
    op.drop_constraint("uq_approvals_binding", "approvals", type_="unique")
    op.drop_constraint("ck_approvals_expiry_cap", "approvals", type_="check")
    op.drop_constraint("fk_action_proposals_run_case", "action_proposals", type_="foreignkey")
    op.create_foreign_key(
        "action_proposals_tenant_id_run_id_fkey",
        "action_proposals",
        "workflow_runs",
        ["tenant_id", "run_id"],
        ["tenant_id", "id"],
    )
    op.drop_constraint("uq_workflow_runs_tenant_id_case", "workflow_runs", type_="unique")
    op.drop_constraint(
        "ck_action_proposals_amount_matches_params", "action_proposals", type_="check"
    )
    op.drop_column("action_proposals", "amount_param")
