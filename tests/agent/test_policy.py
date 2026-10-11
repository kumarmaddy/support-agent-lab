"""Stage 3.2: the policy engine as a pure function, and the loading of its rules (phase-3-design.md, section 5.1)."""
import hashlib
from pathlib import Path

import pytest

from src.agent.policy import (AUTO_EXECUTE, DEFAULT_RULE_ID, DENY, REQUIRE_APPROVAL, SENIOR, STANDARD, PolicyError, PolicyRequest,
                              evaluate, load_policy, parse_policy)

SHIPPED = Path(__file__).resolve().parents[2] / "config" / "policy.toml"


def policy(text: str):
    return parse_policy(("[engine]\nversion = \"t\"\n" + text).encode("utf-8"))


def refund(amount=5000, payment=5000, refunded=False, **more):
    return PolicyRequest("refund", "duplicate_charge", amount, payment, refunded, "standard", 10, 0, False, **more)


# ------------------------------------------------------------------ the shipped rules
def test_the_shipped_file_loads_and_its_hash_is_the_hash_of_the_file():
    p = load_policy(SHIPPED)
    assert p.sha256 == hashlib.sha256(SHIPPED.read_bytes()).hexdigest()
    assert [r.rule_id for r in p.rules] == ["DENY-REFUND-EXCEEDS-PAYMENT", "DENY-REFUND-ALREADY-REFUNDED", "APPROVE-REFUND-SENIOR"]
    assert p.auto_execute_enabled is False, "auto-execute ships switched off"


def test_a_refund_above_the_payment_on_record_is_denied():
    d = evaluate(refund(amount=5001, payment=5000), load_policy(SHIPPED))
    assert (d.outcome, d.rule_id) == (DENY, "DENY-REFUND-EXCEEDS-PAYMENT")
    assert d.evidence == {"action": "refund", "amount_exceeds_payment": True}


def test_a_refund_equal_to_the_payment_is_not_denied_for_that_reason():
    assert evaluate(refund(5000, 5000), load_policy(SHIPPED)).outcome == REQUIRE_APPROVAL


def test_a_second_refund_against_the_same_payment_is_denied():
    d = evaluate(refund(refunded=True), load_policy(SHIPPED))
    assert (d.outcome, d.rule_id) == (DENY, "DENY-REFUND-ALREADY-REFUNDED")


def test_the_senior_threshold_is_inclusive_at_250_dollars():
    p = load_policy(SHIPPED)
    below, at = evaluate(refund(24999, 24999), p), evaluate(refund(25000, 25000), p)
    assert (below.outcome, below.rule_id, below.queue) == (REQUIRE_APPROVAL, DEFAULT_RULE_ID, STANDARD)
    assert (at.outcome, at.rule_id, at.queue) == (REQUIRE_APPROVAL, "APPROVE-REFUND-SENIOR", SENIOR)
    assert at.evidence == {"action": "refund", "amount_cents_gte": 25000}


def test_a_denial_beats_the_senior_queue_when_both_match():
    d = evaluate(refund(amount=90000, payment=30000), load_policy(SHIPPED))
    assert d.outcome == DENY


def test_anything_without_a_matching_rule_needs_approval_in_the_standard_queue():
    p = load_policy(SHIPPED)
    for request in (PolicyRequest("cancel_order"), PolicyRequest("return_label", "return_label"), PolicyRequest("refund", "item_refund_within_window")):
        d = evaluate(request, p)
        assert (d.outcome, d.rule_id, d.queue) == (REQUIRE_APPROVAL, DEFAULT_RULE_ID, STANDARD)
        assert d.policy_sha256 == p.sha256 and d.policy_version == p.version


def test_unknown_inputs_never_make_a_numeric_or_flag_condition_match():
    p = load_policy(SHIPPED)
    unknown = PolicyRequest("refund", "item_refund_within_window")            # no amount, no payment, no refund flag
    assert evaluate(unknown, p).rule_id == DEFAULT_RULE_ID
    assert evaluate(PolicyRequest("refund", amount_cents=99999), p).rule_id == "APPROVE-REFUND-SENIOR"      # amount known, payment unknown: not denied


def test_evaluation_is_pure():
    p, r = load_policy(SHIPPED), refund(30000, 30000)
    assert evaluate(r, p) == evaluate(r, p)


# ------------------------------------------------------------------ precedence and the auto-execute switch
RULES = """
[[rule]]
id = "A-APPROVE"
outcome = "require_approval"
reason = "approve"
[rule.when]
action = ["refund"]
[[rule]]
id = "B-DENY"
outcome = "deny"
reason = "deny"
[rule.when]
action = ["refund"]
amount_cents_gte = 100
[[rule]]
id = "C-AUTO"
outcome = "auto_execute"
reason = "auto"
[rule.when]
action = ["refund"]
"""


def test_outcome_decides_precedence_not_file_order():
    assert evaluate(refund(500, 900), policy(RULES)).rule_id == "B-DENY"                 # deny listed after approval still wins
    assert evaluate(refund(50, 90), policy(RULES)).rule_id == "A-APPROVE"                # approval beats auto-execute


def test_inside_one_outcome_the_file_order_decides():
    two = policy(RULES.replace("C-AUTO", "A2-APPROVE").replace('outcome = "auto_execute"', 'outcome = "require_approval"'))
    assert evaluate(refund(50, 90), two).rule_id == "A-APPROVE"


AUTO = """
[[rule]]
id = "AUTO-LABEL"
outcome = "auto_execute"
reason = "a return label is safe"
[rule.when]
action = ["return_label"]
"""


