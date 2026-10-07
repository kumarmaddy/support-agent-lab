"""Interactive timing session for the manual baseline (docs/project/baseline-protocol.md).

For each ticket the handler starts a timer, reads the ticket, uses read-only lookups, then records a decision:
category, actions, escalation reason, knowledge-base articles used and a short reply. The timer stops when the
reply is submitted; paused time is excluded. Results are appended to a JSON Lines file so a session can be resumed.

This module never reads ground-truth labels: scoring is a separate step (scoring.py).
"""
import json
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.baseline import lookups
from src.datagen.domain.taxonomy import ACTIONS, CATEGORIES

PROTOCOL_VERSION = 1
HELP = """Commands while the timer runs:
  orders          list the orders on the account (account matching the sender's email address)
  order <id>      show one order, e.g. order O-000123
  kb              list knowledge-base articles
  kb <id>         read an article, e.g. kb KB-RET-01
  pause           stop the clock (breaks, interruptions); Enter resumes
  done            finish looking and record your decision (the clock keeps running until the reply is saved)
  help            show this list"""


class SessionQuit(Exception):
    """The handler chose to stop before starting the next ticket."""


class Session:
    def __init__(self, conn, articles, sample: dict, results_path: Path, input_fn=input, output_fn=print,
                 clock=time.monotonic, now=datetime.now):
        self.conn, self.articles, self.sample = conn, articles, sample
        self.results_path = Path(results_path)
        self.input, self.out, self.clock, self.now = input_fn, output_fn, clock, now

    # ------------------------------------------------------------------ persistence
    def completed_ids(self) -> set[str]:
        if not self.results_path.exists():
            return set()
        with open(self.results_path, encoding="utf-8") as f:
            return {json.loads(line)["ticket_id"] for line in f if line.strip()}

    def save(self, record: dict) -> None:
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.results_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ------------------------------------------------------------------ flow
    def run(self) -> int:
        """Handle every remaining ticket (practice first). Returns the number of tickets recorded this run."""
        done = self.completed_ids()
        queue = [(t, True) for t in self.sample["practice_ids"]] + [(t, False) for t in self.sample["ticket_ids"]]
        total_scored, recorded = len(self.sample["ticket_ids"]), 0
        for ticket_id, practice in queue:
            if ticket_id in done:
                continue
            label = ("Practice ticket (not scored)" if practice else
                     f"Ticket {self.sample['ticket_ids'].index(ticket_id) + 1} of {total_scored}")
            try:
                self.save(self.handle(ticket_id, label, practice,
                                      position=None if practice else self.sample["ticket_ids"].index(ticket_id) + 1))
            except SessionQuit:
                self.out("Stopped. Progress is saved; run the same command to resume.")
                return recorded
            recorded += 1
        self.out("All tickets handled. Next: score the results.")
        return recorded

    def handle(self, ticket_id: str, label: str, practice: bool, position: int | None) -> dict:
        row = self.conn.execute("SELECT received_at, customer_email, subject, body FROM tickets "
                                "WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown ticket {ticket_id}")
        received_at, email, subject, body = row
        self.out(f"\n=== {label} ===")
        if self.input("Press Enter to start the timer (or type quit): ").strip().lower() == "quit":
            raise SessionQuit
        started_at, start = self.now().isoformat(timespec="seconds"), self.clock()
        paused, pauses, used = 0.0, 0, Counter()
        self.out(f"\nTicket {ticket_id}   received {received_at}\nFrom: {email}\nSubject: {subject}\n\n{body}\n")
        self.out("Type help for commands.")
        while True:
            command = self.input("> ").strip()
            word, _, arg = command.partition(" ")
            word = word.lower()
            if word == "done":
                break
            elif word == "orders":
                used["orders"] += 1
                self.out(lookups.customer_summary(self.conn, email))
            elif word == "order" and arg:
                used["order"] += 1
                self.out(lookups.order_summary(self.conn, arg.strip().upper()))
            elif word == "kb":
                used["kb"] += 1
                self.out(lookups.kb_article(self.articles, arg) if arg else lookups.kb_list(self.articles))
            elif word == "pause":
                before = self.clock()
                self.input("Clock paused. Press Enter to resume: ")
                paused += self.clock() - before
                pauses += 1
            elif word == "help":
                self.out(HELP)
            else:
                self.out("Unknown command. Type help.")
        category = self.choose_one("Category", CATEGORIES)
        actions = self.choose_many("Actions", ACTIONS)
        reason = self.input("Escalation reason (short phrase): ").strip() if "escalate_human" in actions else None
        kb_ids = self.ask_kb_ids()
        reply = self.input("Reply to the customer (1-3 sentences): ").strip()
        seconds = self.clock() - start - paused               # clock stops here: the reply is submitted
        note = self.input("Optional note (not timed): ").strip()
        self.out(f"Recorded in {seconds:.0f} s.")
        return {"protocol_version": PROTOCOL_VERSION, "ticket_id": ticket_id, "practice": practice,
                "position": position, "started_at": started_at, "seconds": round(seconds, 1),
                "pauses": pauses, "lookups": dict(used), "category": category, "actions": sorted(actions),
                "escalation_reason": reason, "kb_ids": kb_ids, "reply": reply, "note": note}

    # ------------------------------------------------------------------ prompts (timed)
    def choose_one(self, title: str, options) -> str:
        self.out(f"{title}: " + ", ".join(f"{i}={o}" for i, o in enumerate(options, 1)))
        while True:
            answer = self.input(f"{title} (number or name): ").strip()
            picked = self._match(answer, options)
            if picked is not None:
                return picked
            self.out("Not a valid choice.")

    def choose_many(self, title: str, options) -> list[str]:
        self.out(f"{title}: " + ", ".join(f"{i}={o}" for i, o in enumerate(options, 1)))
        while True:
            parts = [p.strip() for p in self.input(f"{title} (comma-separated numbers or names): ").split(",") if p.strip()]
            picked = [self._match(p, options) for p in parts]
            if parts and None not in picked:
                return list(dict.fromkeys(picked))
            self.out("Enter at least one valid choice.")

    def ask_kb_ids(self) -> list[str]:
        while True:
            parts = [p.strip().upper() for p in self.input("Knowledge-base articles you relied on (comma-separated, "
                                                           "or Enter for none): ").split(",") if p.strip()]
            unknown = [p for p in parts if p not in self.articles]
            if not unknown:
                return list(dict.fromkeys(parts))
            self.out(f"Unknown article(s): {', '.join(unknown)}")

    @staticmethod
    def _match(answer: str, options):
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        return answer if answer in options else None
