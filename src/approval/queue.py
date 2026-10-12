"""The approval queue: proposals from one run, and where each stands in the sandbox.

A proposal is a line of ``resolutions.jsonl`` whose action is a ``propose_*``. Its status comes from the sandbox: no approval record means
pending; an approval or rejection record decides it; a ledger row for the approval means executed.
"""
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.actions.service import call_from_proposal
from src.agent.handover import SENIOR, STANDARD
from src.agent.tools import TICKET_ID

PENDING, APPROVED, REJECTED, EXECUTED = "pending", "approved", "rejected", "executed"


class QueueError(Exception):
    pass


@dataclass(frozen=True)
class Item:
    run_id: str
    ticket_id: str
    action: str                 # the pipeline's proposal, e.g. propose_refund
    reason: str
    order_id: str
    queue: str                  # senior | standard
    rule_id: str
    call: Optional[dict]        # what the write tool would be asked to do; None when the proposal has no write tool
    record: dict                # the whole resolution line

    @property
    def tool(self) -> str:
        return self.call["action"] if self.call else ""


def load_items(run_dir) -> list:
    path = Path(run_dir) / "resolutions.jsonl"
    if not path.exists():
        raise QueueError(f"no resolutions.jsonl in {run_dir}")
    items = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip():
            continue
        rec = json.loads(raw)
        if not str(rec.get("action", "")).startswith("propose_") or not TICKET_ID.match(rec.get("ticket_id", "")):
            continue
        policy, handover = rec.get("policy") or {}, rec.get("handover") or {}
        queue = policy.get("queue") or handover.get("queue") or STANDARD
        items.append(Item(rec.get("run_id", ""), rec["ticket_id"], rec["action"], rec.get("reason", ""), rec.get("facts", {}).get("order_id", ""),
                          SENIOR if queue == SENIOR else STANDARD, policy.get("rule_id", ""), call_from_proposal(rec), rec))
    # senior queue first, then by ticket id
    return sorted(items, key=lambda i: (i.queue != SENIOR, i.ticket_id))


def status_of(conn: sqlite3.Connection, item: Item):
    """(status, approval row or None) for an item."""
    row = conn.execute("SELECT * FROM approvals WHERE ticket_id=? AND action=? AND order_id=? ORDER BY approval_id DESC LIMIT 1",
                       (item.ticket_id, item.tool, item.order_id)).fetchone() if item.call else None
    if row is None:
        return PENDING, None
    if row["status"] == "rejected":
        return REJECTED, row
    done = conn.execute("SELECT 1 FROM action_ledger WHERE approval_id=?", (row["approval_id"],)).fetchone()
    return (EXECUTED if done else APPROVED), row