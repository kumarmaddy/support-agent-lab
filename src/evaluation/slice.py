"""Which labelled tickets belong to the Phase 1 slice (order status): scenarios S01-S04 and S22, and S24 when it is about an order."""

IN_SLICE = ("S01", "S02", "S03", "S04", "S22")


def in_slice(label: dict) -> bool:
    return label["scenario_id"] in IN_SLICE or (label["scenario_id"] == "S24" and label["category"] == "order_status")


# Phase 2 stages 2.5a and 2.5b: with --transactions these categories and scenarios join the scope. S11 appears in two categories; only its
# return_exchange tickets (replacement requests) belong here, its refund tickets wait for stage 2.5c.
TRANSACTION_CATEGORIES = ("cancellation", "address_change", "return_exchange")
TRANSACTION_SCENARIOS = ("S05", "S06", "S07", "S08", "S11", "S13", "S14", "S15", "S16", "S24")


# Stage 2.5c: the refund-category tickets of these scenarios join when the run had the refund step. S21 (legal threats) stays out: those are
# escalated by rule and belong to the policy engine of Phase 3.
REFUND_SCENARIOS = ("S09", "S10", "S11", "S23", "S24", "S26")


def in_scope(label: dict, transactions: bool = False, refunds: bool = False) -> bool:
    """The Phase 1 slice, plus the transactional scenarios when the run used --transactions (and, from stage 2.5c, the refund tickets)."""
    return (in_slice(label)
            or (transactions and label["category"] in TRANSACTION_CATEGORIES and label["scenario_id"] in TRANSACTION_SCENARIOS)
            or (refunds and label["category"] == "refund" and label["scenario_id"] in REFUND_SCENARIOS))