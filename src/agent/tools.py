"""Read-only tools for the support agent (docs/design/phase-1-design.md, section 4).

The tools are the only door from the agent to the operational database. They are defined once, with typed inputs and
outputs, so the fixed pipeline and a later agent loop (ADR-006) use exactly the same interface.

Rules enforced here:
- The connection is read-only (opened with ``mode=ro`` and ``PRAGMA query_only``), so no tool can change data (ADR-005).
- Every argument is validated before it reaches SQL, and SQL always uses bound parameters.
- ``get_order`` refuses an order that belongs to another customer and then reveals nothing about it (privacy, KB-SEC-01).
- Results contain only what the pipeline needs: no postal addresses, card digits or payment records (NFR-3).
- Expected conditions (not found, not owned, invalid argument) are returned as a status, not raised, so callers handle them explicitly.
"""
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

OK, NOT_FOUND, NOT_OWNED, INVALID = "ok", "not_found", "not_owned", "invalid_argument"
UNKNOWN_TOOL = "unknown_tool"
OPEN_ORDER_STATUSES = ("processing", "shipped")      # not yet delivered, cancelled or returned

TICKET_ID = re.compile(r"^T-\d{6}$")
ORDER_ID = re.compile(r"^O-\d{6}$")
CUSTOMER_ID = re.compile(r"^C-\d{6}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
MAX_EMAIL = 254


# ------------------------------------------------------------------ result types
@dataclass(frozen=True)
class Ticket:
    ticket_id: str
    received_at: str
    channel: str
    customer_email: str
    subject: str
    body: str


@dataclass(frozen=True)
class Customer:
    customer_id: str
    name: str
    email: str
    tier: str
    status: str


@dataclass(frozen=True)
class OrderLine:
    product: str
    size: str | None
    quantity: int


@dataclass(frozen=True)
class Shipment:
    carrier: str
    tracking_no: str
    dispatched_at: str | None
    delivered_at: str | None
    last_status: str


@dataclass(frozen=True)
class Order:
    order_id: str
    customer_id: str
    status: str
    placed_at: str
    promised_date: str
    total_cents: int
    items: tuple[OrderLine, ...]
    shipment: Shipment | None


@dataclass(frozen=True)
class OpenOrder:
    order_id: str
    status: str
    placed_at: str
    promised_date: str
    items: tuple[OrderLine, ...]


@dataclass(frozen=True)
class ToolResult:
    status: str
    data: object | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK

    def to_dict(self) -> dict:
        return {"status": self.status, "data": _plain(self.data), "detail": self.detail}


def _plain(value):
    """Dataclasses, tuples and lists become plain JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return _plain(asdict(value)) if hasattr(value, "__dataclass_fields__") else {k: _plain(v) for k, v in value.items()}


# ------------------------------------------------------------------ tool definitions (the shared interface)
def _schema(description: str, **properties: str) -> dict:
    return {"description": description,
            "input_schema": {"type": "object", "additionalProperties": False, "required": list(properties),
                             "properties": {k: {"type": "string", "description": v} for k, v in properties.items()}}}


TOOL_SCHEMAS = {
    "get_ticket": _schema("Return a support ticket: sender, subject, body and received time.",
                          ticket_id="Ticket id, for example T-000123"),
    "find_customer": _schema("Find the customer account for an email address (case-insensitive).",
                             email="Sender email address"),
    "list_open_orders": _schema("List a customer's orders that are not delivered, cancelled or returned.",
                                customer_id="Customer id, for example C-000042"),
    "get_order": _schema("Return one order with its items and shipment. Refuses an order that belongs to another customer.",
                         order_id="Order id, for example O-000123", customer_id="The verified customer asking about the order"),
}


def open_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


class Toolbox:
    def __init__(self, conn: sqlite3.Connection):
        conn.execute("PRAGMA query_only = ON")        # defence in depth: even a writable file cannot be changed through this connection
        self.conn = conn

    @classmethod
    def from_path(cls, db_path: Path) -> "Toolbox":
        return cls(open_readonly(db_path))

    # ------------------------------------------------------------------ tools
    def get_ticket(self, ticket_id: str) -> ToolResult:
        if not _matches(TICKET_ID, ticket_id):
            return ToolResult(INVALID, detail="ticket_id must look like T-000123")
        row = self.conn.execute("SELECT ticket_id, received_at, channel, customer_email, subject, body FROM tickets "
                                "WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return ToolResult(OK, Ticket(*row)) if row else ToolResult(NOT_FOUND, detail="no such ticket")

    def find_customer(self, email: str) -> ToolResult:
        if not (isinstance(email, str) and len(email) <= MAX_EMAIL and EMAIL.fullmatch(email)):
            return ToolResult(INVALID, detail="email is not a valid address")
        row = self.conn.execute("SELECT customer_id, name, email, tier, status FROM customers WHERE lower(email) = lower(?)",
                                (email,)).fetchone()
        return ToolResult(OK, Customer(*row)) if row else ToolResult(NOT_FOUND, detail="no account has this email address")

    def list_open_orders(self, customer_id: str) -> ToolResult:
        if not _matches(CUSTOMER_ID, customer_id):
            return ToolResult(INVALID, detail="customer_id must look like C-000123")
        if self.conn.execute("SELECT 1 FROM customers WHERE customer_id = ?", (customer_id,)).fetchone() is None:
            return ToolResult(NOT_FOUND, detail="no such customer")
        marks = ",".join("?" * len(OPEN_ORDER_STATUSES))
        rows = self.conn.execute(
            f"SELECT order_id, status, placed_at, promised_date FROM orders WHERE customer_id = ? AND status IN ({marks}) "
            "ORDER BY placed_at, order_id", (customer_id, *OPEN_ORDER_STATUSES)).fetchall()
        orders = tuple(OpenOrder(oid, status, placed, promised, self._items(oid)) for oid, status, placed, promised in rows)
        return ToolResult(OK, orders)

    def get_order(self, order_id: str, customer_id: str) -> ToolResult:
        if not _matches(ORDER_ID, order_id) or not _matches(CUSTOMER_ID, customer_id):
            return ToolResult(INVALID, detail="order_id must look like O-000123 and customer_id like C-000123")
        row = self.conn.execute("SELECT order_id, customer_id, status, placed_at, promised_date, total_cents FROM orders "
                                "WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            return ToolResult(NOT_FOUND, detail="no such order")
        if row[1] != customer_id:
            return ToolResult(NOT_OWNED, detail="this order does not belong to the verified customer")   # nothing else is revealed
        shipment = self.conn.execute("SELECT carrier, tracking_no, dispatched_at, delivered_at, last_status FROM shipments "
                                     "WHERE order_id = ?", (order_id,)).fetchone()
        return ToolResult(OK, Order(*row, items=self._items(order_id), shipment=Shipment(*shipment) if shipment else None))

    # ------------------------------------------------------------------ dispatch by name (what a model-driven loop would use)
    def call(self, name: str, arguments: dict) -> dict:
        schema = TOOL_SCHEMAS.get(name)
        if schema is None:
            return ToolResult(UNKNOWN_TOOL, detail=f"no tool named {name!r}").to_dict()
        problem = _check_arguments(schema["input_schema"], arguments)
        if problem:
            return ToolResult(INVALID, detail=problem).to_dict()
        return getattr(self, name)(**arguments).to_dict()

    def _items(self, order_id: str) -> tuple[OrderLine, ...]:
        rows = self.conn.execute("SELECT p.name, i.size, i.quantity FROM order_items i JOIN products p USING (product_id) "
                                 "WHERE i.order_id = ? ORDER BY i.order_item_id", (order_id,)).fetchall()
        return tuple(OrderLine(*r) for r in rows)


def _matches(pattern: re.Pattern, value) -> bool:
    # fullmatch, not match: '$' would also accept a trailing newline
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _check_arguments(input_schema: dict, arguments) -> str:
    """Hand-rolled check of the small schema subset in use: required string properties, nothing else."""
    if not isinstance(arguments, dict):
        return "arguments must be an object"
    missing = [k for k in input_schema["required"] if k not in arguments]
    extra = [k for k in arguments if k not in input_schema["properties"]]
    wrong = [k for k, v in arguments.items() if k in input_schema["properties"] and not isinstance(v, str)]
    if missing:
        return f"missing argument(s): {', '.join(missing)}"
    if extra:
        return f"unexpected argument(s): {', '.join(extra)}"
    if wrong:
        return f"argument(s) must be strings: {', '.join(wrong)}"
    return ""