"""Stage 3.3: the must-escalate rules (phase-3-design.md, section 5.2; stage-3.3-acceptance.md).

S18 suspected compromise (read prompt v5), S20 knowledge gap (escalated, not routed), S25 identity not verified (a named order that is
someone else's is escalated even in a category the agent does not handle)."""
from datetime import date
from pathlib import Path

from src.agent import decide as d
from src.agent import run as runner
from src.agent.decide import Identity
from src.agent.handover import SENIOR
from src.agent.knowledge import NOT_FOUND
from src.agent.pipeline import run_ticket
from src.agent.policy import DENY, PolicyRequest, evaluate, load_policy
from src.agent.prompting import load_prompt
from src.agent.reading import (FIELDS, FIELDS_V5, READ_SCHEMA, READ_SCHEMA_V5, Reading, diagnose_reading, has_compromise_field, read_ticket,
                               schema_for)
from src.agent.tools import Customer
from src.agent.tracing import TraceWriter
from src.evaluation.score import compromise_flag_counts, escalation_counts, read_compromise_results, render, score_run
from tests.agent.support import ScriptedModel, oracle_read
from tests.agent.test_handover import REPLY, TX, world  # noqa: F401  (the fixture)
from src.kb.articles import load_articles
from src.kb.retrieve import Hit
from tests.agent.test_knowledge import knowledge

V4, V5 = load_prompt("read_ticket", "v4"), load_prompt("read_ticket", "v5")
OK3 = {"category": "account", "deadline_phrase": "", "mentions_chargeback_or_legal": False}
OK4 = {**OK3, "account_compromise_suspected": True}


# ------------------------------------------------------------------ the read step
def test_prompt_v5_asks_for_four_fields_and_earlier_prompts_for_three():
    assert has_compromise_field(V5) and not has_compromise_field(V4)
    assert schema_for(V5) is READ_SCHEMA_V5 and schema_for(V4) is READ_SCHEMA
    assert READ_SCHEMA_V5["required"] == list(FIELDS_V5) and READ_SCHEMA["required"] == list(FIELDS)
    assert READ_SCHEMA_V5["properties"]["account_compromise_suspected"] == {"type": "boolean"} and READ_SCHEMA_V5["additionalProperties"] is False
    assert "account_compromise_suspected" in V5.text and "account_compromise_suspected" not in V4.text and "{categories}" in V5.text


def test_the_checker_accepts_exactly_the_fields_the_prompt_asks_for():
    ok4 = diagnose_reading(OK4, (), "", FIELDS_V5)[0]
    assert ok4.account_compromise_suspected is True
    assert diagnose_reading(OK3, (), "")[0].account_compromise_suspected is False            # a three-field prompt: the flag is False
    assert diagnose_reading(OK3, (), "", FIELDS_V5)[0] is None                                 # v5 answer missing its field
    assert diagnose_reading(OK4, (), "", FIELDS)[0] is None                                    # v4 answer with a field it was not asked for
    bad, why = diagnose_reading({**OK4, "account_compromise_suspected": "yes"}, (), "", FIELDS_V5)
    assert bad is None and "true or false" in why
    assert "category, deadline_phrase, mentions_chargeback_or_legal and account_compromise_suspected" in diagnose_reading({}, (), "", FIELDS_V5)[1]
    assert "category, deadline_phrase and mentions_chargeback_or_legal." in diagnose_reading({}, (), "")[1]


def test_read_ticket_with_v5_sends_the_four_field_schema_and_returns_the_flag():
    model = ScriptedModel(read=lambda s, u, seed: OK4)
    out = read_ticket(model, V5, "Hacked", "Someone changed my password.")
    assert out.ok and out.reading.account_compromise_suspected is True and model.calls[0]["schema"] == READ_SCHEMA_V5
    old = ScriptedModel(read=lambda s, u, seed: OK3)
    assert read_ticket(old, V4, "s", "b").reading.account_compromise_suspected is False and old.calls[0]["schema"] == READ_SCHEMA


