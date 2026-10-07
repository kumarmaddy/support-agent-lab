"""Shared machinery for scenario families (stage 0.4c).

A scenario family module defines ScenarioDef entries. Each entry builds ONE ticket (plus the
order(s) it refers to) per call, using the same order builder as the background pool.
"""
import random
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Callable

from src.datagen import config
from src.datagen.domain import labels, policy, priority
from src.datagen.generation import text
from src.datagen.generation.orders import (
    OrderContext,
    OrderRows,
    OrderSpec,
    build_order,
    plan_timeline,
)

OPEN_STATUSES = ("processing", "shipped")


@dataclass(frozen=True)
class Phrasing:
    """One way a customer might phrase a request, with the facts it implies."""
    text: str
    tone: str | None = None                       # force a tone; None = random
    difficulty: str = "standard"
    ambiguity: bool = False                       # vague urgency such as "as soon as possible"
    deadline_days: tuple[int, int] | None = None  # stated deadline, days after the ticket arrives
    adversarial_type: str | None = None           # prompt_injection, impersonation, ...; needs difficulty="adversarial"


@dataclass
class ScenarioContext:
    order_ctx: OrderContext
    product_names: dict[str, str]
    customers: dict[str, tuple]
    open_customer_ids: set[str]       # customers with at least one open (processing/shipped) order
    reserved_customer_ids: set[str]   # customers whose open-order count must not change later
    now: datetime = config.AS_OF_DATETIME
    split: str = "dev"                # "dev" or "heldout"; selects the phrasing pool (see pick)


@dataclass
class GeneratedTicket:
    scenario_id: str
    orders: OrderRows
    customer_email: str
    subject: str
    body: str
    received_at: datetime
    label: dict


@dataclass(frozen=True)
class ScenarioDef:
    scenario_id: str
    name: str
    count: int
    build: Callable[[ScenarioContext, random.Random, int], GeneratedTicket]


class MissingHeldoutPhrasing(LookupError):
    """Raised when the held-out split is requested for a scenario that has no held-out phrasing yet."""


def pick(sctx: ScenarioContext, scenario_id: str, dev_pool: list, i: int):
    """Choose entry i of the phrasing pool for the current split.

    The held-out pool has the same length and the same meaning at each index as the dev pool (so
    labels and edge-case coverage match) but different wording. A missing held-out pool is an error,
    never a silent fallback to dev wording, because that would leak dev phrasing into the test set.
    """
    if sctx.split == "dev":
        pool = dev_pool
    else:
        from src.datagen.scenarios.phrasing_heldout import HELDOUT
        if scenario_id not in HELDOUT:
            raise MissingHeldoutPhrasing(scenario_id)
        pool = HELDOUT[scenario_id]
    return pool[i % len(pool)]


def calm(rng: random.Random, phrasing: Phrasing) -> Phrasing:
    """Force a calm tone, for questions from people who have not yet had any service to complain about."""
    return replace(phrasing, tone=rng.choice(["polite", "neutral", "terse"]))


def choose_customer(sctx: ScenarioContext, rng: random.Random, placed_at: datetime,
                    require_no_open: bool = False) -> str:
    """Pick a customer who existed when the order was placed and is not reserved."""
    day = placed_at.date().isoformat()
    pool = sorted(cid for cid, c in sctx.customers.items()
                  if c[4] <= day and cid not in sctx.reserved_customer_ids
                  and not (require_no_open and cid in sctx.open_customer_ids))
    if not pool:
        raise ValueError(f"no eligible customer for an order placed {day}")
    return rng.choice(pool)


def note_open_orders(sctx: ScenarioContext, rows: OrderRows) -> None:
    for order in rows.orders:
        if order[3] in OPEN_STATUSES:
            sctx.open_customer_ids.add(order[1])


def pick_received_at(rng: random.Random, now: datetime, earliest: datetime) -> datetime:
    """Ticket arrival time: within the last 46 hours and after the order's latest event."""
    lo = max(now - timedelta(hours=46), earliest + timedelta(minutes=30))
    hi = now - timedelta(minutes=10)
    if lo >= hi:
        lo = hi - timedelta(minutes=30)
    return lo + timedelta(seconds=rng.randint(0, int((hi - lo).total_seconds())))


def latest_event(*timelines) -> datetime:
    """The latest thing that happened on the order(s); a ticket cannot arrive before it."""
    return max(t for tl in timelines
               for t in (tl.placed_at, tl.dispatched_at, tl.delivered_at, tl.label_issued_at,
                         tl.received_at) if t)


# Facts shared by several scenario families. Signature: (rows, deadline, fields) -> dict
def shipped_facts(rows, deadline, fields):
    order, shipment = rows.orders[0], rows.shipments[0]
    return {"order_status": order[3], "promised_date": order[5], "carrier": shipment[2],
            "tracking_no": shipment[3], "last_status": shipment[6]}


def processing_facts(rows, deadline, fields):
    facts = {"order_status": rows.orders[0][3], "promised_date": rows.orders[0][5],
             "dispatched": False}
    if deadline:
        facts["deadline_date"] = deadline.isoformat()
    return facts


def delivered_at(rows) -> datetime:
    return datetime.fromisoformat(rows.shipments[0][5])


def delivered_date_field(rows, rng, received_at):
    return {"delivered_date": text.fmt_date(delivered_at(rows).date(), rng)}


