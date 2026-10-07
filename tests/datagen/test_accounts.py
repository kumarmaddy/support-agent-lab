"""Tests for stage 0.4c-3b: account problems and general questions (S17-S20)."""
import re

import pytest

from src.datagen.domain import labels
from src.datagen.generation import text
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.domain.kb_catalogue import KB_ARTICLES
from src.datagen.tickets import create_ticket_dataset

ORDER_ID = re.compile(r"O-\d{6}")


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


def ticket(conn, lab):
    return conn.execute("SELECT customer_email, subject, body FROM tickets WHERE ticket_id=?",
                        (lab["ticket_id"],)).fetchone()


def customer_status(conn, email):
    return conn.execute("SELECT status FROM customers WHERE email=?", (email,)).fetchone()[0]


def test_counts(ds):
    _, labs = ds
    assert {s: len(of(labs, s)) for s in ("S17", "S18", "S19", "S20")} == {"S17": 7, "S18": 5, "S19": 7, "S20": 5}


def test_account_tickets_reference_no_order(ds):
    conn, labs = ds
    for lab in of(labs, "S17") + of(labs, "S18") + of(labs, "S19") + of(labs, "S20"):
        email, subject, body = ticket(conn, lab)
        assert lab["referenced_order_id"] is None and lab["order_identifiable"] is False
        assert not ORDER_ID.search(subject + body)


def test_s17_locked_tickets_come_from_customers_who_are_really_locked(ds):
    conn, labs = ds
    s17 = of(labs, "S17")
    locked = [l for l in s17 if l["expected_facts"]["account_status"] == "locked"]
    active = [l for l in s17 if l["expected_facts"]["account_status"] == "active"]
    assert len(locked) == 4 and len(active) == 3
    for lab in locked:
        assert customer_status(conn, ticket(conn, lab)[0]) == "locked"
        assert lab["required_kb_ids"] == ["KB-ACC-02", "KB-ACC-01"]
    for lab in active:
        assert customer_status(conn, ticket(conn, lab)[0]) == "active"
        assert lab["required_kb_ids"] == ["KB-ACC-01"]
    assert len({ticket(conn, l)[0] for l in locked}) == 4            # four different locked customers
    for lab in s17:
        assert lab["priority"] == "MEDIUM" and lab["priority_attributes"]["account_locked_out"]
        assert lab["expected_actions"] == ["provide_info"]


def test_s18_compromise_is_high_priority_and_escalated(ds):
    _, labs = ds
    for lab in of(labs, "S18"):
        assert lab["priority"] == "HIGH" and lab["priority_attributes"]["account_compromise_suspected"]
        assert lab["expected_actions"] == ["escalate_human"] and lab["escalation_reason"] == "suspected_account_compromise"
        assert lab["required_kb_ids"] == ["KB-ACC-03"]


def test_s19_each_question_is_distinct_and_answerable_from_the_knowledge_base(ds):
    _, labs = ds
    s19 = of(labs, "S19")
    topics = [l["expected_facts"]["topic"] for l in s19]
    assert len(set(topics)) == 7
    for lab in s19:
        assert lab["category"] == "product_info" and lab["priority"] == "LOW"
        assert lab["expected_actions"] == ["provide_info"] and lab["required_kb_ids"]
        assert set(lab["required_kb_ids"]) <= set(KB_ARTICLES)


def test_s19_policy_facts_agree_with_the_generated_data(ds):
    """The facts a reply must be consistent with must not contradict what the database shows."""
    conn, labs = ds
    facts = {l["expected_facts"]["topic"]: l["expected_facts"] for l in of(labs, "S19")}
    lo = facts["delivery_time"]["delivery_days_after_dispatch_min"]
    hi = facts["delivery_time"]["delivery_days_after_dispatch_max"]
    gaps = [r[0] for r in conn.execute(
        "SELECT julianday(substr(delivered_at,1,10)) - julianday(substr(dispatched_at,1,10)) "
        "FROM shipments WHERE delivered_at IS NOT NULL")]
    assert min(gaps) >= lo and max(gaps) <= hi
    assert facts["return_policy"]["return_window_days"] == 30
    # a refund still pending must not be older than the stated maximum
    refund_max = facts["refund_time"]["refund_days_after_return_received_max"]
    oldest_pending = conn.execute(
        "SELECT MAX(julianday('2026-10-06') - julianday(substr(requested_at,1,10))) "
        "FROM refunds WHERE status='pending'").fetchone()[0]
    assert oldest_pending <= refund_max


def test_s20_is_not_covered_and_escalates(ds):
    _, labs = ds
    for lab in of(labs, "S20"):
        assert lab["category"] == "other" and lab["required_kb_ids"] == []
        assert lab["expected_actions"] == ["escalate_human"] and lab["escalation_reason"] == "not_in_knowledge_base"
        assert lab["difficulty"] == "edge"


def test_questions_from_new_customers_never_sound_unhappy_about_service(tmp_path):
    """Regression: 'I'm quite disappointed with the service so far' was appended to a pre-purchase question."""
    unhappy = text._EXTRAS["frustrated"]
    for seed in (1, 2, 3, 4, 5, 6):
        conn, labs = build(tmp_path, seed=seed, tag=f"s{seed}")
        for lab in of(labs, "S19") + of(labs, "S20"):
            body = ticket(conn, lab)[2]
            assert not any(phrase in body for phrase in unhappy), (seed, lab["ticket_id"])


def test_polite_tickets_do_not_thank_twice(tmp_path):
    for seed in (1, 2, 3):
        conn, _ = build(tmp_path, seed=seed, tag=f"t{seed}")
        for (body,) in conn.execute("SELECT body FROM tickets"):
            assert not re.search(r"Thanks for your help with this\.\s+(Thank|Many thanks)", body)