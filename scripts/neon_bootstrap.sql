-- One-time Neon bootstrap. Run in the Neon SQL editor on the `main` branch, as neondb_owner,
-- BEFORE creating the `test` branch (child branches copy roles and grants from the parent).
--
-- Why the role is created here and not in the Neon console: console-created roles join
-- neon_superuser, which has BYPASSRLS. The app role must be subject to RLS (hard rule 1).
-- Neon requires a strong password (>= 60 bits entropy), e.g. 24 random alphanumeric chars.

CREATE EXTENSION IF NOT EXISTS vector;

-- LangGraph checkpoint tables live apart from the ledger (PROJECT.md section 7).
CREATE SCHEMA IF NOT EXISTS lg;

CREATE ROLE resolvedesk_app LOGIN PASSWORD 'REPLACE_WITH_STRONG_PASSWORD' NOBYPASSRLS NOSUPERUSER NOCREATEROLE NOCREATEDB;

GRANT CONNECT ON DATABASE neondb TO resolvedesk_app;
GRANT USAGE ON SCHEMA public TO resolvedesk_app;
GRANT USAGE, CREATE ON SCHEMA lg TO resolvedesk_app;

-- Tables are created by migrations running as neondb_owner; the app role gets DML only, never ownership.
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO resolvedesk_app;
ALTER DEFAULT PRIVILEGES FOR ROLE neondb_owner IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO resolvedesk_app;

-- Check: expect resolvedesk_app | f | f
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'resolvedesk_app';
