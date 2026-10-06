"""Tests for stage 0.4a: schema, customers, addresses, products."""
import sqlite3

import pytest

from src.datagen import config
from src.datagen.db import create_database, load_base_data
from src.datagen.schema import EXPECTED_TABLES


def build(tmp_path, seed, name="support.db"):
    conn = create_database(tmp_path / name)
    counts = load_base_data(conn, seed)
    return conn, counts


def dump(conn, table):
    return conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()


def test_schema_contains_all_expected_tables(tmp_path):
    conn = create_database(tmp_path / "s.db")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(EXPECTED_TABLES) <= names


def test_volumes_match_design(tmp_path):
    conn, counts = build(tmp_path, 1)
    assert counts["customers"] == config.N_CUSTOMERS
    assert counts["products"] == config.N_PRODUCTS
    assert counts["addresses"] >= counts["customers"]


def test_same_seed_is_reproducible(tmp_path):
    a, _ = build(tmp_path, 42, "a.db")
    b, _ = build(tmp_path, 42, "b.db")
    for table in ("customers", "addresses", "products"):
        assert dump(a, table) == dump(b, table)


def test_different_seed_changes_data(tmp_path):
    a, _ = build(tmp_path, 1, "a.db")
    b, _ = build(tmp_path, 2, "b.db")
    assert dump(a, "customers") != dump(b, "customers")


def test_emails_unique_and_use_reserved_domain(tmp_path):
    conn, _ = build(tmp_path, 7)
    emails = [r[0] for r in conn.execute("SELECT email FROM customers")]
    assert len(emails) == len(set(emails))
    assert all(e.endswith("@example.com") for e in emails)


def test_every_customer_has_an_address(tmp_path):
    conn, _ = build(tmp_path, 7)
    missing = conn.execute(
        "SELECT COUNT(*) FROM customers c LEFT JOIN addresses a USING (customer_id) "
        "WHERE a.address_id IS NULL").fetchone()[0]
    assert missing == 0


def test_foreign_keys_are_consistent(tmp_path):
    conn, _ = build(tmp_path, 7)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_locked_customers_count(tmp_path):
    conn, _ = build(tmp_path, 7)
    locked = conn.execute("SELECT COUNT(*) FROM customers WHERE status='locked'").fetchone()[0]
    assert locked == config.N_LOCKED_CUSTOMERS


def test_final_sale_products_count(tmp_path):
    conn, _ = build(tmp_path, 7)
    n = conn.execute("SELECT COUNT(*) FROM products WHERE final_sale=1").fetchone()[0]
    assert n == config.N_FINAL_SALE_PRODUCTS


def test_prices_are_integer_cents_and_positive(tmp_path):
    conn, _ = build(tmp_path, 7)
    rows = conn.execute("SELECT price_cents, typeof(price_cents) FROM products").fetchall()
    assert all(p > 0 and t == "integer" for p, t in rows)
    assert all(p % 100 == 99 for p, _ in rows)  # priced like 79.99


def test_product_names_unique(tmp_path):
    conn, _ = build(tmp_path, 7)
    names = [r[0] for r in conn.execute("SELECT name FROM products")]
    assert len(names) == len(set(names))


def test_existing_database_is_not_overwritten_without_force(tmp_path):
    create_database(tmp_path / "keep.db").close()
    with pytest.raises(FileExistsError):
        create_database(tmp_path / "keep.db")
    create_database(tmp_path / "keep.db", force=True).close()  # explicit overwrite works
