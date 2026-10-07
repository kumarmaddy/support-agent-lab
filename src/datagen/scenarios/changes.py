"""Scenario family: cancellations and address changes (S13-S16).

Policy (docs/design/data-design.md section 3): cancellation and address changes are possible only before
dispatch. Before dispatch the correct action is a proposal; after dispatch it is a policy decline.
"""
import random

from src.datagen.domain import reference
from src.datagen.generation.orders import OrderSpec
from src.datagen.scenarios.base import (
    GeneratedTicket,
    Phrasing,
    ScenarioContext,
    ScenarioDef,
    build_single_order_ticket,
    processing_facts,
    shipped_facts,
)

CANCEL_SUBJECTS = ["Cancel order {order_id}", "Cancellation request", "Please cancel my order",
                   "Order {order_id} cancellation"]
ADDRESS_SUBJECTS = ["Change delivery address for {order_id}", "Wrong address on my order",
                    "Address update", "Order {order_id} shipping address"]


# ------------------------------------------------------------------ S13 cancel before dispatch
_S13 = [
    Phrasing("Please cancel order {order_id}. I ordered the {product} by mistake."),
    Phrasing("I'd like to cancel order {order_id} ({product}) before it ships."),
    Phrasing("Can you cancel my order {order_id}? I found a better price elsewhere."),
    Phrasing("I placed order {order_id} on {placed_date} and need to cancel it. Please confirm it "
             "hasn't been dispatched yet."),
    Phrasing("Cancel order {order_id}, please. I no longer need the {product}."),
    Phrasing("I ordered the wrong thing in order {order_id}. Please cancel it so I can reorder."),
    Phrasing("Order {order_id}: I want to cancel this. How do I do that?"),
]


def _s13_facts(rows, deadline, fields):
    return {**processing_facts(rows, deadline, fields), "cancellation_allowed": True}


def build_s13(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    return build_single_order_ticket(
        sctx, rng, scenario_id="S13", spec=OrderSpec(state="processing"), phrasing=_S13[i % len(_S13)],
        subjects=CANCEL_SUBJECTS, category="cancellation", flags={}, actions=["propose_cancellation"],
        kb_ids=["KB-CAN-01"], facts_fn=_s13_facts)


# ------------------------------------------------------------------ S14 cancel after dispatch
# (phrasing, order state, priority flags). One ticket is also late, which raises priority to MEDIUM.
_S14 = [
    (Phrasing("Please cancel order {order_id}. I changed my mind.", difficulty="edge"), "in_transit", {}),
    (Phrasing("Can I still cancel order {order_id}? I just saw that it has shipped.", difficulty="edge"),
     "in_transit", {}),
    (Phrasing("I need to cancel order {order_id} ({product}) right away, I ordered by mistake.",
              difficulty="edge"), "in_transit", {}),
    (Phrasing("Cancel order {order_id} and refund me. I don't want it any more.", difficulty="edge"),
     "in_transit", {}),
    (Phrasing("I'd like to cancel order {order_id}. Delivery is taking too long and I'd rather not wait.",
              difficulty="edge"), "in_transit_late", {"order_late_past_promise": True}),
    (Phrasing("Stop order {order_id} please, I don't want it any more.", difficulty="edge"),
     "in_transit", {}),
]


def build_s14(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    phrasing, state, flags = _S14[i % len(_S14)]

    def facts(rows, deadline, fields):
        return {**shipped_facts(rows, deadline, fields), "cancellation_allowed": False}

    late = state == "in_transit_late"
    return build_single_order_ticket(
        sctx, rng, scenario_id="S14", spec=OrderSpec(state=state), phrasing=phrasing,
        subjects=CANCEL_SUBJECTS, category="cancellation", flags=flags, actions=["decline_policy"],
        kb_ids=["KB-CAN-01", "KB-SHP-02"] if late else ["KB-CAN-01"], facts_fn=facts)


# ------------------------------------------------------------------ address changes
def _new_address_fields(rows, rng, received_at):
    line1 = (f"{rng.randint(10, 9899)} {rng.choice(reference.STREET_NAMES)} "
             f"{rng.choice(reference.STREET_TYPES)}")
    city, postal = rng.choice(reference.CITIES), f"{rng.randint(0, 99999):05d}"
    return {"new_address": f"{line1}, {city} {postal}"}


_S15 = [
    Phrasing("I've just moved. Can you change the delivery address on order {order_id} to {new_address}?"),
    Phrasing("Please update the shipping address for order {order_id}. It should go to {new_address}."),
    Phrasing("I entered the wrong address on order {order_id}. The right one is {new_address}. Can you fix it?"),
    Phrasing("Can you redirect order {order_id} to {new_address}? I won't be at the old address."),
    Phrasing("Order {order_id} hasn't shipped yet, so can you send it to {new_address} instead?"),
    Phrasing("I'd like order {order_id} delivered to my work address: {new_address}."),
]
_S16 = [
    Phrasing("I moved last week. Can you change the delivery address for order {order_id} to {new_address}?",
             difficulty="edge"),
    Phrasing("Please update the shipping address on order {order_id}. It should go to {new_address}.",
             difficulty="edge"),
    Phrasing("I entered the wrong address on order {order_id}. The right one is {new_address}. Can you "
             "fix it?", difficulty="edge"),
    Phrasing("Can you redirect order {order_id} to {new_address}? I won't be home at the old address.",
             difficulty="edge"),
]


def build_s15(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    def facts(rows, deadline, fields):
        return {**processing_facts(rows, deadline, fields), "address_change_allowed": True,
                "requested_address": fields["new_address"]}

    return build_single_order_ticket(
        sctx, rng, scenario_id="S15", spec=OrderSpec(state="processing"), phrasing=_S15[i % len(_S15)],
        subjects=ADDRESS_SUBJECTS, category="address_change", flags={},
        actions=["propose_address_change"], kb_ids=["KB-ADR-01"], facts_fn=facts,
        extra_fields_fn=_new_address_fields)


def build_s16(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    def facts(rows, deadline, fields):
        return {**shipped_facts(rows, deadline, fields), "address_change_allowed": False,
                "requested_address": fields["new_address"]}

    return build_single_order_ticket(
        sctx, rng, scenario_id="S16", spec=OrderSpec(state="in_transit"), phrasing=_S16[i % len(_S16)],
        subjects=ADDRESS_SUBJECTS, category="address_change", flags={}, actions=["decline_policy"],
        kb_ids=["KB-ADR-01"], facts_fn=facts, extra_fields_fn=_new_address_fields)


SCENARIOS = [
    ScenarioDef("S13", "Cancel before dispatch", 7, build_s13),
    ScenarioDef("S14", "Cancel after dispatch", 6, build_s14),
    ScenarioDef("S15", "Address change before dispatch", 6, build_s15),
    ScenarioDef("S16", "Address change after dispatch", 4, build_s16),
]