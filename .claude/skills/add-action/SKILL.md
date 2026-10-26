---
name: add-action
description: Add a new engine action (something the engine can propose and the executor can run, e.g. a partial refund, a reorder, a callback). Use when a tenant needs a new kind of remedy; not for changing an existing action's limits (that's a settings change).
---
# Add an action

An action is proposed (by the resolver or, later, an agent), validated in code, approved by
a human or a tenant rule, and only then run by the executor. Agents never call actions.

## Files
1. `app/actions/<name>.py`: input model + action class (pattern: `app/actions/free_item_voucher.py`).
2. `app/actions/__init__.py`: import the module so `@register_action` runs.
3. `verticals/<pack>.yaml`: add `<name>` to `actions:` for every pack that may use it, plus any
   new limits under `settings:` (`kind: limit` = integer ceiling that lower levels may only lower).
4. Optional: `remedies:` in the pack if a category should propose it deterministically
   (`app/engine/resolver.py` handles `late_tiers`, `refund_missing`, `voucher`).

## Interface (`app/actions/base.py`)
```python
class MyInput(ActionInput):            # strict: extra fields forbidden, ints stay ints
    transaction_id: uuid.UUID          # ids are bound to the case by create_proposal
    value_paise: int = Field(gt=0)     # money: integer paise, name ends in _paise
    reason: str = Field(min_length=1, max_length=500)

@register_action
class MyAction(NotYetExecutable, Action):
    name = "my_action"
    risk = Risk.MEDIUM                 # HIGH for anything that moves money
    Input = MyInput
    amount_field = "value_paise"       # copied to proposals.amount_paise (DB-checked)
    auto_approvable = False            # True only if a tenant rule may approve it

    def validate(self, ctx, inp, facts: Facts) -> ValidationResult:
        # Pure: read facts.settings / order_total_paise / refundable_paise. No I/O.
        ...
    def can_auto_approve(self, inp, facts) -> bool: ...   # only if auto_approvable
```
- `validate` returns `checks` (shown to the approver) and `errors` (block approval and execution).
- Ids in params (`transaction_id`, `customer_id`, `case_id`) must be the case's own:
  `create_proposal` enforces it; don't add new id params without extending that check.
- Execution: refunds run through `app/engine/executor.py`. A new money-moving action needs the
  same pattern there (lock, reserve under a stable key, call outside a transaction, reconcile
  by key, quarantine on doubt). Until then keep `NotYetExecutable` and an honest customer
  message in `app/engine/case_status.py`.

## Tests (both tenants, never name one)
- `tests/unit/test_eligibility.py`: allowed / over-limit / auto-approve boundary with `Facts`
  built from each tenant's resolved settings (`tenant` fixture).
- `tests/unit/test_registries.py`: covered automatically (every pack action is registered).
- `tests/integration/`: propose → decide → (execute) for both tenants if it can execute.

## Checklist
- [ ] Money fields are `int` paise; no floats anywhere in params.
- [ ] Risk set; refunds and other money moves are never `auto_approvable`.
- [ ] Pack `actions:` updated; new limits are `kind: limit` with integer defaults.
- [ ] Customer-facing wording states only what a tool confirmed.
- [ ] `make lint`, `make test`, `make test-isolation` pass; safety-reviewer run (money/approvals).
- [ ] Decision recorded in `docs/DECISIONS.md` if the rules are new.
