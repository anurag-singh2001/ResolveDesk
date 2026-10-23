"""Generate canonical history rows in memory (no DB). See simulator/load.py for persistence."""

import bisect
import hashlib
import itertools
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, timezone

from app.core.models import (
    Consent,
    Customer,
    Fulfilment,
    LineItem,
    Payment,
    Ticket,
    TicketMessage,
    Transaction,
)
from app.core.tenant_config import ProblemCfg, SimulationCfg, TenantConfig
from app.core.verticals import VerticalPack

# Local business time. A fixed offset (no DST in India) keeps generation independent of tzdata.
LOCAL_TZ = timezone(timedelta(hours=5, minutes=30))

FIRST_NAMES = [
    "Aarav", "Aditi", "Akash", "Ananya", "Arjun", "Diya", "Farhan", "Gauri", "Harsh", "Ira",
    "Ishaan", "Kavya", "Kiran", "Meera", "Neel", "Nisha", "Omkar", "Pooja", "Rahul", "Riya",
    "Sahil", "Sana", "Tanvi", "Varun", "Zoya",
]  # fmt: skip
CHANNELS = ["whatsapp", "app", "email"]
PAYMENT_METHODS = ["upi", "card", "wallet"]


@dataclass(frozen=True)
class Refs:
    """Database ids the generator needs; opaque to it."""

    tenant_id: uuid.UUID
    brand_ids: dict[str, uuid.UUID]
    location_ids: dict[str, uuid.UUID]
    user_ids: dict[str, uuid.UUID]  # email -> id, for customers who can log in


@dataclass
class History:
    customers: list[dict] = field(default_factory=list)
    transactions: list[dict] = field(default_factory=list)
    line_items: list[dict] = field(default_factory=list)
    payments: list[dict] = field(default_factory=list)
    fulfilments: list[dict] = field(default_factory=list)
    tickets: list[dict] = field(default_factory=list)
    ticket_messages: list[dict] = field(default_factory=list)
    consents: list[dict] = field(default_factory=list)
    window_start: datetime | None = None

    def tables(self) -> list[tuple[type, list[dict]]]:
        """(model, rows), parents first."""
        return [
            (Customer, self.customers),
            (Transaction, self.transactions),
            (LineItem, self.line_items),
            (Payment, self.payments),
            (Fulfilment, self.fulfilments),
            (Ticket, self.tickets),
            (TicketMessage, self.ticket_messages),
            (Consent, self.consents),
        ]

    def checksum(self) -> str:
        h = hashlib.sha256()
        for model, rows in self.tables():
            h.update(model.__tablename__.encode())
            for row in rows:
                h.update(repr(sorted(row.items())).encode())
        return h.hexdigest()


def stable_seed(seed: int, slug: str) -> int:
    """Per-tenant seed; hashlib (not hash()) so it is the same in every process."""
    return int.from_bytes(hashlib.sha256(f"{seed}:{slug}".encode()).digest()[:8], "big")


def problem_applies(p: ProblemCfg, location: str, local: datetime) -> bool:
    if p.location is not None and p.location != location:
        return False
    if p.hours is not None and not (p.hours[0] <= local.hour < p.hours[1]):
        return False
    return not (p.weekdays_only and local.weekday() >= 5)


def generate(
    cfg: TenantConfig, pack: VerticalPack, refs: Refs, seed: int = 42, scale: float = 1.0
) -> History:
    if cfg.simulation is None:
        return History()
    return _Generator(cfg, pack, refs, seed, scale).run()


