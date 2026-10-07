"""Tests for stage 0.4b: order histories and integrity checks."""
import random
from datetime import datetime

import pytest

from src.datagen import config
from src.datagen.domain import policy
from src.datagen.generation import orders
from src.datagen.store import checks
from src.datagen.store.db import create_database, load_base_data, load_orders


def build_db(tmp_path, seed=20261006, name="support.db"):
    conn = create_database(tmp_path / name)
    load_base_data(conn, seed)
    load_orders(conn, seed)
    return conn


@pytest.fixture
def conn(tmp_path):
    return build_db(tmp_path)


# ---------------------------------------------------------------- generation properties
@pytest.mark.parametrize("seed", [1, 7, 42, 2026, 20261006, 20261007])
def test_integrity_checks_pass_for_many_seeds(tmp_path, seed):
    c = build_db(tmp_path, seed)
    assert checks.run_checks(c) == []


def test_pool_size_and_reproducibility(tmp_path):
    a = build_db(tmp_path, 5, "a.db")
    b = build_db(tmp_path, 5, "b.db")
    assert a.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == config.N_ORDERS
    for table in ("orders", "order_items", "shipments", "payments", "refunds", "returns"):
        assert a.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() == \
               b.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_pool_contains_cases_needed_by_scenarios(conn):
    q = lambda sql: conn.execute(sql).fetchone()[0]
    assert q("SELECT COUNT(*) FROM orders WHERE status='processing'") >= 20
    assert q("SELECT COUNT(*) FROM shipments WHERE last_status='In transit - delayed'") >= 10
    assert q("SELECT COUNT(*) FROM returns WHERE status='label_issued'") >= 10
    assert q("SELECT COUNT(*) FROM refunds WHERE status='pending'") >= 8
    assert q("SELECT COUNT(*) FROM payments WHERE status='duplicate_flagged'") >= 3
    boundary = q("SELECT COUNT(*) FROM orders o JOIN shipments s USING(order_id) "
                 "WHERE o.status='delivered' AND julianday('2026-10-06') - julianday(substr(s.delivered_at,1,10)) "
                 "BETWEEN 29 AND 32")
    assert boundary >= 8


def test_money_is_stored_as_integer_cents(conn):
    for table, col in [("orders", "total_cents"), ("order_items", "unit_price_cents"),
                       ("payments", "amount_cents"), ("refunds", "amount_cents")]:
        bad = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE typeof({col}) != 'integer'").fetchone()[0]
        assert bad == 0, f"{table}.{col} contains non-integer values"


def test_order_ids_ascend_with_order_date(conn):
    rows = conn.execute("SELECT order_id, placed_at FROM orders ORDER BY order_id").fetchall()
    assert [r[1] for r in rows] == sorted(r[1] for r in rows)


# ---------------------------------------------------------------- spec-controlled builds
def make_ctx(conn):
    customers = conn.execute("SELECT * FROM customers").fetchall()
    addresses = conn.execute("SELECT * FROM addresses").fetchall()
    products = conn.execute("SELECT * FROM products").fetchall()
    by_customer = {}
    for a in addresses:
        by_customer.setdefault(a[1], []).append(a[0])
    return orders.OrderContext(customers, by_customer, products)


@pytest.mark.parametrize("days, inside", [(29, True), (30, True), (31, False), (32, False)])
def test_return_window_boundary_is_exact(conn, days, inside):
    rng = random.Random(3)
    spec = orders.OrderSpec(state="delivered", days_since_delivery=days)
    tl = orders.plan_timeline(spec, rng)
    assert policy.days_since_delivery(tl.delivered_at) == days
    assert policy.within_return_window(tl.delivered_at) is inside


def test_forced_final_sale_item_is_included(conn):
    rng = random.Random(4)
    ctx = make_ctx(conn)
    spec = orders.OrderSpec(state="delivered", days_since_delivery=10, include_final_sale_item=True)
    rows = orders.build_order(ctx, spec, orders.plan_timeline(spec, rng), rng)
    final_ids = {p[0] for p in ctx.products if p[4] == 1}
    assert any(item[2] in final_ids for item in rows.order_items)


