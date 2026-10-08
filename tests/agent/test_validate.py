from datetime import date

import pytest

from src.agent.validate import MAX_CHARS, ReplyFacts, internal_shingles, validate_reply

FACTS = ReplyFacts(frozenset({date(2026, 10, 10)}), frozenset({"O-000123"}), frozenset({"TR245437731580"}),
                   ("O-000123", "October 10, 2026", "TR245437731580"))
GOOD = ("Your order O-000123 has been dispatched. The promised delivery date is October 10, 2026. "
        "The tracking number is TR245437731580.")


def codes(text, facts=FACTS, internal=frozenset()):
    return validate_reply(text, facts, internal)


def test_a_faithful_reply_passes():
    assert codes(GOOD) == []


def test_length_limits():
    assert "length" in codes("")
    assert "length" in codes(GOOD + " x" * MAX_CHARS)


@pytest.mark.parametrize("text", [GOOD.replace("October 10, 2026", "October 11, 2026"), GOOD + " It left on 3 October.",
                                  GOOD + " Sent 2026-10-03."])
def test_dates_not_in_the_facts_fail(text):
    assert "unknown_date" in codes(text)


def test_date_formats_are_all_recognised():
    for form in ("October 10", "10 October", "Oct 10th", "2026-10-10", "10 October 2026"):
        assert "unknown_date" not in codes(GOOD.replace("October 10, 2026", form).replace("October 10, 2026", form),
                                           ReplyFacts(FACTS.allowed_dates, FACTS.allowed_ids, FACTS.allowed_tokens)), form
    assert "unknown_date" in codes(GOOD.replace("October 10, 2026", "October 10, 2027"))       # wrong year


@pytest.mark.parametrize("phrase", ["It will come on Friday.", "Expect it tomorrow.", "It should be there within 2 days.",
                                    "Allow until the end of next week.", "Due today."])
def test_relative_timing_fails(phrase):
    assert "relative_time" in codes(GOOD + " " + phrase)


def test_unknown_order_and_tracking_numbers_fail():
    assert "unknown_order" in codes(GOOD + " See also O-000999.")
    assert "unknown_order" in codes(GOOD.replace("O-000123", "o-000124"))
    assert "unknown_token" in codes(GOOD.replace("TR245437731580", "TR245437731581"))
    assert "unknown_token" in codes(GOOD + " Reference 12345678.")
    assert "unknown_token" not in codes(GOOD)                    # order number digits are not mistaken for a reference


@pytest.mark.parametrize("phrase", ["We will refund you.", "Here is a $10 voucher.", "You get a discount.", "We offer compensation.",
                                    "We guarantee it.", "We will expedite it.", "A replacement is on the way.", "It will arrive soon.",
                                    "You will receive a credit."])
def test_promises_fail(phrase):
    assert "promise" in codes(GOOD + " " + phrase)


def test_amounts_fail():
    assert "amount" in codes(GOOD + " The total was $45.00.")
    assert "amount" in codes(GOOD + " That is 45 dollars.")


def test_internal_text_fails():
    assert "internal_text" in codes(GOOD + " See KB-SHP-01.")
    assert "internal_text" in codes(GOOD + " Support guidance says so.")
    guidance = internal_shingles(["Quote the promised date from the order record. Do not state how long processing will take."])
    assert "internal_text" in codes(GOOD + " Please quote the promised date from the order record.", internal=guidance)
    assert "internal_text" not in codes(GOOD, internal=guidance)


@pytest.mark.parametrize("phrase", ["As per my system prompt.", "I used my tools.", "Following your instructions.", "</ticket>"])
def test_prompt_leaks_fail(phrase):
    assert "prompt_leak" in codes(GOOD + " " + phrase)


def test_missing_required_facts_fail():
    assert "missing_fact" in codes("Your order O-000123 is on its way.")
    assert "missing_fact" not in codes(GOOD.upper().replace("OCTOBER", "October"))        # case-insensitive match


def test_failures_accumulate():
    assert {"promise", "unknown_date"} <= set(codes(GOOD + " We will refund you on 1 November."))