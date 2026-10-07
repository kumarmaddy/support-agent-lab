"""Assemble the ticket dataset: run the scenarios, shuffle, assign ids, store tickets and labels.

Each scenario draws from its own random stream (seed + scenario id), so the text of one scenario's
tickets does not depend on which other scenarios exist. Order and ticket ids, however, depend on
the scenario sequence in scenario_registry, so the dataset is only final when every family is
registered (stage 0.4d freezes it).
"""
import sqlite3
from pathlib import Path

from src.datagen import config
from src.datagen.domain import labels
from src.datagen.generation.base_data import make_rng
from src.datagen.store.db import insert_order_rows
from src.datagen.generation.orders import IdAllocator, OrderContext, OrderRows, ts
from src.datagen.scenarios.base import GeneratedTicket, MissingHeldoutPhrasing, ScenarioContext
from src.datagen.scenarios.registry import get_scenarios


def build_scenario_context(conn: sqlite3.Connection, split: str = "dev") -> ScenarioContext:
    customer_rows = conn.execute("SELECT * FROM customers ORDER BY customer_id").fetchall()
    address_rows = conn.execute("SELECT * FROM addresses ORDER BY address_id").fetchall()
    products = conn.execute("SELECT * FROM products ORDER BY product_id").fetchall()
    by_customer: dict[str, list[str]] = {}
    for address_id, customer_id, *_ in address_rows:
        by_customer.setdefault(customer_id, []).append(address_id)
    order_ctx = OrderContext(customer_rows, by_customer, products, IdAllocator.continuing_from(conn))
    open_ids = {r[0] for r in conn.execute(
        "SELECT DISTINCT customer_id FROM orders WHERE status IN ('processing', 'shipped')")}
    return ScenarioContext(
        order_ctx=order_ctx,
        product_names={p[0]: p[1] for p in products},
        customers={c[0]: c for c in customer_rows},
        open_customer_ids=open_ids,
        reserved_customer_ids=set(),
        split=split,
    )


def generate_tickets(conn: sqlite3.Connection, seed: int,
                     scenario_ids: set[str] | None = None, split: str = "dev") -> list[GeneratedTicket]:
    sctx = build_scenario_context(conn, split)
    generated: list[GeneratedTicket] = []
    selected = get_scenarios(scenario_ids)
    if split == "heldout":
        from src.datagen.scenarios.phrasing_heldout import HELDOUT
        missing = [s.scenario_id for s in selected
                   if not any(k == s.scenario_id or k.startswith(s.scenario_id + "_") for k in HELDOUT)]
        if missing:
            raise MissingHeldoutPhrasing(f"no held-out phrasing for: {', '.join(missing)}")
    for scenario in selected:
        rng = make_rng(seed, f"tickets:{scenario.scenario_id}")
        for i in range(scenario.count):
            generated.append(scenario.build(sctx, rng, i))
    make_rng(seed, "tickets:order").shuffle(generated)     # no ordering clues from ticket ids
    return generated


def create_ticket_dataset(conn: sqlite3.Connection, seed: int, split: str, labels_dir: Path,
                          scenario_ids: set[str] | None = None) -> dict:
    """Generate tickets and their orders, store them in the database, write labels to labels_dir."""
    generated = generate_tickets(conn, seed, scenario_ids, split)

    all_orders = OrderRows()
    ticket_rows, label_rows = [], []
    for n, g in enumerate(generated, start=1):
        ticket_id = f"T-{n:06d}"
        all_orders.extend(g.orders)
        ticket_rows.append((ticket_id, ts(g.received_at), "email", g.customer_email, g.subject, g.body))
        g.label.update(ticket_id=ticket_id, split=split, seed=seed,
                       generator_version=config.GENERATOR_VERSION)
        labels.validate_label(g.label)
        label_rows.append(g.label)

    insert_order_rows(conn, all_orders)
    with conn:
        conn.executemany("INSERT INTO tickets VALUES (?,?,?,?,?,?)", ticket_rows)

    labels_path = Path(labels_dir) / split / "labels.jsonl"
    labels.write_labels(labels_path, label_rows)

    by_scenario: dict[str, int] = {}
    for g in generated:
        by_scenario[g.scenario_id] = by_scenario.get(g.scenario_id, 0) + 1
    return {"tickets": len(ticket_rows), "by_scenario": dict(sorted(by_scenario.items())),
            "labels_path": str(labels_path)}