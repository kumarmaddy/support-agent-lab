import ast
import json
import sqlite3
from pathlib import Path

import pytest

from src.agent import tools
from src.agent.tools import INVALID, NOT_FOUND, NOT_OWNED, OK, TOOL_SCHEMAS, UNKNOWN_TOOL, Toolbox

SRC = Path(__file__).resolve().parents[2] / "src" / "agent"


@pytest.fixture()
def box(dev_dataset):
    toolbox = Toolbox.from_path(dev_dataset[0])
    yield toolbox
    toolbox.conn.close()


@pytest.fixture(scope="module")
def raw(dev_dataset):
    conn = sqlite3.connect(dev_dataset[0])
    yield conn
    conn.close()


# ------------------------------------------------------------------ read-only by construction
def test_the_connection_cannot_write(box):
    with pytest.raises(sqlite3.OperationalError):
        box.conn.execute("INSERT INTO audit_log (actor, action, timestamp) VALUES ('x', 'x', 'x')")
    with pytest.raises(sqlite3.OperationalError):
        box.conn.execute("DELETE FROM tickets")


def test_even_a_writable_connection_is_made_read_only(dev_dataset):
    conn = sqlite3.connect(dev_dataset[0])                   # writable on purpose
    Toolbox(conn)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM tickets")
    conn.close()


def test_tool_source_contains_no_write_statements():
    text = (SRC / "tools.py").read_text(encoding="utf-8").upper()
    for word in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "REPLACE INTO"):
        assert word not in text, word


# ------------------------------------------------------------------ get_ticket
def test_get_ticket(box, dev_dataset):
    result = box.get_ticket("T-000001")
    assert result.ok and result.data.ticket_id == "T-000001" and result.data.body
    assert box.get_ticket("T-999999").status == NOT_FOUND


@pytest.mark.parametrize("bad", ["", "t-000001", "T-1", "T-000001; DROP TABLE tickets", None, 5, "T-000001\n"])
def test_get_ticket_rejects_malformed_ids(box, bad):
    assert box.get_ticket(bad).status == INVALID
    assert box.conn.execute("SELECT count(*) FROM tickets").fetchone()[0] == 150          # nothing was touched


# ------------------------------------------------------------------ find_customer
def test_find_customer_is_case_insensitive(box, raw):
    email = raw.execute("SELECT email FROM customers LIMIT 1").fetchone()[0]
    lower, upper = box.find_customer(email.lower()), box.find_customer(email.upper())
    assert lower.ok and upper.ok and lower.data == upper.data and lower.data.email == email
    assert set(lower.data.__dataclass_fields__) == {"customer_id", "name", "email", "tier", "status"}


def test_find_customer_unknown_and_invalid(box):
    assert box.find_customer("nobody@example.com").status == NOT_FOUND
    for bad in ["", "no-at-sign", "a@b", "x@y.com' OR '1'='1", " a@b.com", "a@b.com\n", "a" * 300 + "@example.com", None]:
        assert box.find_customer(bad).status == INVALID, bad


# ------------------------------------------------------------------ list_open_orders
def test_open_orders_match_an_independent_query(box, raw):
    customers = [r[0] for r in raw.execute("SELECT customer_id FROM customers")]
    for cid in customers:
        expected = [r[0] for r in raw.execute("SELECT order_id FROM orders WHERE customer_id = ? AND status IN "
                                              "('processing', 'shipped') ORDER BY placed_at, order_id", (cid,))]
        result = box.list_open_orders(cid)
        assert result.ok and [o.order_id for o in result.data] == expected


def test_open_orders_never_include_closed_orders(box, raw):
    closed = {r[0] for r in raw.execute("SELECT order_id FROM orders WHERE status IN ('delivered', 'cancelled', 'returned')")}
    for (cid,) in raw.execute("SELECT customer_id FROM customers"):
        assert not closed & {o.order_id for o in box.list_open_orders(cid).data}


def test_the_ambiguous_customers_of_scenario_s04_have_several_open_orders(box, dev_dataset):
    s04 = [l for l in dev_dataset[2] if l["scenario_id"] == "S04"]
    assert len(s04) == 6
    for label in s04:
        email = box.get_ticket(label["ticket_id"]).data.customer_email
        customer = box.find_customer(email).data
        assert len(box.list_open_orders(customer.customer_id).data) >= 2


def test_open_orders_unknown_and_invalid(box):
    assert box.list_open_orders("C-999999").status == NOT_FOUND
    assert box.list_open_orders("C-1").status == INVALID


# ------------------------------------------------------------------ get_order
def first_order(raw, status):
    return raw.execute("SELECT order_id, customer_id FROM orders WHERE status = ? ORDER BY order_id LIMIT 1", (status,)).fetchone()


