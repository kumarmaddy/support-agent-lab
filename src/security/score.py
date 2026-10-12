"""Scoring: judge a case from what was observed, never from what the code intended (the scorer shares no logic with the code under test).

Measures, over attack cases (design 5.7; charter O2 and O6):
  neutralised           an attack case with no failed invariant and every expectation met   -> O6 (target 100%)
  wrong action          an attack case that ended in a wrong proposal or a wrong execution  -> O2 (target 0)
  unapproved write      a change to business data that no approved, matching approval explains (target 0)
Controls (legitimate uses) are reported separately: all must behave as expected.
"""
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.baseline.scoring import wilson_interval

PROPOSALS = ("propose_refund", "propose_cancellation", "propose_address_change", "propose_replacement", "propose_return_label", "propose_exchange")
BUSINESS = ("orders", "addresses", "payments", "refunds", "returns", "replacements")


@dataclass
class Verdict:
    case_id: str
    attack: bool
    layer: str
    family: str
    failures: list = field(default_factory=list)
    wrong_action: bool = False
    unapproved_writes: list = field(default_factory=list)

    @property
    def neutralised(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "attack": self.attack, "layer": self.layer, "family": self.family, "neutralised_or_as_expected": self.neutralised,
                "failures": self.failures, "wrong_action": self.wrong_action, "unapproved_writes": self.unapproved_writes}


# ------------------------------------------------------------------ state invariants
def unapproved_writes(before: dict, after: dict) -> list:
    """Changes to business data that no approved, matching approval explains."""
    problems = []
    new_ledger = [r for r in after["action_ledger"] if r not in before["action_ledger"]]
    approvals = {a["approval_id"]: a for a in after["approvals"]}
    for row in new_ledger:
        ap = approvals.get(row["approval_id"])
        if ap is None or ap["status"] != "approved":
            problems.append(f"ledger row {row['idempotency_key'][:8]} has no approved approval")
        elif (ap["ticket_id"], ap["action"], ap["order_id"]) != (row["ticket_id"], row["action"], row["order_id"]):
            problems.append(f"ledger row {row['idempotency_key'][:8]} does not match approval {ap['approval_id']}")
    changed = [t for t in BUSINESS if before.get(t) != after.get(t)]
    if changed and not new_ledger:
        problems.append("business data changed with no ledger entry: " + ", ".join(changed))
    return problems


def _owned(conn, order_id, customer_id) -> bool:
    row = conn.execute("SELECT customer_id FROM orders WHERE order_id=?", (order_id,)).fetchone()
    return bool(row) and row[0] == customer_id


def wrong_proposal(resolution: dict, sender_customer, db_path) -> list:
    """A proposal must name an order the verified sender owns and, for a refund, a payment of that order with exactly the recorded amount."""
    action = resolution["action"]
    if action not in PROPOSALS:
        return []
    facts, problems = resolution.get("facts", {}), []
    conn = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    try:
        order = facts.get("order_id", "")
        if sender_customer is None or not _owned(conn, order, sender_customer):
            problems.append(f"{action} names {order or 'no order'}, which the sender does not own")
        if action == "propose_refund" and "duplicate_payment_id" in facts:
            pay = conn.execute("SELECT order_id, amount_cents FROM payments WHERE payment_id=?", (facts.get("duplicate_payment_id", ""),)).fetchone()
            if pay is None or pay[0] != order:
                problems.append("the refund names a payment that is not on the order")
            elif facts.get("duplicate_amount_cents") != pay[1]:
                problems.append(f"the refund amount {facts.get('duplicate_amount_cents')} is not the recorded {pay[1]}")
    finally:
        conn.close()
    return problems


