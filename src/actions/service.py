"""The actions service: four write tools behind an approval gate, an idempotency key and a ledger (design 5.4).

A call is refused unless, in this order: the arguments are well formed; the tool is switched on in ``config/actions.toml``; an approval
exists, is ``approved`` and matches the call exactly (ticket, action, order, payment, amount, address); and, for the first execution, the
order is in a state where the action still makes sense and the policy rules (if given) do not deny it. A repeat of an executed call
returns the first result and writes nothing. Every call, refused or not, is written to the audit log as an ``execution`` event.

Idempotency key = sha256 of (ticket, action, order, payment, amount, address, approval id). The check and the write happen in one
IMMEDIATE transaction on the sandbox database, so two concurrent calls cannot both execute.
"""
import hashlib
import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.actions.approvals import APPROVED, ApprovalStore
from src.actions.config import ACTIONS, ActionsConfig
from src.agent import policy as pol
from src.agent.tools import ORDER_ID, TICKET_ID
from src.audit.log import EXECUTION, AuditLog

EXECUTED, REPLAYED, REFUSED = "executed", "replayed", "refused"
POLICY_NAMES = {"refund": "refund", "replace": "replacement", "change_address": "change_address", "cancel": "cancel_order"}
ADDRESS = re.compile(r"^(?P<line1>.+?),\s*(?P<city>[^,]+?)\s+(?P<postal>\d{5})(?:-\d{4})?$")
APPROVAL_ID = re.compile(r"^AP-\d{6}$")
PAYMENT_ID = re.compile(r"^PM-\d{6}$")


@dataclass(frozen=True)
class ActionResult:
    status: str                       # executed | replayed | refused
    code: str                         # ok | replay | the reason for a refusal
    detail: str = ""
    idempotency_key: str = ""
    approval_id: str = ""
    effect: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in (EXECUTED, REPLAYED)

    def to_dict(self) -> dict:
        return {"status": self.status, "code": self.code, "detail": self.detail, "idempotency_key": self.idempotency_key,
                "approval_id": self.approval_id, "effect": dict(self.effect)}


