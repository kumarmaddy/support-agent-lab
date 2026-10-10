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
# proposals and refusals for transactional tickets (phase-2-design.md, section 6): the agent proposes, a person acts
PROPOSE_CANCELLATION, PROPOSE_ADDRESS_CHANGE, DECLINE_POLICY = "propose_cancellation", "propose_address_change", "decline_policy"
PROPOSE_RETURN_LABEL, PROPOSE_EXCHANGE, PROPOSE_REPLACEMENT = "propose_return_label", "propose_exchange", "propose_replacement"
PROPOSE_REFUND = "propose_refund"
REFUND_PENDING_DAYS = 7                       # KB-REF-01: the refund is issued within 5 to 7 calendar days after the return is received
RETURN_WINDOW_DAYS = 30                       # KB-RET-01: the day of delivery is day 0; day 30 is inside the window, day 31 is not

# the ticket categories the agent handles. Phase 1 handled order status only; --transactions adds the rest, one stage at a time.
PHASE1_SCOPE = frozenset({"order_status"})
TRANSACTION_SCOPE = PHASE1_SCOPE | {"cancellation", "address_change"}
RETURNS_SCOPE = TRANSACTION_SCOPE | {"return_exchange"}
REFUNDS_SCOPE = RETURNS_SCOPE | {"refund"}

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
class ReturnRequest:
    """What a return-or-exchange ticket asks for, after the checks in transactions.py: the kind, the order line it concerns (None if it
    could not be pinned down) and the requested size (empty if none)."""
    kind: str
    item: Optional[tools.OrderLine] = None
    requested_size: str = ""


@dataclass(frozen=True)
class RefundRequest:
    """What a refund ticket is about (the model's topic, checked against the records in decide) with the payment records of the order and the
    dollar amounts the customer wrote (in cents; used only to check that the customer and the records agree)."""
    topic: str
    records: Optional[tools.PaymentRecords] = None
    stated_amounts: tuple = ()


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    article: Optional[str]
    facts: dict = field(default_factory=dict)       # verified facts only; the reply may use nothing else


def requires_lookup(reading: Reading, scope: frozenset = PHASE1_SCOPE) -> bool:
    """Only tickets in scope without a legal threat need the customer and order (a legal threat is escalated in any category)."""
    return reading.category in scope and not reading.mentions_chargeback_or_legal


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


def decide(reading: Reading, identity: Optional[Identity], today: date, scope: frozenset = PHASE1_SCOPE,
           requested_address: str = "", request: Optional[ReturnRequest] = None, refund: Optional[RefundRequest] = None) -> Decision:
    # 1. threat of chargeback or legal action: always escalated (KB-REF-04), whatever the category; no account details are read
    if reading.mentions_chargeback_or_legal:
        return Decision(ESCALATE_HUMAN, "chargeback_or_legal_threat", "KB-REF-04")
    # 2. out of slice
    if reading.category not in scope:
        return Decision(ROUTE_TO_HUMAN, "out_of_slice", None)
    if identity is None:
        raise ValueError("an identity is required for a ticket in scope without a legal threat")
    # 3. who and which order
    if identity.outcome == NO_ACCOUNT:
        return Decision(REQUEST_INFO, "no_account", "KB-ORD-02")
    if identity.outcome == ORDER_NOT_OWNED:
        return Decision(ESCALATE_HUMAN, "order_not_owned", "KB-SEC-01")        # reveal nothing; a person follows up
    if identity.outcome == ORDER_NOT_FOUND:
        return Decision(REQUEST_INFO, "order_not_found", "KB-ORD-02")
    if identity.outcome == MULTIPLE_ORDER_IDS:
        return Decision(REQUEST_INFO, "multiple_order_ids", "KB-ORD-02", {"candidates": [{"order_id": i} for i in identity.named_ids]})
    if identity.outcome == NEEDS_ORDER_NUMBER and not identity.open_orders:
        return Decision(REQUEST_INFO, "no_open_orders", "KB-ORD-02")           # nothing to list: ask for the number, name no orders
    if identity.outcome == NEEDS_ORDER_NUMBER:
        candidates = [{"order_id": o.order_id, "items": [line.product for line in o.items]} for o in identity.open_orders]
        return Decision(REQUEST_INFO, "needs_order_number", "KB-ORD-02", {"candidates": candidates})
    order, shipment = identity.order, identity.order.shipment
    base = {"order_id": order.order_id, "status": order.status, "promised_date": order.promised_date}
    if reading.category == "cancellation":
        return _cancellation(order, shipment, base)
    if reading.category == "address_change":
        return _address_change(order, shipment, base, requested_address)
    if reading.category == "return_exchange":
        return _return_exchange(order, shipment, base, request, today)
    if reading.category == "refund":
        return _refund(order, shipment, base, refund, today)
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


def _shipment_facts(base: dict, shipment) -> dict:
    return {**base, "carrier": shipment.carrier, "tracking_no": shipment.tracking_no, "last_status": shipment.last_status}