def window_facts(rows, deadline, fields):
    """Return-window facts for a delivered order; computed by policy, never hard-coded."""
    order, delivered = rows.orders[0], delivered_at(rows)
    return {"order_status": order[3], "promised_date": order[5],
            "delivered_date": delivered.date().isoformat(),
            "days_since_delivery": policy.days_since_delivery(delivered),
            "within_return_window": policy.within_return_window(delivered),
            "return_window_days": config.RETURN_WINDOW_DAYS}


def duplicate_fields(rows, rng, received_at):
    duplicate = next(p for p in rows.payments if p[4] == "duplicate_flagged")
    return {"amount": text.fmt_money(duplicate[2]), "amount_cents": duplicate[2], "last4": duplicate[3]}


def duplicate_facts(rows, fields):
    return {"duplicate_amount_cents": fields["amount_cents"],
            "duplicate_payment_id": next(p[0] for p in rows.payments if p[4] == "duplicate_flagged")}


def build_single_order_ticket(sctx: ScenarioContext, rng: random.Random, *, scenario_id: str,
                              spec: OrderSpec, phrasing: Phrasing, subjects: list[str],
                              category: str, flags: dict[str, bool], actions: list[str],
                              kb_ids: list[str], facts_fn, escalate_reason: str | None = None,
                              secondary_categories: tuple[str, ...] = (), extra_fields_fn=None
                              ) -> GeneratedTicket:
    """Build one order and one ticket about it, with its ground-truth label.

    extra_fields_fn(rows, rng, received_at) may return additional values for the ticket text; they
    are also passed to facts_fn(rows, deadline, fields) so labels and text always agree."""
    tl = plan_timeline(spec, rng)
    spec.customer_id = choose_customer(sctx, rng, tl.placed_at)
    rows = build_order(sctx.order_ctx, spec, tl, rng)
    note_open_orders(sctx, rows)

    order = rows.orders[0]
    customer = sctx.customers[order[1]]
    received_at = pick_received_at(rng, sctx.now, latest_event(tl))

    product = sctx.product_names[rows.order_items[0][2]]
    fields = {
        **text.grammar_fields(product),
        "order_id": order[0],
        "product": product,
        "placed_date": text.fmt_date(datetime.fromisoformat(order[2]).date(), rng),
        "promised_date": text.fmt_date(date.fromisoformat(order[5]), rng),
    }
    deadline = None
    if phrasing.deadline_days:
        lo, hi = phrasing.deadline_days
        deadline = received_at.date() + timedelta(days=rng.randint(lo, hi))
        fields["deadline_date"] = text.fmt_date(deadline, rng)
        fields["deadline_weekday"] = text.weekday_name(deadline)
    if extra_fields_fn:
        fields.update(extra_fields_fn(rows, rng, received_at))

    tone = phrasing.tone or rng.choices(text.TONES, weights=text.TONE_WEIGHTS)[0]
    typo_roll = rng.random() < 0.3                 # always drawn, so random streams stay aligned
    protect = tuple(fields[k] for k in ("new_address",) if k in fields)     # facts the label records
    body = text.compose(rng, phrasing.text.format(**fields), customer[1].split()[0], tone,
                        typo=typo_roll and phrasing.adversarial_type is None,   # attack text stays intact
                        protect=protect)
    subject = rng.choice(subjects).format(**fields)

    label = labels.new_label(
        scenario_id=scenario_id, category=category,
        attributes=priority.make_attributes(**flags),
        expected_actions=actions, required_kb_ids=kb_ids, referenced_order_id=order[0],
        expected_escalate=escalate_reason is not None, escalation_reason=escalate_reason,
        expected_facts=facts_fn(rows, deadline, fields),
        difficulty=phrasing.difficulty, ambiguity_flag=phrasing.ambiguity,
        adversarial_type=phrasing.adversarial_type, secondary_categories=secondary_categories)
    return GeneratedTicket(scenario_id, rows, customer[2], subject, body, received_at, label)


def build_account_ticket(sctx: ScenarioContext, rng: random.Random, *, scenario_id: str,
                         customer_id: str, phrasing: Phrasing, subjects: list[str], category: str,
                         flags: dict[str, bool], actions: list[str], kb_ids: list[str],
                         facts: dict, escalate_reason: str | None = None) -> GeneratedTicket:
    """Build a ticket that is not about a specific order (account problems, general questions).

    No order rows are created; the label records that no order is referenced.
    """
    customer = sctx.customers[customer_id]
    received_at = pick_received_at(rng, sctx.now, datetime(2000, 1, 1))
    tone = phrasing.tone or rng.choices(text.TONES, weights=text.TONE_WEIGHTS)[0]
    typo_roll = rng.random() < 0.3
    body = text.compose(rng, phrasing.text, customer[1].split()[0], tone,
                        typo=typo_roll and phrasing.adversarial_type is None)
    subject = rng.choice(subjects)
    label = labels.new_label(
        scenario_id=scenario_id, category=category, attributes=priority.make_attributes(**flags),
        expected_actions=actions, required_kb_ids=kb_ids, referenced_order_id=None,
        order_identifiable=False, expected_escalate=escalate_reason is not None,
        escalation_reason=escalate_reason, expected_facts=facts, difficulty=phrasing.difficulty,
        adversarial_type=phrasing.adversarial_type, ambiguity_flag=phrasing.ambiguity)
    return GeneratedTicket(scenario_id, OrderRows(), customer[2], subject, body, received_at, label)