"""Tests for stage 0.4c-1: priority rubric, labels, text helpers, order-status tickets, CLI."""
import re
import sqlite3
from datetime import date, datetime, timedelta
import random

import pytest

from src.datagen import cli, config
from src.datagen.domain import labels, priority
from src.datagen.generation import text
from src.datagen.store import checks
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.generation.orders import IdAllocator
from src.datagen.scenarios.registry import SCENARIOS
from src.datagen.tickets import create_ticket_dataset

ORDER_ID = re.compile(r"O-\d{6}")


def build_dataset(tmp_path, seed=20261006, tag="a", scenario_ids=None):
    conn = create_database(tmp_path / f"{tag}.db")
    load_base_data(conn, seed)
    load_orders(conn, seed)
    summary = create_ticket_dataset(conn, seed, "dev", tmp_path / f"labels_{tag}", scenario_ids)
    return conn, summary


@pytest.fixture
def dataset(tmp_path):
    conn, summary = build_dataset(tmp_path)
    return conn, labels.read_labels(summary["labels_path"]), summary


def ticket_row(conn, ticket_id):
    return conn.execute("SELECT received_at, customer_email, subject, body FROM tickets "
                        "WHERE ticket_id = ?", (ticket_id,)).fetchone()


# ------------------------------------------------------------------ priority rubric v1.0
@pytest.mark.parametrize("flags, expected", [
    ({}, "LOW"),
    ({"order_late_past_promise": True}, "MEDIUM"),
    ({"item_damaged_or_wrong": True}, "MEDIUM"),
    ({"account_locked_out": True}, "MEDIUM"),
    ({"duplicate_or_unauthorized_charge": True}, "HIGH"),
    ({"account_compromise_suspected": True}, "HIGH"),
    ({"chargeback_or_legal_threat": True}, "HIGH"),
    ({"deadline_within_3_days": True}, "HIGH"),
    ({"order_late_past_promise": True, "duplicate_or_unauthorized_charge": True}, "HIGH"),  # highest wins
])
def test_priority_rubric(flags, expected):
    assert priority.compute_priority(priority.make_attributes(**flags)) == expected


def test_priority_rejects_unknown_or_incomplete_attributes():
    with pytest.raises(ValueError):
        priority.make_attributes(angry_customer=True)
    with pytest.raises(ValueError):
        priority.compute_priority({"order_late_past_promise": True})


# ------------------------------------------------------------------ label validation
def valid_label():
    lab = labels.new_label(scenario_id="S01", category="order_status", attributes=priority.make_attributes(),
                           expected_actions=["provide_info"], required_kb_ids=["KB-SHP-01"],
                           referenced_order_id="O-000001")
    lab.update(ticket_id="T-000001", split="dev", seed=1)
    return lab


def test_valid_label_passes():
    assert labels.label_problems(valid_label()) == []


@pytest.mark.parametrize("change", [
    {"category": "billing"},
    {"priority": "HIGH"},                                  # does not match attributes
    {"expected_actions": []},
    {"expected_actions": ["delete_account"]},
    {"expected_escalate": True},                           # no escalate_human action
    {"expected_actions": ["escalate_human"]},              # escalate flag not set
    {"required_kb_ids": ["KB-XXX-99"]},
    {"referenced_order_id": None},                         # order_identifiable still True
    {"difficulty": "adversarial"},                         # no adversarial_type
    {"split": "test"},
    {"text_source": "human"},
])
def test_invalid_labels_are_rejected(change):
    lab = valid_label()
    lab.update(change)
    assert labels.label_problems(lab) != []
    with pytest.raises(ValueError):
        labels.validate_label(lab)


def test_escalation_requires_reason():
    lab = valid_label()
    lab.update(expected_actions=["escalate_human"], expected_escalate=True, escalation_reason=None)
    assert any("escalation_reason" in p for p in labels.label_problems(lab))


# ------------------------------------------------------------------ text helpers
def test_weekday_name():
    assert text.weekday_name(date(2026, 10, 6)) == "Tuesday"


def test_typos_are_deterministic_and_protect_dates_ids_and_numbers():
    sample = "Order O-000123 arrives Wednesday September 9 with tracking number 123456 attached"
    a = text.add_typos(random.Random(1), sample)
    b = text.add_typos(random.Random(1), sample)
    assert a == b
    for protected in ("O-000123", "Wednesday", "September 9", "123456"):
        assert protected in a


def test_compose_includes_name_and_core():
    body = text.compose(random.Random(2), "Where is my order?", "Priya", "polite", typo=False)
    assert "Where is my order?" in body and body.rstrip().endswith("Priya")


# ------------------------------------------------------------------ dataset structure
def test_counts_match_registry(dataset):
    conn, labs, summary = dataset
    expected = {s.scenario_id: s.count for s in SCENARIOS}
    assert summary["by_scenario"] == expected
    assert summary["tickets"] == sum(expected.values()) == len(labs)
    assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == len(labs)