def test_a_v5_answer_without_the_flag_is_retried_with_a_hint():
    answers = iter([OK3, OK4])
    model = ScriptedModel(read=lambda s, u, seed: next(answers))
    out = read_ticket(model, V5, "s", "b")
    assert out.ok and out.reading.account_compromise_suspected and "account_compromise_suspected" in out.hints[0]


def test_warm_up_uses_the_schema_of_the_prompt():
    model = ScriptedModel(read=lambda s, u, seed: OK4)
    runner.warm_up(model, V5)
    assert model.calls[0]["schema"] == READ_SCHEMA_V5


# ------------------------------------------------------------------ the decision
def reading(category="account", compromise=True, legal=False, ids=()):
    return Reading(category, "", legal, ids, compromise)


def test_a_suspected_compromise_is_escalated_in_any_category_without_a_lookup():
    for category in ("account", "order_status", "refund", "cancellation", "other", "product_info"):
        r = reading(category)
        assert d.requires_lookup(r) is False
        dec = d.decide(r, None, date(2026, 10, 1))
        assert (dec.action, dec.reason, dec.article, dec.facts) == (d.ESCALATE_HUMAN, "account_compromise_suspected", "KB-ACC-03", {})


def test_a_legal_threat_is_decided_before_a_compromise():
    dec = d.decide(reading(legal=True), None, date(2026, 10, 1))
    assert dec.reason == "chargeback_or_legal_threat"


def test_a_ticket_without_the_flag_is_unchanged():
    r = reading("account", compromise=False)
    assert d.requires_lookup(r) is False and d.decide(r, None, date(2026, 10, 1)).reason == "out_of_slice"


def test_only_the_other_category_with_a_named_order_is_looked_up_outside_the_scope():
    assert d.requires_lookup(reading("other", False, ids=("O-000001",))) is True
    assert d.requires_lookup(reading("other", False)) is False
    assert d.requires_lookup(reading("account", False, ids=("O-000001",))) is False
    assert d.requires_lookup(reading("refund", False, ids=("O-000001",))) is False               # outside the Phase 1 scope: no lookup


def test_an_out_of_scope_ticket_naming_someone_elses_order_is_escalated():
    customer, today = Customer("C-1", "A B", "a@example.com", "standard", "active"), date(2026, 10, 1)
    r = reading("other", False, ids=("O-000001",))
    dec = d.decide(r, Identity(d.ORDER_NOT_OWNED, customer), today)
    assert (dec.action, dec.reason, dec.article) == (d.ESCALATE_HUMAN, "order_not_owned", "KB-SEC-01")
    assert d.decide(r, Identity(d.ORDER_NOT_FOUND, customer), today).reason == "out_of_slice"      # unknown order: still only routed
    assert d.decide(r, Identity(d.NO_ACCOUNT), today).reason == "out_of_slice"
    # the lookup is made only for category "other" (requires_lookup); whenever an identity says the order is not the sender's it is escalated
    assert d.decide(reading("account", False), Identity(d.ORDER_NOT_OWNED, customer), today).reason == "order_not_owned"


# ------------------------------------------------------------------ the pipeline on the development tickets
def run5(world, tid, k=None, read=None, check=None):
    box, by_id, internal = world
    flag = bool(by_id[tid]["priority_attributes"]["account_compromise_suspected"])
    answer = read or (lambda s, u, seed: {**oracle_read(by_id, box, tid), "account_compromise_suspected": flag})
    model = ScriptedModel(read=answer, check=check)
    return run_ticket(box, model, V5, REPLY, internal, tid, 0, "template", k, TX, load_policy("config/policy.toml")), model


def tickets(world, scenario):
    return sorted(t for t, lab in world[1].items() if lab["scenario_id"] == scenario)


