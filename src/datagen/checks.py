"""Independent integrity checks on a generated database.

These checks are written separately from the generator on purpose: they validate the data as a
reviewer would, using SQL, not by re-using generator logic. Each check returns the offending rows;
an empty result means the check passes. Extended with label checks in stage 0.4d.
"""
import sqlite3

from . import config

_NOW = config.AS_OF_DATETIME.strftime("%Y-%m-%dT%H:%M:%S")
_TODAY = config.AS_OF_DATE.isoformat()

CHECKS: dict[str, tuple[str, tuple]] = {
    "order_has_items": (
        "SELECT order_id FROM orders WHERE order_id NOT IN (SELECT order_id FROM order_items)", ()),
    "total_matches_items": (
        "SELECT o.order_id FROM orders o JOIN (SELECT order_id, SUM(quantity * unit_price_cents) AS s "
        "FROM order_items GROUP BY order_id) i USING (order_id) WHERE o.total_cents != i.s", ()),
    "exactly_one_primary_payment": (
        "SELECT o.order_id FROM orders o LEFT JOIN payments p ON p.order_id = o.order_id "
        "AND p.status IN ('captured', 'refunded') GROUP BY o.order_id HAVING COUNT(p.payment_id) != 1", ()),
    "primary_payment_equals_total": (
        "SELECT o.order_id FROM orders o JOIN payments p ON p.order_id = o.order_id "
        "AND p.status IN ('captured', 'refunded') WHERE p.amount_cents != o.total_cents", ()),
    "shipment_presence_matches_status": (
        "SELECT o.order_id FROM orders o LEFT JOIN shipments s USING (order_id) "
        "GROUP BY o.order_id, o.status HAVING "
        "(o.status IN ('processing', 'cancelled') AND COUNT(s.shipment_id) > 0) OR "
        "(o.status IN ('shipped', 'delivered', 'returned') AND COUNT(s.shipment_id) != 1)", ()),
    "dates_in_logical_order": (
        "SELECT s.order_id FROM shipments s JOIN orders o USING (order_id) "
        "WHERE s.dispatched_at <= o.placed_at "
        "OR (s.delivered_at IS NOT NULL AND s.delivered_at <= s.dispatched_at)", ()),
    "delivery_matches_order_status": (
        "SELECT o.order_id FROM orders o JOIN shipments s USING (order_id) "
        "WHERE (o.status IN ('delivered', 'returned') AND s.delivered_at IS NULL) "
        "OR (o.status = 'shipped' AND s.delivered_at IS NOT NULL)", ()),
    "promised_date_not_before_order": (
        "SELECT order_id FROM orders WHERE promised_date < substr(placed_at, 1, 10)", ()),
    "late_flag_matches_promised_date": (
        "SELECT o.order_id FROM orders o JOIN shipments s USING (order_id) WHERE o.status = 'shipped' AND "
        "((o.promised_date < ? AND s.last_status != 'In transit - delayed') OR "
        "(o.promised_date >= ? AND s.last_status != 'In transit'))", (_TODAY, _TODAY)),
    "no_timestamps_after_reference_time": (
        "SELECT order_id FROM orders WHERE placed_at > ? "
        "UNION SELECT payment_id FROM payments WHERE created_at > ? "
        "UNION SELECT shipment_id FROM shipments WHERE dispatched_at > ? OR delivered_at > ? "
        "UNION SELECT return_id FROM returns WHERE label_issued_at > ? OR received_at > ? "
        "UNION SELECT refund_id FROM refunds WHERE requested_at > ? "
        "UNION SELECT ticket_id FROM tickets WHERE received_at > ?", (_NOW,) * 8),
    "return_dates_and_status_consistent": (
        "SELECT r.return_id FROM returns r JOIN shipments s USING (order_id) "
        "WHERE r.label_issued_at <= s.delivered_at "
        "OR (r.received_at IS NOT NULL AND r.received_at <= r.label_issued_at) "
        "OR (r.status = 'received' AND r.received_at IS NULL) "
        "OR (r.status = 'label_issued' AND r.received_at IS NOT NULL)", ()),
    "returned_orders_have_received_return": (
        "SELECT o.order_id FROM orders o LEFT JOIN returns r USING (order_id) "
        "WHERE o.status = 'returned' AND (r.return_id IS NULL OR r.status != 'received')", ()),
    "refund_matches_payment": (
        "SELECT rf.refund_id FROM refunds rf JOIN payments p USING (payment_id) "
        "WHERE rf.amount_cents != p.amount_cents "
        "OR (rf.status = 'processed' AND p.status != 'refunded') "
        "OR (rf.status = 'pending' AND p.status != 'captured')", ()),
    "no_final_sale_items_in_returns": (
        "SELECT DISTINCT r.order_id FROM returns r JOIN order_items i USING (order_id) "
        "JOIN products p USING (product_id) WHERE p.final_sale = 1", ()),
    "shipping_address_belongs_to_customer": (
        "SELECT o.order_id FROM orders o JOIN addresses a ON a.address_id = o.shipping_address_id "
        "WHERE a.customer_id != o.customer_id", ()),
    "customer_existed_when_ordering": (
        "SELECT o.order_id FROM orders o JOIN customers c USING (customer_id) "
        "WHERE c.created_at > substr(o.placed_at, 1, 10)", ()),
    "tickets_come_from_known_customers": (
        "SELECT ticket_id FROM tickets WHERE customer_email NOT IN (SELECT email FROM customers)", ()),
    "duplicate_charge_follows_original": (
        "SELECT d.payment_id FROM payments d LEFT JOIN payments p ON p.order_id = d.order_id "
        "AND p.status IN ('captured', 'refunded') AND p.amount_cents = d.amount_cents "
        "AND d.created_at > p.created_at "
        "AND (julianday(d.created_at) - julianday(p.created_at)) * 1440 <= 10 "
        "WHERE d.status = 'duplicate_flagged' AND p.payment_id IS NULL", ()),
}


def run_checks(conn: sqlite3.Connection) -> list[str]:
    """Return a list of violation messages. An empty list means every check passed."""
    violations = []
    for name, (sql, params) in CHECKS.items():
        rows = conn.execute(sql, params).fetchall()
        if rows:
            examples = ", ".join(str(r[0]) for r in rows[:3])
            violations.append(f"{name}: {len(rows)} violation(s), e.g. {examples}")
    return violations