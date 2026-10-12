"""Approval records: a person's decision on one proposed action. The actions server accepts nothing without one (design 5.4).

An approval names the ticket, action and order and, depending on the action, the payment and amount (refund) or the address
(change_address). The approval service of stage 3.6 will call ``grant`` and ``reject``; the audit events are written here so the two
stages share one path.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.actions.config import ACTIONS
from src.audit.log import APPROVAL, REJECTION, AuditLog
from src.agent.tools import ORDER_ID, TICKET_ID

APPROVED, REJECTED = "approved", "rejected"
MAX_ADDRESS = 200


class ApprovalError(Exception):
    pass


@dataclass(frozen=True)
class Approval:
    approval_id: str
    ticket_id: str
    action: str
    order_id: str
    payment_id: str
    amount_cents: Optional[int]
    address: str
    status: str
    approver: str
    rule_id: str
    note: str
    decided_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ApprovalStore:
    def __init__(self, conn: sqlite3.Connection, audit: Optional[AuditLog] = None, clock=_now):
        self.conn, self.audit, self.clock = conn, audit, clock

    def _record(self, status, ticket_id, action, order_id, approver, payment_id, amount_cents, address, rule_id, note) -> Approval:
        if action not in ACTIONS:
            raise ApprovalError(f"unknown action {action!r}")
        if not (isinstance(ticket_id, str) and TICKET_ID.match(ticket_id)) or not (isinstance(order_id, str) and ORDER_ID.match(order_id)):
            raise ApprovalError("ticket and order ids must look like T-000001 and O-000001")
        if not (isinstance(approver, str) and approver.strip()):
            raise ApprovalError("an approval needs the name of the person who decided")
        if status == APPROVED:
            if action == "refund" and not (payment_id and isinstance(amount_cents, int) and not isinstance(amount_cents, bool) and amount_cents > 0):
                raise ApprovalError("a refund approval needs a payment id and an amount in whole cents above zero")
            if action == "change_address" and not (isinstance(address, str) and address.strip() and len(address) <= MAX_ADDRESS):
                raise ApprovalError(f"an address approval needs the address (up to {MAX_ADDRESS} characters)")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            n = self.conn.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] + 1
            approval_id = f"AP-{n:06d}"
            row = (approval_id, ticket_id, action, order_id, payment_id or "", amount_cents, (address or "").strip(), status, approver.strip(),
                   rule_id or "", note or "", self.clock())
            self.conn.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", row)
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        approval = Approval(*row)
        if self.audit is not None:
            self.audit.append(APPROVAL if status == APPROVED else REJECTION, ticket_id,
                              {"approval_id": approval_id, "action": action, "order_id": order_id, "payment_id": payment_id or "",
                               "amount_cents": amount_cents, "address": approval.address, "rule_id": rule_id or "", "note": note or ""},
                              actor=approval.approver)
        return approval

    def grant(self, ticket_id, action, order_id, approver, *, payment_id="", amount_cents=None, address="", rule_id="", note="") -> Approval:
        return self._record(APPROVED, ticket_id, action, order_id, approver, payment_id, amount_cents, address, rule_id, note)

    def reject(self, ticket_id, action, order_id, approver, *, rule_id="", note="") -> Approval:
        return self._record(REJECTED, ticket_id, action, order_id, approver, "", None, "", rule_id, note)

    def get(self, approval_id: str) -> Optional[Approval]:
        row = self.conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone() if isinstance(approval_id, str) else None
        return Approval(*tuple(row)) if row else None