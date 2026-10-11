"""Stage 3.2: the policy decision on every proposal, in the pipeline, the note, the trace and the runner."""
import json
from pathlib import Path

import pytest

from src.agent import decide as d
from src.agent import run as runner
from src.agent.handover import SENIOR, STANDARD
from src.agent.pipeline import POLICY_ACTIONS, run_ticket
from src.agent.policy import DEFAULT_RULE_ID, load_policy, parse_policy
from src.agent.tools import INVALID, NOT_FOUND, OK, TOOL_SCHEMAS, Toolbox
from src.agent.tracing import TraceWriter, read_jsonl
from tests.agent.support import ScriptedModel, oracle_read
from tests.agent.test_handover import READ, REPLY, TX, TOPIC, world  # noqa: F401  (the fixture)

SHIPPED = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.toml")
DEFAULT_TICKET, SENIOR_TICKET, ITEM_TICKET, LABEL_TICKET = "T-000029", "T-000149", "T-000046", "T-000009"


def run(world, ticket_id, policy):
    box, by_id, internal = world
    topic = {"topic": TOPIC.get(by_id[ticket_id]["scenario_id"], "duplicate_charge")}
    request = {"request": "return", "item": "", "requested_size": ""}
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ticket_id), extract=lambda s, u, seed: topic if '"topic"' in s else request)
    return run_ticket(box, model, READ, REPLY, internal, ticket_id, 0, "template", None, TX, policy)


def custom(text, switch=False):
    return parse_policy(f'[engine]\nversion = "t"\nauto_execute_enabled = {str(switch).lower()}\n{text}'.encode())


def test_without_a_policy_nothing_changes(world):
    res = run(world, DEFAULT_TICKET, None)
    assert res.policy is None and "policy" not in [s["step"] for s in res.steps]
    assert res.action == d.PROPOSE_REFUND and res.handover["policy_rule"] == "" and "Policy rule" not in "\n".join(res.handover["records"])


def test_every_proposal_gets_a_policy_decision_with_the_rule_and_the_hash(world):
    for tid in (DEFAULT_TICKET, ITEM_TICKET, LABEL_TICKET, "T-000011"):               # refund, item refund, return label, cancellation
        res = run(world, tid, SHIPPED)
        assert res.action in POLICY_ACTIONS, tid
        assert res.policy["rule_id"] == DEFAULT_RULE_ID and res.policy["outcome"] == "require_approval"
        assert res.policy["policy_sha256"] == SHIPPED.sha256
        step = next(s for s in res.steps if s["step"] == "policy")
        assert step["rule_id"] == DEFAULT_RULE_ID and step["policy_sha256"] == SHIPPED.sha256
        assert res.handover["policy_rule"] == DEFAULT_RULE_ID and res.handover["queue"] == STANDARD


def test_a_large_refund_goes_to_the_senior_queue_using_the_amount_on_the_record(world):
    box, _, _ = world
    res = run(world, SENIOR_TICKET, SHIPPED)
    assert res.action == d.PROPOSE_REFUND and res.policy["rule_id"] == "APPROVE-REFUND-SENIOR" and res.policy["queue"] == SENIOR
    assert res.handover["queue"] == SENIOR and res.handover["policy_rule"] == "APPROVE-REFUND-SENIOR"
    assert res.policy["evidence"]["amount_cents_gte"] == res.facts["duplicate_amount_cents"] >= 25000
    assert "Policy rule: APPROVE-REFUND-SENIOR (require_approval)." in runner_note(res)


def runner_note(res):
    from src.agent.handover import Handover
    note = Handover(**{**res.handover, "order_ids": tuple(res.handover["order_ids"]), "records": tuple(res.handover["records"])})
    return note.render()


def test_an_item_refund_states_no_amount_so_no_amount_rule_matches(world):
    res = run(world, ITEM_TICKET, SHIPPED)
    assert res.reason == "item_refund_within_window" and res.policy["rule_id"] == DEFAULT_RULE_ID


def test_a_denied_action_is_handed_to_a_person_and_nothing_is_proposed(world):
    deny = custom('[[rule]]\nid = "NO-REFUNDS"\noutcome = "deny"\nreason = "no"\n[rule.when]\naction = ["refund"]\n')
    res = run(world, DEFAULT_TICKET, deny)
    assert (res.action, res.reason) == (d.ROUTE_TO_HUMAN, "policy_denied")
    assert res.policy["outcome"] == "deny" and res.policy["rule_id"] == "NO-REFUNDS"
    assert res.handover["policy_rule"] == "NO-REFUNDS" and res.handover["approval_required"] is False
    assert res.reply_source == "template" and "refund" not in res.reply.lower() and "$" not in res.reply
    assert "duplicate_amount_cents" in res.facts                                     # verified facts stay for the person; approval flag removed
    assert "approval_required" not in res.facts


def test_an_action_the_policy_does_not_cover_still_needs_approval(world):
    only_refunds = custom('[[rule]]\nid = "X"\noutcome = "deny"\nreason = "x"\n[rule.when]\naction = ["refund"]\n')
    assert run(world, LABEL_TICKET, only_refunds).policy["rule_id"] == DEFAULT_RULE_ID


def test_auto_execute_is_decided_but_the_pipeline_still_only_proposes(world):
    rule = '[[rule]]\nid = "AUTO-LABEL"\noutcome = "auto_execute"\nreason = "ok"\n[rule.when]\naction = ["return_label"]\n'
    on, off = run(world, LABEL_TICKET, custom(rule, True)), run(world, LABEL_TICKET, custom(rule, False))
    assert (on.policy["outcome"], on.action) == ("auto_execute", d.PROPOSE_RETURN_LABEL)       # no write tool exists in this stage
    assert (off.policy["outcome"], off.policy["rule_id"]) == ("require_approval", "AUTO-LABEL")