def test_all_five_s18_tickets_are_escalated_to_the_senior_queue_with_no_promise(world):
    found = tickets(world, "S18")
    assert len(found) == 5
    for tid in found:
        res, model = run5(world, tid)
        assert (res.action, res.reason, res.article) == (d.ESCALATE_HUMAN, "account_compromise_suspected", "KB-ACC-03"), tid
        assert res.handover["queue"] == SENIOR and res.handover["account"] == "not_looked_up" and res.handover["customer_id"] is None
        steps = [s["step"] for s in res.steps]
        assert "identify" not in steps and "policy" not in steps and "knowledge" not in steps and len(model.calls) == 1
        assert next(s for s in res.steps if s["step"] == "read_ticket")["reading"]["compromise"] is True
        low = res.reply.lower()
        assert "senior colleague" in low and "do not share your password" in low
        assert not any(word in low for word in ("reset", "secured", "locked", "we have changed", "refund", "$"))


def test_the_knowledge_path_is_never_tried_for_a_flagged_ticket(world):
    tid = tickets(world, "S18")[0]
    k = knowledge(load_articles("data/seed/kb"), [Hit("KB-ACC-03", 0.95)])
    res, model = run5(world, tid, k, read=lambda s, u, seed: {"category": "product_info", "deadline_phrase": "", "mentions_chargeback_or_legal": False,
                                                              "account_compromise_suspected": True})
    assert res.reason == "account_compromise_suspected" and k.retriever.queries == [] and len(model.calls) == 1


def test_a_knowledge_gap_is_escalated_to_the_senior_queue(world):
    s20 = tickets(world, "S20")
    assert len(s20) == 5
    k = knowledge(load_articles("data/seed/kb"), [Hit("KB-SIZ-01", 0.40)])
    for tid in s20:
        res, model = run5(world, tid, k, read=lambda s, u, seed: {"category": "product_info", "deadline_phrase": "", "mentions_chargeback_or_legal": False,
                                                                 "account_compromise_suspected": False})
        assert (res.action, res.reason, res.article) == (d.ESCALATE_HUMAN, NOT_FOUND, None), tid
        assert res.handover["queue"] == SENIOR and "passed" in res.reply and res.reply_source == "template"


def test_a_weak_match_that_fails_the_check_is_still_only_routed(world):
    tid = tickets(world, "S20")[0]
    k = knowledge(load_articles("data/seed/kb"), [Hit("KB-SIZ-01", 0.90)])
    res, _ = run5(world, tid, k, check=lambda s, u, seed: {"answers_question": False},
                  read=lambda s, u, seed: {"category": "product_info", "deadline_phrase": "", "mentions_chargeback_or_legal": False, "account_compromise_suspected": False})
    assert (res.action, res.reason) == (d.ROUTE_TO_HUMAN, "knowledge_not_answered")


def test_the_impersonation_ticket_that_was_only_routed_is_now_escalated(world):
    outcomes = {}
    for tid in tickets(world, "S25"):
        res, _ = run5(world, tid)
        outcomes[tid] = (res.action, res.reason)
    assert len(outcomes) == 4 and set(outcomes.values()) == {(d.ESCALATE_HUMAN, "order_not_owned")}, outcomes
    box = world[0]
    assert all(box.get_ticket(t).data for t in outcomes)


def test_no_other_development_ticket_is_flagged_or_escalated_for_these_reasons_with_a_perfect_reader(world):
    box, by_id, _ = world
    reasons = {}
    for tid in sorted(by_id):
        res, _ = run5(world, tid)
        reasons.setdefault(res.reason, []).append(tid)
    assert sorted(reasons["account_compromise_suspected"]) == tickets(world, "S18")
    assert "knowledge_not_found" not in reasons                               # no knowledge object in this run: the S20 tickets are out of slice
    assert sorted(t for t in reasons.get("order_not_owned", [])) == sorted(t for t in by_id if by_id[t]["escalation_reason"] == "identity_not_verified")


