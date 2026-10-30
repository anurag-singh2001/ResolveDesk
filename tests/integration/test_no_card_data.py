"""P5 (owner decision, S8.8): nothing that looks like a card number, CVV or UPI PIN is stored.

The privacy page may say "we never see or store your card number, CVV or UPI PIN" only while
this test passes; `data_held.CONFIRMED_NOT_KEPT` lists `card_numbers` on that basis. The UPI ID
claim (`upi_details`) is NOT made: a gateway refund payload can carry the payer's UPI ID, and
this test does not prove otherwise.

Three checks, for every tenant (none named): no column is named like a card or PIN field; no
stored text or JSON value holds a Luhn-valid 13-19 digit number; no stored JSON key is named
like a card, CVV or PIN field. A scanner that cannot fail is useless, so the unit tests at the
bottom show it does catch a card number, a spaced one, a CVV key and a PIN key.
"""

import re

import pytest
from sqlalchemy import text

from app.core.db import tenant_session
from app.core.tenancy import tenant_id_for
from app.core.tenant_config import load_tenant
from app.engine import data_held

# Tables we do not scan: policy text and its embedding (floats look like long digit runs and
# policy files carry no customer data).
SKIP_TABLES = {"policy_chunks", "policy_documents"}
COLUMN_NAME = re.compile(
    r"(card_?(number|no|num)|\bpan\b|cvv|cvc|upi_?pin|\bpin\b|net_?banking)", re.I
)
KEY_NAME = re.compile(
    r'"(card_?(number|no|num)|cvv|cvc|cvv2|upi_?pin|pin|card_?pin|expiry|exp_?date)"\s*:', re.I
)
# 13-19 digits, optionally grouped with single spaces or dashes, not part of a longer number
# or a decimal fraction.
CANDIDATE = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
# SQL pre-filter: only rows with a long digit run or a grouped one come back to Python.
SQL_PREFILTER = r"[0-9]{13}|[0-9]{4}[ -][0-9]{4}[ -][0-9]{4}"


def luhn_ok(digits: str) -> bool:
    total, flip = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if flip:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        flip = not flip
    return total % 10 == 0


def card_like_numbers(blob: str) -> list[str]:
    out = []
    for m in CANDIDATE.finditer(blob):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            out.append(digits)
    return out


def sensitive_keys(blob: str) -> list[str]:
    return [m.group(1) for m in KEY_NAME.finditer(blob)]


def test_scanner_catches_what_it_is_meant_to_catch():
    assert card_like_numbers("paid with 4111111111111111 ok")
    assert card_like_numbers("card 4111 1111 1111 1111")
    assert card_like_numbers("card 4111-1111-1111-1111")
    assert sensitive_keys('{"cvv": "123"}') == ["cvv"]
    assert sensitive_keys('{"upi_pin": "1234"}') == ["upi_pin"]
    assert COLUMN_NAME.search("card_number") and COLUMN_NAME.search("cvv")


def test_scanner_ignores_ordinary_numbers():
    assert not card_like_numbers("order 1234567890 total 4999 at 2026-10-31 12:30")
    assert not card_like_numbers("0.12345678901234567")  # a float, not a card
    assert not card_like_numbers("4111111111111112")  # right length, fails the Luhn check
    assert not sensitive_keys('{"method": "upi", "amount_paise": 100}')


@pytest.fixture
def scanned(app_engine, seeded_history, tenant):
    return tenant_id_for(load_tenant(tenant).slug)


def _tenant_tables(s) -> list[str]:
    rows = s.execute(
        text(
            "SELECT DISTINCT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t ON t.table_name = c.table_name "
            "AND t.table_schema = c.table_schema AND t.table_type = 'BASE TABLE' "
            "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' "
            "ORDER BY c.table_name"
        )
    )
    return [r[0] for r in rows if r[0] not in SKIP_TABLES]


def test_no_column_is_named_like_a_card_or_pin_field(app_engine, scanned):
    with tenant_session(scanned, app_engine) as s:
        names = [
            (r[0], r[1])
            for r in s.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public'"
                )
            )
        ]
    bad = [f"{t}.{c}" for t, c in names if COLUMN_NAME.search(c)]
    assert not bad, f"columns that look like card or PIN fields: {bad}"


def test_no_stored_value_is_a_card_number_or_holds_a_card_field(app_engine, scanned):
    hits = []
    with tenant_session(scanned, app_engine) as s:
        for table in _tenant_tables(s):
            # RLS limits the scan to this tenant; row_to_json covers every text and JSON column.
            rows = s.execute(
                text(
                    f'SELECT row_to_json(t)::text FROM "{table}" t '  # noqa: S608 (table names come from information_schema)
                    "WHERE row_to_json(t)::text ~ :pre OR row_to_json(t)::text ~* :keys"
                ),
                {"pre": SQL_PREFILTER, "keys": KEY_NAME.pattern},
            )
            for (blob,) in rows:
                if card_like_numbers(blob):
                    hits.append(f"{table}: a Luhn-valid 13-19 digit number")
                keys = sensitive_keys(blob)
                if keys:
                    hits.append(f"{table}: key {keys[0]}")
    assert not hits, hits


def test_the_card_number_claim_is_confirmed_in_code_but_the_upi_id_claim_is_not():
    # This file is the evidence for the first; nothing proves the second.
    assert "card_numbers" in data_held.CONFIRMED_NOT_KEPT
    assert "upi_details" not in data_held.CONFIRMED_NOT_KEPT
