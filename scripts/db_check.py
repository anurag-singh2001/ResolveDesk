"""Check Neon connectivity for each configured URL and that the app role cannot bypass RLS."""

import sys

from sqlalchemy import create_engine, text

from app.config import get_settings

QUERY = text(
    "SELECT current_user, r.rolsuper, r.rolbypassrls, "
    "EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') "
    "FROM pg_roles r WHERE r.rolname = current_user"
)


def main() -> int:
    s = get_settings()
    urls = {"DATABASE_URL": s.database_url, "TEST_DATABASE_URL": s.test_database_url}
    ok = True
    for name, url in urls.items():
        if not url:
            print(f"{name}: not set")
            ok = False
            continue
        try:
            with create_engine(url).connect() as conn:
                user, superuser, bypass, vector = conn.execute(QUERY).one()
        except Exception as exc:  # report and continue with the next URL
            print(f"{name}: connection failed: {exc.__class__.__name__}: {exc}")
            ok = False
            continue
        safe = not superuser and not bypass
        print(f"{name}: user={user} superuser={superuser} bypassrls={bypass} vector={vector}")
        if not safe:
            print(f"  {name} must use the non-owner app role (RLS would be bypassed).")
        ok = ok and safe and vector
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
