"""Score one pipeline run against the development labels.

    python -m src.evaluation.score data/runs/<run_id>

Reads ``resolutions.jsonl``, ``trace.jsonl`` and ``summary.json`` from the run directory and the development labels, and writes
``score.json`` beside them. It does not call a model. Two sets are reported, because they answer different questions:

* Set A, the in-slice tickets: did the agent take the labelled action, cite the labelled article and state the labelled facts?
* Set B, every other ticket: did the agent hand it to a person instead of answering it? (It is not expected to resolve them.)
"""
import argparse
import json
from datetime import date
from pathlib import Path
from typing import Optional

from src.baseline.scoring import wilson_interval
from src.evaluation.slice import in_scope

ANSWERS = ("provide_info", "request_info", "decline_policy")     # actions that reply to the customer without a person
PROPOSALS = ("propose_cancellation", "propose_address_change", "propose_return_label", "propose_exchange", "propose_replacement")   # the agent proposes, a person acts
HAND_OVERS = ("route_to_human", "escalate_human")
FACT_KEYS = {"order_status": "status", "promised_date": "promised_date", "carrier": "carrier", "tracking_no": "tracking_no",
             "last_status": "last_status", "deadline_date": "deadline_date"}
# facts a return or exchange resolution carries (stage 2.5b); compared only for return_exchange labels. days_since_delivery is not compared
# with the label: the dataset counts to its snapshot date (2026-10-06) and the agent to the day the request was received (KB-RET-01), so the
# scorer checks that the agent's own count is consistent with its request date instead.
RETURN_FACT_KEYS = {"delivered_date": "delivered_date", "within_return_window": "within_return_window",
                    "return_window_days": "return_window_days", "current_size": "current_size", "requested_size": "requested_size"}
HELDOUT_REFUSAL = "Refusing to score against the held-out split (it is opened once, in Phase 4)."


def read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def check_labels(labels: list, path: Path) -> None:
    if "heldout" in str(path).lower() or any(lab.get("split") != "dev" for lab in labels):
        raise SystemExit(HELDOUT_REFUSAL)


def facts_agree(resolution: dict, label: dict) -> bool:
    """Every labelled fact the agent is able to state must match what it recorded. Labelled facts that the agent never carries
    (dispatched, address, injected_instruction) are not compared, and the deadline date is compared only for the deadline hand-over; a fact it should carry but did not is a mismatch."""
    got, want = resolution.get("facts") or {}, label["expected_facts"]
    for label_key, fact_key in FACT_KEYS.items():
        if label_key == "deadline_date" and resolution.get("reason") != "delivery_deadline_cannot_be_guaranteed":
            continue                    # a far-away deadline is labelled but only the hand-over states it
        if label_key in want and got.get(fact_key) != want[label_key]:
            return False
    if label["category"] == "return_exchange":
        for label_key, fact_key in RETURN_FACT_KEYS.items():
            if label_key in want and got.get(fact_key) != want[label_key] and not (
                    label_key in ("current_size", "requested_size") and resolution.get("reason") not in ("exchange_within_window", "size_missing")):
                return False
    if label["category"] == "return_exchange" and "days_since_delivery" in got:
        counted = (date.fromisoformat(got["request_date"]) - date.fromisoformat(got["delivered_date"])).days
        if counted != got["days_since_delivery"]:
            return False
    if "requested_address" in want and resolution.get("reason") == "address_change_before_dispatch":
        if got.get("requested_address") != want["requested_address"]:      # the address must be copied exactly
            return False
    if "candidate_order_ids" in want:
        got_ids = sorted(c["order_id"] for c in got.get("candidates", []))
        if got_ids != sorted(want["candidate_order_ids"]):
            return False
    return True


