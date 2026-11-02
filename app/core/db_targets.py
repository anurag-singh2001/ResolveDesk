"""Compare database URLs by what they connect to, decoded the way the driver reads them.

A name-only check is bypassed by percent-encoding (/de%6Do) and by query overrides
(?dbname=, ?options=), so URLs are parsed with SQLAlchemy's make_url (which decodes) and a
URL that carries any such override is refused outright. The target is (host, port, database):
the same database name on another host is a different database (Neon branches share one name);
a pooled Neon endpoint ("-pooler" in the first host label) is the same server as its direct one.
"""

from sqlalchemy.engine import make_url

Target = tuple[str, int, str]
_OVERRIDES = {"dbname", "database", "options", "host", "hostaddr", "port", "service", "user"}


class BadDbUrl(ValueError):
    """Unparseable, or carries query overrides the guard cannot reason about."""


def db_target(url: str) -> Target:
    try:
        u = make_url(url)
    except Exception:
        raise BadDbUrl("not a database url") from None
    if u.drivername.split("+")[0] not in ("postgresql", "postgres"):
        raise BadDbUrl("not a postgresql url")
    if {k.lower() for k in u.query} & _OVERRIDES:
        raise BadDbUrl("the url carries a query override (dbname, options, host, ...)")
    if not u.database:
        raise BadDbUrl("the url names no database")
    labels = (u.host or "").lower().split(".")
    labels[0] = labels[0].removesuffix("-pooler")
    return (".".join(labels), u.port or 5432, u.database.lower())


def safe_target(url: str | None) -> Target | None:
    """The target, or None for a missing url. A malformed url raises BadDbUrl."""
    return db_target(url) if url and url.strip() else None
