"""Scenario family: returns, exchanges and refunds (S05-S11, S21, S23).

Design reference: docs/data-design.md section 7. Whether a return is accepted is decided by
policy.within_return_window, not by hard-coded expectations, so labels always follow the policy.
"""
import random

from . import policy, reference, text
from .orders import OrderSpec
from .scenario_base import (GeneratedTicket, Phrasing, ScenarioContext, ScenarioDef,
                            build_single_order_ticket, delivered_at, delivered_date_field,
                            duplicate_facts, duplicate_fields, shipped_facts, window_facts)

RETURN_SUBJECTS = ["Return request for {order_id}", "Return question", "How do I return an item?",
                   "Order {order_id} return"]
EXCHANGE_SUBJECTS = ["Exchange request for {order_id}", "Size exchange", "Can I swap sizes?",
                     "Order {order_id} exchange"]
DAMAGE_SUBJECTS = ["Problem with my order {order_id}", "Issue with my delivery", "Order {order_id} problem"]
REFUND_SUBJECTS = ["Refund for order {order_id}", "Refund question", "Problem with my order {order_id}",
                   "Question about my payment"]


# ------------------------------------------------------------------ S05 return within the window
_S05 = [
    Phrasing("The {product} from order {order_id} {doesnt} fit the way I hoped. How do I return {them}?"),
    Phrasing("I'd like to return the {product} from order {order_id}. It wasn't what I expected."),
    Phrasing("Changed my mind about the {product} in order {order_id}. Can I send it back?"),
    Phrasing("Please send me a return label for order {order_id}. I want to return the {product}."),
    Phrasing("I'd like to return order {order_id}, the {product} {be} not for me."),
    Phrasing("How do I return the {product} from order {order_id}?"),
]
_S05_BOUNDARY = [   # delivery date stated, so the boundary is visible to the agent
    Phrasing("Can I still return the {product} from order {order_id}? It was delivered on {delivered_date}.",
             difficulty="edge"),
    Phrasing("I'd like to return order {order_id}. It arrived on {delivered_date}, is that still okay?",
             difficulty="edge"),
]
_S05_DAYS = [2, 4, 6, 8, 11, 14, 18, 23, 29, 30]      # 29 and 30 are inside the window (30 inclusive)


