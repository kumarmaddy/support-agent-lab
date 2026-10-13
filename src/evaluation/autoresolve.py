"""Stage 4.5: simulated limited auto-resolve, an offline replay of the stored, scored held-out 7B run.

Nothing is executed and no model is called. Eligibility uses only what the agent knew or produced (stage-4.5-acceptance.md section 2);
labels are used only afterwards, through the run's ``score.json`` rows, to judge the eligible tickets (section 3).

    python -m src.evaluation.autoresolve --run data\\runs\\run-20261012-145613-97bb60
"""
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

from src.baseline.scoring import wilson_interval
from src.evaluation.score import PROPOSALS, read_jsonl

ELIGIBLE_ACTIONS = ("provide_info", "request_info")
ELIGIBLE_CATEGORIES = ("order_status", "product_info")
UPPER_LIMIT = 0.05
Z = 1.96
MARKER = "heldout_run.json"
RULES = ("E1_action", "E2_category", "E3_flag", "E4_reply_source", "E5_citation")


def min_eligible_for_bound(limit: float = UPPER_LIMIT) -> int:
    """Smallest n at which zero wrong replies gives a Wilson upper bound at or below the limit: z^2 / (n + z^2) <= limit."""
    return math.ceil(Z * Z / limit - Z * Z)


def backstop_flagged(trace: list) -> set:
    return {r["ticket_id"] for r in trace if r.get("step") == "backstop" and r.get("outcome") == "flag_raised"}


def failed_rules(row: dict, resolution: dict, flagged: set, kb_ids: frozenset) -> list:
    """The eligibility conditions this ticket fails (empty = eligible). Agent-side facts only."""
    failed = []
    if resolution["action"] not in ELIGIBLE_ACTIONS:
        failed.append("E1_action")
    if row["read_category"] not in ELIGIBLE_CATEGORIES:
        failed.append("E2_category")
    if row["read_legal"] or row["read_compromise"] or row["ticket_id"] in flagged:
        failed.append("E3_flag")
    if resolution["reply_source"] != "model":
        failed.append("E4_reply_source")
    if resolution.get("article") is not None and resolution["article"] not in kb_ids:
        failed.append("E5_citation")
    return failed


def judge(row: dict) -> dict:
    """Judge one eligible ticket against its label (via the scorer's row)."""
    missed = bool(row["label_escalate"])
    consequential = row["expected_action"] in PROPOSALS
    wrong = (not row["in_slice"]) or (not row.get("end_to_end_ok", False)) or missed or consequential
    return {"wrong_reply": wrong, "missed_escalation": missed, "consequential_miss": consequential}


def rate(k: int, n: int) -> dict:
    low, high = wilson_interval(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "low": None if not n else round(low, 4), "high": None if not n else round(high, 4)}


def simulate(score: dict, resolutions: list, trace: list, kb_ids: frozenset) -> dict:
    rows = {r["ticket_id"]: r for r in score["rows"]}
    flagged = backstop_flagged(trace)
    eligible, only_one_rule, by_rule = [], {}, {rule: 0 for rule in RULES}
    for res in resolutions:
        row = rows[res["ticket_id"]]
        failed = failed_rules(row, res, flagged, kb_ids)
        for rule in failed:
            by_rule[rule] += 1
        if len(failed) == 1:
            only_one_rule.setdefault(failed[0], []).append(res["ticket_id"])
        if not failed:
            eligible.append((res, row, judge(row)))
    n = len(eligible)
    wrong = [r["ticket_id"] for _, r, j in eligible if j["wrong_reply"]]
    missed = [r["ticket_id"] for _, r, j in eligible if j["missed_escalation"]]
    conseq = [r["ticket_id"] for _, r, j in eligible if j["consequential_miss"]]
    wrong_rate = rate(len(wrong), n)
    in_scope = sum(1 for r in rows.values() if r["in_slice"])
    errors = bool(wrong or missed or conseq)
    meets = (not missed) and (not conseq) and n > 0 and wrong_rate["high"] <= UPPER_LIMIT
    if meets:
        verdict, reason = "acceptable for a supervised pilot", "all three conditions hold"
    else:
        verdict = "not yet acceptable"
        reason = "errors found" if errors else "not enough eligible tickets to show it"
    return {
        "schema": 1, "tickets": len(resolutions), "in_scope": in_scope,
        "eligible_of_all": rate(n, len(resolutions)), "eligible_of_in_scope": rate(sum(1 for _, r, _ in eligible if r["in_slice"]), in_scope),
        "eligible_by_action": {a: sum(1 for res, _, _ in eligible if res["action"] == a) for a in ELIGIBLE_ACTIONS},
        "eligible_by_category_read": {c: sum(1 for _, r, _ in eligible if r["read_category"] == c) for c in ELIGIBLE_CATEGORIES},
        "fails_by_rule": by_rule, "fails_only_one_rule": {k: sorted(v) for k, v in only_one_rule.items()},
        "wrong_replies": wrong_rate, "wrong_tickets": sorted(wrong),
        "missed_escalations": missed, "consequential_misses": conseq, "eligible_tickets": sorted(r["ticket_id"] for _, r, _ in eligible),
        "min_eligible_for_bound": min_eligible_for_bound(), "upper_limit": UPPER_LIMIT, "verdict": verdict, "reason": reason,
    }


def pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def render(result: dict, run_id: str, day: str) -> str:
    e, w = result["eligible_of_all"], result["wrong_replies"]
    lines = ["# Phase 4 Simulated Auto-resolve Results (stage 4.5)", "",
             f"Generated by `python -m src.evaluation.autoresolve` on {day}. Criteria: `stage-4.5-acceptance.md` (written before the run). Replay of `{run_id}`; nothing was executed and no model was called.", "",
             f"**Verdict: {result['verdict']}.** Reason: {result['reason']}.", "",
             "## 1. How many tickets would be eligible", "", "| Measure | Count | 95% interval |", "|---|---|---|",
             f"| Eligible, of all {result['tickets']} tickets | {e['k']} ({pct(e['rate'])}) | {pct(e['low'])} to {pct(e['high'])} |"]
    s = result["eligible_of_in_scope"]
    lines += [f"| Eligible, of the {result['in_scope']} in-scope tickets | {s['k']} ({pct(s['rate'])}) | {pct(s['low'])} to {pct(s['high'])} |", "",
              "| Eligible by action | Tickets |", "|---|---|"]
    lines += [f"| `{a}` | {n} |" for a, n in result["eligible_by_action"].items()]
    lines += ["", "| Condition | Tickets failing it | Tickets whose only failure it is |", "|---|---|---|"]
    names = {"E1_action": "E1 action is provide_info or request_info", "E2_category": "E2 category read is order_status or product_info",
             "E3_flag": "E3 no escalation flag", "E4_reply_source": "E4 reply from the model (no template)", "E5_citation": "E5 cited article exists"}
    for rule in RULES:
        lines.append(f"| {names[rule]} | {result['fails_by_rule'][rule]} | {len(result['fails_only_one_rule'].get(rule, []))} |")
    lines += ["", "## 2. How the eligible replies would have fared", "", "| Measure | Result |", "|---|---|",
              f"| Wrong replies | {w['k']} of {w['n']} ({pct(w['rate'])}); 95% interval {pct(w['low'])} to {pct(w['high'])} |",
              f"| Missed escalations | {len(result['missed_escalations'])}" + (f" ({', '.join(result['missed_escalations'])})" if result["missed_escalations"] else "") + " |",
              f"| Consequential misses | {len(result['consequential_misses'])}" + (f" ({', '.join(result['consequential_misses'])})" if result["consequential_misses"] else "") + " |"]
    if result["wrong_tickets"]:
        lines += ["", "Wrong replies by ticket: " + ", ".join(result["wrong_tickets"]) + "."]
    lines += ["", "## 3. Decision rule", "",
              f"Acceptable for a supervised pilot only if there are no missed escalations and no consequential misses, and the wrong-reply upper bound is {pct(result['upper_limit'])} or less.",
              f"With no wrong replies, that bound needs at least {result['min_eligible_for_bound']} eligible tickets; this replay has {e['k']}.", "",
              f"Result: **{result['verdict']}** ({result['reason']}).", ""]
    if result["reason"].startswith("not enough"):
        lines += ["This does not mean the replies were bad. It means 150 held-out tickets, with this narrow eligibility rule, cannot show that the wrong-reply rate is below 5%.", ""]
    lines += ["## 4. Limits", "",
              "- One run, one model, temperature 0, 150 synthetic tickets. A replay, not a pilot.",
              "- Judged by the labels (action, escalation, article, facts); tone and wording are not graded.",
              "- Eligibility is narrow and was fixed before the data. A wider rule would be a new experiment on a new split.",
              "- Review time saved is not computed here; stage 4.6 applies its review-time grid. Shadow-mode review timings were not a valid measure.", ""]
    return "\n".join(lines)


def load_kb_ids(kb_dir: Path) -> frozenset:
    return frozenset(p.stem for p in Path(kb_dir).glob("KB-*.md"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Simulated limited auto-resolve on a stored held-out run.")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    parser.add_argument("--report", type=Path, default=Path("docs/project/phase-4-autoresolve-results.md"))
    args = parser.parse_args(argv)
    run = args.run
    marker = run / MARKER
    if not marker.exists() or json.loads(marker.read_text(encoding="utf-8")).get("status") != "complete":
        print("This is not a complete run made by the held-out gate (no heldout_run.json), so it is not simulated.")
        return 2
    if not (run / "score.json").exists():
        print("The run has no score.json; score it with `python -m src.evaluation.heldout score` first.")
        return 2
    score = json.loads((run / "score.json").read_text(encoding="utf-8"))
    result = simulate(score, read_jsonl(run / "resolutions.jsonl"), read_jsonl(run / "trace.jsonl"), load_kb_ids(args.kb))
    (run / "autoresolve.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    text = render(result, run.name, date.today().isoformat())
    args.report.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())