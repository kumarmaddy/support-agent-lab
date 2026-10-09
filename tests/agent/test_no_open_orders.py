"""A customer with no open order and no order number is asked for the number; no order is named (found in the stage 2.5a run)."""
import pytest

from src.agent import decide as d
from src.agent.decide import Identity, decide
from src.agent.reply import template_body
from src.agent.validate import ReplyFacts, validate_reply
from tests.agent.test_decide import CUSTOMER, TODAY, reading


@pytest.mark.parametrize("category", ["order_status", "cancellation", "address_change"])
def test_no_open_orders_asks_for_the_number_without_naming_any_order(category):
    out = decide(reading(category), Identity(d.NEEDS_ORDER_NUMBER, CUSTOMER, open_orders=()), TODAY, d.TRANSACTION_SCOPE)
    assert (out.action, out.reason, out.article) == (d.REQUEST_INFO, "no_open_orders", "KB-ORD-02")
    assert not out.facts
    assert validate_reply(template_body(out), ReplyFacts(), frozenset()) == []


@pytest.mark.parametrize("text", [
    "Please choose ORDER12345 or ORDER67890.", "Your order ORDER-123456 is on its way.", "Order #12345 has shipped.",
    "Your order number is order 9876.",
])
def test_an_order_number_in_another_shape_is_an_invented_order(text):
    assert "unknown_order" in validate_reply(text, ReplyFacts(), frozenset())


def test_a_listed_order_and_ordinary_words_are_not_flagged():
    assert "unknown_order" not in validate_reply("Please order a size larger, and reply with the order number.",
                                                 ReplyFacts(allowed_ids=frozenset({"O-000001"})), frozenset())