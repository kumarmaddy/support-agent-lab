"""Post-run review of baseline disagreements (docs/project/baseline-protocol.md, section 8).

For every ticket where the handler's answer differed from the label, show the evidence in one place and record a
classification:  H handler error, L label error, K knowledge-base defect, P policy or rubric ambiguity.

The classification is a human judgement and is never inferred: the tool shows the evidence, the person decides.
Decisions are appended to a log (data/baseline/review.jsonl, resumable) and the review document is rendered from that log.

This module reads ground-truth labels. It runs only after all tickets are handled, and is deliberately separate from
session.py and lookups.py, which must never be able to reach labels (enforced by tests/baseline/test_scoring.py).
"""
import json
import os
from datetime import datetime
from pathlib import Path

from src.baseline.lookups import customer_summary, order_summary
from src.baseline.scoring import MEASURES, wilson_interval

CODES = {
    "H": "Handler error: the label and the materials were clear and the handler answered wrongly",
    "L": "Label error: the label is wrong or does not follow the data design",
    "K": "Knowledge-base article missing, wrong or ambiguous",
    "P": "Policy or rubric wording ambiguous",
}
CHECKS = {   # neutral prompts for where to look; they do not suggest a classification
    "category": "Compare with the category boundary rules in docs/design/data-design.md (section 5).",
    "actions": "Compare with the policy table (data-design section 3) and the clarification for this scenario (section 7).",
    "escalate": "Check whether the ticket meets an escalation rule in the data design or the priority rubric.",
    "consequential": "Check the policy table: which consequential action does the policy allow for these facts?",
    "kb": "Read the required articles' Key facts below: do they support the answer, or does another article?",
}
DEFAULT_H_ACTION = "None: handler error, no change to project artefacts"
LOG_DEFAULT = Path("data/baseline/review.jsonl")
DRAFT_DEFAULT = Path("data/baseline/review-draft.jsonl")
DRAFT_SOURCE = "drafted with assistance, confirmed by reviewer"


def failed_measures(row: dict) -> list[str]:
    return [k.replace("_ok", "") for k in MEASURES if not row[k]]


def cell(text: str) -> str:
    return " ".join(str(text).replace("|", "/").split()) or "-"


# ------------------------------------------------------------------ evidence
def evidence_text(conn, articles, result: dict, label: dict, row: dict) -> str:
    ticket = conn.execute("SELECT received_at, customer_email, subject, body FROM tickets WHERE ticket_id = ?",
                          (label["ticket_id"],)).fetchone()
    received, email, subject, body = ticket
    out = [f"{'=' * 78}", f"Ticket {label['ticket_id']}  scenario {label['scenario_id']}  {label['difficulty']}  "
           f"failed: {', '.join(failed_measures(row))}", f"{'=' * 78}",
           f"\nTICKET  received {received}\nFrom: {email}\nSubject: {subject}\n\n{body}\n"]
    order_id = label.get("referenced_order_id")
    out.append("RECORDS\n" + (order_summary(conn, order_id) if order_id else customer_summary(conn, email)))
    out.append("\nHANDLER'S ANSWER\n"
               f"  category: {result['category']}\n  actions: {', '.join(sorted(result['actions'])) or 'none'}\n"
               f"  escalation reason: {result.get('escalation_reason') or '-'}\n"
               f"  articles relied on: {', '.join(result['kb_ids']) or 'none'}\n"
               f"  reply: {result.get('reply') or '-'}\n  note: {result.get('note') or '-'}")
    out.append("\nLABEL\n"
               f"  category: {label['category']}\n  actions: {', '.join(label['expected_actions']) or 'none'}\n"
               f"  escalate: {label['expected_escalate']}  reason: {label.get('escalation_reason') or '-'}\n"
               f"  required articles: {', '.join(label['required_kb_ids']) or 'none'}\n"
               f"  expected facts: {json.dumps(label.get('expected_facts', {}), ensure_ascii=False)}")
    for kb_id in dict.fromkeys([*label["required_kb_ids"], *result["kb_ids"]]):
        article = articles.get(kb_id)
        if article is None:
            continue
        tag = "required" if kb_id in label["required_kb_ids"] else "cited by handler"
        out.append(f"\nARTICLE {kb_id} ({tag}): {article.title}\n" + "\n".join(f"  - {f}" for f in article.key_facts))
    out.append("\nWHERE TO LOOK\n" + "\n".join(f"  {m}: {CHECKS[m]}" for m in failed_measures(row)))
    return "\n".join(out)


