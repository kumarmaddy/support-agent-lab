"""Scenario family: order status and delivery timing (S01, S02, S03, S04, S22).

Design reference: docs/design/data-design.md section 7.
"""
import random
from datetime import datetime

from src.datagen.domain import labels, priority
from src.datagen.generation import text
from src.datagen.generation.orders import OrderSpec, build_order, plan_timeline
from src.datagen.scenarios.base import (
    GeneratedTicket,
    Phrasing,
    ScenarioContext,
    ScenarioDef,
    build_single_order_ticket,
    choose_customer,
    latest_event,
    note_open_orders,
    pick,
    pick_received_at,
    processing_facts,
    shipped_facts,
)

STATUS_SUBJECTS = [
    "Where is my order {order_id}?",
    "Order {order_id} status",
    "Tracking update for {order_id}",
    "Delivery question",
    "Checking on my order",
]


# ------------------------------------------------------------------ S01 in transit, within promise
_S01 = [
    Phrasing("I placed order {order_id} on {placed_date} for the {product}. The tracking page says it's "
             "in transit but doesn't give a delivery date. When should I expect it?"),
    Phrasing("Could you tell me where order {order_id} is right now? It's the {product} I ordered on "
             "{placed_date}."),
    Phrasing("Checking on order {order_id}. It shipped a few days ago and I haven't seen any update. "
             "What's the expected delivery date?"),
    Phrasing("Order {order_id} (the {product}) should be on its way. Can you confirm it has shipped and "
             "when it will get here?"),
    Phrasing("Order {order_id}: what's the status? I'd like to know when it will arrive."),
    Phrasing("I'm tracking order {order_id} and the last update was a couple of days ago. Is the "
             "delivery going as planned?"),
]


