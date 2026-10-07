"""Tests for stage 0.4c-2: returns, exchanges and refunds (S05-S11, S21, S23)."""
import re
from datetime import datetime

import pytest

from src.datagen import config, labels, policy, reference, text
from src.datagen.db import create_database, load_base_data, load_orders
from src.datagen.scenario_registry import SCENARIOS
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


def ticket(conn, label):
    return conn.execute("SELECT received_at, subject, body FROM tickets WHERE ticket_id=?",
                        (label["ticket_id"],)).fetchone()


def delivered_at(conn, order_id):
    return datetime.fromisoformat(
        conn.execute("SELECT delivered_at FROM shipments WHERE order_id=?", (order_id,)).fetchone()[0])


# ------------------------------------------------------------------ structure
def test_registry_order_is_stable():
    """Ids depend on this order; new families must be appended, never inserted."""
    assert [s.scenario_id for s in SCENARIOS] == [
        "S01", "S02", "S03", "S04", "S22", "S05", "S06", "S07", "S08", "S09", "S10", "S11", "S21", "S23"]


def test_counts(ds):
    _, labs = ds
    expected = {"S05": 10, "S06": 6, "S07": 5, "S08": 6, "S09": 8, "S10": 6, "S11": 8, "S21": 4, "S23": 4}
    for scenario, n in expected.items():
        assert len(of(labs, scenario)) == n, scenario
    assert len(labs) == 90


def test_ticket_arrives_after_every_event_on_its_order(ds):
    """A customer cannot complain about damage before delivery or ask about a refund before the return."""
    conn, labs = ds
    for lab in labs:
        oid = lab["referenced_order_id"]
        if oid is None:
            continue
        events = [r[0] for r in conn.execute(
            "SELECT placed_at FROM orders WHERE order_id=? UNION "
            "SELECT dispatched_at FROM shipments WHERE order_id=? UNION "
            "SELECT delivered_at FROM shipments WHERE order_id=? UNION "
            "SELECT label_issued_at FROM returns WHERE order_id=? UNION "
            "SELECT received_at FROM returns WHERE order_id=?", (oid,) * 5) if r[0]]
        assert ticket(conn, lab)[0] > max(events), lab["ticket_id"]


# ------------------------------------------------------------------ return window (policy-driven labels)
def test_window_facts_agree_with_policy_and_database(ds):
    conn, labs = ds
    for scenario in ("S05", "S06", "S07", "S08", "S11"):
        for lab in of(labs, scenario):
            d = delivered_at(conn, lab["referenced_order_id"])
            facts = lab["expected_facts"]
            assert facts["days_since_delivery"] == policy.days_since_delivery(d)
            assert facts["within_return_window"] == policy.within_return_window(d)


def test_s05_is_inside_the_window_and_includes_both_boundary_days(ds):
    conn, labs = ds
    s05 = of(labs, "S05")
    assert all(l["expected_facts"]["within_return_window"] and l["expected_actions"] == ["propose_return_label"]
               for l in s05)
    days = sorted(l["expected_facts"]["days_since_delivery"] for l in s05)
    assert 29 in days and 30 in days                          # day 30 is still inside the window
    assert sum(l["difficulty"] == "edge" for l in s05) == 2


def test_s06_is_outside_the_window_and_includes_the_first_day_outside(ds):
    _, labs = ds
    s06 = of(labs, "S06")
    assert all(not l["expected_facts"]["within_return_window"] and l["expected_actions"] == ["decline_policy"]
               for l in s06)
    days = [l["expected_facts"]["days_since_delivery"] for l in s06]
    assert min(days) == 31 and days.count(31) >= 2


def test_s07_blocks_only_because_of_final_sale(ds):
    conn, labs = ds
    final_ids = {r[0] for r in conn.execute("SELECT product_id FROM products WHERE final_sale=1")}
    for lab in of(labs, "S07"):
        assert lab["expected_facts"]["within_return_window"]
        assert lab["expected_facts"]["final_sale_product_id"] in final_ids
        first_item = conn.execute("SELECT product_id FROM order_items WHERE order_id=? ORDER BY order_item_id LIMIT 1",
                                  (lab["referenced_order_id"],)).fetchone()[0]
        assert first_item == lab["expected_facts"]["final_sale_product_id"]
        assert lab["expected_actions"] == ["decline_policy"]


def test_other_return_scenarios_never_contain_final_sale_items(ds):
    conn, labs = ds
    for scenario in ("S05", "S06", "S08", "S11"):
        for lab in of(labs, scenario):
            n = conn.execute("SELECT COUNT(*) FROM order_items i JOIN products p USING(product_id) "
                             "WHERE i.order_id=? AND p.final_sale=1", (lab["referenced_order_id"],)).fetchone()[0]
            assert n == 0, lab["ticket_id"]


def test_s08_requests_an_adjacent_size_of_the_ordered_item(ds):
    conn, labs = ds
    for lab in of(labs, "S08"):
        item = conn.execute("SELECT p.category, i.size FROM order_items i JOIN products p USING(product_id) "
                            "WHERE i.order_id=? ORDER BY i.order_item_id LIMIT 1",
                            (lab["referenced_order_id"],)).fetchone()
        sizes = reference.SIZES[reference.CATEGORY_SIZING[item[0]]]
        facts = lab["expected_facts"]
        assert sizes and facts["current_size"] == item[1]
        assert abs(sizes.index(facts["requested_size"]) - sizes.index(facts["current_size"])) == 1
        assert lab["expected_actions"] == ["propose_exchange"]


# ------------------------------------------------------------------ refunds and charges
@pytest.mark.parametrize("cents, expected", [(1499, "$14.99"), (5, "$0.05"), (0, "$0.00"),
                                             (100000, "$1,000.00"), (12999, "$129.99")])