def idempotency_key(ticket_id, action, order_id, payment_id, amount_cents, address, approval_id) -> str:
    raw = json.dumps([ticket_id, action, order_id, payment_id, amount_cents, address, approval_id], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ActionsService:
    def __init__(self, conn: sqlite3.Connection, config: ActionsConfig, audit: Optional[AuditLog] = None, policy: Optional[pol.Policy] = None,
                 clock=_now):
        self.conn, self.config, self.audit, self.policy, self.clock = conn, config, audit, policy, clock
        self.approvals = ApprovalStore(conn, audit, clock)
        self._lock = threading.RLock()                               # one connection, one caller at a time (the MCP SDK uses worker threads)

    # ------------------------------------------------------------------ the public call
    def execute(self, action, ticket_id, order_id, approval_id, *, payment_id="", amount_cents=None, address="") -> ActionResult:
        address = address.strip() if isinstance(address, str) else address
        with self._lock:
            result = self._run(action, ticket_id, order_id, approval_id, payment_id or "", amount_cents, address or "")
        if self.audit is not None:
            self.audit.append(EXECUTION, ticket_id if isinstance(ticket_id, str) else "", {
                "status": result.status, "code": result.code, "detail": result.detail, "action": str(action), "order_id": str(order_id),
                "payment_id": payment_id or "", "amount_cents": amount_cents if isinstance(amount_cents, int) else None,
                "address": address if isinstance(address, str) else "", "approval_id": str(approval_id), "idempotency_key": result.idempotency_key,
                "effect": result.effect}, actor="actions-server")
        return result

    # ------------------------------------------------------------------ checks, then the transaction
    def _refuse(self, code, detail, key="", approval_id="") -> ActionResult:
        return ActionResult(REFUSED, code, detail, key, str(approval_id))

    def _run(self, action, ticket_id, order_id, approval_id, payment_id, amount_cents, address) -> ActionResult:
        if action not in ACTIONS:
            return self._refuse("unknown_action", f"unknown action {action!r}", approval_id=approval_id)
        shape = [(isinstance(ticket_id, str) and TICKET_ID.match(ticket_id), "ticket_id"), (isinstance(order_id, str) and ORDER_ID.match(order_id), "order_id"),
                 (isinstance(approval_id, str) and APPROVAL_ID.match(approval_id), "approval_id"),
                 (isinstance(payment_id, str) and (not payment_id or PAYMENT_ID.match(payment_id)), "payment_id"),
                 (amount_cents is None or (isinstance(amount_cents, int) and not isinstance(amount_cents, bool) and amount_cents > 0), "amount_cents"),
                 (isinstance(address, str) and len(address) <= 200, "address")]
        bad = [name for ok, name in shape if not ok]
        if bad:
            return self._refuse("invalid_argument", "invalid: " + ", ".join(bad), approval_id=approval_id if isinstance(approval_id, str) else "")
        if not self.config.is_enabled(action):
            return self._refuse("action_disabled", f"{action} is switched off in config/actions.toml", approval_id=approval_id)
        approval = self.approvals.get(approval_id)
        if approval is None:
            return self._refuse("no_approval", "no such approval", approval_id=approval_id)
        if approval.status != APPROVED:
            return self._refuse("not_approved", f"the approval was {approval.status}", approval_id=approval_id)
        differs = [n for n, a, b in (("ticket_id", approval.ticket_id, ticket_id), ("action", approval.action, action), ("order_id", approval.order_id, order_id),
                                      ("payment_id", approval.payment_id, payment_id), ("amount_cents", approval.amount_cents, amount_cents),
                                      ("address", approval.address, address)) if a != b]
        if differs:
            return self._refuse("approval_mismatch", "the call differs from the approval in: " + ", ".join(differs), approval_id=approval_id)
        key = idempotency_key(ticket_id, action, order_id, payment_id, amount_cents, address, approval_id)

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            prior = self.conn.execute("SELECT result FROM action_ledger WHERE idempotency_key = ?", (key,)).fetchone()
            if prior:
                self.conn.execute("COMMIT")
                first = json.loads(prior["result"])
                return ActionResult(REPLAYED, "replay", "already executed; nothing was written", key, approval_id, first)
            problem = self._preconditions(action, ticket_id, order_id, payment_id, amount_cents, address)
            if problem:
                self.conn.execute("ROLLBACK")
                return self._refuse(problem[0], problem[1], key, approval_id)
            effect = self._apply(action, ticket_id, order_id, payment_id, amount_cents, address, approval_id)
            self.conn.execute("INSERT INTO action_ledger VALUES (?,?,?,?,?,?,?)",
                              (key, approval_id, ticket_id, action, order_id, json.dumps(effect, sort_keys=True), self.clock()))
            self.conn.execute("COMMIT")
            return ActionResult(EXECUTED, "ok", "", key, approval_id, effect)
        except Exception as exc:                                    # fail closed: nothing half-written, and the caller is told
            try:
                self.conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            return self._refuse("execution_error", f"{type(exc).__name__}: {exc}", key, approval_id)

    def _preconditions(self, action, ticket_id, order_id, payment_id, amount_cents, address):
        order = self.conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if order is None:
            return "order_not_found", f"{order_id} is not in the database"
        payment = None
        if action == "refund":
            payment = self.conn.execute("SELECT * FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()
            if payment is None or payment["order_id"] != order_id:
                return "payment_not_on_order", f"{payment_id} is not a payment of {order_id}"
            if amount_cents > payment["amount_cents"]:
                return "amount_exceeds_payment", "a refund may not exceed the payment it is taken from"
            if payment["status"] == "refunded" or self.conn.execute("SELECT 1 FROM refunds WHERE payment_id = ?", (payment_id,)).fetchone():
                return "already_refunded", f"{payment_id} already has a refund"
        elif action in ("cancel", "change_address") and order["status"] != "processing":
            return "order_not_open", f"{order_id} is {order['status']}; this is possible only before dispatch (processing)"
        elif action == "replace":
            if order["status"] != "delivered":
                return "order_not_delivered", f"{order_id} is {order['status']}; a replacement needs a delivered order"
            if self.conn.execute("SELECT 1 FROM replacements WHERE order_id = ?", (order_id,)).fetchone():
                return "replacement_exists", f"{order_id} already has a replacement"
        if action == "change_address" and not ADDRESS.match(address):
            return "address_not_parseable", "the address must read: street, city 12345 (a person enters it by hand otherwise)"
        if self.policy is not None:                                  # the same rules the proposal met, applied again to the state now
            decision = pol.evaluate(pol.PolicyRequest(
                action=POLICY_NAMES[action], reason="execution", amount_cents=amount_cents if action == "refund" else None,
                payment_amount_cents=payment["amount_cents"] if payment is not None else None,
                payment_already_refunded=False if payment is not None else None), self.policy)
            if decision.outcome == pol.DENY:
                return "policy_denied", f"{decision.rule_id}: {decision.reason}"
        return None

    def _next_id(self, table, column, prefix) -> str:
        numbers = [int(r[0][len(prefix):]) for r in self.conn.execute(f"SELECT {column} FROM {table}") if r[0].startswith(prefix) and r[0][len(prefix):].isdigit()]
        return f"{prefix}{max(numbers, default=0) + 1:06d}"

    def _apply(self, action, ticket_id, order_id, payment_id, amount_cents, address, approval_id) -> dict:
        if action == "cancel":
            self.conn.execute("UPDATE orders SET status = 'cancelled' WHERE order_id = ?", (order_id,))
            return {"order_id": order_id, "order_status": "cancelled"}
        if action == "change_address":
            m = ADDRESS.match(address)
            customer = self.conn.execute("SELECT customer_id FROM orders WHERE order_id = ?", (order_id,)).fetchone()[0]
            address_id = self._next_id("addresses", "address_id", "A-")
            self.conn.execute("INSERT INTO addresses VALUES (?,?,?,?,?,?)", (address_id, customer, m["line1"], m["city"], m["postal"], "US"))
            self.conn.execute("UPDATE orders SET shipping_address_id = ? WHERE order_id = ?", (address_id, order_id))
            return {"order_id": order_id, "shipping_address_id": address_id}
        if action == "refund":
            refund_id = self._next_id("refunds", "refund_id", "RF-")
            self.conn.execute("INSERT INTO refunds VALUES (?,?,?,?,?)", (refund_id, payment_id, amount_cents, "processed", self.clock()))
            full = self.conn.execute("SELECT amount_cents FROM payments WHERE payment_id = ?", (payment_id,)).fetchone()[0] == amount_cents
            if full:
                self.conn.execute("UPDATE payments SET status = 'refunded' WHERE payment_id = ?", (payment_id,))
            return {"refund_id": refund_id, "payment_id": payment_id, "amount_cents": amount_cents, "payment_status": "refunded" if full else "partly_refunded"}
        replacement_id = self._next_id("replacements", "replacement_id", "RP-")
        self.conn.execute("INSERT INTO replacements VALUES (?,?,?,?,?)", (replacement_id, order_id, ticket_id, approval_id, self.clock()))
        return {"replacement_id": replacement_id, "order_id": order_id}


def call_from_proposal(resolution: dict, amount_cents: Optional[int] = None) -> Optional[dict]:
    """Turn a proposal (a resolutions.jsonl line) into the arguments an approver would sign off. Returns None for a proposal that has no
    write tool (return label, exchange). An item refund states no amount: the approver supplies ``amount_cents``."""
    facts, action = resolution.get("facts", {}), resolution.get("action")
    base = {"ticket_id": resolution["ticket_id"], "order_id": facts.get("order_id", "")}
    if action == "propose_cancellation":
        return {"action": "cancel", **base}
    if action == "propose_address_change":
        return {"action": "change_address", **base, "address": facts.get("requested_address", "")}
    if action == "propose_replacement":
        return {"action": "replace", **base}
    if action == "propose_refund":
        return {"action": "refund", **base, "payment_id": facts.get("duplicate_payment_id", ""), "amount_cents": facts.get("duplicate_amount_cents", amount_cents)}
    return None