def test_return_orders_never_contain_final_sale_items(conn):
    final_in_returns = conn.execute(
        "SELECT COUNT(*) FROM returns r JOIN order_items i USING(order_id) "
        "JOIN products p USING(product_id) WHERE p.final_sale=1").fetchone()[0]
    assert final_in_returns == 0


def test_invalid_specs_are_rejected(conn):
    rng = random.Random(5)
    ctx = make_ctx(conn)
    bad_dup = orders.OrderSpec(state="cancelled", duplicate_charge=True)
    with pytest.raises(ValueError):
        orders.build_order(ctx, bad_dup, orders.plan_timeline(bad_dup, rng), rng)
    bad_final = orders.OrderSpec(state="returned_refunded", include_final_sale_item=True)
    with pytest.raises(ValueError):
        orders.build_order(ctx, bad_final, orders.plan_timeline(bad_final, rng), rng)
    with pytest.raises(ValueError):
        orders.plan_timeline(orders.OrderSpec(state="teleported"), rng)


def test_duplicate_charge_spec_creates_flagged_payment(conn):
    rng = random.Random(6)
    ctx = make_ctx(conn)
    spec = orders.OrderSpec(state="delivered", days_since_delivery=5, duplicate_charge=True)
    rows = orders.build_order(ctx, spec, orders.plan_timeline(spec, rng), rng)
    assert sorted(p[4] for p in rows.payments) == ["captured", "duplicate_flagged"]
    assert rows.payments[0][2] == rows.payments[1][2]


# ---------------------------------------------------------------- the checks must catch damage
TAMPERS = {
    "total_matches_items": "UPDATE orders SET total_cents = total_cents + 1 WHERE order_id = 'O-000001'",
    "exactly_one_primary_payment": "DELETE FROM payments WHERE order_id = 'O-000001' AND status != 'duplicate_flagged'",
    "primary_payment_equals_total": "UPDATE payments SET amount_cents = amount_cents + 100 "
                                    "WHERE order_id = 'O-000001' AND status IN ('captured','refunded')",
    "dates_in_logical_order": "UPDATE shipments SET delivered_at = '2000-01-01T10:00:00' "
                              "WHERE delivered_at IS NOT NULL AND order_id = "
                              "(SELECT order_id FROM shipments WHERE delivered_at IS NOT NULL LIMIT 1)",
    "no_timestamps_after_reference_time": "UPDATE orders SET placed_at = '2030-01-01T10:00:00' WHERE order_id = 'O-000001'",
    "late_flag_matches_promised_date": "UPDATE shipments SET last_status = 'In transit' "
                                       "WHERE last_status = 'In transit - delayed'",
    "returned_orders_have_received_return": "DELETE FROM returns WHERE status = 'received'",
    "refund_matches_payment": "UPDATE refunds SET amount_cents = amount_cents + 1 WHERE refund_id = 'RF-000001'",
    "no_final_sale_items_in_returns": "UPDATE products SET final_sale = 1 WHERE product_id IN "
                                      "(SELECT product_id FROM order_items WHERE order_id IN (SELECT order_id FROM returns))",
    "shipping_address_belongs_to_customer": "UPDATE orders SET shipping_address_id = "
                                            "(SELECT address_id FROM addresses WHERE customer_id != orders.customer_id LIMIT 1) "
                                            "WHERE order_id = 'O-000001'",
    "duplicate_charge_follows_original": "UPDATE payments SET created_at = '2000-01-01T00:00:00' "
                                         "WHERE status = 'duplicate_flagged'",
}


@pytest.mark.parametrize("check_name", sorted(TAMPERS))
def test_each_check_detects_tampering(conn, check_name):
    assert checks.run_checks(conn) == []
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(TAMPERS[check_name])
    conn.commit()
    violations = checks.run_checks(conn)
    assert any(v.startswith(check_name) for v in violations), f"{check_name} not triggered: {violations}"


def test_order_timestamps_are_not_artificially_identical(conn):
    # Regression: processing orders once shared exact round timestamps (e.g. 20:00:00).
    rows = conn.execute("SELECT placed_at FROM orders WHERE status='processing'").fetchall()
    assert len({r[0] for r in rows}) == len(rows)
    assert not all(r[0].endswith(":00:00") for r in rows)