def test_a_ticket_that_is_not_a_proposal_has_no_policy_decision(world):
    res = run(world, "T-000015", SHIPPED)                                              # a legal threat: escalated, not proposed
    assert res.action == d.ESCALATE_HUMAN and res.policy is None and "policy" not in [s["step"] for s in res.steps]


def test_the_policy_decision_is_written_to_the_trace_and_the_run_records_the_rules(world, tmp_path):
    res = run(world, SENIOR_TICKET, SHIPPED)
    box, _, _ = world
    meta = runner.build_meta(ScriptedModel(), READ, REPLY, Path(box.conn.execute("PRAGMA database_list").fetchone()[2]), 0, [SENIOR_TICKET], policy=SHIPPED)
    assert meta["policy"] == {"version": SHIPPED.version, "sha256": SHIPPED.sha256, "rules": [r.rule_id for r in SHIPPED.rules], "auto_execute_enabled": False}
    with TraceWriter(tmp_path, "run-x", meta) as writer:
        writer.write(res)
    line = read_jsonl(tmp_path / "run-x" / "resolutions.jsonl")[0]
    assert line["policy"]["rule_id"] == "APPROVE-REFUND-SENIOR" and line["handover"]["policy_rule"] == "APPROVE-REFUND-SENIOR"
    assert json.loads((tmp_path / "run-x" / "run.json").read_text())["policy"]["sha256"] == SHIPPED.sha256
    assert any(s["step"] == "policy" for s in read_jsonl(tmp_path / "run-x" / "trace.jsonl"))


def test_the_runner_refuses_to_start_on_a_bad_policy(tmp_path):
    bad = tmp_path / "policy.toml"
    bad.write_text('[engine]\nversion = "t"\n[[rule]]\nid = "R"\noutcome = "allow"\nreason = "r"\n[rule.when]\naction = ["refund"]\n')
    with pytest.raises(SystemExit) as stop:
        runner.main(["--policy", str(bad), "--limit", "1"])
    assert "Policy error" in str(stop.value)
    with pytest.raises(SystemExit) as gone:
        runner.main(["--policy", str(tmp_path / "missing.toml"), "--limit", "1"])
    assert "Policy error" in str(gone.value)


# ------------------------------------------------------------------ the refund-history tool
def test_count_refunds_is_a_read_only_tool_with_a_schema(world):
    box, _, _ = world
    assert "count_refunds" in TOOL_SCHEMAS
    row = box.conn.execute("SELECT o.customer_id, COUNT(*) FROM refunds r JOIN payments p USING (payment_id) JOIN orders o USING (order_id) "
                           "GROUP BY o.customer_id ORDER BY 2 DESC LIMIT 1").fetchone()
    assert box.call("count_refunds", {"customer_id": row[0]}) == {"status": OK, "data": row[1], "detail": ""}
    quiet = box.conn.execute("SELECT customer_id FROM customers WHERE customer_id NOT IN (SELECT o.customer_id FROM refunds r JOIN payments p USING (payment_id) "
                             "JOIN orders o USING (order_id)) LIMIT 1").fetchone()[0]
    assert box.call("count_refunds", {"customer_id": quiet})["data"] == 0
    assert box.call("count_refunds", {"customer_id": "C-999999"})["status"] == NOT_FOUND
    assert box.call("count_refunds", {"customer_id": "bad"})["status"] == INVALID


# ------------------------------------------------------------------ the request is built from the records
def test_the_policy_request_uses_the_tier_order_age_and_refund_history_from_the_records(world):
    box, _, _ = world
    ticket = box.get_ticket(DEFAULT_TICKET).data
    tier, customer = box.conn.execute("SELECT tier, customer_id FROM customers WHERE lower(email) = lower(?)", (ticket.customer_email,)).fetchone()
    prior = box.count_refunds(customer).data
    first = run(world, DEFAULT_TICKET, SHIPPED)
    order = box.get_order(first.facts["order_id"], customer).data
    from datetime import date
    age = (date.fromisoformat(ticket.received_at[:10]) - date.fromisoformat(order.placed_at[:10])).days

    def deny(**conditions):
        lines = "".join(f"{k} = {json.dumps(v)}\n" for k, v in conditions.items())
        return custom(f'[[rule]]\nid = "PROBE"\noutcome = "deny"\nreason = "probe"\n[rule.when]\n{lines}')

    exact = dict(action=["refund"], reason=["duplicate_charge"], customer_tier=[tier], order_age_days_gte=age, order_age_days_lte=age,
                 prior_refunds_gte=prior, legal_flag=False, payment_already_refunded=False, amount_exceeds_payment=False, amount_cents_lte=first.facts["duplicate_amount_cents"])
    assert run(world, DEFAULT_TICKET, deny(**exact)).policy["rule_id"] == "PROBE"
    for key, wrong in (("customer_tier", ["nobody"]), ("order_age_days_gte", age + 1), ("order_age_days_lte", age - 1), ("prior_refunds_gte", prior + 1),
                       ("amount_cents_lte", first.facts["duplicate_amount_cents"] - 1)):
        assert run(world, DEFAULT_TICKET, deny(**{**exact, key: wrong})).policy["rule_id"] == DEFAULT_RULE_ID, key


def test_a_denied_action_is_never_worded_by_the_model():
    from src.agent.reply import TEMPLATE_ONLY
    assert "policy_denied" in TEMPLATE_ONLY