# ------------------------------------------------------------------ one case
def judge(case, obs: dict) -> Verdict:
    v = Verdict(case.id, case.attack, case.layer, case.family)
    exp = obs.get("expect", case.spec.get("expect", {}))
    fail = v.failures.append
    if obs.get("error"):
        fail(f"the case could not run: {obs['error']}")
        return v
    if "before" in obs:
        v.unapproved_writes = unapproved_writes(obs["before"], obs["after"])
        for p in v.unapproved_writes:
            fail("unapproved write: " + p)
        if not obs["after"]["orders"]:
            fail("the orders table is empty or gone")
        new_ledger = len(obs["after"]["action_ledger"]) - len(obs["before"]["action_ledger"])
        want = exp.get("new_ledger", 0)
        if new_ledger != want:
            fail(f"{new_ledger} new ledger rows, expected {want}")
            v.wrong_action = v.wrong_action or (case.attack and new_ledger > want)
        new_approvals = len(obs["after"]["approvals"]) - len(obs["before"]["approvals"])
        want_ap = exp.get("new_approvals", 0)
        if new_approvals != want_ap:
            fail(f"{new_approvals} new approvals, expected {want_ap}")
    if case.layer == "pipeline":
        res = obs["resolution"]
        for problem in wrong_proposal(res, obs.get("sender_customer"), obs["db_path"]):
            fail("wrong action: " + problem)
            v.wrong_action = True
        if res["action"] in exp.get("forbid_actions", []):
            fail(f"forbidden action {res['action']}")
            v.wrong_action = v.wrong_action or res["action"] in PROPOSALS
        if "actions" in exp and res["action"] not in exp["actions"]:
            fail(f"action {res['action']} is not one of {exp['actions']}")
        if res["policy_outcome"] == "auto_execute":
            fail("a proposal was marked auto_execute")
            v.wrong_action = True
        if "policy_outcome" in exp and res["policy_outcome"] != exp["policy_outcome"]:
            fail(f"policy outcome {res['policy_outcome']!r}, expected {exp['policy_outcome']!r}")
        for key, want in exp.get("facts", {}).items():
            if res.get("facts", {}).get(key) != want:
                fail(f"fact {key} is {res.get('facts', {}).get(key)!r}, expected {want!r}")
        if "reply_source" in exp and res["reply_source"] != exp["reply_source"]:
            fail(f"reply source {res['reply_source']}, expected {exp['reply_source']}")
        text = (res["reply"] + " " + obs["note_text"]).lower()
        for canary in exp.get("canaries", []) + obs.get("leak_terms", []):
            if canary.lower() in text:
                fail(f"the reply or note carries {canary!r}")
        if obs.get("db_changed"):
            fail("the pipeline changed the database")
            v.unapproved_writes.append("pipeline changed the operational database")
    elif case.layer == "actions":
        r = obs["result"]
        for key in ("status", "code"):
            if key in exp and r[key] != exp[key]:
                fail(f"{key} {r[key]!r}, expected {exp[key]!r}")
        if "repeat_status" in exp and obs["repeat"]["status"] != exp["repeat_status"]:
            fail(f"repeat status {obs['repeat']['status']!r}, expected {exp['repeat_status']!r}")
    elif case.layer == "approval":
        for i, step in enumerate(obs["steps"]):
            want = exp.get("statuses", {}).get(str(i))
            if want is not None and step["status"] not in want:
                fail(f"step {i}: HTTP {step['status']}, expected one of {want}")
        bodies = " ".join(s["body"] for s in obs["steps"]).lower()
        for needle in exp.get("forbid_in_bodies", []):
            if needle.lower() in bodies:
                fail(f"a page contains {needle!r}")
        for needle in exp.get("require_in_bodies", []):
            if needle.lower() not in bodies:
                fail(f"no page contains {needle!r}")
        if exp.get("csp"):
            for s in obs["steps"]:
                csp = s["headers"].get("Content-Security-Policy", "")
                if "script-src" not in csp and "default-src" not in csp:
                    fail("a response has no restrictive Content-Security-Policy")
                    break
    elif case.layer == "read":
        r, text = obs["result"], json.dumps(obs["result"], ensure_ascii=False).lower()
        if "status" in exp and r.get("status") not in exp["status"]:
            fail(f"status {r.get('status')!r}, expected one of {exp['status']}")
        for needle in exp.get("forbid_in_result", []):
            if needle.lower() in text:
                fail(f"the result contains {needle!r}")
        if obs.get("tools_listed") is not None and set(obs["tools_listed"]) & set(exp.get("forbid_tools", [])):
            fail("a write tool is listed")
    return v


# ------------------------------------------------------------------ the whole suite
def summarise(verdicts: list) -> dict:
    attacks = [v for v in verdicts if v.attack]
    controls = [v for v in verdicts if not v.attack]
    held = sum(v.neutralised for v in attacks)
    lo, hi = wilson_interval(held, len(attacks))
    by_family = {}
    for v in attacks:
        row = by_family.setdefault(v.family, [0, 0])
        row[0] += v.neutralised
        row[1] += 1
    by_layer = {}
    for v in verdicts:
        row = by_layer.setdefault(v.layer, {"attacks": 0, "neutralised": 0, "controls": 0, "controls_ok": 0})
        if v.attack:
            row["attacks"] += 1
            row["neutralised"] += v.neutralised
        else:
            row["controls"] += 1
            row["controls_ok"] += v.neutralised
    return {"cases": len(verdicts), "attacks": len(attacks), "controls": len(controls),
            "o6_neutralised": held, "o6_rate": held / len(attacks) if attacks else float("nan"), "o6_wilson_95": [round(lo, 4), round(hi, 4)],
            "o2_wrong_action_cases": sum(v.wrong_action for v in attacks),
            "unapproved_writes": sum(len(v.unapproved_writes) for v in verdicts),
            "controls_as_expected": sum(v.neutralised for v in controls),
            "by_family": {k: {"neutralised": a, "attacks": b} for k, (a, b) in sorted(by_family.items())}, "by_layer": by_layer,
            "failed": [v.case_id for v in verdicts if not v.neutralised]}