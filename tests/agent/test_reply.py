import pytest

from src.agent import decide as d
from src.agent.prompting import load_prompt
from src.agent.reply import (INSTRUCTIONS, REPLY_SCHEMA, compose, draft_reply, facts_for, first_name, fmt_date, render_facts,
                             render_system, template_body)
from src.agent.validate import validate_reply
from tests.agent.support import ScriptedModel

PROMPT = load_prompt("reply", "v1")
SHIPPED = {"order_id": "O-000123", "status": "shipped", "promised_date": "2026-10-10", "carrier": "TrailExpress",
           "tracking_no": "TR245437731580", "last_status": "In transit"}
BASE = {"order_id": "O-000123", "status": "processing", "promised_date": "2026-10-15"}
CANDIDATES = {"candidates": [{"order_id": "O-000628", "items": ["Ridgeline Merino Crew"]}, {"order_id": "O-000629", "items": ["Sierra Hiking Boot", "Trail Socks"]}]}

DECISIONS = {
    "order_processing": d.Decision(d.PROVIDE_INFO, "order_processing", "KB-ORD-01", BASE),
    "shipped_on_time": d.Decision(d.PROVIDE_INFO, "shipped_on_time", "KB-SHP-01", SHIPPED),
    "shipped_late": d.Decision(d.PROVIDE_INFO, "shipped_late", "KB-SHP-02", {**SHIPPED, "last_status": "In transit - delayed"}),
    "delivered": d.Decision(d.PROVIDE_INFO, "delivered", "KB-SHP-01", {**BASE, "status": "delivered", "delivered_date": "2026-10-04"}),
    "needs_order_number": d.Decision(d.REQUEST_INFO, "needs_order_number", "KB-ORD-02", CANDIDATES),
    "multiple_order_ids": d.Decision(d.REQUEST_INFO, "multiple_order_ids", "KB-ORD-02", {"candidates": [{"order_id": "O-000628"}, {"order_id": "O-000629"}]}),
    "order_not_found": d.Decision(d.REQUEST_INFO, "order_not_found", "KB-ORD-02"),
    "no_account": d.Decision(d.REQUEST_INFO, "no_account", "KB-ORD-02"),
    "delivery_deadline_cannot_be_guaranteed": d.Decision(d.ESCALATE_HUMAN, "delivery_deadline_cannot_be_guaranteed", "KB-SHP-03", {**BASE, "deadline_date": "2026-10-08"}),
    "order_not_owned": d.Decision(d.ESCALATE_HUMAN, "order_not_owned", "KB-SEC-01"),
    "chargeback_or_legal_threat": d.Decision(d.ESCALATE_HUMAN, "chargeback_or_legal_threat", "KB-REF-04"),
    "out_of_slice": d.Decision(d.ROUTE_TO_HUMAN, "out_of_slice", None),
    "reading_failed": d.Decision(d.ROUTE_TO_HUMAN, "reading_failed", None),
    "order_state_not_covered": d.Decision(d.ROUTE_TO_HUMAN, "order_state_not_covered", None),
}


@pytest.mark.parametrize("reason", sorted(DECISIONS))
def test_every_template_body_passes_the_validator(reason):
    decision = DECISIONS[reason]
    assert validate_reply(template_body(decision), facts_for(decision)) == [], reason


def test_every_model_drafted_reason_has_an_instruction():
    for reason, decision in DECISIONS.items():
        if decision.action in (d.PROVIDE_INFO, d.REQUEST_INFO):
            assert reason in INSTRUCTIONS


def test_escalation_templates_state_no_facts_and_no_promises():
    for reason in ("delivery_deadline_cannot_be_guaranteed", "order_not_owned", "chargeback_or_legal_threat", "out_of_slice"):
        body = template_body(DECISIONS[reason])
        assert "O-0" not in body and "2026" not in body
        assert facts_for(DECISIONS[reason]) == facts_for(d.Decision(d.ROUTE_TO_HUMAN, "x", None))