def build_s01(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_single_order_ticket(
        sctx, rng, scenario_id="S01", spec=OrderSpec(state="in_transit"),
        phrasing=pick(sctx, "S01", _S01, i),
        subjects=STATUS_SUBJECTS, category="order_status", flags={}, actions=["provide_info"],
        kb_ids=["KB-SHP-01"], facts_fn=shipped_facts)


# ------------------------------------------------------------------ S02 late past promised date
_S02 = [
    Phrasing("Order {order_id} was supposed to arrive by {promised_date} and it still hasn't. What is "
             "going on?"),
    Phrasing("Order {order_id} ({product}) is late. The delivery estimate was {promised_date}. "
             "Can you tell me where it is?"),
    Phrasing("It's past the delivery date you gave me for order {order_id}, and tracking hasn't moved "
             "much. Please look into it."),
    Phrasing("Order {order_id} still shows in transit even though it was due on {promised_date}. Is "
             "something wrong with the shipment?"),
    Phrasing("I ordered the {product} on {placed_date} (order {order_id}) and the promised delivery "
             "date has passed. When will it actually arrive?"),
]


def build_s02(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_single_order_ticket(
        sctx, rng, scenario_id="S02", spec=OrderSpec(state="in_transit_late"),
        phrasing=pick(sctx, "S02", _S02, i), subjects=STATUS_SUBJECTS, category="order_status",
        flags={"order_late_past_promise": True}, actions=["provide_info"], kb_ids=["KB-SHP-02"],
        facts_fn=shipped_facts)


# ------------------------------------------------------------------ S03 not yet dispatched
# Each of the five phrasings covers a distinct case, including rubric edge cases:
# a deadline that is too far away, vague urgency, and anger without a qualifying trigger.
_S03 = [
    Phrasing("I placed order {order_id} on {placed_date} but haven't received a shipping confirmation. "
             "Has it been dispatched?"),
    Phrasing("Can you tell me if order {order_id} has shipped yet? I only got the order confirmation."),
    Phrasing("I'd like the {product} before my trip on {deadline_date}. Order {order_id} hasn't shipped "
             "yet. Can you tell me when it will go out?",
             difficulty="edge", deadline_days=(6, 9)),               # deadline too far: no trigger
    Phrasing("Please ship order {order_id} as soon as possible, I need it soon.",
             difficulty="edge", ambiguity=True),                     # vague urgency: no trigger
    Phrasing("Order {order_id} still hasn't shipped and I'm annoyed. When is it going out?",
             tone="frustrated", difficulty="edge"),                  # anger alone: no trigger
]


def build_s03(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_single_order_ticket(
        sctx, rng, scenario_id="S03", spec=OrderSpec(state="processing"),
        phrasing=pick(sctx, "S03", _S03, i), subjects=STATUS_SUBJECTS, category="order_status", flags={},
        actions=["provide_info"], kb_ids=["KB-ORD-01"], facts_fn=processing_facts)


# ------------------------------------------------------------------ S04 order number missing, several open orders
_S04 = [
    Phrasing("Where is my order? It's been a while and I haven't heard anything."),
    Phrasing("Can you check on my package please? I can't find the order number."),
    Phrasing("I ordered something and want to know when it arrives. I don't have the order number handy."),
    Phrasing("Any update on my order?"),
    Phrasing("Just checking in on my order."),
    Phrasing("Please tell me the delivery status of my order."),
]
_S04_STATE_PAIRS = [("in_transit", "processing"), ("in_transit", "in_transit"), ("processing", "processing")]


def build_s04(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    """The customer has two open orders and does not say which one: the agent must ask."""
    phrasing = pick(sctx, "S04", _S04, i)
    states = rng.choice(_S04_STATE_PAIRS)
    specs = [OrderSpec(state=s) for s in states]
    timelines = [plan_timeline(s, rng) for s in specs]

    customer_id = choose_customer(sctx, rng, min(t.placed_at for t in timelines), require_no_open=True)
    sctx.reserved_customer_ids.add(customer_id)        # keep exactly two open orders for this customer
    rows = None
    for spec, tl in zip(specs, timelines):
        spec.customer_id = customer_id
        built = build_order(sctx.order_ctx, spec, tl, rng)
        if rows is None:
            rows = built
        else:
            rows.extend(built)
    note_open_orders(sctx, rows)

    customer = sctx.customers[customer_id]
    received_at = pick_received_at(rng, sctx.now, latest_event(*timelines))
    tone = phrasing.tone or rng.choices(text.TONES, weights=text.TONE_WEIGHTS)[0]
    body = text.compose(rng, phrasing.text, customer[1].split()[0], tone, typo=rng.random() < 0.3)
    subject = rng.choice(["Delivery question", "Checking on my order", "Order status", "Where is my package?"])

    order_ids = sorted(o[0] for o in rows.orders)
    label = labels.new_label(
        scenario_id="S04", category="order_status", attributes=priority.make_attributes(),
        expected_actions=["request_info"], required_kb_ids=["KB-ORD-02"],
        referenced_order_id=None, order_identifiable=False,
        expected_facts={"open_order_count": 2, "candidate_order_ids": order_ids},
        difficulty="edge")
    return GeneratedTicket("S04", rows, customer[2], subject, body, received_at, label)


# ------------------------------------------------------------------ S22 hard deadline within 3 days
_S22 = [
    Phrasing("I need order {order_id} ({product}) by {deadline_weekday} {deadline_date} for an event. "
             "It hasn't shipped yet. Can you expedite it?", deadline_days=(1, 3), difficulty="edge"),
    Phrasing("The {product} in order {order_id} {be} a gift for {deadline_weekday}. It still shows as "
             "processing. Is there any way to get it here in time?", deadline_days=(1, 3), difficulty="edge"),
    Phrasing("Urgent: order {order_id} must arrive before {deadline_date}. The status still says "
             "processing.", deadline_days=(1, 3), difficulty="edge"),
    Phrasing("I'm travelling on {deadline_weekday} and need the {product} before then. Order "
             "{order_id} hasn't been dispatched. What can you do?", deadline_days=(1, 3), difficulty="edge"),
]


def build_s22(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_single_order_ticket(
        sctx, rng, scenario_id="S22", spec=OrderSpec(state="processing"),
        phrasing=pick(sctx, "S22", _S22, i), subjects=STATUS_SUBJECTS, category="order_status",
        flags={"deadline_within_3_days": True}, actions=["escalate_human"], kb_ids=["KB-SHP-03"],
        facts_fn=processing_facts, escalate_reason="delivery_deadline_cannot_be_guaranteed")


SCENARIOS = [
    ScenarioDef("S01", "Order in transit, within promise", 10, build_s01),
    ScenarioDef("S02", "Order late past promised date", 8, build_s02),
    ScenarioDef("S03", "Order not yet dispatched", 5, build_s03),
    ScenarioDef("S04", "Order number missing; several open orders", 6, build_s04),
    ScenarioDef("S22", "Hard deadline within 3 days", 4, build_s22),
]