def test_ticket_ids_sequential_and_labels_valid(dataset):
    conn, labs, _ = dataset
    ids = [l["ticket_id"] for l in labs]
    assert ids == [f"T-{n:06d}" for n in range(1, len(labs) + 1)]
    for lab in labs:
        labels.validate_label(lab)
        assert lab["split"] == "dev" and lab["seed"] == config.DEFAULT_SEED_DEV


def test_ticket_ids_do_not_reveal_scenario_grouping(dataset):
    _, labs, _ = dataset
    sequence = [l["scenario_id"] for l in labs]
    assert sequence != sorted(sequence)


def test_labels_live_outside_the_database(dataset):
    conn, _, summary = dataset
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not any("label" in t for t in tables)
    assert "labels.jsonl" in summary["labels_path"]


def test_bodies_are_unique(dataset):
    conn, _, _ = dataset
    bodies = [r[0] for r in conn.execute("SELECT body FROM tickets")]
    assert len(bodies) == len(set(bodies))


def test_integrity_checks_still_pass_with_tickets(dataset):
    conn, _, _ = dataset
    assert checks.run_checks(conn) == []


# ------------------------------------------------------------------ labels agree with the database
def test_referenced_orders_belong_to_the_sender_and_are_mentioned(dataset):
    conn, labs, _ = dataset
    for lab in labs:
        received_at, email, subject, body = ticket_row(conn, lab["ticket_id"])
        if lab["referenced_order_id"] is None:
            assert not ORDER_ID.search(body) and not ORDER_ID.search(subject)
            continue
        owner = conn.execute("SELECT c.email, o.placed_at FROM orders o JOIN customers c USING(customer_id) "
                             "WHERE o.order_id = ?", (lab["referenced_order_id"],)).fetchone()
        assert owner is not None, lab["ticket_id"]
        if lab["adversarial_type"] == "impersonation":      # S25: the order belongs to someone else
            assert owner[0] != email                        # (asserted in detail in test_datagen_adversarial)
        else:
            assert owner[0] == email
        assert lab["referenced_order_id"] in body + subject
        assert received_at > owner[1]                       # ticket arrives after the order was placed
        assert set(ORDER_ID.findall(body + subject)) <= {lab["referenced_order_id"]}


def test_expected_facts_match_database(dataset):
    conn, labs, _ = dataset
    for lab in labs:
        oid = lab["referenced_order_id"]
        if oid is None or lab["adversarial_type"] == "impersonation":   # S25 facts describe the request, not the order
            continue
        status, promised = conn.execute("SELECT status, promised_date FROM orders WHERE order_id=?", (oid,)).fetchone()
        facts = lab["expected_facts"]
        assert facts["order_status"] == status and facts["promised_date"] == promised
        ship = conn.execute("SELECT carrier, tracking_no, last_status FROM shipments WHERE order_id=?", (oid,)).fetchone()
        if "tracking_no" in facts:
            assert (facts["carrier"], facts["tracking_no"], facts["last_status"]) == ship
        if "dispatched" in facts:
            assert (ship is not None) == facts["dispatched"]


def labels_for(labs, scenario):
    return [l for l in labs if l["scenario_id"] == scenario]


def test_s01_orders_are_in_transit_within_promise(dataset):
    conn, labs, _ = dataset
    for lab in labels_for(labs, "S01"):
        promised, last = conn.execute("SELECT o.promised_date, s.last_status FROM orders o JOIN shipments s "
                                      "USING(order_id) WHERE o.order_id=?", (lab["referenced_order_id"],)).fetchone()
        assert last == "In transit" and promised >= config.AS_OF_DATE.isoformat()
        assert lab["priority"] == "LOW"


def test_s02_orders_are_late_and_medium_priority(dataset):
    conn, labs, _ = dataset
    for lab in labels_for(labs, "S02"):
        promised, last = conn.execute("SELECT o.promised_date, s.last_status FROM orders o JOIN shipments s "
                                      "USING(order_id) WHERE o.order_id=?", (lab["referenced_order_id"],)).fetchone()
        assert last == "In transit - delayed" and promised < config.AS_OF_DATE.isoformat()
        assert lab["priority"] == "MEDIUM" and lab["priority_attributes"]["order_late_past_promise"]


def test_s03_and_s22_orders_are_not_dispatched(dataset):
    conn, labs, _ = dataset
    for lab in labels_for(labs, "S03") + labels_for(labs, "S22"):
        status, shipments = conn.execute(
            "SELECT o.status, (SELECT COUNT(*) FROM shipments s WHERE s.order_id=o.order_id) "
            "FROM orders o WHERE o.order_id=?", (lab["referenced_order_id"],)).fetchone()
        assert status == "processing" and shipments == 0


def test_s03_covers_the_rubric_edge_cases_without_raising_priority(dataset):
    conn, labs, _ = dataset
    s03 = labels_for(labs, "S03")
    assert len(s03) == 5 and all(l["priority"] == "LOW" for l in s03)
    assert sum(l["ambiguity_flag"] for l in s03) == 1
    far = [l for l in s03 if "deadline_date" in l["expected_facts"]]
    assert len(far) == 1
    received = datetime.fromisoformat(ticket_row(conn, far[0]["ticket_id"])[0]).date()
    gap = (date.fromisoformat(far[0]["expected_facts"]["deadline_date"]) - received).days
    assert gap >= 6                                          # too far away to be HIGH
    assert sum(l["difficulty"] == "edge" for l in s03) == 3  # far deadline, vague urgency, anger


