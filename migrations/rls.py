"""RLS helpers shared by migrations. Every tenant-owned table gets exactly this policy."""

from alembic import op

# current_setting(..., true) returns NULL when unset; nullif handles '' left by a reset.
# NULL never equals tenant_id, so "no tenant set" means no rows visible and no rows writable.
TENANT_PREDICATE = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # FORCE: the table owner is subject to the policy too, unless the role has BYPASSRLS.
    # On Neon the owner (neondb_owner) DOES have BYPASSRLS: owner-run code must filter on
    # tenant_id itself. The app role is NOBYPASSRLS, so for it RLS always applies.
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def disable_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
