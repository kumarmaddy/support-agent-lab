"""Database creation and loading helpers."""
import sqlite3
from pathlib import Path

from . import base_data, orders
from .schema import DDL


def create_database(path: Path, force: bool = False) -> sqlite3.Connection:
    """Create an empty database with the full schema.

    Refuses to overwrite an existing file unless force=True, so a frozen dataset is never
    replaced by accident.
    """
    path = Path(path)
    if path.exists():
        if not force:
            raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(DDL)
    return conn


def load_base_data(conn: sqlite3.Connection, seed: int) -> dict[str, int]:
    customers, addresses = base_data.generate_customers_and_addresses(seed)
    products = base_data.generate_products(seed)
    with conn:  # single transaction
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?)", customers)
        conn.executemany("INSERT INTO addresses VALUES (?,?,?,?,?,?)", addresses)
        conn.executemany("INSERT INTO products VALUES (?,?,?,?,?)", products)
    return {"customers": len(customers), "addresses": len(addresses), "products": len(products)}


def load_orders(conn: sqlite3.Connection, seed: int) -> dict[str, int]:
    customers = conn.execute("SELECT * FROM customers ORDER BY customer_id").fetchall()
    addresses = conn.execute("SELECT * FROM addresses ORDER BY address_id").fetchall()
    products = conn.execute("SELECT * FROM products ORDER BY product_id").fetchall()
    pool = orders.generate_order_pool(seed, customers, addresses, products)
    with conn:
        conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?,?,?)", pool.orders)
        conn.executemany("INSERT INTO order_items VALUES (?,?,?,?,?,?)", pool.order_items)
        conn.executemany("INSERT INTO shipments VALUES (?,?,?,?,?,?,?)", pool.shipments)
        conn.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", pool.payments)
        conn.executemany("INSERT INTO refunds VALUES (?,?,?,?,?)", pool.refunds)
        conn.executemany("INSERT INTO returns VALUES (?,?,?,?,?)", pool.returns)
    return {"orders": len(pool.orders), "order_items": len(pool.order_items),
            "shipments": len(pool.shipments), "payments": len(pool.payments),
            "refunds": len(pool.refunds), "returns": len(pool.returns)}
