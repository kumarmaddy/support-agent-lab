"""Pipeline steps 3 and 4: identify the customer and order, then decide (phase-1-design.md, sections 2 and 3).

``identify`` uses the read-only tools. ``decide`` is a pure function: the same reading, identity and date always give the
same decision, and every branch is covered by a test. The model plays no part here; it never chooses an action.

"Today" is the day the ticket arrived, so a replay of the same ticket always gives the same answer.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.agent import tools
from src.agent.deadline import is_within_window, resolve_deadline
from src.agent.reading import Reading

# actions
PROVIDE_INFO, REQUEST_INFO, ESCALATE_HUMAN, ROUTE_TO_HUMAN = "provide_info", "request_info", "escalate_human", "route_to_human"

# identification outcomes
IDENTIFIED, NO_ACCOUNT, ORDER_NOT_FOUND, ORDER_NOT_OWNED = "identified", "no_account", "order_not_found", "order_not_owned"
NEEDS_ORDER_NUMBER, MULTIPLE_ORDER_IDS = "needs_order_number", "multiple_order_ids"


@dataclass(frozen=True)
class Identity:
    outcome: str
    customer: Optional[tools.Customer] = None
    order: Optional[tools.Order] = None
    open_orders: tuple = ()
    named_ids: tuple = ()


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    article: Optional[str]
    facts: dict = field(default_factory=dict)       # verified facts only; the reply may use nothing else


def requires_lookup(reading: Reading) -> bool:
    """Only order-status tickets without a legal threat need the customer and order (a legal threat is escalated in any category)."""
    return reading.category == "order_status" and not reading.mentions_chargeback_or_legal


def identify(box: tools.Toolbox, ticket: tools.Ticket, reading: Reading) -> Identity:
    found = box.find_customer(ticket.customer_email)
    if not found.ok:
        return Identity(NO_ACCOUNT)
    customer = found.data
    ids = reading.order_ids
    if len(ids) > 1:
        return Identity(MULTIPLE_ORDER_IDS, customer, named_ids=ids)
    if len(ids) == 1:
        got = box.get_order(ids[0], customer.customer_id)
        if got.ok:
            return Identity(IDENTIFIED, customer, order=got.data)
        return Identity(ORDER_NOT_OWNED if got.status == tools.NOT_OWNED else ORDER_NOT_FOUND, customer)
    open_orders = box.list_open_orders(customer.customer_id).data or ()
    if len(open_orders) == 1:
        got = box.get_order(open_orders[0].order_id, customer.customer_id)
        if got.ok:
            return Identity(IDENTIFIED, customer, order=got.data)
    return Identity(NEEDS_ORDER_NUMBER, customer, open_orders=tuple(open_orders))


def _day(stamp: Optional[str]) -> Optional[str]:
    return stamp[:10] if stamp else None


def decide(reading: Reading, identity: Optional[Identity], today: date) -> Decision:
    # 1. threat of chargeback or legal action: always escalated (KB-REF-04), whatever the category; no account details are read
    if reading.mentions_chargeback_or_legal:
        return Decision(ESCALATE_HUMAN, "chargeback_or_legal_threat", "KB-REF-04")
    # 2. out of slice
    if reading.category != "order_status":
        return Decision(ROUTE_TO_HUMAN, "out_of_slice", None)
    if identity is None:
        raise ValueError("an identity is required for an order-status ticket without a legal threat")
    # 3. who and which order
    if identity.outcome == NO_ACCOUNT:
        return Decision(REQUEST_INFO, "no_account", "KB-ORD-02")
    if identity.outcome == ORDER_NOT_OWNED:
        return Decision(ESCALATE_HUMAN, "order_not_owned", "KB-SEC-01")        # reveal nothing; a person follows up
    if identity.outcome == ORDER_NOT_FOUND:
        return Decision(REQUEST_INFO, "order_not_found", "KB-ORD-02")
    if identity.outcome == MULTIPLE_ORDER_IDS:
        return Decision(REQUEST_INFO, "multiple_order_ids", "KB-ORD-02", {"candidates": [{"order_id": i} for i in identity.named_ids]})
    if identity.outcome == NEEDS_ORDER_NUMBER:
        candidates = [{"order_id": o.order_id, "items": [line.product for line in o.items]} for o in identity.open_orders]
        return Decision(REQUEST_INFO, "needs_order_number", "KB-ORD-02", {"candidates": candidates})
    order, shipment = identity.order, identity.order.shipment
    base = {"order_id": order.order_id, "status": order.status, "promised_date": order.promised_date}
    # 4. by order state
    if order.status == "processing":
        deadline = resolve_deadline(reading.deadline_phrase, today)
        if is_within_window(deadline, today):
            return Decision(ESCALATE_HUMAN, "delivery_deadline_cannot_be_guaranteed", "KB-SHP-03",
                            {**base, "deadline_date": deadline.isoformat()})
        return Decision(PROVIDE_INFO, "order_processing", "KB-ORD-01", base)
    if order.status == "shipped" and shipment is not None:
        facts = {**base, "carrier": shipment.carrier, "tracking_no": shipment.tracking_no, "last_status": shipment.last_status}
        if today > date.fromisoformat(order.promised_date):
            return Decision(PROVIDE_INFO, "shipped_late", "KB-SHP-02", facts)
        return Decision(PROVIDE_INFO, "shipped_on_time", "KB-SHP-01", facts)
    if order.status == "delivered" and shipment is not None and _day(shipment.delivered_at):
        return Decision(PROVIDE_INFO, "delivered", "KB-SHP-01", {**base, "delivered_date": _day(shipment.delivered_at)})
    return Decision(ROUTE_TO_HUMAN, "order_state_not_covered", None)           # cancelled, returned, or an inconsistent record