def test_an_auto_execute_rule_is_reported_as_approval_while_the_switch_is_off():
    d = evaluate(PolicyRequest("return_label"), policy(AUTO))
    assert (d.outcome, d.rule_id) == (REQUIRE_APPROVAL, "AUTO-LABEL") and d.evidence["auto_execute_enabled"] is False


def test_an_auto_execute_rule_applies_when_the_switch_is_on():
    on = parse_policy(("[engine]\nversion = \"t\"\nauto_execute_enabled = true\n" + AUTO).encode())
    d = evaluate(PolicyRequest("return_label"), on)
    assert (d.outcome, d.rule_id) == (AUTO_EXECUTE, "AUTO-LABEL")


def test_a_denial_beats_an_auto_execute_rule_even_with_the_switch_on():
    text = "[engine]\nversion = \"t\"\nauto_execute_enabled = true\n" + RULES
    assert evaluate(refund(500, 900), parse_policy(text.encode())).outcome == DENY


# ------------------------------------------------------------------ each condition
@pytest.mark.parametrize("when,match,miss", [
    ('reason = ["duplicate_charge"]', refund(), PolicyRequest("refund", "other")),
    ('customer_tier = ["gold"]', PolicyRequest("refund", customer_tier="gold"), PolicyRequest("refund", customer_tier="silver")),
    ('amount_cents_lte = 100', PolicyRequest("refund", amount_cents=100), PolicyRequest("refund", amount_cents=101)),
    ('order_age_days_gte = 30', PolicyRequest("refund", order_age_days=30), PolicyRequest("refund", order_age_days=29)),
    ('order_age_days_lte = 30', PolicyRequest("refund", order_age_days=30), PolicyRequest("refund", order_age_days=31)),
    ('prior_refunds_gte = 2', PolicyRequest("refund", prior_refunds=2), PolicyRequest("refund", prior_refunds=1)),
    ('legal_flag = true', PolicyRequest("refund", legal_flag=True), PolicyRequest("refund", legal_flag=False)),
    ('payment_already_refunded = false', PolicyRequest("refund", payment_already_refunded=False), PolicyRequest("refund", payment_already_refunded=True)),
])
def test_every_condition_matches_and_misses_at_its_boundary(when, match, miss):
    p = policy(f'[[rule]]\nid = "R"\noutcome = "deny"\nreason = "r"\n[rule.when]\n{when}\n')
    assert evaluate(match, p).rule_id == "R"
    assert evaluate(miss, p).rule_id == DEFAULT_RULE_ID


def test_all_conditions_of_a_rule_must_hold():
    p = policy('[[rule]]\nid = "R"\noutcome = "deny"\nreason = "r"\n[rule.when]\naction = ["refund"]\ncustomer_tier = ["gold"]\n')
    assert evaluate(PolicyRequest("refund", customer_tier="gold"), p).rule_id == "R"
    assert evaluate(PolicyRequest("refund", customer_tier="standard"), p).rule_id == DEFAULT_RULE_ID
    assert evaluate(PolicyRequest("cancel_order", customer_tier="gold"), p).rule_id == DEFAULT_RULE_ID


# ------------------------------------------------------------------ the file is validated when loaded (fail closed)
RULE = '[[rule]]\nid = "R"\noutcome = "deny"\nreason = "r"\n[rule.when]\naction = ["refund"]\n'


@pytest.mark.parametrize("text", [
    RULE.replace("[rule.when]\naction", "[rule.when]\nbogus = 1\naction"),            # unknown condition
    RULE.replace('"deny"', '"allow"'),                                                # unknown outcome
    RULE + RULE,                                                                      # duplicate id
    RULE.replace('id = "R"', 'id = "DEFAULT-APPROVAL"'),                              # reserved id
    RULE.replace('reason = "r"\n', 'reason = "r"\nsurprise = 1\n'),                   # unknown rule key
    RULE.replace('reason = "r"\n', ''),                                               # no reason
    RULE.replace('[rule.when]\naction = ["refund"]\n', ''),                           # no conditions: would match everything
    RULE.replace('[rule.when]\naction = ["refund"]\n', '[rule.when]\n'),
    RULE.replace('["refund"]', '["wire_money"]'),                                     # unknown action
    RULE.replace('["refund"]', '"refund"'),                                           # not a list
    RULE.replace('["refund"]', '[]'),
    RULE + 'amount_cents_gte = "5"\n',                                                # wrong type
    RULE + 'amount_cents_gte = true\n',                                               # a bool is not a number
    RULE + 'amount_cents_gte = -1\n',
    RULE + 'legal_flag = "yes"\n',
    RULE.replace('reason = "r"\n', 'reason = "r"\nqueue = "senior"\n'),               # a queue on a deny rule
    RULE.replace('outcome = "deny"', 'outcome = "require_approval"\nqueue = "boss"'),
    "this is not toml [",
    '[surprise]\nx = 1\n',
])
def test_a_bad_policy_file_is_refused(text):
    with pytest.raises(PolicyError):
        policy(text)


def test_engine_settings_are_validated():
    for bad in ('[engine]\nversion = "t"\nauto_execute_enabled = "no"\n', '[engine]\nauto_execute_enabled = false\n',
                '[engine]\nversion = "t"\nextra = 1\n'):
        with pytest.raises(PolicyError):
            parse_policy(bad.encode())


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "nope.toml")


def test_a_changed_rule_changes_the_hash():
    assert policy(RULE).sha256 != policy(RULE.replace("refund", "exchange")).sha256