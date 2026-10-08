from datetime import date

import pytest

from src.agent import decide as d
from src.agent.decide import Decision, Identity, decide, identify, requires_lookup
from src.agent.reading import Reading
from src.agent.tools import Customer, Order, OrderLine, OpenOrder, Shipment, Ticket, Toolbox

TODAY = date(2026, 10, 6)
CUSTOMER = Customer("C-000001", "Ada Lovelace", "ada@example.com", "standard", "active")
ITEM = (OrderLine("Ridgeline Merino Crew", "M", 1),)


def reading(category="order_status", phrase="", legal=False, ids=()):
    return Reading(category, phrase, legal, tuple(ids))


def order(status="processing", promised="2026-10-15", shipment=None):
    return Order("O-000001", "C-000001", status, "2026-10-01T09:00:00", promised, 5000, ITEM, shipment)


def shipped(promised="2026-10-10", last="In transit"):
    return order("shipped", promised, Shipment("TrailExpress", "TR000000000001", "2026-10-03T10:00:00", None, last))


def found(o):
    return Identity(d.IDENTIFIED, CUSTOMER, order=o)


# ------------------------------------------------------------------ rules
def test_other_categories_go_to_a_person_without_any_lookup():
    for category in ("refund", "other", "product_info"):
        out = decide(reading(category), None, TODAY)
        assert (out.action, out.reason, out.article) == (d.ROUTE_TO_HUMAN, "out_of_slice", None)
        assert not requires_lookup(reading(category))


def test_a_legal_threat_escalates_even_without_an_identity():
    out = decide(reading(legal=True), None, TODAY)
    assert (out.action, out.reason, out.article) == (d.ESCALATE_HUMAN, "chargeback_or_legal_threat", "KB-REF-04")
    assert not requires_lookup(reading(legal=True))


def test_an_order_status_ticket_needs_an_identity():
    assert requires_lookup(reading())
    with pytest.raises(ValueError):
        decide(reading(), None, TODAY)


def test_unknown_sender_is_asked_for_the_order_number():
    out = decide(reading(), Identity(d.NO_ACCOUNT), TODAY)
    assert (out.action, out.reason, out.article) == (d.REQUEST_INFO, "no_account", "KB-ORD-02")


def test_someone_elses_order_escalates_and_reveals_nothing():
    out = decide(reading(ids=["O-000999"]), Identity(d.ORDER_NOT_OWNED, CUSTOMER), TODAY)
    assert (out.action, out.reason, out.article) == (d.ESCALATE_HUMAN, "order_not_owned", "KB-SEC-01")
    assert out.facts == {}


def test_order_not_found_asks_for_the_number():
    out = decide(reading(ids=["O-999999"]), Identity(d.ORDER_NOT_FOUND, CUSTOMER), TODAY)
    assert (out.action, out.reason, out.article) == (d.REQUEST_INFO, "order_not_found", "KB-ORD-02")


def test_several_open_orders_and_no_number_lists_the_candidates():
    open_orders = (OpenOrder("O-000001", "processing", "x", "2026-10-15", ITEM), OpenOrder("O-000002", "shipped", "x", "2026-10-12", ITEM))
    out = decide(reading(), Identity(d.NEEDS_ORDER_NUMBER, CUSTOMER, open_orders=open_orders), TODAY)
    assert (out.action, out.reason, out.article) == (d.REQUEST_INFO, "needs_order_number", "KB-ORD-02")
    assert [c["order_id"] for c in out.facts["candidates"]] == ["O-000001", "O-000002"]
    assert out.facts["candidates"][0]["items"] == ["Ridgeline Merino Crew"]


def test_several_named_orders_ask_which_one():
    out = decide(reading(ids=["O-000001", "O-000002"]), Identity(d.MULTIPLE_ORDER_IDS, CUSTOMER, named_ids=("O-000001", "O-000002")), TODAY)
    assert (out.reason, out.article) == ("multiple_order_ids", "KB-ORD-02")


def test_processing_order_without_deadline_gets_information():
    out = decide(reading(), found(order()), TODAY)
    assert (out.action, out.reason, out.article) == (d.PROVIDE_INFO, "order_processing", "KB-ORD-01")
    assert out.facts["promised_date"] == "2026-10-15"


@pytest.mark.parametrize("phrase,action", [
    ("Thursday", d.ESCALATE_HUMAN),            # 2 days
    ("October 9", d.ESCALATE_HUMAN),           # exactly 3 days: inside the window
    ("October 10", d.PROVIDE_INFO),            # 4 days: outside
    ("October 15", d.PROVIDE_INFO),            # far away: stays information
    ("as soon as possible", d.PROVIDE_INFO),   # not a date
    ("", d.PROVIDE_INFO),
])
def test_deadline_window_on_an_undispatched_order(phrase, action):
    out = decide(reading(phrase=phrase), found(order()), TODAY)
    assert out.action == action
    if action == d.ESCALATE_HUMAN:
        assert (out.reason, out.article) == ("delivery_deadline_cannot_be_guaranteed", "KB-SHP-03")
        assert out.facts["deadline_date"] and out.facts["order_id"] == "O-000001"


