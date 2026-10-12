"""A throw-away world for one case: a copy of the development database holding the attack ticket, and a sandbox made from that copy.

The source database is opened read-only and never changed. Roles name real development customers and orders so a case can say "the
customer who asked to cancel" or "somebody else's order" without hard-coding ids. Ticket ids for attack tickets start at T-900001.
"""
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.actions.sandbox import create_sandbox, open_sandbox

# role -> the development ticket whose sender, order and payment it borrows
ROLE_TICKETS = {"addr": "T-000001", "label": "T-000009", "cancel": "T-000011", "refund": "T-000029", "item": "T-000046", "senior": "T-000149"}
ATTACK_TICKET_BASE = 900000
_ORDER = re.compile(r"\bO-\d{6}\b")
BUSINESS_TABLES = ("orders", "addresses", "payments", "refunds", "returns", "replacements")


def _connect_ro(path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_roles(source_db) -> dict:
    conn = _connect_ro(source_db)
    try:
        roles = {}
        for role, ticket_id in ROLE_TICKETS.items():
            t = conn.execute("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,)).fetchone()
            customer = conn.execute("SELECT * FROM customers WHERE email=?", (t["customer_email"],)).fetchone()
            order = _ORDER.search(t["subject"] + " " + t["body"]).group(0)
            status = conn.execute("SELECT status FROM orders WHERE order_id=?", (order,)).fetchone()[0]
            pays = conn.execute("SELECT payment_id, amount_cents, status FROM payments WHERE order_id=? ORDER BY payment_id", (order,)).fetchall()
            pay = next((p for p in pays if p["status"] == "duplicate_flagged"), pays[0])
            tracking = conn.execute("SELECT tracking_no FROM shipments WHERE order_id=?", (order,)).fetchone()
            roles[role] = {"ticket": ticket_id, "email": customer["email"], "customer": customer["customer_id"], "name": customer["name"],
                           "first": customer["name"].split()[0], "order": order, "status": status, "payment": pay["payment_id"],
                           "amount": pay["amount_cents"], "dollars": f"{pay['amount_cents'] / 100:.2f}",
                           "tracking": tracking[0] if tracking else "no-tracking"}
        return roles
    finally:
        conn.close()


@dataclass
class World:
    root: Path
    source: Path
    roles: dict
    ops_db: Path = field(init=False)
    sandbox: Path = field(init=False)
    ticket_id: str = ""

    def __post_init__(self):
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ops_db, self.sandbox = self.root / "ops.db", self.root / "sandbox.db"
        src = _connect_ro(self.source)
        out = sqlite3.connect(self.ops_db)
        try:
            src.backup(out)
        finally:
            src.close()
            out.close()

    def add_ticket(self, number: int, email: str, subject: str, body: str, received_at: str = "2026-10-06T09:00:00") -> str:
        self.ticket_id = f"T-{ATTACK_TICKET_BASE + number:06d}"
        conn = sqlite3.connect(self.ops_db)
        try:
            conn.execute("INSERT INTO tickets VALUES (?,?,?,?,?,?)", (self.ticket_id, received_at, "email", email, subject, body))
            conn.commit()
        finally:
            conn.close()
        return self.ticket_id

    def make_sandbox(self):
        """The sandbox is made from the ops copy, so it holds the attack ticket as well. Returns an open connection."""
        create_sandbox(self.ops_db, self.sandbox)
        return open_sandbox(self.sandbox)

    def customer_of(self, email: str):
        conn = _connect_ro(self.ops_db)
        try:
            row = conn.execute("SELECT customer_id FROM customers WHERE lower(email)=lower(?)", (email,)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()


def snapshot(db_path) -> dict:
    """What a write would change: every row of the business tables, plus the approvals and the ledger. Read with a separate connection."""
    conn = _connect_ro(db_path)
    try:
        have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        out = {}
        for table in BUSINESS_TABLES:
            if table in have:
                out[table] = sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {table}"))
        for table in ("approvals", "action_ledger"):
            out[table] = [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")] if table in have else []
        return out
    finally:
        conn.close()