class _Generator:
    def __init__(self, cfg, pack, refs, seed, scale):
        self.cfg, self.pack, self.refs = cfg, pack, refs
        self.sim: SimulationCfg = cfg.simulation
        self.rng = random.Random(stable_seed(seed, cfg.slug))
        self.scale = scale
        self.out = History()
        # (order_id, customer index, completed_at, problem kind | None), for past tickets
        self.problem_orders: list[tuple] = []
        self.plain_orders: list[tuple] = []
        self.start_day: date = self.sim.end_date - timedelta(days=self.sim.days - 1)
        self.out.window_start = datetime.combine(self.start_day, time(0), LOCAL_TZ)
        self.locations = [loc.slug for loc in cfg.locations]
        self.brands_at = {loc.slug: loc.brands for loc in cfg.locations}
        self.items_by_brand: dict[str, list] = {}
        for item in cfg.catalogue:
            self.items_by_brand.setdefault(item.brand, []).append(item)

    def uid(self, kind: str, n: int) -> uuid.UUID:
        return uuid.uuid5(self.refs.tenant_id, f"sim:{kind}:{n}")

    def scaled(self, n: int, minimum: int = 0) -> int:
        return max(minimum, round(n * self.scale))

    def run(self) -> History:
        self._customers()
        self._orders()
        self._tickets()
        self._consents()
        return self.out

    # -- customers -------------------------------------------------------------------------

    def _customers(self) -> None:
        rng, sim = self.rng, self.sim
        demo = [u for u in self.cfg.users if u.role == "customer"]
        n = self.scaled(sim.customers, minimum=len(demo) + len(self.locations))
        self.pools: dict[str, list[int]] = {slug: [] for slug in self.locations}
        weights = []
        for i in range(n):
            home = self.locations[i % len(self.locations)]
            if i < len(demo):
                name, email = demo[i].name, demo[i].email
                user_id = self.refs.user_ids.get(email)
                weight = 25.0  # demo customers always have a real order history
            else:
                name = f"{rng.choice(FIRST_NAMES)} {chr(65 + rng.randrange(26))}."
                email, user_id = None, None
                weight = min(rng.paretovariate(1.3), 20.0)  # few regulars, many occasional
            self.out.customers.append(
                {
                    "id": self.uid("customer", i),
                    "tenant_id": self.refs.tenant_id,
                    "external_ref": f"C{i:06d}",
                    "name": name,
                    "phone": f"9{rng.randrange(10**9):09d}",
                    "email": email,
                    "user_id": user_id,
                    "home_location_id": self.refs.location_ids[home],
                    "attributes": {},
                }
            )
            self.pools[home].append(i)
            weights.append(weight)

        messy = sim.messy
        others = list(range(len(demo), n))
        for i in rng.sample(
            others, min(len(others), round(len(others) * messy.duplicate_phone_rate))
        ):
            j = rng.choice([k for k in (i - 1, i + 1) if 0 <= k < n])
            self.out.customers[i]["phone"] = self.out.customers[j]["phone"]
        if len(self.locations) > 1:
            k = round(len(others) * messy.multi_location_customer_rate)
            for i in rng.sample(others, min(len(others), k)):
                home = self.locations[i % len(self.locations)]
                extra = rng.choice([slug for slug in self.locations if slug != home])
                self.pools[extra].append(i)

        self.cum_weights = {
            slug: list(itertools.accumulate(weights[i] for i in pool))
            for slug, pool in self.pools.items()
        }
        self.n_customers = n

    def _pick_customer(self, location: str) -> int:
        pool, cum = self.pools[location], self.cum_weights[location]
        return pool[bisect.bisect(cum, self.rng.random() * cum[-1])]

    # -- orders ----------------------------------------------------------------------------

    def _orders(self) -> None:
        rng, sim = self.rng, self.sim
        loc_weights = [sim.location_weights.get(s, 1.0) for s in self.locations]
        sources = self.pack.order_sources
        src_weights = [sim.source_weights.get(s, 1.0) for s in sources]
        n_in = self.scaled(sim.orders, minimum=1)
        n_out = self.scaled(sim.messy.orders_outside_window)

        slots = []
        for _ in range(n_in):
            slots.append((rng.randrange(sim.days), self._minute_of_day()))
        for _ in range(n_out):  # messy: history from before the analysis window
            slots.append((-rng.randint(1, 30), self._minute_of_day()))
        slots.sort()

        drops = [p for p in sim.problems if p.kind == "repeat_drop"]
        seen_at: dict[str, set[int]] = {slug: set() for slug in self.locations}
        for n, (day, minute) in enumerate(slots):
            location = rng.choices(self.locations, weights=loc_weights)[0]
            local = datetime.combine(self.start_day + timedelta(days=day), time(0), LOCAL_TZ)
            local += timedelta(minutes=minute)
            customer = self._pick_customer(location)
            if day >= 0 and any(
                d.location == location and day >= d.from_day and rng.random() < d.factor
                for d in drops
            ):
                customer = self._newcomer(seen_at[location])
            seen_at[location].add(customer)
            source = rng.choices(sources, weights=src_weights)[0]
            self._order(n, day, local, location, customer, source)

    def _minute_of_day(self) -> int:
        start, end = self.sim.hours
        return self.rng.randrange(start * 60, end * 60)

    def _newcomer(self, seen: set[int]) -> int:
        """A customer with no order at this location yet (a regular's order lost to churn)."""
        for _ in range(50):
            i = self.rng.randrange(self.n_customers)
            if i not in seen:
                return i
        return self.rng.randrange(self.n_customers)

    def _order(self, n, day, local, location, customer, source) -> None:
        rng, sim, tid = self.rng, self.sim, self.refs.tenant_id
        order_id = self.uid("order", n)
        brand = rng.choice(self.brands_at[location])
        menu = self.items_by_brand[brand]
        lines = rng.sample(menu, min(len(menu), rng.randint(*sim.items_per_order)))

        active = {}
        if day >= 0:  # planted problems only inside the analysis window
            for p in sim.problems:
                applies = p.kind != "repeat_drop" and problem_applies(p, location, local)
                if applies and (p.kind not in active or p.rate > active[p.kind].rate):
                    active[p.kind] = p
        flags = {kind for kind, p in active.items() if rng.random() < p.rate}

        total = 0
        missing_line = rng.randrange(len(lines)) if "missing_item" in flags else None
        for k, item in enumerate(lines):
            qty = 1 if rng.random() < 0.8 else 2
            line_total = item.price_paise * qty
            total += line_total
            self.out.line_items.append(
                {
                    "id": self.uid("line", n * 10 + k),
                    "tenant_id": tid,
                    "transaction_id": order_id,
                    "sku": item.sku,
                    "name": item.name,
                    "quantity": qty,
                    "quantity_fulfilled": qty - 1 if k == missing_line else qty,
                    "unit_price_paise": item.price_paise,
                    "total_paise": line_total,
                }
            )

        placed = local.astimezone(UTC)
        promised = placed + timedelta(minutes=rng.randint(*sim.promise_minutes))
        if "late" in flags:
            completed = promised + timedelta(minutes=rng.randint(*active["late"].extra_minutes))
        else:
            completed = promised + timedelta(minutes=rng.randint(*sim.delay_minutes))
        self.out.transactions.append(
            {
                "id": order_id,
                "tenant_id": tid,
                "customer_id": self.uid("customer", customer),
                "brand_id": self.refs.brand_ids[brand],
                "location_id": self.refs.location_ids[location],
                "source": source,
                "external_ref": f"O{n:07d}",
                "placed_at": placed,
                "total_paise": total,
                "status": "completed",
                "attributes": {},
            }
        )
        self.out.payments.append(
            {
                "id": self.uid("payment", n),
                "tenant_id": tid,
                "transaction_id": order_id,
                "method": rng.choice(PAYMENT_METHODS),
                "amount_paise": total,
                "status": "captured",
                "provider_reference": f"PAY-{self.uid('payref', n).hex[:16]}",
                "captured_at": placed,
            }
        )
        self.out.fulfilments.append(
            {
                "id": self.uid("fulfilment", n),
                "tenant_id": tid,
                "transaction_id": order_id,
                "kind": self.pack.fulfilment_kinds[source],
                "promised_at": promised,
                "completed_at": completed,
                "status": "completed",
                "attributes": {"wrong_item": True} if "wrong_item" in flags else {},
            }
        )
        if flags:
            self.problem_orders.append((order_id, customer, completed, sorted(flags)[0]))
        else:
            self.plain_orders.append((order_id, customer, completed, None))

    # -- tickets & consents ----------------------------------------------------------------

    def _tickets(self) -> None:
        rng, sim, tid = self.rng, self.sim, self.refs.tenant_id
        n = self.scaled(sim.past_tickets)
        candidates = rng.sample(self.problem_orders, len(self.problem_orders))
        candidates += rng.sample(self.plain_orders, min(len(self.plain_orders), n))
        for t, (order_id, customer, completed, kind) in enumerate(candidates[:n]):
            category = sim.ticket_categories.get(kind, sim.default_ticket_category)
            opened = completed + timedelta(minutes=rng.randint(5, 180))
            closed = opened + timedelta(minutes=rng.randint(20, 720))
            ticket_id = self.uid("ticket", t)
            self.out.tickets.append(
                {
                    "id": ticket_id,
                    "tenant_id": tid,
                    "customer_id": self.uid("customer", customer),
                    "transaction_id": order_id,
                    "category": category,
                    "status": rng.choice(["resolved", "closed"]),
                    "channel": rng.choice(CHANNELS),
                    "opened_at": opened,
                    "closed_at": closed,
                }
            )
            for m, (author, body, at) in enumerate(
                [
                    ("customer", f"Problem with my order: {category.replace('_', ' ')}.", opened),
                    ("staff", "Sorry about that. We have looked into it.", closed),
                ]
            ):
                self.out.ticket_messages.append(
                    {
                        "id": self.uid("message", t * 10 + m),
                        "tenant_id": tid,
                        "ticket_id": ticket_id,
                        "author": author,
                        "body": body,
                        "sent_at": at,
                    }
                )

    def _consents(self) -> None:
        rate = self.sim.messy.opted_out_rate
        for i, customer in enumerate(self.out.customers):
            for k, (purpose, granted) in enumerate(
                [("marketing", self.rng.random() >= rate), ("service", True)]
            ):
                self.out.consents.append(
                    {
                        "id": self.uid("consent", i * 10 + k),
                        "tenant_id": self.refs.tenant_id,
                        "customer_id": customer["id"],
                        "channel": "whatsapp",
                        "purpose": purpose,
                        "granted": granted,
                    }
                )
