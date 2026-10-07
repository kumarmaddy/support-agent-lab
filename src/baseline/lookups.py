"""Read-only record lookups for the manual baseline.

These show the handler the same records the agent's read-only tools will expose, so the manual and automated
runs work from the same information. Nothing here can read ground-truth labels.
"""
import sqlite3
from pathlib import Path


def open_readonly(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def customer_by_email(conn: sqlite3.Connection, email: str):
    return conn.execute("SELECT customer_id, name, email, tier, created_at, status FROM customers "
                        "WHERE lower(email) = lower(?)", (email,)).fetchone()


def customer_summary(conn: sqlite3.Connection, email: str) -> str:
    row = customer_by_email(conn, email)
    if row is None:
        return f"No customer account has the email address {email}."
    cid, name, mail, tier, created, status = row
    lines = [f"Customer {cid}: {name} <{mail}>, tier {tier}, account {status}, created {created[:10]}"]
    for _id, line1, city, postal, country in conn.execute(
            "SELECT address_id, line1, city, postal_code, country FROM addresses WHERE customer_id = ?", (cid,)):
        lines.append(f"  address {_id}: {line1}, {city} {postal}, {country}")
    orders = conn.execute("SELECT order_id, placed_at, status, total_cents FROM orders WHERE customer_id = ? "
                          "ORDER BY placed_at", (cid,)).fetchall()
    lines.append(f"  {len(orders)} order(s):")
    for oid, placed, ostatus, total in orders:
        lines.append(f"    {oid}  placed {placed[:10]}  {ostatus}  {money(total)}")
    return "\n".join(lines)


def order_summary(conn: sqlite3.Connection, order_id: str) -> str:
    order = conn.execute(
        "SELECT o.order_id, o.placed_at, o.status, o.total_cents, o.promised_date, c.customer_id, c.name, c.email, "
        "a.line1, a.city, a.postal_code FROM orders o JOIN customers c USING (customer_id) "
        "JOIN addresses a ON a.address_id = o.shipping_address_id WHERE o.order_id = ?", (order_id,)).fetchone()
    if order is None:
        return f"No order {order_id}."
    oid, placed, status, total, promised, cid, name, email, line1, city, postal = order
    lines = [f"Order {oid}: {status}, placed {placed[:10]}, promised {promised}, total {money(total)}",
             f"  account holder: {cid} {name} <{email}>",
             f"  ships to: {line1}, {city} {postal}"]
    for pname, size, qty, unit, final_sale in conn.execute(
            "SELECT p.name, i.size, i.quantity, i.unit_price_cents, p.final_sale FROM order_items i "
            "JOIN products p USING (product_id) WHERE i.order_id = ?", (order_id,)):
        lines.append(f"  item: {qty} x {pname}" + (f" size {size}" if size else "") + f" at {money(unit)}"
                     + ("  [FINAL SALE]" if final_sale else ""))
    for carrier, tracking, dispatched, delivered, last in conn.execute(
            "SELECT carrier, tracking_no, dispatched_at, delivered_at, last_status FROM shipments "
            "WHERE order_id = ?", (order_id,)):
        lines.append(f"  shipment: {carrier} {tracking}, dispatched {(dispatched or 'not yet')[:10]}, "
                     f"delivered {(delivered or 'not yet')[:10]}, last status: {last}")
    for pid, amount, last4, pstatus, created in conn.execute(
            "SELECT payment_id, amount_cents, method_last4, status, created_at FROM payments WHERE order_id = ?",
            (order_id,)):
        lines.append(f"  payment {pid}: {money(amount)} card ending {last4}, {pstatus}, {created[:10]}")
    for rid, pid, amount, rstatus, requested in conn.execute(
            "SELECT r.refund_id, r.payment_id, r.amount_cents, r.status, r.requested_at FROM refunds r "
            "JOIN payments p USING (payment_id) WHERE p.order_id = ?", (order_id,)):
        lines.append(f"  refund {rid} (payment {pid}): {money(amount)}, {rstatus}, requested {requested[:10]}")
    for rid, rstatus, label, received in conn.execute(
            "SELECT return_id, status, label_issued_at, received_at FROM returns WHERE order_id = ?", (order_id,)):
        lines.append(f"  return {rid}: {rstatus}, label issued {(label or '-')[:10]}, "
                     f"received {(received or 'not yet')[:10]}")
    return "\n".join(lines)


def kb_list(articles) -> str:
    return "\n".join(f"  {a.kb_id}  {a.title}" for a in articles.values())


def kb_article(articles, kb_id: str) -> str:
    article = articles.get(kb_id.upper())
    if article is None:
        return f"No article {kb_id}. Type kb to list the articles."
    body = "\n\n".join(f"{name}\n{text}" for name, text in article.sections.items())
    return f"{article.kb_id}: {article.title}\n\n{body}"