def test_s22_deadlines_are_within_three_days_and_escalate(dataset):
    conn, labs, _ = dataset
    for lab in labels_for(labs, "S22"):
        received = datetime.fromisoformat(ticket_row(conn, lab["ticket_id"])[0]).date()
        gap = (date.fromisoformat(lab["expected_facts"]["deadline_date"]) - received).days
        assert 1 <= gap <= 3
        assert lab["priority"] == "HIGH" and lab["expected_escalate"] and lab["expected_actions"] == ["escalate_human"]


def test_s04_customers_have_exactly_two_open_orders_and_no_order_number(dataset):
    conn, labs, _ = dataset
    for lab in labels_for(labs, "S04"):
        email = ticket_row(conn, lab["ticket_id"])[1]
        open_orders = sorted(r[0] for r in conn.execute(
            "SELECT o.order_id FROM orders o JOIN customers c USING(customer_id) "
            "WHERE c.email=? AND o.status IN ('processing','shipped')", (email,)))
        assert open_orders == lab["expected_facts"]["candidate_order_ids"] and len(open_orders) == 2
        assert lab["expected_actions"] == ["request_info"] and not lab["order_identifiable"]


# ------------------------------------------------------------------ reproducibility
def test_same_seed_gives_byte_identical_labels_and_tickets(tmp_path):
    conn_a, sum_a = build_dataset(tmp_path, tag="a")
    conn_b, sum_b = build_dataset(tmp_path, tag="b")
    assert open(sum_a["labels_path"], "rb").read() == open(sum_b["labels_path"], "rb").read()
    assert conn_a.execute("SELECT * FROM tickets ORDER BY 1").fetchall() == \
           conn_b.execute("SELECT * FROM tickets ORDER BY 1").fetchall()


def test_different_seed_changes_tickets(tmp_path):
    a, _ = build_dataset(tmp_path, seed=1, tag="a")
    b, _ = build_dataset(tmp_path, seed=2, tag="b")
    assert a.execute("SELECT body FROM tickets ORDER BY 1").fetchall() != \
           b.execute("SELECT body FROM tickets ORDER BY 1").fetchall()


def test_scenario_text_does_not_depend_on_other_scenarios(tmp_path):
    """Each scenario has its own random stream, so S02 reads the same with or without S01 present."""
    only, _ = build_dataset(tmp_path, tag="only", scenario_ids={"S02"})
    full, _ = build_dataset(tmp_path, tag="full")
    norm = lambda s: ORDER_ID.sub("O-X", s)

    def s02_texts(conn, scenario_labels):
        return sorted((norm(r[2]), norm(r[3])) for r in conn.execute("SELECT * FROM tickets")
                      if r[0] in scenario_labels)

    full_labels = {l["ticket_id"] for l in labels.read_labels(tmp_path / "labels_full" / "dev" / "labels.jsonl")
                   if l["scenario_id"] == "S02"}
    only_labels = {l["ticket_id"] for l in labels.read_labels(tmp_path / "labels_only" / "dev" / "labels.jsonl")}
    assert s02_texts(only, only_labels) == s02_texts(full, full_labels)


# ------------------------------------------------------------------ supporting pieces
def test_id_allocator_continues_after_existing_rows(tmp_path):
    conn = create_database(tmp_path / "x.db")
    load_base_data(conn, 3)
    load_orders(conn, 3)
    alloc = IdAllocator.continuing_from(conn)
    assert alloc.next("order") == f"O-{config.N_ORDERS + 1:06d}"
    assert alloc.next("payment").startswith("PM-")


def test_new_ticket_checks_detect_tampering(dataset):
    conn, _, _ = dataset
    conn.execute("UPDATE tickets SET customer_email = 'stranger@example.org' WHERE ticket_id = 'T-000001'")
    conn.execute("UPDATE tickets SET received_at = '2031-01-01T00:00:00' WHERE ticket_id = 'T-000002'")
    conn.commit()
    names = [v.split(":")[0] for v in checks.run_checks(conn)]
    assert "tickets_come_from_known_customers" in names
    assert "no_timestamps_after_reference_time" in names


def test_cli_end_to_end_and_refuses_to_overwrite(tmp_path, capsys):
    args = ["--split", "dev", "--out", str(tmp_path / "gen"), "--labels-dir", str(tmp_path / "lab")]
    assert cli.main(args) == 0
    assert "Integrity checks: PASS" in capsys.readouterr().out
    assert (tmp_path / "gen" / "support.db").exists()
    assert (tmp_path / "lab" / "dev" / "labels.jsonl").exists()
    with pytest.raises(FileExistsError):
        cli.main(args)
    assert cli.main(args + ["--force"]) == 0