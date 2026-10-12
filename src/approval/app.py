"""The approval page: routing, decisions and the checks around them (design 5.5). Standard library only; no script runs in the browser.

Safety rules:
  * bound to 127.0.0.1 only (``serve`` refuses anything else), and every request must carry a Host header for that address and port
    (blocks DNS rebinding);
  * every POST needs the per-start token from the form and must be a same-origin request (Sec-Fetch-Site, else the Origin header), which
    blocks cross-site posts;
  * ticket text, addresses and every other dynamic value are HTML-escaped; the Content-Security-Policy forbids scripts and inline styles;
  * the approver's name and role are fixed when the server starts, so a decision cannot be attributed to anyone else from the page;
  * a decision is refused if the policy engine denies it, if it would need a senior approver the server was not started as, or if the
    ticket already has a decision (checked inside the database transaction).
"""
import hmac
import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs

from src.actions.approvals import AlreadyDecided, ApprovalError
from src.actions.config import ActionsConfig
from src.actions.sandbox import open_sandbox
from src.actions.service import POLICY_NAMES, ActionsService
from src.agent import policy as pol
from src.agent.handover import SENIOR
from src.agent.tools import TICKET_ID
from src.approval import pages
from src.approval.queue import APPROVED, PENDING, Item, load_items, status_of
from src.audit.log import EDIT, AuditLog

MAX_BODY = 16_384
MAX_REASON = 300
LOOPBACK = "127.0.0.1"
TICKET_PATH = re.compile(r"^/ticket/(T-\d{6})(?:/(decide|execute))?$")
EDITS_FILE = Path("data/edits/edits.jsonl")


class Response:
    def __init__(self, status: int, body: str = "", content_type: str = "text/html; charset=utf-8", headers: Optional[dict] = None):
        self.status, self.body, self.content_type, self.headers = status, body, content_type, headers or {}


def parse_dollars(text: str) -> int:
    """'119.99' -> 11999. Whole cents only, above zero, up to 100,000.00."""
    try:
        value = Decimal(text.strip().replace(",", "").lstrip("$"))
    except (InvalidOperation, AttributeError):
        raise ValueError("enter the amount as dollars, for example 119.99")
    if value != value.quantize(Decimal("0.01")) or not value.is_finite():
        raise ValueError("an amount has at most two decimal places")
    if not Decimal("0.01") <= value <= Decimal("100000"):
        raise ValueError("the amount must be between 0.01 and 100000.00")
    return int(value * 100)


