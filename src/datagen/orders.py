"""Order histories (stage 0.4b).

Two steps keep the logic testable:
  1. plan_timeline(): decides every date for an order from its requested lifecycle state.
  2. build_order():   turns a spec plus timeline into rows for all related tables.

Scenario builders (stage 0.4c) call the same functions with forced specs, so scenario orders and
background orders follow identical consistency rules.

Simplifications (documented in docs/data-design.md): calendar days (no business-day calendar),
full-order refunds and returns, no tax or shipping charges, cancellations only before dispatch,
duplicate charges only on orders that are not cancelled or returned.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import random

from . import config, reference
from .base_data import make_rng

STATES = tuple(config.ORDER_STATE_WEIGHTS)
RETURN_STATES = {"return_in_progress", "returned_refund_pending", "returned_refunded"}
DUPLICATE_ELIGIBLE = {"processing", "in_transit", "in_transit_late", "delivered"}

_ORDER_STATUS = {
    "processing": "processing",
    "in_transit": "shipped",
    "in_transit_late": "shipped",
    "delivered": "delivered",
    "return_in_progress": "delivered",
    "returned_refund_pending": "returned",
    "returned_refunded": "returned",
    "cancelled": "cancelled",
}


def ts(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") if dt else None


@dataclass
class OrderSpec:
    state: str
    days_since_delivery: int | None = None   # only for delivered / return_in_progress
    duplicate_charge: bool = False
    include_final_sale_item: bool = False
    n_items: int | None = None
    customer_id: str | None = None


@dataclass
class Timeline:
    placed_at: datetime
    promised_date: date
    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None
    label_issued_at: datetime | None = None
    received_at: datetime | None = None


class IdAllocator:
    FORMATS = {"order": ("O-", 6), "item": ("OI-", 6), "shipment": ("SH-", 6),
               "payment": ("PM-", 6), "refund": ("RF-", 6), "return": ("RT-", 6)}

    def __init__(self) -> None:
        self._n = {k: 0 for k in self.FORMATS}

    def next(self, kind: str) -> str:
        self._n[kind] += 1
        prefix, width = self.FORMATS[kind]
        return f"{prefix}{self._n[kind]:0{width}d}"

    @classmethod
    def continuing_from(cls, conn) -> "IdAllocator":
        """Start numbering after the highest id already stored, so scenario orders never collide
        with the background order pool."""
        tables = {"order": ("orders", "order_id"), "item": ("order_items", "order_item_id"),
                  "shipment": ("shipments", "shipment_id"), "payment": ("payments", "payment_id"),
                  "refund": ("refunds", "refund_id"), "return": ("returns", "return_id")}
        allocator = cls()
        for kind, (table, column) in tables.items():
            highest = conn.execute(f"SELECT MAX({column}) FROM {table}").fetchone()[0]
            if highest:
                allocator._n[kind] = int(highest.rsplit("-", 1)[1])
        return allocator


@dataclass
class OrderContext:
    customers: list[tuple]
    addresses_by_customer: dict[str, list[str]]
    products: list[tuple]
    ids: IdAllocator = field(default_factory=IdAllocator)


@dataclass
class OrderRows:
    orders: list[tuple] = field(default_factory=list)
    order_items: list[tuple] = field(default_factory=list)
    shipments: list[tuple] = field(default_factory=list)
    payments: list[tuple] = field(default_factory=list)
    refunds: list[tuple] = field(default_factory=list)
    returns: list[tuple] = field(default_factory=list)

    def extend(self, other: "OrderRows") -> None:
        for name in ("orders", "order_items", "shipments", "payments", "refunds", "returns"):
            getattr(self, name).extend(getattr(other, name))


# ----------------------------------------------------------------------------- timelines
def _dt(rng: random.Random, d: date) -> datetime:
    """Random working-hours time on date d, never later than the reference time."""
    hour = rng.randint(8, 11) if d == config.AS_OF_DATE else rng.randint(8, 19)
    return datetime(d.year, d.month, d.day, hour, rng.randint(0, 59), rng.randint(0, 59))


def _sample_days_since_delivery(rng: random.Random) -> int:
    r = rng.random()
    if r < 0.25:
        return rng.randint(0, 14)
    if r < 0.45:
        return rng.randint(15, 28)
    if r < 0.50:
        return rng.randint(29, 32)      # return-window boundary cases
    return rng.randint(33, 180)


def plan_timeline(spec: OrderSpec, rng: random.Random) -> Timeline:
    if spec.state not in STATES:
        raise ValueError(f"unknown order state: {spec.state}")
    now, today = config.AS_OF_DATETIME, config.AS_OF_DATE
    promise = timedelta(days=config.PROMISE_DAYS)
    lag = rng.randint(1, 2)          # days from order to dispatch
    transit = rng.randint(3, 7)      # days from dispatch to delivery
    s = spec.state

    if s == "processing":
        placed = now - timedelta(hours=rng.randint(2, 40), minutes=rng.randint(0, 59),
                                 seconds=rng.randint(0, 59))
        return Timeline(placed, placed.date() + promise)

    if s == "cancelled":
        placed_d = today - timedelta(days=rng.randint(3, 120))
        return Timeline(_dt(rng, placed_d), placed_d + promise)

    if s in ("in_transit", "in_transit_late"):
        days_ago = rng.randint(3, 8) if s == "in_transit" else rng.randint(12, 25)
        placed_d = today - timedelta(days=days_ago)
        return Timeline(_dt(rng, placed_d), placed_d + promise,
                        dispatched_at=_dt(rng, placed_d + timedelta(days=lag)))

    # delivered family
    received_days_ago = None
    if s == "delivered":
        d = spec.days_since_delivery if spec.days_since_delivery is not None \
            else _sample_days_since_delivery(rng)
    elif s == "return_in_progress":
        d = spec.days_since_delivery if spec.days_since_delivery is not None else rng.randint(3, 25)
        if d < 1:
            raise ValueError("return_in_progress needs days_since_delivery >= 1")
    elif s == "returned_refund_pending":
        received_days_ago = rng.randint(1, 6)
        d = received_days_ago + rng.randint(5, 20)
    else:  # returned_refunded
        received_days_ago = rng.randint(8, 40)
        d = received_days_ago + rng.randint(5, 20)
    if not 0 <= d <= 365:
        raise ValueError("days_since_delivery out of range")

    delivered_d = today - timedelta(days=d)
    dispatched_d = delivered_d - timedelta(days=transit)
    placed_d = dispatched_d - timedelta(days=lag)
    tl = Timeline(_dt(rng, placed_d), placed_d + promise,
                  dispatched_at=_dt(rng, dispatched_d), delivered_at=_dt(rng, delivered_d))
    if s == "return_in_progress":
        tl.label_issued_at = _dt(rng, delivered_d + timedelta(days=rng.randint(1, d)))
    elif received_days_ago is not None:
        tl.label_issued_at = _dt(rng, delivered_d + timedelta(days=rng.randint(1, 3)))
        tl.received_at = _dt(rng, today - timedelta(days=received_days_ago))
    return tl


# ----------------------------------------------------------------------------- rows
def _pick_customer(ctx: OrderContext, spec: OrderSpec, tl: Timeline, rng: random.Random) -> tuple:
    placed_day = tl.placed_at.date().isoformat()
    eligible = [c for c in ctx.customers if c[4] <= placed_day]      # created_at on or before order
    if spec.customer_id:
        match = [c for c in eligible if c[0] == spec.customer_id]
        if not match:
            raise ValueError(f"customer {spec.customer_id} not eligible for an order placed {placed_day}")
        return match[0]
    if not eligible:
        raise ValueError(f"no customer existed on {placed_day}")
    return rng.choice(eligible)


def _pick_items(ctx: OrderContext, spec: OrderSpec, rng: random.Random) -> list[tuple]:
    no_final_sale = spec.state in RETURN_STATES
    pool = [p for p in ctx.products if not (no_final_sale and p[4] == 1)]
    n = spec.n_items or rng.choices([1, 2, 3], weights=[0.6, 0.3, 0.1])[0]
    chosen: list[tuple] = []
    if spec.include_final_sale_item:
        first = rng.choice([p for p in ctx.products if p[4] == 1])
        chosen.append(first)
        pool = [p for p in pool if p[0] != first[0]]
    chosen += rng.sample(pool, n - len(chosen))
    return chosen


def build_order(ctx: OrderContext, spec: OrderSpec, tl: Timeline, rng: random.Random) -> OrderRows:
    if spec.duplicate_charge and spec.state not in DUPLICATE_ELIGIBLE:
        raise ValueError(f"duplicate charge not supported for state {spec.state}")
    if spec.include_final_sale_item and spec.state in RETURN_STATES:
        raise ValueError("final-sale items cannot appear in orders that have returns")

    ids = ctx.ids
    rows = OrderRows()
    customer = _pick_customer(ctx, spec, tl, rng)
    customer_id = customer[0]
    address_id = rng.choice(ctx.addresses_by_customer[customer_id])
    order_id = ids.next("order")

    total = 0
    for product in _pick_items(ctx, spec, rng):
        quantity = rng.choices([1, 2], weights=[0.85, 0.15])[0]
        sizes = reference.SIZES[reference.CATEGORY_SIZING[product[2]]]
        size = rng.choice(sizes) if sizes else None
        rows.order_items.append((ids.next("item"), order_id, product[0], size, quantity, product[3]))
        total += quantity * product[3]

    rows.orders.append((order_id, customer_id, ts(tl.placed_at), _ORDER_STATUS[spec.state], total,
                        tl.promised_date.isoformat(), address_id))

    if tl.dispatched_at:
        carrier = rng.choice(reference.CARRIERS)
        tracking = f"{carrier[:2].upper()}{rng.randint(10**11, 10**12 - 1)}"
        last_status = {"in_transit": "In transit", "in_transit_late": "In transit - delayed"}.get(
            spec.state, "Delivered")
        rows.shipments.append((ids.next("shipment"), order_id, carrier, tracking,
                               ts(tl.dispatched_at), ts(tl.delivered_at), last_status))

    refunded = spec.state in ("cancelled", "returned_refunded")
    payment_id = ids.next("payment")
    last4 = f"{rng.randint(0, 9999):04d}"
    paid_at = tl.placed_at + timedelta(seconds=rng.randint(5, 120))
    rows.payments.append((payment_id, order_id, total, last4,
                          "refunded" if refunded else "captured", ts(paid_at)))
    if spec.duplicate_charge:
        dup_at = paid_at + timedelta(minutes=rng.randint(1, 5))
        rows.payments.append((ids.next("payment"), order_id, total, last4, "duplicate_flagged", ts(dup_at)))

    if spec.state == "cancelled":
        rows.refunds.append((ids.next("refund"), payment_id, total, "processed",
                             ts(tl.placed_at + timedelta(hours=rng.randint(1, 20)))))
    if spec.state in RETURN_STATES:
        received = tl.received_at is not None
        rows.returns.append((ids.next("return"), order_id, "received" if received else "label_issued",
                             ts(tl.label_issued_at), ts(tl.received_at)))
        if received:
            rows.refunds.append((ids.next("refund"), payment_id, total,
                                 "processed" if refunded else "pending", ts(tl.received_at)))
    return rows


def generate_order_pool(seed: int, customers: list[tuple], addresses: list[tuple],
                        products: list[tuple], n: int = config.N_ORDERS) -> OrderRows:
    rng = make_rng(seed, "orders")
    by_customer: dict[str, list[str]] = {}
    for address_id, customer_id, *_ in addresses:
        by_customer.setdefault(customer_id, []).append(address_id)
    ctx = OrderContext(customers, by_customer, products)

    states = list(config.ORDER_STATE_WEIGHTS)
    weights = [config.ORDER_STATE_WEIGHTS[s] for s in states]
    plans = []
    for _ in range(n):
        state = rng.choices(states, weights=weights)[0]
        dup = state in DUPLICATE_ELIGIBLE and rng.random() < config.P_DUPLICATE_CHARGE
        spec = OrderSpec(state=state, duplicate_charge=dup)
        plans.append((spec, plan_timeline(spec, rng)))
    plans.sort(key=lambda p: p[1].placed_at)          # ids ascend with order date

    pool = OrderRows()
    for spec, tl in plans:
        pool.extend(build_order(ctx, spec, tl, rng))
    return pool