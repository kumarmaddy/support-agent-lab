"""Pipeline step 8: the hand-over summary (phase-2-design.md, section 5d).

When the agent escalates a ticket, routes it to a person, or proposes an action that a person must carry out, the person receives a
short, structured note: what the agent found, why it stopped, and what the policy suggests as the next step. The note is built by code
from the reading, the identification outcome, the decision and its verified facts. No model writes it, so it cannot invent a record.

It holds no ticket text and no email address (the same rule as the trace): the person opens the ticket by its id. The "next step"
is a suggestion taken from the policy article; the person decides.
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

from src.agent import decide as d
from src.agent.reply import fmt_date, fmt_money

PROPOSALS = (d.PROPOSE_CANCELLATION, d.PROPOSE_ADDRESS_CHANGE, d.PROPOSE_RETURN_LABEL, d.PROPOSE_EXCHANGE, d.PROPOSE_REPLACEMENT, d.PROPOSE_REFUND)
HANDOVER_ACTIONS = (d.ESCALATE_HUMAN, d.ROUTE_TO_HUMAN) + PROPOSALS
SENIOR, STANDARD = "senior", "standard"

# reason -> (why the agent stopped or what it proposes, the suggested next step). Every reason that can accompany a hand-over action
# must be listed; a test reads the source files and fails when one is missing.
REASONS = {
    # escalations
    "chargeback_or_legal_threat": ("The customer mentions a chargeback, a payment dispute or legal action. Such tickets are always escalated (KB-REF-04). "
                                   "The agent's reply argues nothing and concedes nothing.",
                                   "Review the order and the issue below and respond; policy is to make no concession in the first reply."),
    "order_not_owned": ("The order number in the ticket is not on the account of the sender's email address. Nothing about that order was read or shared.",
                        "Verify the customer's identity before sharing any order detail."),
    "delivery_deadline_cannot_be_guaranteed": ("The customer needs the order by a date that falls inside the delivery period, and delivery cannot be guaranteed.",
                                               "Review what is possible (expedite or an alternative) and reply to the customer."),
    # routes
    "out_of_slice": ("The ticket is in a category the agent does not handle yet.", "Handle the ticket as usual."),
    "ticket_not_found": ("The ticket could not be read from the database.", "Check the ticket id."),
    "reading_failed": ("The agent could not read the ticket reliably.", "Read the ticket and handle it as usual."),
    "order_state_not_covered": ("The order is in a state the agent does not decide on (cancelled, returned or inconsistent records).", "Check the order and reply."),
    "request_not_covered": ("The request is not one the agent decides on (a refund request on a return ticket, or an unclear request).", "Read the ticket and decide."),
    "replacement_outside_window": ("A replacement was asked for after the 30 days allowed (KB-REF-03).", "Decide whether to make an exception."),
    "exchange_item_has_no_size": ("An exchange was asked for an item that has no sizes.", "Clarify with the customer what they want."),
    "refund_records_unavailable": ("The payment records could not be read.", "Check the payment records for the order."),
    "no_refund_on_record": ("The customer asks about a refund but no refund is recorded for the order.", "Check whether a return was received and whether a refund is due."),
    "refund_ambiguous": ("More than one refund is recorded for the order.", "Check which refund the customer means."),
    "refund_pending_without_return": ("A refund is pending but no received return is recorded.", "Check the return before replying."),
    "refund_pending_outside_period": ("The refund is still pending more than 7 days after the return was received (KB-REF-01).", "Chase the refund and tell the customer."),
    "refund_state_not_covered": ("The refund is in a state the agent does not describe.", "Check the refund record."),
    "duplicate_not_on_record": ("The customer reports a duplicate charge but the records show none.", "Check the payments with the customer."),
    "duplicate_ambiguous": ("More than one payment on the order is flagged as a duplicate.", "Check which payment to refund."),
    "duplicate_amount_differs": ("The amount in the ticket differs from the duplicate payment in the records.", "Check the amounts with the customer."),
    "duplicate_already_refunded": ("A refund is already recorded against the duplicate payment.", "Tell the customer the refund exists and its status."),
    "refund_window_closed": ("A refund for a damaged or wrong item was asked for more than 30 days after delivery (KB-REF-03).", "Decide whether to make an exception."),
    "item_already_refunded": ("The order already has a refund recorded.", "Check the existing refund before acting."),
    "knowledge_unavailable": ("The knowledge base could not be searched.", "Answer the question from the policy."),
    "knowledge_not_found": ("No policy article matched the question closely enough.", "Answer the question."),
    "knowledge_not_answered": ("A policy article matched but did not answer the question.", "Answer the question."),
    # proposals
    "cancellation_before_dispatch": ("The order has not been dispatched, so it can be cancelled (KB-CAN-01).", "Cancel the order and confirm to the customer."),
    "address_change_before_dispatch": ("The order has not been dispatched, so the address can be changed (KB-ADR-01).", "Change the address to the one shown (copied from the ticket) and confirm to the customer."),
    "return_label": ("The order was delivered inside the 30-day return window (KB-RET-01).", "Email the customer a free return label."),
    "exchange_within_window": ("The order is inside the return window and the customer asks for another size (KB-RET-04).", "Check the requested size is in stock and arrange the exchange."),
    "replacement_within_window": ("The customer reports a damaged or wrong item inside 30 days of delivery and asks for a replacement (KB-REF-03).", "Arrange the replacement and confirm to the customer."),
    "duplicate_charge": ("The records show one payment flagged as a duplicate of the order's payment (KB-REF-02).", "Approve or reject a refund of that payment only, then tell the customer."),
    "item_refund_within_window": ("The customer reports a damaged or wrong item inside 30 days of delivery and asks for a refund (KB-REF-03).", "Decide the refund amount, approve or reject it, then tell the customer."),
}


@dataclass(frozen=True)
class Handover:
    ticket_id: str
    received_at: str
    queue: str
    action: str
    reason: str
    why: str
    next_step: str
    article: Optional[str]
    category_read: Optional[str]
    legal_flag: bool
    account: str                                    # found / not_found / not_looked_up
    customer_id: Optional[str]
    order_ids: tuple                                # numbers named in the ticket, plus the order identified
    records: tuple = field(default_factory=tuple)   # plain-text lines, from verified facts only
    approval_required: bool = False
    reply_source: str = ""

    def to_dict(self) -> dict:
        out = asdict(self)
        out["order_ids"], out["records"] = list(self.order_ids), list(self.records)
        return out

    def render(self) -> str:
        read = f"Read as: {self.category_read or 'unknown'}" + ("; legal or chargeback threat flagged" if self.legal_flag else "") + "."
        lines = [f"Ticket {self.ticket_id}, received {self.received_at[:10]}. Queue: {self.queue}.",
                 f"Agent action: {self.action} ({self.reason}).", read, f"Why: {self.why}"]
        if self.order_ids:
            lines.append("Order: " + ", ".join(self.order_ids))
        lines.append("Records checked:" + ("" if self.records else " none"))
        lines += [f"  - {r}" for r in self.records]
        if self.approval_required:
            lines.append("Approval: required before anything is done.")
        lines.append(f"Suggested next step: {self.next_step}")
        if self.article:
            lines.append(f"Policy: {self.article}")
        return "\n".join(lines)


def _records(facts: dict) -> list:
    f, out = facts, []
    if "order_id" in f:
        out.append(f"Order {f['order_id']} is {f.get('status')}; promised {fmt_date(f['promised_date'])}.")
    if "delivered_date" in f:
        line = f"Delivered {fmt_date(f['delivered_date'])}"
        if "days_since_delivery" in f:
            line += f", {f['days_since_delivery']} days before this request; {f['return_window_days']}-day window: {'inside' if f['within_return_window'] else 'outside'}"
        out.append(line + ".")
    if "tracking_no" in f:
        out.append(f"Shipment: {f['carrier']}, tracking {f['tracking_no']}, latest status: {f['last_status']}.")
    if "item" in f:
        out.append(f"Item: {f['item']}" + (f", size {f['current_size']}" if f.get("current_size") else "") + ".")
    if f.get("requested_size"):
        out.append(f"Requested size: {f['requested_size']}.")
    if f.get("requested_address"):
        out.append(f"New address (as written in the ticket): {f['requested_address']}.")
    if f.get("deadline_date"):
        out.append(f"Date the customer needs it by: {fmt_date(f['deadline_date'])}.")
    if "refund_status" in f:
        out.append(f"Refund of {fmt_money(f['refund_amount_cents'])}, requested {fmt_date(f['refund_requested_date'])}: {f['refund_status']}"
                   + (f"; return received {fmt_date(f['return_received_date'])}" if f.get("return_received_date") else "") + ".")
    if "duplicate_amount_cents" in f:
        out.append(f"Duplicate payment {f['duplicate_payment_id']} of {fmt_money(f['duplicate_amount_cents'])}.")
    if f.get("candidates"):
        out.append("Orders offered to the customer: " + ", ".join(c["order_id"] for c in f["candidates"]) + ".")
    return out


def order_context(identity) -> dict:
    """Facts about the identified order for the summary of a ticket that was escalated before any lookup (KB-REF-04 asks for the order, the
    issue and the latest status). Empty when the order could not be identified."""
    if identity is None or identity.outcome != d.IDENTIFIED:
        return {}
    o = identity.order
    facts = {"order_id": o.order_id, "status": o.status, "promised_date": o.promised_date}
    if o.shipment is not None:
        facts.update(carrier=o.shipment.carrier, tracking_no=o.shipment.tracking_no, last_status=o.shipment.last_status)
        if o.shipment.delivered_at:
            facts["delivered_date"] = o.shipment.delivered_at[:10]
    return facts


def payment_context(records) -> dict:
    """Refund facts for the note of a refund ticket that was escalated before any payment lookup: the single refund on the order, and the
    single payment flagged as a duplicate, when the records show exactly one of each. Empty otherwise."""
    if records is None:
        return {}
    out = {}
    if len(records.refunds) == 1:
        r = records.refunds[0]
        out.update(refund_status=r.status, refund_amount_cents=r.amount_cents, refund_requested_date=r.requested_at[:10])
        received = next((x.received_at[:10] for x in records.returns if x.status == "received" and x.received_at), None)
        if received:
            out["return_received_date"] = received
    flagged = [p for p in records.payments if p.status == "duplicate_flagged"]
    if len(flagged) == 1:
        out.update(duplicate_amount_cents=flagged[0].amount_cents, duplicate_payment_id=flagged[0].payment_id)
    return out


def build_handover(ticket_id: str, received_at: str, reading, identity, decision: d.Decision, reply_source: str,
                   context: Optional[dict] = None) -> Optional[Handover]:
    """The note for the person who receives the ticket, or None when the agent replied by itself. ``context`` adds order facts the decision
    did not carry (see ``order_context``)."""
    if decision.action not in HANDOVER_ACTIONS:
        return None
    why, step = REASONS.get(decision.reason, ("The agent stopped on this ticket.", "Read the ticket and handle it."))
    account = "not_looked_up" if identity is None else ("not_found" if identity.outcome == d.NO_ACCOUNT else "found")
    named = list(reading.order_ids) if reading is not None else []
    facts = {**(context or {}), **decision.facts}
    if facts.get("order_id") and facts["order_id"] not in named:
        named.append(facts["order_id"])
    senior = decision.action == d.ESCALATE_HUMAN
    return Handover(ticket_id, received_at, SENIOR if senior else STANDARD, decision.action, decision.reason, why, step, decision.article,
                    reading.category if reading is not None else None, bool(reading.mentions_chargeback_or_legal) if reading is not None else False,
                    account, identity.customer.customer_id if identity is not None and identity.customer else None, tuple(named),
                    tuple(_records(facts)), bool(facts.get("approval_required")), reply_source)