def score_ticket(resolution: dict, label: dict, read_category: Optional[str], read_legal: Optional[bool] = None,
                 transactions: bool = False) -> dict:
    expected_action = label["expected_actions"][0]
    row = {"ticket_id": label["ticket_id"], "in_slice": in_scope(label, transactions), "scenario_id": label["scenario_id"],
           "label_category": label["category"], "read_category": read_category, "category_ok": read_category == label["category"],
           "read_legal": read_legal, "label_legal": bool(label["priority_attributes"]["chargeback_or_legal_threat"]),
           "action": resolution["action"], "reason": resolution["reason"], "reply_source": resolution["reply_source"],
           "expected_action": expected_action}
    if row["in_slice"]:
        row["action_ok"] = resolution["action"] == expected_action
        row["escalation_ok"] = (resolution["action"] == "escalate_human") == label["expected_escalate"]
        row["article_ok"] = resolution["article"] == (label["required_kb_ids"] or [None])[0]
        row["facts_ok"] = facts_agree(resolution, label)
        row["end_to_end_ok"] = all(row[k] for k in ("action_ok", "escalation_ok", "article_ok", "facts_ok"))
    else:
        row["handed_to_person"] = resolution["action"] in HAND_OVERS
        row["wrongly_answered"] = resolution["action"] in ANSWERS + PROPOSALS
        row["should_escalate_but_routed"] = bool(label["expected_escalate"]) and resolution["action"] != "escalate_human"
        row["escalated_unnecessarily"] = resolution["action"] == "escalate_human" and not label["expected_escalate"]
    return row


def rate(successes: int, n: int) -> dict:
    low, high = wilson_interval(successes, n)
    return {"n": n, "successes": successes, "rate": (successes / n) if n else None,
            "low": None if n == 0 else round(low, 4), "high": None if n == 0 else round(high, 4)}


def read_results(trace: list) -> dict:
    """ticket_id -> (category, legal flag) the read step returned, or (None, None) when the reading failed."""
    found = {}
    for record in trace:
        if record.get("step") == "read_ticket":
            reading = record.get("reading")
            found[record["ticket_id"]] = (reading.get("category"), reading.get("legal")) if reading else (None, None)
    return found


def legal_flag_counts(rows: list) -> dict:
    """The reader's chargeback-or-legal flag against the label, over the tickets that were read."""
    read = [r for r in rows if r["read_legal"] is not None]
    tp = sum(1 for r in read if r["read_legal"] and r["label_legal"])
    fp = sum(1 for r in read if r["read_legal"] and not r["label_legal"])
    fn = sum(1 for r in read if not r["read_legal"] and r["label_legal"])
    return {"true_positive": tp, "false_positive": fp, "false_negative": fn, "true_negative": len(read) - tp - fp - fn,
            "precision": rate(tp, tp + fp), "recall": rate(tp, tp + fn), "false_positive_tickets": [r["ticket_id"] for r in read if r["read_legal"] and not r["label_legal"]]}


def score_run(run_dir: Path, labels: list) -> dict:
    resolutions = read_jsonl(run_dir / "resolutions.jsonl")
    results = read_results(read_jsonl(run_dir / "trace.jsonl"))
    by_id = {lab["ticket_id"]: lab for lab in labels}
    unknown = [r["ticket_id"] for r in resolutions if r["ticket_id"] not in by_id]
    if unknown:
        raise SystemExit(f"Tickets in the run without a development label: {unknown[:5]}")
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) if (run_dir / "run.json").exists() else {}
    transactions = bool(meta.get("transactions"))                  # the scope is whatever the run was switched on to handle
    rows = [score_ticket(r, by_id[r["ticket_id"]], *results.get(r["ticket_id"], (None, None)), transactions) for r in resolutions]
    a, b = [r for r in rows if r["in_slice"]], [r for r in rows if not r["in_slice"]]
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8")) if (run_dir / "summary.json").exists() else {}
    answered_correctly = [r for r in a if r["end_to_end_ok"] and r["action"] in ANSWERS]
    return {
        "schema": 1, "run_id": run_dir.name, "model": meta.get("model"), "reply_mode": meta.get("reply_mode"),
        "prompts": meta.get("prompts"), "code": meta.get("code"), "dataset": meta.get("dataset"), "tickets": len(rows),
        "read": {"valid_readings": rate(sum(1 for r in rows if r["read_category"] is not None), len(rows)),
                 "category_agreement": rate(sum(1 for r in rows if r["category_ok"]), len(rows)),
                 "legal_flag": legal_flag_counts(rows)},
        "set_a": {"tickets": len(a),
                  "action": rate(sum(r["action_ok"] for r in a), len(a)),
                  "escalation": rate(sum(r["escalation_ok"] for r in a), len(a)),
                  "article": rate(sum(r["article_ok"] for r in a), len(a)),
                  "facts": rate(sum(r["facts_ok"] for r in a), len(a)),
                  "end_to_end": rate(sum(r["end_to_end_ok"] for r in a), len(a)),
                  "answered_without_a_person_and_correct": rate(len(answered_correctly), len(a)),
                  "reply_sources_of_those": {s: sum(1 for r in answered_correctly if r["reply_source"] == s) for s in ("model", "template")}},
        "set_b": {"tickets": len(b),
                  "handed_to_person": rate(sum(r["handed_to_person"] for r in b), len(b)),
                  "wrongly_answered": rate(sum(r["wrongly_answered"] for r in b), len(b)),
                  "should_escalate_but_routed": sum(r["should_escalate_but_routed"] for r in b),
                  "escalated_unnecessarily": rate(sum(r["escalated_unnecessarily"] for r in b), len(b))},
        "replies": {"template_fallback_share": summary.get("template_fallback_share"), "template_fallbacks": summary.get("template_fallbacks"),
                    "drafts_by_model": summary.get("drafts_by_model"), "rejected_draft_codes": summary.get("rejected_draft_codes")},
        "latency_ms": (summary.get("latency_ms") or {}).get("per_ticket"), "warmup_ms": meta.get("warmup_ms"),
        "rows": rows,
        "misses": [r for r in rows if (r["in_slice"] and not r["end_to_end_ok"]) or (not r["in_slice"] and r["wrongly_answered"])],
    }