def test_a_shipped_order_has_a_shipment_and_a_processing_order_does_not(box, raw):
    shipped = box.get_order(*first_order(raw, "shipped")).data
    assert shipped.status == "shipped" and shipped.shipment.tracking_no and shipped.items
    processing = box.get_order(*first_order(raw, "processing")).data
    assert processing.status == "processing" and processing.shipment is None


def test_one_shipment_per_order_in_the_dataset(raw):
    """The Order type carries a single shipment; this guards that assumption."""
    assert raw.execute("SELECT max(n) FROM (SELECT count(*) n FROM shipments GROUP BY order_id)").fetchone()[0] == 1


def test_another_customers_order_is_refused_and_reveals_nothing(box, raw):
    order_id, owner = first_order(raw, "shipped")
    other = raw.execute("SELECT customer_id FROM customers WHERE customer_id != ? LIMIT 1", (owner,)).fetchone()[0]
    result = box.get_order(order_id, other)
    assert result.status == NOT_OWNED and result.data is None
    dumped = json.dumps(result.to_dict())
    tracking = raw.execute("SELECT tracking_no FROM shipments WHERE order_id = ?", (order_id,)).fetchone()[0]
    assert tracking not in dumped and owner not in dumped and order_id not in dumped


def test_unknown_and_malformed_order_requests(box):
    assert box.get_order("O-999999", "C-000001").status == NOT_FOUND
    for order_id, cid in [("O-1", "C-000001"), ("O-000001", "C-1"), ("O-000001' --", "C-000001"), (None, "C-000001")]:
        assert box.get_order(order_id, cid).status == INVALID


def test_results_carry_no_addresses_or_card_data(box, raw):
    order_id, cid = first_order(raw, "shipped")
    text = json.dumps(box.get_order(order_id, cid).to_dict()).lower()
    for field in ("line1", "postal", "method_last4", "card", "payment"):
        assert field not in text


# ------------------------------------------------------------------ agreement with the labelled facts (tests may read labels; the tools may not)
def test_tools_agree_with_the_labelled_facts_for_every_in_slice_ticket(box, dev_dataset):
    in_slice = [l for l in dev_dataset[2] if l["category"] == "order_status" and l["referenced_order_id"]]
    assert len(in_slice) >= 25
    for label in in_slice:
        ticket = box.get_ticket(label["ticket_id"]).data
        customer = box.find_customer(ticket.customer_email).data
        order = box.get_order(label["referenced_order_id"], customer.customer_id).data
        facts = label["expected_facts"]
        assert order.status == facts["order_status"], label["ticket_id"]
        assert order.promised_date == facts["promised_date"], label["ticket_id"]
        if facts["order_status"] == "shipped":
            assert (order.shipment.carrier, order.shipment.tracking_no, order.shipment.last_status) == \
                   (facts["carrier"], facts["tracking_no"], facts["last_status"]), label["ticket_id"]


# ------------------------------------------------------------------ the shared interface
def test_call_dispatches_and_returns_plain_json(box, raw):
    order_id, cid = first_order(raw, "shipped")
    reply = box.call("get_order", {"order_id": order_id, "customer_id": cid})
    assert reply["status"] == OK and reply["data"]["order_id"] == order_id
    assert reply["data"]["shipment"]["tracking_no"] and isinstance(reply["data"]["items"], list)
    json.dumps(reply)                                                 # serialisable without custom encoders
    assert box.call("list_open_orders", {"customer_id": cid})["status"] == OK


def test_call_rejects_bad_requests_without_touching_the_database(box):
    assert box.call("refund_order", {"order_id": "O-000001"})["status"] == UNKNOWN_TOOL
    assert box.call("get_order", {"order_id": "O-000001"})["status"] == INVALID                       # missing argument
    assert box.call("get_order", {"order_id": "O-000001", "customer_id": "C-000001", "x": "y"})["status"] == INVALID
    assert box.call("get_ticket", {"ticket_id": 5})["status"] == INVALID                              # wrong type
    assert box.call("get_ticket", "T-000001")["status"] == INVALID                                    # not an object


def test_every_tool_has_a_schema_and_a_method():
    for name, schema in TOOL_SCHEMAS.items():
        assert callable(getattr(Toolbox, name)) and schema["description"]
        assert schema["input_schema"]["additionalProperties"] is False
        assert set(schema["input_schema"]["required"]) == set(schema["input_schema"]["properties"])


# ------------------------------------------------------------------ the agent package cannot reach labels, the generator or the baseline tool
def test_agent_package_has_no_forbidden_imports_or_label_paths():
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith(("src.datagen", "src.baseline")), f"{path.name} imports {module}"
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith(("src.datagen", "src.baseline")) for a in node.names), path.name
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert "labels.jsonl" not in node.value and "data/labels" not in node.value, path.name