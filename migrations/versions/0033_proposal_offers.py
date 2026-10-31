"""Ask the customer (S8.10): an approver offers two remedies and the customer picks one.

One row per proposal. The options are code-computed ({code, action, amount_paise}); the
customer's answer (chosen_code, chosen_at, new_proposal_id) is write-once: a trigger refuses a
second answer. The proposal itself is never touched (it is immutable). The app role may INSERT,
SELECT and UPDATE (for the one answer) but not DELETE; RLS keeps it to its tenant.

Numbered 0033 and chained after the head at build time (0027); the coordinator renumbers
when branches merge.

Revision ID: 0033
Revises: 0027
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations.rls import disable_rls, enable_rls

APP_ROLE = "resolvedesk_app"

revision: str = "0033"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "proposal_offers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("proposal_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("asked_by", sa.UUID(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("chosen_code", sa.String(32), nullable=True),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("new_proposal_id", sa.UUID(), nullable=True),
        # Set instead of an answer when the offer is closed without a pick (a safety report
        # arrived while the customer was answering): the case goes to a person.
        sa.Column("closed_reason", sa.String(24), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "case_id"], ["cases.tenant_id", "cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asked_by"], ["users.tenant_id", "users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "new_proposal_id"],
            ["action_proposals.tenant_id", "action_proposals.id"],
        ),
        sa.UniqueConstraint("tenant_id", "proposal_id", name="uq_proposal_offers_proposal"),
        sa.CheckConstraint(
            "(chosen_code IS NULL) = (chosen_at IS NULL)", name="ck_proposal_offers_answer"
        ),
        sa.CheckConstraint(
            "(chosen_code IS NULL) = (new_proposal_id IS NULL)", name="ck_proposal_offers_pick"
        ),
        sa.CheckConstraint("expires_at > asked_at", name="ck_proposal_offers_deadline"),
        sa.CheckConstraint(
            "closed_reason IS NULL OR (chosen_code IS NULL AND closed_reason = 'safety_review')",
            name="ck_proposal_offers_closed",
        ),
    )
    op.create_index("ix_proposal_offers_tenant_id", "proposal_offers", ["tenant_id"])
    op.create_index("ix_proposal_offers_case", "proposal_offers", ["tenant_id", "case_id"])
    enable_rls("proposal_offers")
    op.execute(
        "CREATE TRIGGER trg_proposal_offers_updated_at BEFORE UPDATE ON proposal_offers "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    # The question, the options and who asked never change; the answer is written once.
    op.execute(
        """
        CREATE FUNCTION proposal_offers_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.proposal_id IS DISTINCT FROM OLD.proposal_id
               OR NEW.case_id IS DISTINCT FROM OLD.case_id
               OR NEW.asked_by IS DISTINCT FROM OLD.asked_by
               OR NEW.asked_at IS DISTINCT FROM OLD.asked_at
               OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
               OR NEW.options IS DISTINCT FROM OLD.options THEN
                RAISE EXCEPTION 'proposal_offers: the question is immutable';
            END IF;
            IF (OLD.chosen_code IS NOT NULL OR OLD.closed_reason IS NOT NULL)
               AND (NEW.closed_reason IS DISTINCT FROM OLD.closed_reason
                    OR NEW.chosen_code IS DISTINCT FROM OLD.chosen_code
                    OR NEW.chosen_at IS DISTINCT FROM OLD.chosen_at
                    OR NEW.new_proposal_id IS DISTINCT FROM OLD.new_proposal_id) THEN
                RAISE EXCEPTION 'proposal_offers: the answer is write-once';
            END IF;
            IF OLD.chosen_code IS NOT NULL
               AND (NEW.chosen_code IS DISTINCT FROM OLD.chosen_code
                    OR NEW.chosen_at IS DISTINCT FROM OLD.chosen_at
                    OR NEW.new_proposal_id IS DISTINCT FROM OLD.new_proposal_id) THEN
                RAISE EXCEPTION 'proposal_offers: the answer is write-once';
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_proposal_offers_guard BEFORE UPDATE ON proposal_offers "
        "FOR EACH ROW EXECUTE FUNCTION proposal_offers_guard()"
    )
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
        f"RAISE EXCEPTION 'role {APP_ROLE} missing: run scripts/neon_bootstrap.sql first'; "
        f"END IF; REVOKE DELETE, TRUNCATE ON proposal_offers FROM {APP_ROLE}; END $$"
    )


def downgrade() -> None:
    disable_rls("proposal_offers")
    op.execute("DROP TRIGGER IF EXISTS trg_proposal_offers_guard ON proposal_offers")
    op.execute("DROP FUNCTION IF EXISTS proposal_offers_guard()")
    op.drop_index("ix_proposal_offers_case", table_name="proposal_offers")
    op.drop_index("ix_proposal_offers_tenant_id", table_name="proposal_offers")
    op.drop_table("proposal_offers")