def _cancellation(order, shipment, base: dict) -> Decision:
    """KB-CAN-01: an order can be cancelled only before dispatch. The agent proposes; a person cancels."""
    if order.status == "processing":
        return Decision(PROPOSE_CANCELLATION, "cancellation_before_dispatch", "KB-CAN-01", base)
    if order.status == "shipped" and shipment is not None:
        return Decision(DECLINE_POLICY, "cancellation_after_dispatch", "KB-CAN-01", _shipment_facts(base, shipment))
    return Decision(ROUTE_TO_HUMAN, "order_state_not_covered", None)


def _address_change(order, shipment, base: dict, requested_address: str) -> Decision:
    """KB-ADR-01: the address can be changed only before dispatch. The address to propose is the customer's own wording, verified
    against the ticket (transactions.py); without one the customer is asked for it."""
    if order.status == "processing":
        if not requested_address:
            return Decision(REQUEST_INFO, "address_missing", "KB-ADR-01", {"candidates": [{"order_id": order.order_id}]})
        return Decision(PROPOSE_ADDRESS_CHANGE, "address_change_before_dispatch", "KB-ADR-01", {**base, "requested_address": requested_address})
    if order.status == "shipped" and shipment is not None:
        return Decision(DECLINE_POLICY, "address_change_after_dispatch", "KB-ADR-01", _shipment_facts(base, shipment))
    return Decision(ROUTE_TO_HUMAN, "order_state_not_covered", None)


def _return_exchange(order, shipment, base: dict, request: Optional[ReturnRequest], today: date) -> Decision:
    """KB-RET-01 to KB-RET-04 and KB-REF-03. The window is counted in code from the delivery date to the day the request was received
    (KB-RET-01: a return "requested on the thirtieth day" is accepted); the model only says what was asked.
    The agent proposes a label, exchange or replacement and a person arranges it; it never promises a refund."""
    if order.status != "delivered" or shipment is None or not _day(shipment.delivered_at):
        return Decision(ROUTE_TO_HUMAN, "order_state_not_covered", None)
    delivered = date.fromisoformat(_day(shipment.delivered_at))
    days = (today - delivered).days
    within = 0 <= days <= RETURN_WINDOW_DAYS
    kind = request.kind if request else "unclear"
    facts = {**base, "delivered_date": delivered.isoformat(), "days_since_delivery": days, "within_return_window": within,
             "return_window_days": RETURN_WINDOW_DAYS, "request_kind": kind,
             "request_date": today.isoformat()}
    if kind not in ("return", "exchange", "replacement"):
        return Decision(ROUTE_TO_HUMAN, "request_not_covered", None, facts)                  # refunds and unclear requests: a person
    if kind == "replacement":
        if within:
            return Decision(PROPOSE_REPLACEMENT, "replacement_within_window", "KB-REF-03", facts)
        return Decision(ROUTE_TO_HUMAN, "replacement_outside_window", None, facts)
    if not within:
        return Decision(DECLINE_POLICY, "return_window_closed", "KB-RET-01", facts)
    # With no item pinned down, a return is still proposed when nothing in the order is final sale (the answer cannot depend on the item);
    # otherwise, and for any exchange (the size depends on the item), the customer is asked which item they mean.
    if request.item is None and (kind == "exchange" or any(line.final_sale for line in order.items)):
        names = [line.product for line in order.items]
        return Decision(REQUEST_INFO, "item_unclear", "KB-RET-01", {**facts, "candidates": [{"order_id": order.order_id, "items": names}]})
    if request.item is None:
        return Decision(PROPOSE_RETURN_LABEL, "return_label", "KB-RET-01", facts)
    facts["item"] = request.item.product
    if request.item.final_sale:
        return Decision(DECLINE_POLICY, "return_final_sale", "KB-RET-03", facts)
    if kind == "return":
        return Decision(PROPOSE_RETURN_LABEL, "return_label", "KB-RET-01", facts)
    if not request.item.size:                                                              # an item without sizes: a person decides
        return Decision(ROUTE_TO_HUMAN, "exchange_item_has_no_size", None, facts)
    current = request.item.size
    facts["current_size"] = current
    if not request.requested_size or request.requested_size == current.upper():
        return Decision(REQUEST_INFO, "size_missing", "KB-RET-04", {**facts, "candidates": [{"order_id": order.order_id}]})
    return Decision(PROPOSE_EXCHANGE, "exchange_within_window", "KB-RET-04", {**facts, "requested_size": request.requested_size})


# ------------------------------------------------------------------ refunds (stage 2.5c)
def _refund(order, shipment, base: dict, refund: Optional[RefundRequest], today: date) -> Decision:
    """KB-REF-01 to KB-REF-03. The model only says what the ticket is about; every amount and date comes from the records. A refund is
    only ever proposed (a person approves it), the order's own records must support it, and the reply states no amount or date the
    records do not hold."""
    if refund is None or refund.records is None:
        return Decision(ROUTE_TO_HUMAN, "refund_records_unavailable", None, base)
    records = refund.records
    if refund.topic == "status":
        return _refund_status(base, records, today)
    if refund.topic == "duplicate_charge":
        return _duplicate_charge(order, shipment, base, refund, today)
    if refund.topic in ("item_refund", "item_unspecified"):
        return _item_refund(order, shipment, base, refund, today)
    return Decision(ROUTE_TO_HUMAN, "request_not_covered", None, base)