def load_drafts(path: Path) -> dict[str, dict]:
    """Proposed decisions prepared outside the tool (one JSON object per line). They are proposals only: nothing is
    recorded until the reviewer has seen each one and accepted it."""
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        drafts = [json.loads(line) for line in f if line.strip()]
    for d in drafts:
        if d.get("code") not in CODES or not d.get("evidence") or not d.get("action"):
            raise ValueError(f"draft for {d.get('ticket_id')} needs a code (H, L, K, P), evidence and an action")
    return {d["ticket_id"]: d for d in drafts}


def answer_line(row: dict) -> str:
    return (f"handler: {row['handled_category']}; {', '.join(row['handled_actions']) or 'none'}; "
            f"escalated {'yes' if row['handled_escalate'] else 'no'}\n  label:   {row['category']}; "
            f"{', '.join(row['expected_actions']) or 'none'}; escalate {'yes' if row['expected_escalate'] else 'no'}")


# ------------------------------------------------------------------ the interactive review
class ReviewSession:
    def __init__(self, conn, articles, results: list[dict], labels_by_id: dict, disagreements: list[dict],
                 log_path: Path, input_fn=input, output_fn=print, now=datetime.now):
        self.conn, self.articles, self.labels = conn, articles, labels_by_id
        self.results = {r["ticket_id"]: r for r in results if not r["practice"]}
        self.disagreements, self.log_path = disagreements, Path(log_path)
        self.input, self.out, self.now = input_fn, output_fn, now

    def records(self) -> dict[str, dict]:
        """Saved decisions; if a ticket was reviewed twice the later decision stands."""
        if not self.log_path.exists():
            return {}
        with open(self.log_path, encoding="utf-8") as f:
            return {r["ticket_id"]: r for r in map(json.loads, filter(str.strip, f))}

    def save(self, record: dict) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def pending(self, redo=()) -> list[dict]:
        done = self.records()
        return [d for d in self.disagreements if d["ticket_id"] not in done or d["ticket_id"] in redo]

    def confirm_drafts(self, drafts: dict[str, dict], redo=()) -> int:
        """Show each proposed decision; the reviewer accepts it (Enter), reviews it from scratch (n) or stops (q).

        An accepted draft is recorded with its source, so the finished document says the decision was drafted with assistance."""
        queue = [d for d in self.pending(redo) if d["ticket_id"] in drafts]
        accepted = 0
        for number, row in enumerate(queue, 1):
            draft = drafts[row["ticket_id"]]
            self.out(f"\n[draft {number} of {len(queue)}] {row['ticket_id']}  scenario {row['scenario_id']}  "
                     f"failed: {', '.join(failed_measures(row))}\n  {answer_line(row)}\n"
                     f"  PROPOSED {draft['code']} ({CODES[draft['code']]})\n  evidence: {draft['evidence']}\n  action: {draft['action']}")
            while True:
                choice = self.input("Enter = accept, n = review this one yourself, q = quit: ").strip().lower()
                if choice in ("", "n", "q"):
                    break
                self.out("Press Enter, n or q.")
            if choice == "q":
                break
            if choice == "n":
                continue
            self.save({"ticket_id": row["ticket_id"], "scenario_id": row["scenario_id"], "failed": failed_measures(row),
                       "code": draft["code"], "evidence": draft["evidence"], "action": draft["action"], "source": DRAFT_SOURCE,
                       "reviewed_at": self.now().isoformat(timespec="seconds")})
            accepted += 1
        return accepted

    def run(self, redo=()) -> int:
        """Review the remaining disagreements; returns how many were recorded in this run."""
        queue, recorded = self.pending(redo), 0
        self.out(f"{len(queue)} disagreement(s) to review. Codes: " + "; ".join(f"{k} = {v}" for k, v in CODES.items()))
        for number, row in enumerate(queue, 1):
            tid = row["ticket_id"]
            self.out(f"\n[{number} of {len(queue)}]")
            self.out(evidence_text(self.conn, self.articles, self.results[tid], self.labels[tid], row))
            while True:
                code = self.input("\nClassification (H, L, K, P), s to skip for now, q to quit: ").strip().upper()
                if code == "Q":
                    self.out(f"Stopped. {recorded} recorded this run; run the command again to continue.")
                    return recorded
                if code == "S" or code in CODES:
                    break
                self.out("Enter H, L, K, P, s or q.")
            if code == "S":
                continue
            reasoning = self._required("Evidence and reasoning (the sentence in the ticket, article or data design that decides it)")
            action = self.input("Action (Enter for the default when the code is H): ").strip() if code == "H" else self._required(
                "Action (document or file to change, or the decision needed)")
            self.save({"ticket_id": tid, "scenario_id": row["scenario_id"], "failed": failed_measures(row), "code": code,
                       "evidence": reasoning, "action": action or DEFAULT_H_ACTION,
                       "reviewed_at": self.now().isoformat(timespec="seconds")})
            recorded += 1
        return recorded

    def _required(self, prompt: str) -> str:
        while True:
            answer = self.input(f"{prompt}: ").strip()
            if answer:
                return answer
            self.out("This cannot be empty.")


