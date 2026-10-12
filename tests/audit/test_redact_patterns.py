"""Stage 3.4: what is redacted, and what is deliberately kept."""
import pytest

from src.audit.redact import ADDRESS_MARK, NAME_MARK, leftovers, redact, redact_text


@pytest.mark.parametrize("text,marker", [
    ("write to jane.o'neil+x@example.co.uk please", "[EMAIL]"),
    ("my card ending 4242 was charged", "[CARD-LAST4]"),
    ("last four digits of my card is 1881", "[CARD-LAST4]"),
    ("card 4111 1111 1111 1111 twice", "[CARD]"),
    ("card 4111-1111-1111-1111", "[CARD]"),
    ("call 415-555-0134 now", "[PHONE]"),
    ("call (415) 555-0134 now", "[PHONE]"),
    ("call +44 20 7946 0958 now", "[PHONE]"),
    ("send it to 12 Oak Lane, Springfield 62704", "[ADDRESS]"),
    ("send it to 1450 North Maple Street", "[ADDRESS]"),
])
def test_patterns_are_replaced(text, marker):
    out = redact_text(text)
    assert marker in out and leftovers(out) == []


def test_a_greeting_loses_the_name_but_keeps_the_greeting():
    assert redact_text("Hello Maria Lopez,\n\nThanks") == f"Hello {NAME_MARK},\n\nThanks"
    assert redact_text("Dear Sam,\nx") == f"Dear {NAME_MARK},\nx"


@pytest.mark.parametrize("keep", ["T-000070", "O-000691", "C-000012", "PAY-000044", "RF-000001", "KB-REF-02", "1Z999AA10123456784", "order 691 of 3 items",
                                  "refund of 119.99 USD", "within 30 days"])
def test_identifiers_and_ordinary_numbers_are_kept(keep):
    assert redact_text(keep) == keep and leftovers(keep) == []


def test_keyed_fields_are_replaced_whole_and_identifier_keys_are_left_alone():
    out = redact({"requested_address": "somewhere odd", "name": "Ana", "customer_email": "x", "tracking_no": "1Z999AA10123456784",
                  "sha256": "a" * 64, "order_id": "O-000001", "nested": [{"address": "z"}, "mail a@b.com"]})
    assert out == {"requested_address": ADDRESS_MARK, "name": NAME_MARK, "customer_email": "[EMAIL]", "tracking_no": "1Z999AA10123456784",
                   "sha256": "a" * 64, "order_id": "O-000001", "nested": [{"address": ADDRESS_MARK}, "mail [EMAIL]"]}


def test_empty_values_and_non_strings_pass_through():
    assert redact({"address": "", "n": 3, "ok": True, "none": None}) == {"address": "", "n": 3, "ok": True, "none": None}


def test_redaction_is_idempotent():
    once = redact({"reply": "Hello Ana,\nsee 12 Oak Lane, Springfield 62704 or a@b.com"})
    assert redact(once) == once


def test_leftovers_is_broader_than_the_patterns():
    assert leftovers("a@b") == ["email"] and leftovers("12345678901234") == ["card"]