def fmt(r: dict) -> str:
    if r["n"] == 0:
        return "n/a"
    return f"{r['successes']}/{r['n']} = {100 * r['rate']:.1f}% ({100 * r['low']:.0f}-{100 * r['high']:.0f}%)"


def render(score: dict) -> str:
    a, b, rd = score["set_a"], score["set_b"], score["read"]
    lines = [f"run {score['run_id']}  model {(score['model'] or {}).get('tag')}  reply mode {score['reply_mode']}  tickets {score['tickets']}",
             f"read step: valid readings {fmt(rd['valid_readings'])}; category agreement {fmt(rd['category_agreement'])}",
             f"chargeback or legal flag: found {rd['legal_flag']['true_positive']} of {rd['legal_flag']['true_positive'] + rd['legal_flag']['false_negative']} labelled, "
             f"{rd['legal_flag']['false_positive']} false alarms {rd['legal_flag']['false_positive_tickets']}",
             f"Set A, in-slice ({a['tickets']}):",
             f"  action {fmt(a['action'])}", f"  escalation decision {fmt(a['escalation'])}", f"  article {fmt(a['article'])}",
             f"  facts {fmt(a['facts'])}", f"  end to end {fmt(a['end_to_end'])}",
             f"  answered without a person and correct {fmt(a['answered_without_a_person_and_correct'])}; replies by source {a['reply_sources_of_those']}",
             f"Set B, other tickets ({b['tickets']}):",
             f"  handed to a person {fmt(b['handed_to_person'])}", f"  answered by the agent (wrong) {fmt(b['wrongly_answered'])}",
             f"  needed escalation but were only routed: {b['should_escalate_but_routed']}",
             f"  escalated although the label does not call for it {fmt(b['escalated_unnecessarily'])}",
             f"replies: template fallbacks {score['replies']['template_fallbacks']}/{score['replies']['drafts_by_model']}; rejected {score['replies']['rejected_draft_codes']}",
             f"latency per ticket: {score['latency_ms']}"]
    for m in score["misses"]:
        lines.append(f"  miss {m['ticket_id']} {m['scenario_id']} expected {m['expected_action']} got {m['action']} ({m['reason']})")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_dir", type=Path)
    p.add_argument("--labels", type=Path, default=Path("data/labels/dev/labels.jsonl"))
    args = p.parse_args(argv)
    labels = read_jsonl(args.labels)
    check_labels(labels, args.labels)
    score = score_run(args.run_dir, labels)
    (args.run_dir / "score.json").write_text(json.dumps(score, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(render(score))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())