def test_money_formatting_uses_integer_cents(cents, expected):
    assert text.fmt_money(cents) == expected


def test_s09_duplicate_charges_match_database_and_text(ds):
    conn, labs = ds
    for lab in of(labs, "S09") + of(labs, "S23"):
        oid = lab["referenced_order_id"]
        pays = conn.execute("SELECT payment_id, amount_cents, status FROM payments WHERE order_id=? "
                            "ORDER BY created_at", (oid,)).fetchall()
        assert [p[2] for p in pays] == ["captured", "duplicate_flagged"] and pays[0][1] == pays[1][1]
        assert lab["expected_facts"]["duplicate_payment_id"] == pays[1][0]
        assert lab["expected_facts"]["duplicate_amount_cents"] == pays[1][1]
        amounts = set(re.findall(r"\$[\d,]+\.\d{2}", ticket(conn, lab)[2]))
        assert amounts <= {text.fmt_money(pays[1][1])}
        assert lab["priority"] == "HIGH"


def test_s09_always_mentions_the_order_number(ds):
    conn, labs = ds
    for lab in of(labs, "S09"):
        assert lab["referenced_order_id"] in ticket(conn, lab)[1] + ticket(conn, lab)[2]
        assert lab["category"] == "refund" and lab["expected_actions"] == ["propose_refund"]


def test_s10_refund_state_matches_database(ds):
    conn, labs = ds
    s10 = of(labs, "S10")
    assert sorted(l["expected_facts"]["refund_status"] for l in s10) == ["pending"] * 4 + ["processed"] * 2
    for lab in s10:
        oid = lab["referenced_order_id"]
        status, amount = conn.execute("SELECT rf.status, rf.amount_cents FROM refunds rf JOIN payments p "
                                      "USING(payment_id) WHERE p.order_id=?", (oid,)).fetchone()
        assert lab["expected_facts"]["refund_status"] == status
        assert lab["expected_facts"]["refund_amount_cents"] == amount
        assert (lab["difficulty"] == "edge") == (status == "processed")   # already-refunded is the harder case


def test_s11_damage_requests_split_between_refund_and_replacement(ds):
    conn, labs = ds
    s11 = of(labs, "S11")
    refunds = [l for l in s11 if l["category"] == "refund"]
    replacements = [l for l in s11 if l["category"] == "return_exchange"]
    assert len(refunds) == len(replacements) == 4
    assert all(l["expected_actions"] == ["propose_refund"] for l in refunds)
    assert all(l["expected_actions"] == ["propose_replacement"] for l in replacements)
    for lab in s11:
        assert lab["priority"] == "MEDIUM" and lab["priority_attributes"]["item_damaged_or_wrong"]
        assert 1 <= lab["expected_facts"]["days_since_delivery"] <= 20


def test_s21_threats_escalate_with_the_right_secondary_category(ds):
    conn, labs = ds
    s21 = of(labs, "S21")
    for lab in s21:
        assert lab["priority"] == "HIGH" and lab["priority_attributes"]["chargeback_or_legal_threat"]
        assert lab["expected_actions"] == ["escalate_human"] and lab["escalation_reason"] == "chargeback_or_legal_threat"
        late = lab["expected_facts"].get("last_status") == "In transit - delayed"
        assert lab["priority_attributes"]["order_late_past_promise"] == late
        assert lab["secondary_categories"] == (["order_status"] if late else [])
        assert not re.search(r"\b\d+ (hours?|days?)\b", ticket(conn, lab)[2])   # no threat deadline wording


def test_s23_is_late_and_duplicated_and_high(ds):
    conn, labs = ds
    for lab in of(labs, "S23"):
        assert lab["priority"] == "HIGH"
        assert lab["priority_attributes"]["duplicate_or_unauthorized_charge"]
        assert lab["priority_attributes"]["order_late_past_promise"]
        assert lab["expected_actions"] == ["propose_refund", "provide_info"]
        assert lab["secondary_categories"] == ["order_status"]
        assert lab["expected_facts"]["last_status"] == "In transit - delayed"


# ------------------------------------------------------------------ grammar regression
def test_grammar_fields_for_plural_and_singular_products():
    plural = text.grammar_fields("Backcountry Hiking Pants")
    assert (plural["be"], plural["was"], plural["has"], plural["them"]) == ("are", "were", "have", "them")
    assert text.grammar_fields("Alpine Hiking Pants 20")["be"] == "are"     # collision suffix on the name
    singular = text.grammar_fields("Evergreen Shell Jacket")
    assert (singular["be"], singular["has"], singular["them"]) == ("is", "has", "it")


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_ticket_grammar_across_seeds(tmp_path, seed):
    conn, _ = build(tmp_path, seed=seed)
    problems = []
    for tid, body in conn.execute("SELECT ticket_id, body FROM tickets"):
        flat = " ".join(body.split())
        # A plural product word as the grammatical subject: directly before the verb, after
        # "from/in order O-xxxxxx", or directly before "(order O-xxxxxx)" and then the verb.
        singular_verb = r"(is|has|was|doesn't|isn't)\b"
        plural_word = r"(Pants|Shorts|Gloves|Poles|Socks)"
        if re.search(plural_word + r"(\s+(from|in)\s+order\s+O-\d{6}|\s*\(order\s+O-\d{6}\))?\s+" + singular_verb, flat):
            problems.append((tid, "plural product with singular verb"))
        if re.search(r"\b(exchange|replace|return) they\b", flat):
            problems.append((tid, "'they' used as an object"))
        if re.search(r"\ba (XS|S|M|L|XL|XXL|\d+)\b", flat):
            problems.append((tid, "article before a size"))
    assert problems == []