# ------------------------------------------------------------------ rendering
def render_review(records: dict[str, dict], disagreements: list[dict], n_tickets: int, reviewed_on: str) -> str:
    rows = [records[d["ticket_id"]] for d in disagreements if d["ticket_id"] in records]
    pending = [d["ticket_id"] for d in disagreements if d["ticket_id"] not in records]
    counts = {c: sum(r["code"] == c for r in rows) for c in CODES}
    assisted = sum(r.get("source") == DRAFT_SOURCE for r in rows)
    h_low, h_high = wilson_interval(counts["H"], n_tickets)
    d_low, d_high = wilson_interval(len(disagreements), n_tickets)
    lines = [
        "# Baseline Disagreement Review", "",
        "| | |", "|---|---|",
        f"| Version | 1.0{' (partial: ' + str(len(pending)) + ' ticket(s) not yet reviewed)' if pending else ''} |",
        f"| Date | {reviewed_on} |", "| Owner | Kumar Maddipatla, Project Lead |",
        "| Phase | 0 (Discovery and baseline), stage 0.7 |",
        "| Related | baseline-protocol.md (section 8), baseline-report.md, risk-register.md (R5), data-design.md (section 13) |", "",
        "Generated by `python -m src.baseline.cli review` from `data/baseline/review.jsonl`; the decisions are the reviewer's.",
        *([f"{assisted} of {len(rows)} decisions were drafted with AI assistance; the reviewer read and confirmed each one."]
          if assisted else []), "",
        "## 1. Purpose",
        "The manual baseline produced tickets where the handler's answer differed from the generated label. A difference has",
        "four possible causes, and only one of them is a handler error. This review classifies each difference so that the",
        "manual accuracy figures are stated correctly and any defect in the dataset, knowledge base or policy wording is corrected.",
        "It also serves as a check of the generated labels against an independent handling of the sampled tickets (risk R5).", "",
        "## 2. Classification", "| Code | Meaning | Consequence |", "|------|---------|-------------|",
        f"| H | {CODES['H']} | Counts as a manual error |",
        f"| L | {CODES['L']} | Dataset version bump, ADR and re-freeze (data design, section 13) |",
        f"| K | {CODES['K']} | Correct the article; log in the build log; re-run the KB tests |",
        f"| P | {CODES['P']} | Clarify the data design or rubric (version increment); decide whether labels are affected |", "",
        "## 3. Review record",
        "| Ticket | Scenario | Failed measures | Code | Evidence and reasoning | Action |",
        "|--------|----------|-----------------|------|------------------------|--------|",
    ]
    lines += [f"| {r['ticket_id']} | {r['scenario_id']} | {cell(', '.join(r['failed']))} | {r['code']} | "
              f"{cell(r['evidence'])} | {cell(r['action'])} |" for r in rows]
    lines += [f"| {t} | | | pending | | |" for t in pending]
    lines += ["", "## 4. Summary", "| Item | Count |", "|------|-------|",
              f"| Disagreements reviewed | {len(rows)} of {len(disagreements)} |",
              f"| H handler errors | {counts['H']} |", f"| L label errors | {counts['L']} |",
              f"| K knowledge-base defects | {counts['K']} |", f"| P policy or rubric ambiguities | {counts['P']} |", "",
              f"Manual accuracy, stated both ways (denominator: all {n_tickets} scored tickets; none removed):", "",
              f"- First pass, ticket differed from the label on any measure: {len(disagreements)} of {n_tickets} "
              f"({len(disagreements) / n_tickets * 100:.1f}%; 95% CI {d_low * 100:.1f}% to {d_high * 100:.1f}%).",
              f"- After review, handler errors only: {counts['H']} of {n_tickets} "
              f"({counts['H'] / n_tickets * 100:.1f}%; 95% CI {h_low * 100:.1f}% to {h_high * 100:.1f}%).",
              f"- Defects in the project's own artefacts (L, K, P): {counts['L'] + counts['K'] + counts['P']} ticket(s).", "",
              "## 5. Decisions arising"]
    arising = [r for r in rows if r["code"] != "H"]
    lines += [f"- {r['ticket_id']} ({r['code']}): {cell(r['action'])}" for r in arising] or ["None: every reviewed disagreement was a handler error."]
    lines += ["", "## 6. Limitations",
              "The reviewer is the handler and the author of the dataset. The classification is therefore a self-review: it identifies",
              "defects and ambiguities, but it is not an independent validation and is reported as such.", ""]
    return "\n".join(lines)