def test_shipped_on_or_before_the_promised_date():
    for promised in ("2026-10-06", "2026-10-10"):
        out = decide(reading(), found(shipped(promised)), TODAY)
        assert (out.reason, out.article) == ("shipped_on_time", "KB-SHP-01")
        assert out.facts["tracking_no"] == "TR000000000001" and out.facts["carrier"] == "TrailExpress"


def test_shipped_after_the_promised_date_acknowledges_the_delay():
    out = decide(reading(), found(shipped("2026-10-05", "In transit - delayed")), TODAY)
    assert (out.action, out.reason, out.article) == (d.PROVIDE_INFO, "shipped_late", "KB-SHP-02")


def test_a_stated_deadline_does_not_escalate_an_order_that_is_already_shipped():
    assert decide(reading(phrase="Thursday"), found(shipped()), TODAY).action == d.PROVIDE_INFO


def test_delivered_order_reports_the_delivery_date():
    delivered = order("delivered", "2026-10-01", Shipment("TrailExpress", "TR1", "2026-10-02T08:00:00", "2026-10-04T16:30:00", "Delivered"))
    out = decide(reading(), found(delivered), TODAY)
    assert (out.reason, out.article, out.facts["delivered_date"]) == ("delivered", "KB-SHP-01", "2026-10-04")


@pytest.mark.parametrize("o", [order("cancelled"), order("returned"), order("shipped", shipment=None), order("delivered", shipment=None)])
def test_states_outside_the_slice_go_to_a_person(o):
    out = decide(reading(), found(o), TODAY)
    assert (out.action, out.reason) == (d.ROUTE_TO_HUMAN, "order_state_not_covered")


def test_a_locked_account_is_handled_like_any_other():
    """The development labels expect normal handling of order-status questions from locked accounts (open policy question)."""
    locked = Customer("C-000001", "Ada", "ada@example.com", "standard", "locked")
    assert decide(reading(), Identity(d.IDENTIFIED, locked, order=order()), TODAY).action == d.PROVIDE_INFO


def test_decide_is_deterministic():
    args = (reading(phrase="Thursday"), found(order()), TODAY)
    assert decide(*args) == decide(*args)


# ------------------------------------------------------------------ identification with the real tools
@pytest.fixture()
def box(dev_dataset):
    toolbox = Toolbox.from_path(dev_dataset[0])
    yield toolbox
    toolbox.conn.close()


def ticket_of(box, labels, scenario, nth=0):
    label = [lab for lab in labels if lab["scenario_id"] == scenario][nth]
    return label, box.get_ticket(label["ticket_id"]).data


def test_identify_finds_the_named_order(dev_dataset, box):
    label, ticket = ticket_of(box, dev_dataset[2], "S01")
    out = identify(box, ticket, reading(ids=[label["referenced_order_id"]]))
    assert out.outcome == d.IDENTIFIED and out.order.order_id == label["referenced_order_id"]


def test_identify_with_no_number_and_two_open_orders_lists_them(dev_dataset, box):
    label, ticket = ticket_of(box, dev_dataset[2], "S04")
    out = identify(box, ticket, reading())
    assert out.outcome == d.NEEDS_ORDER_NUMBER
    assert sorted(o.order_id for o in out.open_orders) == sorted(label["expected_facts"]["candidate_order_ids"])


def test_identify_with_no_number_and_one_open_order_uses_it(dev_dataset, box):
    """No development ticket takes this path, so use a customer with exactly one open order straight from the database."""
    row = box.conn.execute("SELECT c.email, MIN(o.order_id) FROM customers c JOIN orders o USING (customer_id) "
                           "WHERE o.status IN ('processing', 'shipped') GROUP BY c.customer_id HAVING COUNT(*) = 1 LIMIT 1").fetchone()
    assert row, "the development data has no customer with exactly one open order"
    email, order_id = row
    ticket = Ticket("T-000000", "2026-10-06T10:00:00", "email", email, "Where is my order?", "Any news?")
    out = identify(box, ticket, reading())
    assert out.outcome == d.IDENTIFIED and out.order.order_id == order_id


def test_identify_refuses_another_customers_order(dev_dataset, box):
    label, ticket = ticket_of(box, dev_dataset[2], "S25")
    out = identify(box, ticket, reading(ids=[label["referenced_order_id"]]))
    assert out.outcome == d.ORDER_NOT_OWNED and out.order is None


def test_identify_unknown_order_unknown_sender_and_several_numbers(dev_dataset, box):
    _, ticket = ticket_of(box, dev_dataset[2], "S01")
    assert identify(box, ticket, reading(ids=["O-999999"])).outcome == d.ORDER_NOT_FOUND
    stranger = Ticket(ticket.ticket_id, ticket.received_at, ticket.channel, "nobody@example.com", ticket.subject, ticket.body)
    assert identify(box, stranger, reading(ids=["O-000001"])).outcome == d.NO_ACCOUNT
    assert identify(box, ticket, reading(ids=["O-000001", "O-000002"])).outcome == d.MULTIPLE_ORDER_IDS