def test_privacy_reply_does_not_confirm_the_order_exists():
    body = template_body(DECISIONS["order_not_owned"]).lower()
    assert "order" in body and "belong" not in body and "another customer" not in body


def test_dates_and_names_are_formatted():
    assert fmt_date("2026-10-04T16:30:00") == "October 4, 2026"
    assert first_name("Ada Lovelace") == "Ada" and first_name("  ") == "" and first_name(None) == ""
    assert first_name("<script>Bob") == "scriptBob" and first_name("Zoë Q") == "Zo"
    assert compose("Ada", "Body.").startswith("Hello Ada,\n\nBody.") and compose("", "Body.").startswith("Hello,\n\n")


def test_system_prompt_contains_instruction_and_facts_only():
    text = render_system(PROMPT, DECISIONS["shipped_late"])
    assert "Tracking number: TR245437731580" in text and "checking with the carrier" in text
    assert "{" not in text.replace('{"body": "..."}', "")
    assert "Orders to choose from" in render_facts(DECISIONS["needs_order_number"])
    assert render_facts(DECISIONS["order_not_found"]) == "(none)"


GOOD_BODY = ("Your order O-000123 has been dispatched with TrailExpress. The tracking number is TR245437731580 and the promised "
             "delivery date is October 10, 2026.")


def test_a_valid_draft_is_used_and_attributed_to_the_model():
    model = ScriptedModel(reply=lambda s, u, seed: {"body": GOOD_BODY})
    out = draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada Lovelace")
    assert out.source == "model" and out.text.startswith("Hello Ada,") and GOOD_BODY in out.text and out.failures == []
    assert len(model.calls) == 1 and model.calls[0]["schema"] is REPLY_SCHEMA


def test_the_reply_model_never_sees_ticket_text():
    model = ScriptedModel(reply=lambda s, u, seed: {"body": GOOD_BODY})
    draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada")
    assert model.calls[0]["user"] == "Write the email body now."
    assert "ticket" not in model.calls[0]["system"].lower()


def test_a_rejected_draft_is_retried_once_with_a_new_seed():
    answers = iter([{"body": GOOD_BODY + " We will refund you."}, {"body": GOOD_BODY}])
    model = ScriptedModel(reply=lambda s, u, seed: next(answers))
    out = draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada", seed=4)
    assert out.source == "model" and out.failures == [["promise"]] and [c["seed"] for c in model.calls] == [4, 5]


def test_two_rejected_drafts_fall_back_to_the_template():
    model = ScriptedModel(reply=lambda s, u, seed: {"body": GOOD_BODY.replace("October 10", "October 12")})
    out = draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada")
    assert out.source == "template" and len(out.failures) == 2 and all("unknown_date" in f for f in out.failures) and len(model.calls) == 2
    assert "October 10, 2026" in out.text and "October 12" not in out.text


@pytest.mark.parametrize("answer", ["request_failed", {"wrong": "shape"}, {"body": 5}])
def test_model_failures_fall_back_to_the_template(answer):
    out = draft_reply(ScriptedModel(reply=lambda s, u, seed: answer), PROMPT, DECISIONS["order_processing"], "Ada")
    assert out.source == "template" and out.failures == [["model_error"], ["model_error"]]


def test_a_draft_that_omits_the_tracking_number_is_rejected():
    model = ScriptedModel(reply=lambda s, u, seed: {"body": "Your order O-000123 is on its way, due October 10, 2026."})
    assert draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada").failures[0] == ["missing_fact"]


@pytest.mark.parametrize("reason", ["delivery_deadline_cannot_be_guaranteed", "order_not_owned", "chargeback_or_legal_threat", "out_of_slice", "reading_failed"])
def test_hand_overs_use_templates_and_never_call_the_model(reason):
    model = ScriptedModel(reply=lambda s, u, seed: {"body": "ignored"})
    out = draft_reply(model, PROMPT, DECISIONS[reason], "Ada")
    assert out.source == "template" and model.calls == []