def _refund_status(base: dict, records: tools.PaymentRecords, today: date) -> Decision:
    """KB-REF-01: say whether the refund is pending or processed and for how much. A pending refund is described only while it is inside
    the 5 to 7 day period counted from the day the return was received; after that a person looks into it."""
    if not records.refunds:
        return Decision(ROUTE_TO_HUMAN, "no_refund_on_record", None, base)
    if len(records.refunds) > 1:
        return Decision(ROUTE_TO_HUMAN, "refund_ambiguous", None, base)
    refund = records.refunds[0]
    received = next((_day(r.received_at) for r in records.returns if r.status == "received" and r.received_at), None)
    facts = {**base, "refund_status": refund.status, "refund_amount_cents": refund.amount_cents,
             "refund_requested_date": _day(refund.requested_at), "request_date": today.isoformat()}
    if received:
        facts["return_received_date"] = received
    if refund.status == "processed":
        return Decision(PROVIDE_INFO, "refund_processed", "KB-REF-01", facts)
    if refund.status != "pending":
        return Decision(ROUTE_TO_HUMAN, "refund_state_not_covered", None, facts)
    if not received:
        return Decision(ROUTE_TO_HUMAN, "refund_pending_without_return", None, facts)
    waited = (today - date.fromisoformat(received)).days
    facts["days_since_return_received"] = waited
    if not 0 <= waited <= REFUND_PENDING_DAYS:
        return Decision(ROUTE_TO_HUMAN, "refund_pending_outside_period", None, facts)       # overdue (or an inconsistent date): a person chases it
    return Decision(PROVIDE_INFO, "refund_pending", "KB-REF-01", facts)


def _duplicate_charge(order, shipment, base: dict, refund: RefundRequest, today: date) -> Decision:
    """KB-REF-02: propose a refund of the duplicate payment only, taken from the payment record. The ticket's own amount is never used;
    if it disagrees with the record, or the record shows no single duplicate, a person decides."""
    records = refund.records
    flagged = [p for p in records.payments if p.status == "duplicate_flagged"]
    if not flagged:
        return Decision(ROUTE_TO_HUMAN, "duplicate_not_on_record", None, base)
    if len(flagged) > 1:
        return Decision(ROUTE_TO_HUMAN, "duplicate_ambiguous", None, base)
    duplicate = flagged[0]
    if refund.stated_amounts and duplicate.amount_cents not in refund.stated_amounts:
        return Decision(ROUTE_TO_HUMAN, "duplicate_amount_differs", None, base)
    if any(r.payment_id == duplicate.payment_id for r in records.refunds):
        return Decision(ROUTE_TO_HUMAN, "duplicate_already_refunded", None, base)
    facts = {**base, "duplicate_amount_cents": duplicate.amount_cents, "duplicate_payment_id": duplicate.payment_id, "approval_required": True}
    if order.status == "shipped" and shipment is not None:                  # a ticket that also asks where the parcel is gets the update
        facts.update(_shipment_facts({}, shipment))
        facts["delivery_late"] = today > date.fromisoformat(order.promised_date)
    return Decision(PROPOSE_REFUND, "duplicate_charge", "KB-REF-02", facts)


def _item_refund(order, shipment, base: dict, refund: RefundRequest, today: date) -> Decision:
    """KB-REF-03: a damaged or wrong item can be refunded or replaced if the customer tells us within 30 days of delivery. Whether the
    customer wants money back is for them to say; if they do not, they are asked. No amount is stated: a person sets it."""
    if order.status != "delivered" or shipment is None or not _day(shipment.delivered_at):
        return Decision(ROUTE_TO_HUMAN, "order_state_not_covered", None, base)
    delivered = date.fromisoformat(_day(shipment.delivered_at))
    days = (today - delivered).days
    within = 0 <= days <= RETURN_WINDOW_DAYS
    facts = {**base, "delivered_date": delivered.isoformat(), "days_since_delivery": days, "within_return_window": within,
             "return_window_days": RETURN_WINDOW_DAYS, "request_date": today.isoformat()}
    if not within:
        return Decision(ROUTE_TO_HUMAN, "refund_window_closed", None, facts)
    if refund.records.refunds or any(p.status == "refunded" for p in refund.records.payments):
        return Decision(ROUTE_TO_HUMAN, "item_already_refunded", None, facts)
    if refund.topic == "item_unspecified":
        return Decision(REQUEST_INFO, "remedy_unclear", "KB-REF-03", {**facts, "candidates": [{"order_id": order.order_id}]})
    return Decision(PROPOSE_REFUND, "item_refund_within_window", "KB-REF-03", {**facts, "approval_required": True})