def build_s05(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    days = _S05_DAYS[i % len(_S05_DAYS)]
    phrasing = _S05_BOUNDARY[i % 2] if days >= 29 else _S05[i % len(_S05)]

    def facts(rows, deadline, fields):
        assert policy.within_return_window(delivered_at(rows)), "S05 orders must be inside the window"
        return window_facts(rows, deadline, fields)

    return build_single_order_ticket(
        sctx, rng, scenario_id="S05",
        spec=OrderSpec(state="delivered", days_since_delivery=days, exclude_final_sale=True),
        phrasing=phrasing, subjects=RETURN_SUBJECTS, category="return_exchange", flags={},
        actions=["propose_return_label"], kb_ids=["KB-RET-01", "KB-RET-02"], facts_fn=facts,
        extra_fields_fn=delivered_date_field)


# ------------------------------------------------------------------ S06 return outside the window
_S06 = [
    Phrasing("I'd like to return the {product} from order {order_id}. It was delivered on {delivered_date}.",
             difficulty="edge"),
    Phrasing("Can I still return order {order_id}? It arrived {delivered_date} and I only just tried it.",
             difficulty="edge"),
    Phrasing("Please arrange a return for the {product} in order {order_id}. {It} {doesnt} suit me.",
             difficulty="edge"),
    Phrasing("I'm sorry for the delay, but I'd like to return order {order_id} (delivered {delivered_date}).",
             difficulty="edge"),
]
_S06_DAYS = [31, 31, 32, 33, 38, 45]                  # day 31 is the first day outside the window


def build_s06(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    def facts(rows, deadline, fields):
        assert not policy.within_return_window(delivered_at(rows)), "S06 orders must be outside the window"
        return window_facts(rows, deadline, fields)

    return build_single_order_ticket(
        sctx, rng, scenario_id="S06",
        spec=OrderSpec(state="delivered", days_since_delivery=_S06_DAYS[i % len(_S06_DAYS)],
                       exclude_final_sale=True),
        phrasing=_S06[i % len(_S06)], subjects=RETURN_SUBJECTS, category="return_exchange", flags={},
        actions=["decline_policy"], kb_ids=["KB-RET-01"], facts_fn=facts,
        extra_fields_fn=delivered_date_field)


# ------------------------------------------------------------------ S07 return of a final-sale item
_S07 = [
    Phrasing("I'd like to return the {product} from order {order_id}.", difficulty="edge"),
    Phrasing("Can I send back the {product} from order {order_id}? {It} {isnt} right for me.",
             difficulty="edge"),
    Phrasing("Please arrange a return for the {product} in order {order_id}.", difficulty="edge"),
    Phrasing("I need to return the {product} from order {order_id}, {it} {doesnt} do what I need.",
             difficulty="edge"),
    Phrasing("How do I return the {product} (order {order_id})?", difficulty="edge"),
]


def build_s07(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    def facts(rows, deadline, fields):
        facts = window_facts(rows, deadline, fields)
        assert facts["within_return_window"], "S07 must be inside the window; only final sale blocks it"
        facts["final_sale_product_id"] = rows.order_items[0][2]
        return facts

    return build_single_order_ticket(
        sctx, rng, scenario_id="S07",
        spec=OrderSpec(state="delivered", days_since_delivery=rng.randint(3, 25),
                       include_final_sale_item=True),
        phrasing=_S07[i % len(_S07)], subjects=RETURN_SUBJECTS, category="return_exchange", flags={},
        actions=["decline_policy"], kb_ids=["KB-RET-03"], facts_fn=facts)


# ------------------------------------------------------------------ S08 exchange for a different size
_S08 = [
    Phrasing("The {product} from order {order_id} {be} {fit_issue} in size {current_size}. Can I exchange "
             "{them} for size {new_size}?"),
    Phrasing("I'd like to swap the {product} in order {order_id} (size {current_size}) for size {new_size}. "
             "{It} {be} {fit_issue}."),
    Phrasing("Order {order_id}: I ordered the {product} in {current_size} but {it} {be} {fit_issue}. Can I get "
             "size {new_size} instead?"),
    Phrasing("Could I exchange order {order_id}? The {product} {be} {fit_issue}, I need size {new_size}."),
    Phrasing("Is it possible to exchange the {product} for a different size? Order {order_id}, currently "
             "{current_size}, I need {new_size}."),
    Phrasing("The size {current_size} {product} (order {order_id}) {be} {fit_issue}. Please exchange "
             "{them} for size {new_size}."),
]


def build_s08(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    categories = {p[0]: p[2] for p in sctx.order_ctx.products}

    def size_fields(rows, rng, received_at):
        item = rows.order_items[0]
        sizes = reference.SIZES[reference.CATEGORY_SIZING[categories[item[2]]]]
        idx = sizes.index(item[3])
        if idx == len(sizes) - 1:
            bigger = False
        elif idx == 0:
            bigger = True
        else:
            bigger = rng.random() < 0.5
        return {"current_size": item[3], "new_size": sizes[idx + 1 if bigger else idx - 1],
                "fit_issue": "too small" if bigger else "too big"}

    def facts(rows, deadline, fields):
        facts = window_facts(rows, deadline, fields)
        facts.update(current_size=fields["current_size"], requested_size=fields["new_size"])
        return facts

    return build_single_order_ticket(
        sctx, rng, scenario_id="S08",
        spec=OrderSpec(state="delivered", days_since_delivery=rng.randint(2, 25),
                       exclude_final_sale=True, require_sized_item=True),
        phrasing=_S08[i % len(_S08)], subjects=EXCHANGE_SUBJECTS, category="return_exchange", flags={},
        actions=["propose_exchange"], kb_ids=["KB-RET-04"], facts_fn=facts, extra_fields_fn=size_fields)


# ------------------------------------------------------------------ S09 duplicate charge
_S09 = [
    Phrasing("I was charged twice for order {order_id}. The second charge of {amount} should be refunded."),
    Phrasing("There are two identical charges of {amount} on my card ending {last4} for order {order_id}. "
             "Please refund the duplicate."),
    Phrasing("My bank statement shows order {order_id} billed twice. Can you reverse the extra {amount}?"),
    Phrasing("Order {order_id}: I see a duplicate payment of {amount}. I only placed one order, so please "
             "refund one of them."),
    Phrasing("I got charged two times for the {product} (order {order_id}). Please fix this and refund the "
             "extra charge."),
]


def build_s09(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    state = rng.choice(["processing", "in_transit", "delivered", "delivered"])
    spec = OrderSpec(state=state, duplicate_charge=True,
                     days_since_delivery=rng.randint(1, 120) if state == "delivered" else None)

    def facts(rows, deadline, fields):
        return {"order_status": rows.orders[0][3], "promised_date": rows.orders[0][5],
                **duplicate_facts(rows, fields)}

    return build_single_order_ticket(
        sctx, rng, scenario_id="S09", spec=spec, phrasing=_S09[i % len(_S09)],
        subjects=REFUND_SUBJECTS + ["Charged twice"], category="refund",
        flags={"duplicate_or_unauthorized_charge": True}, actions=["propose_refund"],
        kb_ids=["KB-REF-02"], facts_fn=facts, extra_fields_fn=duplicate_fields)


# ------------------------------------------------------------------ S10 refund status after a return
_S10 = [
    Phrasing("I returned the {product} from order {order_id} and I haven't seen my refund yet. Can you "
             "check the status?"),
    Phrasing("Has my refund for order {order_id} been processed? I sent the return back recently."),
    Phrasing("Following up on the return for order {order_id}. When will the refund reach my card?"),
    Phrasing("I sent back order {order_id} and was told I'd get a refund. What's the status?"),
]


def build_s10(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    pending = i < 4                                   # 4 pending, 2 already processed (harder)
    phrasing = _S10[i % len(_S10)]
    if not pending:
        phrasing = Phrasing(phrasing.text, difficulty="edge")

    def facts(rows, deadline, fields):
        ret, refund = rows.returns[0], rows.refunds[0]
        return {"order_status": rows.orders[0][3], "promised_date": rows.orders[0][5],
                "return_received_date": ret[4][:10], "refund_status": refund[3],
                "refund_amount_cents": refund[2], "refund_requested_date": refund[4][:10]}

    return build_single_order_ticket(
        sctx, rng, scenario_id="S10",
        spec=OrderSpec(state="returned_refund_pending" if pending else "returned_refunded"),
        phrasing=phrasing, subjects=REFUND_SUBJECTS, category="refund", flags={},
        actions=["provide_info"], kb_ids=["KB-REF-01"], facts_fn=facts)


# ------------------------------------------------------------------ S11 damaged or wrong item
_S11_REFUND = [
    Phrasing("The {product} from order {order_id} arrived damaged. I'd like a refund."),
    Phrasing("I received order {order_id} and the {product} {be} broken. Please refund me."),
    Phrasing("My {product} (order {order_id}) {was} damaged when the parcel arrived. I want my money back."),
    Phrasing("Order {order_id} contained the wrong item, not the {product} I ordered. Please refund it."),
]
_S11_REPLACE = [
    Phrasing("The {product} in order {order_id} arrived damaged. Could you send a replacement?"),
    Phrasing("I received the wrong item in order {order_id}; I ordered the {product}. Can you send the "
             "right one?"),
    Phrasing("Order {order_id}: the {product} {has} visible damage. I'd like a replacement rather than a "
             "refund."),
    Phrasing("My {product} from order {order_id} {was} damaged in transit. Please replace {them}."),
]


def build_s11(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    wants_refund = i % 2 == 0                         # boundary rule 2: money back vs replacement
    phrasing = (_S11_REFUND if wants_refund else _S11_REPLACE)[(i // 2) % 4]
    return build_single_order_ticket(
        sctx, rng, scenario_id="S11",
        spec=OrderSpec(state="delivered", days_since_delivery=rng.randint(1, 20), exclude_final_sale=True),
        phrasing=phrasing, subjects=DAMAGE_SUBJECTS, category="refund" if wants_refund else "return_exchange",
        flags={"item_damaged_or_wrong": True},
        actions=["propose_refund"] if wants_refund else ["propose_replacement"], kb_ids=["KB-REF-03"],
        facts_fn=window_facts)


# ------------------------------------------------------------------ S21 chargeback or legal threat
_S21 = [   # (phrasing, underlying issue)
    (Phrasing("Order {order_id} still hasn't arrived and I'm done waiting. If I don't get my money back "
              "I will file a chargeback with my bank."), "late"),
    (Phrasing("This is unacceptable. Order {order_id} is long overdue. I'm contacting my lawyer about "
              "this unless it is refunded."), "late"),
    (Phrasing("I returned order {order_id} and still have no refund. I'm going to dispute the charge "
              "with my credit card company."), "refund_pending"),
    (Phrasing("Where is my refund for order {order_id}? If this isn't sorted out I will report your "
              "company to the consumer protection authority."), "refund_pending"),
]


def build_s21(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    phrasing, issue = _S21[i % len(_S21)]
    late = issue == "late"

    def facts(rows, deadline, fields):
        if late:
            return shipped_facts(rows, deadline, fields)
        refund = rows.refunds[0]
        return {"order_status": rows.orders[0][3], "promised_date": rows.orders[0][5],
                "refund_status": refund[3], "refund_amount_cents": refund[2]}

    flags = {"chargeback_or_legal_threat": True}
    if late:
        flags["order_late_past_promise"] = True
    return build_single_order_ticket(
        sctx, rng, scenario_id="S21",
        spec=OrderSpec(state="in_transit_late" if late else "returned_refund_pending"),
        phrasing=phrasing, subjects=REFUND_SUBJECTS, category="refund", flags=flags,
        actions=["escalate_human"], kb_ids=["KB-REF-04"], facts_fn=facts,
        escalate_reason="chargeback_or_legal_threat",
        secondary_categories=("order_status",) if late else ())


# ------------------------------------------------------------------ S23 late order and duplicate charge
_S23 = [
    Phrasing("Two problems with order {order_id}: it's late (it was due {promised_date}) and I was also "
             "charged twice, {amount} each time. Please refund the duplicate and tell me where the parcel is.",
             difficulty="edge"),
    Phrasing("Order {order_id} still hasn't arrived and my card shows two charges of {amount}. Can you "
             "sort out the double charge and find out what's happening with delivery?", difficulty="edge"),
    Phrasing("My {product} {be} overdue (order {order_id}, promised {promised_date}) and I see a duplicate "
             "payment of {amount}. Please help with both.", difficulty="edge"),
    Phrasing("I'm unhappy: order {order_id} is late and I've been billed twice. Please refund the extra "
             "{amount} and give me a delivery update.", difficulty="edge"),
]


def build_s23(sctx: ScenarioContext, rng: random.Random, i: int) -> GeneratedTicket:
    def facts(rows, deadline, fields):
        return {**shipped_facts(rows, deadline, fields), **duplicate_facts(rows, fields)}

    return build_single_order_ticket(
        sctx, rng, scenario_id="S23", spec=OrderSpec(state="in_transit_late", duplicate_charge=True),
        phrasing=_S23[i % len(_S23)], subjects=REFUND_SUBJECTS, category="refund",
        flags={"duplicate_or_unauthorized_charge": True, "order_late_past_promise": True},
        actions=["propose_refund", "provide_info"], kb_ids=["KB-REF-02", "KB-SHP-02"], facts_fn=facts,
        extra_fields_fn=duplicate_fields, secondary_categories=("order_status",))


SCENARIOS = [
    ScenarioDef("S05", "Return within the window", 10, build_s05),
    ScenarioDef("S06", "Return outside the window", 6, build_s06),
    ScenarioDef("S07", "Return of a final-sale item", 5, build_s07),
    ScenarioDef("S08", "Exchange for a different size", 6, build_s08),
    ScenarioDef("S09", "Duplicate charge", 8, build_s09),
    ScenarioDef("S10", "Refund status after a return", 6, build_s10),
    ScenarioDef("S11", "Damaged or wrong item", 8, build_s11),
    ScenarioDef("S21", "Chargeback or legal threat", 4, build_s21),
    ScenarioDef("S23", "Late order plus duplicate charge", 4, build_s23),
]