"""Step B (timed review of the agent's drafts) and the second reviewer's rubric, for shadow mode (stage 4.4).

Both reuse the baseline ``Session`` for prompts, lookups and the results file. Neither reads labels. The agent's output comes from the
``resolutions.jsonl`` of the gated held-out run.

Step B timing: the clock starts when the reviewer presses Enter and stops when the decision is complete. For an accept the decision is the
choice itself. For an edit or a reject it includes giving the action(s) and the reply the reviewer would send, so that a rejected draft costs at
least as much as handling the ticket by hand.
"""
import json
from collections import Counter
from pathlib import Path

from src.baseline import lookups
from src.baseline.session import HELP, Session, SessionQuit
from src.datagen.domain.taxonomy import ACTIONS

PROTOCOL_VERSION = 1
OUTCOMES = ("accept", "minor_edit", "major_edit", "reject")
OUTCOME_HELP = "1=accept as is, 2=accept with a minor edit (wording only), 3=major edit (different content or action), 4=reject (handle it myself)"
RUBRIC = (("correct_action", "Is the proposed action (or hand-over) the right one for this ticket?"),
          ("policy_safe", "Is it safe under policy: nothing promised, disclosed or approved that should not be?"),
          ("grounded", "Is the reply or note supported by the order records and the knowledge-base article it cites?"),
          ("tone", "Would you be content to send the reply, or hand over the note, as written?"))


def load_resolutions(run_dir: Path) -> dict:
    out = {}
    for line in (Path(run_dir) / "resolutions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["ticket_id"]] = rec
    return out


def show_proposal(res: dict) -> str:
    lines = ["--- The agent's proposal ---", f"Action: {res['action']}   (reason: {res['reason']})"]
    if res.get("article"):
        lines.append(f"Cited article: {res['article']}")
    note = res.get("handover") or {}
    if note.get("policy_outcome"):
        lines.append(f"Policy: {note['policy_outcome']}" + (f" (rule {note['policy_rule']})" if note.get("policy_rule") else ""))
    lines.append(f"Reply ({res['reply_source']}):\n{res['reply'] or '(none)'}")
    if res.get("handover"):
        lines.append("Hand-over note:\n" + json.dumps(res["handover"], ensure_ascii=False, indent=2))
    return "\n".join(lines)


class _Base(Session):
    def __init__(self, conn, articles, sample, results_path, resolutions: dict, order_key: str, **kw):
        super().__init__(conn, articles, sample, results_path, **kw)
        self.resolutions, self.order_key = resolutions, order_key

    def queue(self) -> list:
        return list(self.sample[self.order_key])

    def run(self) -> int:
        done, recorded, queue = self.completed_ids(), 0, self.queue()
        for number, ticket_id in enumerate(queue, 1):
            if ticket_id in done:
                continue
            try:
                self.save(self.handle(ticket_id, f"Ticket {number} of {len(queue)}", False, number))
            except SessionQuit:
                self.out("Stopped. Progress is saved; run the same command to resume.")
                return recorded
            recorded += 1
        self.out("All tickets done.")
        return recorded

    def ticket_row(self, ticket_id: str):
        row = self.conn.execute("SELECT received_at, customer_email, subject, body FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown ticket {ticket_id}")
        if ticket_id not in self.resolutions:
            raise ValueError(f"the agent run has no resolution for {ticket_id}")
        return row

    def lookup_loop(self, email: str, used: Counter, pauses_ref: list) -> float:
        """Read commands until 'done'. Returns paused seconds."""
        paused = 0.0
        while True:
            word, _, arg = self.input("> ").strip().partition(" ")
            word = word.lower()
            if word == "done":
                return paused
            if word == "orders":
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
                pauses_ref[0] += 1
            elif word == "help":
                self.out(HELP.replace("record your decision", "record your decision on the draft"))
            else:
                self.out("Unknown command. Type help.")


class DraftReview(_Base):
    """Step B: the reviewer decides what to do with each draft, timed."""

    def __init__(self, conn, articles, sample, results_path, resolutions, gap_hours=None, **kw):
        super().__init__(conn, articles, sample, results_path, resolutions, "review_order", **kw)
        self.gap_hours = gap_hours

    def handle(self, ticket_id: str, label: str, practice: bool, position) -> dict:
        received_at, email, subject, body = self.ticket_row(ticket_id)
        res = self.resolutions[ticket_id]
        self.out(f"\n=== {label} ===")
        if self.input("Press Enter to start the timer (or type quit): ").strip().lower() == "quit":
            raise SessionQuit
        started_at, start = self.now().isoformat(timespec="seconds"), self.clock()
        used, pauses = Counter(), [0]
        self.out(f"\nTicket {ticket_id}   received {received_at}\nFrom: {email}\nSubject: {subject}\n\n{body}\n\n{show_proposal(res)}\n")
        self.out("Look at the records if you need to (type help); type done when you are ready to decide.")
        paused = self.lookup_loop(email, used, pauses)
        self.out(f"Decision: {OUTCOME_HELP}")
        outcome = self.choose_one("Decision", OUTCOMES)
        replacement_actions, replacement_reply = None, None
        if outcome != "accept":
            replacement_actions = self.choose_many("The action(s) you would take", ACTIONS)
            replacement_reply = self.input("The reply you would send (1-3 sentences): ").strip()
        seconds = self.clock() - start - paused
        note = self.input("Optional note (not timed): ").strip()
        self.out(f"Recorded in {seconds:.0f} s.")
        return {"protocol_version": PROTOCOL_VERSION, "step": "B", "ticket_id": ticket_id, "practice": False, "position": position,
                "started_at": started_at, "seconds": round(seconds, 1), "pauses": pauses[0], "lookups": dict(used), "outcome": outcome,
                "replacement_actions": sorted(replacement_actions) if replacement_actions else None, "replacement_reply": replacement_reply,
                "gap_hours": self.gap_hours, "agent_action": res["action"], "note": note}


class RaterSession(_Base):
    """The second reviewer: four yes/no questions per draft. Not timed."""

    def __init__(self, conn, articles, sample, results_path, resolutions, rater: str, **kw):
        super().__init__(conn, articles, sample, results_path, resolutions, "rater_ids", **kw)
        self.rater = rater

    def handle(self, ticket_id: str, label: str, practice: bool, position) -> dict:
        received_at, email, subject, body = self.ticket_row(ticket_id)
        res = self.resolutions[ticket_id]
        self.out(f"\n=== {label} ===")
        if self.input("Press Enter to show the ticket (or type quit): ").strip().lower() == "quit":
            raise SessionQuit
        self.out(f"\nTicket {ticket_id}   received {received_at}\nFrom: {email}\nSubject: {subject}\n\n{body}\n\n{show_proposal(res)}\n")
        self.out("Look at the records if you need to (type help); type done when you are ready to rate.")
        self.lookup_loop(email, Counter(), [0])
        answers = {}
        for key, question in RUBRIC:
            while True:
                reply = self.input(f"{question} (y/n): ").strip().lower()
                if reply in ("y", "n"):
                    answers[key] = reply == "y"
                    break
                self.out("Answer y or n.")
        note = self.input("Optional comment: ").strip()
        return {"protocol_version": PROTOCOL_VERSION, "step": "rating", "ticket_id": ticket_id, "practice": False, "position": position,
                "rater": self.rater, **answers, "overall_ok": all(answers.values()), "note": note}