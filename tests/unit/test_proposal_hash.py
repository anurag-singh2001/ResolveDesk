import uuid

import pytest

from app.engine.proposals import ProposalError, canonical_json, payload_hash

CASE = uuid.UUID("00000000-0000-0000-0000-000000000001")
TXN = "00000000-0000-0000-0000-0000000000aa"
PARAMS = {"transaction_id": TXN, "amount_paise": 34900, "reason": "late delivery"}


def test_hash_ignores_key_order():
    reordered = {"reason": "late delivery", "amount_paise": 34900, "transaction_id": TXN}
    assert payload_hash("refund", CASE, PARAMS) == payload_hash("refund", CASE, reordered)


@pytest.mark.parametrize(
    "action,case,params",
    [
        ("free_item_voucher", CASE, PARAMS),
        ("refund", uuid.UUID(int=2), PARAMS),
        ("refund", CASE, {**PARAMS, "amount_paise": 34901}),
        ("refund", CASE, {**PARAMS, "transaction_id": "00000000-0000-0000-0000-0000000000bb"}),
        ("refund", CASE, {**PARAMS, "reason": "late"}),
    ],
    ids=["action", "case", "amount", "order", "reason"],
)
def test_any_material_change_changes_the_hash(action, case, params):
    assert payload_hash(action, case, params) != payload_hash("refund", CASE, PARAMS)


def test_hash_is_hex_sha256_and_stable_across_runs():
    digest = payload_hash("refund", CASE, PARAMS)
    assert len(digest) == 64 and int(digest, 16) >= 0
    assert digest == payload_hash("refund", CASE, dict(PARAMS))


@pytest.mark.parametrize("bad", [{"amount": 1.0}, {"nested": [{"x": 0.5}]}, {1: "int key"}])
def test_floats_and_non_string_keys_are_refused(bad):
    with pytest.raises(ProposalError):
        canonical_json(bad)


def test_unicode_is_kept_not_escaped():
    assert canonical_json({"reason": "बिरयानी ठंडी"}) == '{"reason":"बिरयानी ठंडी"}'