# ------------------------------------------------------------------ the policy engine's second check
def test_the_shipped_policy_denies_any_action_on_a_flagged_account():
    p = load_policy("config/policy.toml")
    for action in ("refund", "cancel_order", "change_address"):
        decision = evaluate(PolicyRequest(action, compromise_flag=True), p)
        assert (decision.outcome, decision.rule_id) == (DENY, "DENY-ACTION-ON-COMPROMISED-ACCOUNT")
    assert evaluate(PolicyRequest("refund", compromise_flag=False), p).outcome != DENY


# ------------------------------------------------------------------ the scorer
def row(tid, read_c=None, label_c=False, escalated=False, label_e=False):
    return {"ticket_id": tid, "read_compromise": read_c, "label_compromise": label_c, "escalated": escalated, "label_escalate": label_e}


def test_compromise_flag_counts():
    rows = [row("a", True, True), row("b", False, True), row("c", True, False), row("d", False, False), row("e", None, True)]
    c = compromise_flag_counts(rows)
    assert (c["read"], c["true_positive"], c["false_positive"], c["false_negative"]) == (4, 1, 1, 1)
    assert c["false_positive_tickets"] == ["c"] and c["missed_tickets"] == ["b"]
    assert compromise_flag_counts([row("a")])["read"] == 0


def test_escalation_counts_cover_all_tickets():
    rows = [row("a", escalated=True, label_e=True), row("b", escalated=False, label_e=True), row("c", escalated=True, label_e=False),
            row("d"), row("e", escalated=True, label_e=True)]
    e = escalation_counts(rows)
    assert (e["labelled_must_escalate"], e["escalated"]) == (3, 3)
    assert (e["recall"]["successes"], e["recall"]["n"], e["precision"]["successes"], e["precision"]["n"]) == (2, 3, 2, 3)
    assert e["missed_tickets"] == ["b"] and e["unnecessary_tickets"] == ["c"]


def test_read_compromise_results_come_from_the_read_step_only():
    trace = [{"step": "read_ticket", "ticket_id": "T-1", "reading": {"category": "account", "legal": False, "compromise": True}},
             {"step": "read_ticket", "ticket_id": "T-2", "reading": None},
             {"step": "read_ticket", "ticket_id": "T-3", "reading": {"category": "account", "legal": False}},
             {"step": "decide", "ticket_id": "T-1"}]
    assert read_compromise_results(trace) == {"T-1": True, "T-2": None, "T-3": None}


def test_a_scored_run_reports_the_flag_and_the_escalation_counts(world, tmp_path):
    box, by_id, _ = world
    ids = tickets(world, "S18") + tickets(world, "S25")[:2] + tickets(world, "S20")[:1]
    meta = runner.build_meta(ScriptedModel(), V5, REPLY, Path(box.conn.execute("PRAGMA database_list").fetchone()[2]), 0, ids)
    with TraceWriter(tmp_path, "run-x", meta) as writer:
        for tid in ids:
            writer.write(run5(world, tid)[0])
    labels = [by_id[t] for t in ids]
    score = score_run(tmp_path / "run-x", labels)
    assert score["read"]["compromise_flag"]["true_positive"] == 5 and score["read"]["compromise_flag"]["false_positive"] == 0
    assert score["escalation"]["escalated"] == 7 and score["escalation"]["missed_tickets"] == tickets(world, "S20")[:1]
    text = render(score)
    assert "account compromise flag: found 5 of 5 labelled, 0 false alarms []" in text and "escalation over all tickets: 7 escalated" in text


def test_prompt_v6_is_the_three_b_family_prompt_v3_with_the_same_fourth_field():
    v3, v5, v6 = (load_prompt("read_ticket", v) for v in ("v3", "v5", "v6"))
    assert has_compromise_field(v6) and "{categories}" in v6.text and "{rules}" in v6.text
    field4 = v5.text[v5.text.index("4. account_compromise_suspected"):v5.text.index("Answer with JSON only.")]
    assert field4 in v6.text and "Fill in exactly four fields." in v6.text
    assert "All of these are false: being unhappy or angry; asking for a refund" not in v6.text            # v4's longer legal wording is not in v6
    assert v6.text.replace(field4, "").replace("four fields", "three fields") == v3.text