# ------------------------------------------------------------------ the retry tells the model what was wrong
def test_a_retry_names_the_facts_the_draft_left_out():
    short = "Your order O-000123 has been dispatched with TrailExpress and is in transit."
    answers = iter([{"body": short}, {"body": GOOD_BODY}])
    model = ScriptedModel(reply=lambda s, u, seed: next(answers))
    out = draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada")
    first, second = model.calls[0]["user"], model.calls[1]["user"]
    assert out.source == "model" and out.failures == [["missing_fact"]] and first == "Write the email body now."
    assert "TR245437731580" in second and "October 10, 2026" in second and "TrailExpress" not in second
    assert short not in second                                   # the rejected draft itself is not fed back
    assert out.hints == [second.split("rejected. ", 1)[1]]


def test_a_retry_after_a_promise_says_not_to_promise():
    answers = iter([{"body": GOOD_BODY + " We will refund you."}, {"body": GOOD_BODY}])
    model = ScriptedModel(reply=lambda s, u, seed: next(answers))
    draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada")
    assert "Do not mention refunds" in model.calls[1]["user"]


def test_retry_hints_use_only_codes_and_supplied_facts():
    from src.agent.reply import RETRY_HINTS, retry_hint
    facts = facts_for(DECISIONS["shipped_on_time"])
    assert retry_hint(["unknown_date", "promise"], GOOD_BODY, facts).count(".") >= 2
    assert retry_hint(["something_else"], GOOD_BODY, facts) == "Follow the facts exactly."
    assert set(RETRY_HINTS) <= {"unknown_date", "relative_time", "unknown_order", "unknown_token", "amount", "promise", "internal_text", "prompt_leak", "length",
                                   "missing_fact", "unsupported_claim", "misplaced_reference", "wrong_date_role"}


def test_a_model_error_draft_is_retried_without_a_hint():
    answers = iter(["request_failed", {"body": GOOD_BODY}])
    model = ScriptedModel(reply=lambda s, u, seed: next(answers))
    out = draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada")
    assert out.source == "model" and model.calls[1]["user"] == "Write the email body now." and out.hints == []


LATE_BODY = ("We apologise for the delay. Your order O-000123 is with TrailExpress, tracking number TR245437731580. "
             "It was promised for October 10, 2026 and we are checking with the carrier.")


def test_a_late_shipment_reply_must_say_promised():
    late = DECISIONS["shipped_late"]
    assert "promised" in facts_for(late).must_include
    facts = facts_for(late)
    assert "missing_fact" in validate_reply(LATE_BODY.replace("promised", "expected"), facts_to_reply_facts(late))


def facts_to_reply_facts(decision):
    from src.agent.validate import ReplyFacts
    from datetime import date
    f = decision.facts
    return ReplyFacts(frozenset({date.fromisoformat(f["promised_date"])}), frozenset({f["order_id"]}),
                      frozenset({f["tracking_no"]}), tuple(facts_for(decision).must_include))


def test_template_mode_makes_no_model_call_and_uses_the_template():
    model = ScriptedModel(reply=lambda s, u, seed: {"body": GOOD_BODY})
    out = draft_reply(model, PROMPT, DECISIONS["shipped_on_time"], "Ada", use_model=False)
    assert model.calls == [] and out.source == "template"


def test_only_an_undispatched_order_has_delivery_dates_only():
    assert facts_for(DECISIONS["order_processing"]).delivery_dates_only
    for name in ("shipped_on_time", "shipped_late", "delivered"):
        assert not facts_for(DECISIONS[name]).delivery_dates_only, name


def test_a_processing_reply_that_calls_the_promised_date_a_shipping_date_is_rejected_and_the_template_is_not():
    facts = facts_for(DECISIONS["order_processing"])
    bad = "Your order O-000123 has not been dispatched yet. We are expecting to ship it on October 15, 2026."
    good = "Your order O-000123 has not been dispatched yet. The promised delivery date is October 15, 2026."
    assert "wrong_date_role" in validate_reply(bad, facts) and "wrong_date_role" not in validate_reply(good, facts)
    assert "wrong_date_role" not in validate_reply(template_body(DECISIONS["order_processing"]), facts)