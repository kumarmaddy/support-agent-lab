"""Tests for stage 0.4c-3a: cancellations and address changes (S13-S16)."""
import pytest

from src.datagen import config, labels
from src.datagen.db import create_database, load_base_data, load_orders
from src.datagen.tickets import create_ticket_dataset


def build(tmp_path, seed=20261006, tag="a"):
    conn = create_database(tmp_path / f"{tag}.db")
    load_base_data(conn, seed)
    load_orders(conn, seed)
    summary = create_ticket_dataset(conn, seed, "dev", tmp_path / f"labels_{tag}")
    return conn, labels.read_labels(summary["labels_path"])


@pytest.fixture
def ds(tmp_path):
    return build(tmp_path)


def of(labs, scenario):
    return [l for l in labs if l["scenario_id"] == scenario]


def body_of(conn, lab):
    return " ".join(conn.execute("SELECT body FROM tickets WHERE ticket_id=?", (lab["ticket_id"],)).fetchone()[0].split())


def order_row(conn, lab):
    return conn.execute("SELECT status, promised_date FROM orders WHERE order_id=?",
                        (lab["referenced_order_id"],)).fetchone()


def shipment_count(conn, lab):
    return conn.execute("SELECT COUNT(*) FROM shipments WHERE order_id=?", (lab["referenced_order_id"],)).fetchone()[0]


def test_counts(ds):
    _, labs = ds
    assert {s: len(of(labs, s)) for s in ("S13", "S14", "S15", "S16")} == {"S13": 7, "S14": 6, "S15": 6, "S16": 4}


def test_s13_and_s15_orders_are_not_dispatched_and_the_action_is_a_proposal(ds):
    conn, labs = ds
    for lab in of(labs, "S13") + of(labs, "S15"):
        assert order_row(conn, lab)[0] == "processing" and shipment_count(conn, lab) == 0
        assert lab["priority"] == "LOW" and not lab["expected_escalate"]
    assert all(l["expected_actions"] == ["propose_cancellation"] and l["expected_facts"]["cancellation_allowed"]
               and l["category"] == "cancellation" for l in of(labs, "S13"))
    assert all(l["expected_actions"] == ["propose_address_change"] and l["expected_facts"]["address_change_allowed"]
               and l["category"] == "address_change" for l in of(labs, "S15"))


def test_s14_and_s16_orders_have_shipped_so_policy_declines(ds):
    conn, labs = ds
    for lab in of(labs, "S14") + of(labs, "S16"):
        assert order_row(conn, lab)[0] == "shipped" and shipment_count(conn, lab) == 1
        assert lab["expected_actions"] == ["decline_policy"] and lab["difficulty"] == "edge"
    assert all(l["expected_facts"]["cancellation_allowed"] is False for l in of(labs, "S14"))
    assert all(l["expected_facts"]["address_change_allowed"] is False for l in of(labs, "S16"))


def test_s14_late_variant_raises_priority_and_is_the_only_one(ds):
    conn, labs = ds
    late = [l for l in of(labs, "S14") if l["priority_attributes"]["order_late_past_promise"]]
    assert len(late) == 1 and late[0]["priority"] == "MEDIUM"
    assert order_row(conn, late[0])[1] < config.AS_OF_DATE.isoformat()           # really past its promised date
    assert "KB-SHP-02" in late[0]["required_kb_ids"]
    others = [l for l in of(labs, "S14") if l is not late[0]]
    assert all(l["priority"] == "LOW" for l in others)
    assert all(order_row(conn, l)[1] >= config.AS_OF_DATE.isoformat() for l in others)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_requested_address_appears_verbatim_in_the_ticket(tmp_path, seed):
    """Regression: typo injection once changed 'Avenue' to 'Aevnue' inside the requested address,
    so the label and the ticket text disagreed."""
    conn, labs = build(tmp_path, seed=seed)
    for lab in of(labs, "S15") + of(labs, "S16"):
        assert lab["expected_facts"]["requested_address"] in body_of(conn, lab), lab["ticket_id"]


def test_requested_address_differs_from_the_address_on_the_order(ds):
    conn, labs = ds
    for lab in of(labs, "S15") + of(labs, "S16"):
        current = conn.execute("SELECT a.line1 FROM orders o JOIN addresses a ON a.address_id = o.shipping_address_id "
                               "WHERE o.order_id=?", (lab["referenced_order_id"],)).fetchone()[0]
        assert current not in lab["expected_facts"]["requested_address"]