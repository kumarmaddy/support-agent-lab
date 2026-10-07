"""SQLite schema for the operational database.

Design reference: docs/design/data-design.md section 4.
All monetary amounts are integer cents (USD). Ground-truth labels are NOT stored here.
"""

DDL = """
CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    tier        TEXT NOT NULL CHECK (tier IN ('standard', 'silver', 'gold')),
    created_at  TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'locked'))
);

CREATE TABLE addresses (
    address_id  TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers (customer_id),
    line1       TEXT NOT NULL,
    city        TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country     TEXT NOT NULL
);

CREATE TABLE products (
    product_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    final_sale  INTEGER NOT NULL CHECK (final_sale IN (0, 1))
);

CREATE TABLE orders (
    order_id            TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers (customer_id),
    placed_at           TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN
                            ('processing', 'shipped', 'delivered', 'cancelled', 'returned')),
    total_cents         INTEGER NOT NULL CHECK (total_cents >= 0),
    promised_date       TEXT NOT NULL,
    shipping_address_id TEXT NOT NULL REFERENCES addresses (address_id)
);

CREATE TABLE order_items (
    order_item_id    TEXT PRIMARY KEY,
    order_id         TEXT NOT NULL REFERENCES orders (order_id),
    product_id       TEXT NOT NULL REFERENCES products (product_id),
    size             TEXT,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents > 0)
);

CREATE TABLE shipments (
    shipment_id   TEXT PRIMARY KEY,
    order_id      TEXT NOT NULL REFERENCES orders (order_id),
    carrier       TEXT NOT NULL,
    tracking_no   TEXT NOT NULL,
    dispatched_at TEXT,
    delivered_at  TEXT,
    last_status   TEXT NOT NULL
);

CREATE TABLE payments (
    payment_id   TEXT PRIMARY KEY,
    order_id     TEXT NOT NULL REFERENCES orders (order_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    method_last4 TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('captured', 'refunded', 'duplicate_flagged')),
    created_at   TEXT NOT NULL
);

CREATE TABLE refunds (
    refund_id    TEXT PRIMARY KEY,
    payment_id   TEXT NOT NULL REFERENCES payments (payment_id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    status       TEXT NOT NULL,
    requested_at TEXT NOT NULL
);

CREATE TABLE returns (
    return_id       TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES orders (order_id),
    status          TEXT NOT NULL,
    label_issued_at TEXT,
    received_at     TEXT
);

CREATE TABLE tickets (
    ticket_id      TEXT PRIMARY KEY,
    received_at    TEXT NOT NULL,
    channel        TEXT NOT NULL,
    customer_email TEXT NOT NULL,
    subject        TEXT NOT NULL,
    body           TEXT NOT NULL
);

CREATE TABLE kb_articles (
    kb_id    TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    category TEXT NOT NULL,
    version  TEXT NOT NULL,
    path     TEXT NOT NULL
);

CREATE TABLE audit_log (
    event_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT,
    actor     TEXT NOT NULL,
    action    TEXT NOT NULL,
    detail    TEXT,
    timestamp TEXT NOT NULL
);
"""

EXPECTED_TABLES = [
    "customers", "addresses", "products", "orders", "order_items", "shipments",
    "payments", "refunds", "returns", "tickets", "kb_articles", "audit_log",
]
