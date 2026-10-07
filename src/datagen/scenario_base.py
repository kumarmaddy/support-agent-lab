"""Shared machinery for scenario families (stage 0.4c).

A scenario family module defines ScenarioDef entries. Each entry builds ONE ticket (plus the
order(s) it refers to) per call, using the same order builder as the background pool.
"""
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

from . import config, labels, priority, text
from .orders import OrderContext, OrderRows, OrderSpec, build_order, plan_timeline

OPEN_STATUSES = ("processing", "shipped")


@dataclass(frozen=True)
class Phrasing:
    """One way a customer might phrase a request, with the facts it implies."""
    text: str
    tone: str | None = None                       # force a tone; None = random
    difficulty: str = "standard"
    ambiguity: bool = False                       # vague urgency such as "as soon as possible"
    deadline_days: tuple[int, int] | None = None  # stated deadline, days after the ticket arrives


@dataclass
class ScenarioContext:
    order_ctx: OrderContext
    product_names: dict[str, str]
    customers: dict[str, tuple]
    open_customer_ids: set[str]       # customers with at least one open (processing/shipped) order
    reserved_customer_ids: set[str]   # customers whose open-order count must not change later
    now: datetime = config.AS_OF_DATETIME


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
    return max(t for tl in timelines for t in (tl.placed_at, tl.dispatched_at) if t)


def build_single_order_ticket(sctx: ScenarioContext, rng: random.Random, *, scenario_id: str,
                              spec: OrderSpec, phrasing: Phrasing, subjects: list[str],
                              category: str, flags: dict[str, bool], actions: list[str],
                              kb_ids: list[str], facts_fn, escalate_reason: str | None = None
                              ) -> GeneratedTicket:
    """Build one order and one ticket about it, with its ground-truth label."""
    tl = plan_timeline(spec, rng)
    spec.customer_id = choose_customer(sctx, rng, tl.placed_at)
    rows = build_order(sctx.order_ctx, spec, tl, rng)
    note_open_orders(sctx, rows)

    order = rows.orders[0]
    customer = sctx.customers[order[1]]
    received_at = pick_received_at(rng, sctx.now, latest_event(tl))

    fields = {
        "order_id": order[0],
        "product": sctx.product_names[rows.order_items[0][2]],
        "placed_date": text.fmt_date(datetime.fromisoformat(order[2]).date(), rng),
        "promised_date": text.fmt_date(date.fromisoformat(order[5]), rng),
    }
    deadline = None
    if phrasing.deadline_days:
        lo, hi = phrasing.deadline_days
        deadline = received_at.date() + timedelta(days=rng.randint(lo, hi))
        fields["deadline_date"] = text.fmt_date(deadline, rng)
        fields["deadline_weekday"] = text.weekday_name(deadline)

    tone = phrasing.tone or rng.choices(text.TONES, weights=text.TONE_WEIGHTS)[0]
    body = text.compose(rng, phrasing.text.format(**fields), customer[1].split()[0], tone,
                        typo=rng.random() < 0.3)
    subject = rng.choice(subjects).format(**fields)

    label = labels.new_label(
        scenario_id=scenario_id, category=category,
        attributes=priority.make_attributes(**flags),
        expected_actions=actions, required_kb_ids=kb_ids, referenced_order_id=order[0],
        expected_escalate=escalate_reason is not None, escalation_reason=escalate_reason,
        expected_facts=facts_fn(rows, deadline),
        difficulty=phrasing.difficulty, ambiguity_flag=phrasing.ambiguity)
    return GeneratedTicket(scenario_id, rows, customer[2], subject, body, received_at, label)