class ApprovalApp:
    def __init__(self, run_dir, sandbox, approver: str, role: str, config: ActionsConfig, policy: pol.Policy, audit: Optional[AuditLog] = None,
                 edits_file: Path = EDITS_FILE, port: int = 0):
        if role not in ("standard", "senior"):
            raise ValueError("role must be 'standard' or 'senior'")
        if not (isinstance(approver, str) and approver.strip()):
            raise ValueError("the approver's name is required")
        self.run_dir, self.sandbox, self.approver, self.role = Path(run_dir), Path(sandbox), approver.strip(), role
        self.config, self.policy, self.audit, self.edits_file, self.port = config, policy, audit, Path(edits_file), port
        self.token = secrets.token_urlsafe(24)
        self.items = {i.ticket_id: i for i in load_items(self.run_dir)}
        self.run_id = next((i.run_id for i in self.items.values()), self.run_dir.name)
        self._edits_lock = threading.Lock()

    # ------------------------------------------------------------------ entry point used by the server and by the tests
    def handle(self, method: str, path: str, headers: dict, body: bytes = b"") -> Response:
        headers = {k.lower(): v for k, v in headers.items()}
        response = self._route(method, path, headers, body)
        response.headers = {**pages.SECURITY_HEADERS, **response.headers}
        return response

    def _allowed_hosts(self):
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def _route(self, method, path, headers, body) -> Response:
        if headers.get("host", "") not in self._allowed_hosts():
            return Response(403, pages.message_page("Not allowed", "This page answers only on 127.0.0.1."))
        path = path.split("?", 1)[0]
        if path == "/style.css":
            return Response(200, pages.STYLE, "text/css; charset=utf-8") if method == "GET" else Response(405)
        conn = open_sandbox(self.sandbox)
        try:
            if path == "/":
                return self._list(conn) if method == "GET" else Response(405, headers={"Allow": "GET"})
            m = TICKET_PATH.match(path)
            if not m or m.group(1) not in self.items:
                return Response(404, pages.message_page("Not found", "No such proposal in this run."))
            item, verb = self.items[m.group(1)], m.group(2)
            if verb is None:
                return self._detail(conn, item) if method == "GET" else Response(405, headers={"Allow": "GET"})
            if method != "POST":
                return Response(405, headers={"Allow": "POST"})
            form = self._form(headers, body)
            if isinstance(form, Response):
                return form
            if verb == "execute":
                return self._execute(conn, item)
            return self._decide(conn, item, form)
        finally:
            conn.close()

    def _same_site(self, headers) -> bool:
        """Fetch Metadata first (what current browsers send, including embedded ones): only a same-origin request, or one typed by the person
        (``none``), may post. Without it, fall back to the Origin header. The form token is checked afterwards in every case."""
        site = headers.get("sec-fetch-site")
        if site is not None:
            return site in ("same-origin", "none")
        origin = headers.get("origin")
        return origin is None or origin in {f"http://{h}" for h in self._allowed_hosts()}

    def _form(self, headers, body):
        if len(body) > MAX_BODY:
            return Response(413, pages.message_page("Too large", "The form was larger than allowed."))
        if not self._same_site(headers):
            seen = f"Sec-Fetch-Site: {headers.get('sec-fetch-site', '-')[:40]}; Origin: {headers.get('origin', '-')[:80]}"
            return Response(403, pages.message_page("Not allowed", f"The request came from another site. ({seen})"))
        try:
            form = {k: v[0] for k, v in parse_qs(body.decode("utf-8"), keep_blank_values=True, strict_parsing=bool(body)).items()}
        except (UnicodeDecodeError, ValueError):
            return Response(400, pages.message_page("Bad request", "The form could not be read."))
        if not hmac.compare_digest(form.get("token", ""), self.token):
            return Response(403, pages.message_page("Not allowed", "The form is out of date. Reload the page and try again."))
        return form

    # ------------------------------------------------------------------ pages
    def _statuses(self, conn):
        return {tid: status_of(conn, item)[0] for tid, item in self.items.items()}

    def _list(self, conn) -> Response:
        return Response(200, pages.list_page(list(self.items.values()), self._statuses(conn), self.approver, self.role, self.run_id))

    def _ticket(self, conn, ticket_id):
        row = conn.execute("SELECT subject, body FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
        return {"subject": row["subject"], "body": row["body"]} if row else None

    def _payments(self, conn, order_id):
        return [dict(r) for r in conn.execute("SELECT payment_id, amount_cents, status FROM payments WHERE order_id=? ORDER BY payment_id", (order_id,))]

    def _detail(self, conn, item: Item, notice: str = "", kind: str = "", status_code: int = 200) -> Response:
        status, approval = status_of(conn, item)
        html = pages.detail_page(item, status, approval, self._ticket(conn, item.ticket_id), self._payments(conn, item.order_id), self.token, self.role,
                                 bool(item.call) and self.config.is_enabled(item.tool), notice, kind)
        return Response(status_code, html)

    # ------------------------------------------------------------------ decisions
    def _refuse(self, conn, item, message, code=422) -> Response:
        return self._detail(conn, item, message, "bad", code)

    def _policy_check(self, conn, item, tool, payment_id, amount_cents):
        payment = None
        refunded = None
        if tool == "refund":
            payment = conn.execute("SELECT amount_cents, status FROM payments WHERE payment_id=? AND order_id=?", (payment_id, item.order_id)).fetchone()
            refunded = bool(payment) and (payment["status"] == "refunded" or bool(conn.execute("SELECT 1 FROM refunds WHERE payment_id=?", (payment_id,)).fetchone()))
        request = pol.PolicyRequest(action=POLICY_NAMES[tool], reason=item.reason, amount_cents=amount_cents if tool == "refund" else None,
                                    payment_amount_cents=payment["amount_cents"] if payment else None, payment_already_refunded=refunded)
        return pol.evaluate(request, self.policy)

    def _decide(self, conn, item: Item, form: dict) -> Response:
        if not item.call:
            return self._refuse(conn, item, "This proposal has no write tool.", 409)
        if item.queue == SENIOR and self.role != SENIOR:
            return self._refuse(conn, item, "This proposal needs a senior approver.", 403)
        verb, reason = form.get("verb", ""), form.get("reason", "").strip()
        if verb not in ("approve", "edit", "reject"):
            return self._refuse(conn, item, "Choose Approve, Approve with my change, or Reject.", 400)
        if not reason or len(reason) > MAX_REASON:
            return self._refuse(conn, item, f"A reason is required (up to {MAX_REASON} characters).")
        call, tool = item.call, item.call["action"]
        store = ActionsService(conn, self.config, self.audit, self.policy).approvals
        try:
            if verb == "reject":
                approval = store.reject(item.ticket_id, tool, item.order_id, self.approver, rule_id=item.rule_id, note=reason, once=True)
                return self._detail(conn, item, f"Rejected ({approval.approval_id}). Nothing will be done.", "good")
            payment_id, amount, address = call.get("payment_id", ""), call.get("amount_cents"), call.get("address", "")
            if tool == "refund":
                payment_id = form.get("payment_id", payment_id)
                try:
                    amount_new = parse_dollars(form["amount"]) if "amount" in form or amount is None else amount     # absent field: the proposed amount
                except ValueError as exc:
                    return self._refuse(conn, item, str(exc))
                if payment_id not in {p["payment_id"] for p in self._payments(conn, item.order_id)}:
                    return self._refuse(conn, item, "Choose one of this order's payments.")
                changed = amount is not None and (amount_new != amount or payment_id != call.get("payment_id"))
                amount = amount_new
            elif tool == "change_address":
                address_new = form.get("address", address).strip()                                            # absent field: the proposed address
                if not address_new:
                    return self._refuse(conn, item, "Enter the address.")
                changed, address = address_new != call.get("address", ""), address_new
            else:
                changed = False
            if verb == "edit" and not changed:
                return self._refuse(conn, item, "Nothing was changed. Use Approve to accept the proposal as it is.")
            if verb == "approve" and changed:
                return self._refuse(conn, item, "The values differ from the proposal. Use Approve with my change, or put the proposed values back.")
            decision = self._policy_check(conn, item, tool, payment_id, amount)
            if decision.outcome == pol.DENY:
                return self._refuse(conn, item, f"Policy rule {decision.rule_id} denies this: {decision.reason}")
            if decision.queue == SENIOR and self.role != SENIOR:
                return self._refuse(conn, item, f"With these values the case needs a senior approver (rule {decision.rule_id}).", 403)
            approval = store.grant(item.ticket_id, tool, item.order_id, self.approver, payment_id=payment_id, amount_cents=amount if tool == "refund" else None,
                                   address=address if tool == "change_address" else "", rule_id=decision.rule_id, note=reason, once=True)
        except AlreadyDecided:
            return self._refuse(conn, item, "This proposal has already been decided.", 409)
        except ApprovalError as exc:
            return self._refuse(conn, item, str(exc))
        if verb == "edit":
            self._record_edit(item, tool, call, approval, reason)
        return self._detail(conn, item, f"Approved ({approval.approval_id}). Press Execute to carry it out.", "good")

    def _record_edit(self, item, tool, call, approval, reason):
        """The edit as labelled data for evaluation (FR-11) and as an audit event."""
        if tool == "refund":
            field, proposed, final = "amount_cents", call.get("amount_cents"), approval.amount_cents
        else:
            field, proposed, final = "address", call.get("address", ""), approval.address
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": self.run_id, "ticket_id": item.ticket_id, "action": tool,
                  "field": field, "proposed": proposed, "final": final, "reason": reason, "approver": self.approver, "approval_id": approval.approval_id}
        with self._edits_lock:
            self.edits_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.edits_file, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        if self.audit is not None:
            self.audit.append(EDIT, item.ticket_id, {k: record[k] for k in ("approval_id", "action", "field", "proposed", "final", "reason")}, self.run_id, self.approver)

    def _execute(self, conn, item: Item) -> Response:
        status, approval = status_of(conn, item)
        if not item.call or status not in (APPROVED, "executed"):
            return self._refuse(conn, item, "Only an approved proposal can be executed.", 409)
        service = ActionsService(conn, self.config, self.audit, self.policy)
        result = service.execute(approval["action"], approval["ticket_id"], approval["order_id"], approval["approval_id"], payment_id=approval["payment_id"],
                                 amount_cents=approval["amount_cents"], address=approval["address"])
        if result.ok:
            return self._detail(conn, item, "Executed in the sandbox." if result.status == "executed" else "Already executed; nothing was written again.", "good")
        return self._detail(conn, item, f"Not executed: {result.detail} ({result.code}).", "bad", 422)


# ------------------------------------------------------------------ the HTTP server
def make_handler(app: ApprovalApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ApprovalPage"
        sys_version = ""

        def _serve(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(length, MAX_BODY + 1)) if length else b""
            r = app.handle(method, self.path, dict(self.headers.items()), body)
            data = r.body.encode("utf-8")
            self.send_response(r.status)
            self.send_header("Content-Type", r.content_type)
            self.send_header("Content-Length", str(len(data)))
            for k, v in r.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._serve("GET")

        def do_POST(self):
            self._serve("POST")

        def do_PUT(self):
            self._serve("PUT")

        do_DELETE = do_PATCH = do_PUT

        def log_message(self, fmt, *args):                                # no request lines (they can carry ids) on the console
            pass
    return Handler


def serve(app: ApprovalApp, host: str = LOOPBACK, port: int = 8765) -> ThreadingHTTPServer:
    if host != LOOPBACK:
        raise ValueError("the approval page may only be bound to 127.0.0.1")
    server = ThreadingHTTPServer((host, port), make_handler(app))
    app.port = server.server_address[1]
    return server