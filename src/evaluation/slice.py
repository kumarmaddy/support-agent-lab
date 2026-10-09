"""Which labelled tickets belong to the Phase 1 slice (order status): scenarios S01-S04 and S22, and S24 when it is about an order."""

IN_SLICE = ("S01", "S02", "S03", "S04", "S22")


def in_slice(label: dict) -> bool:
    return label["scenario_id"] in IN_SLICE or (label["scenario_id"] == "S24" and label["category"] == "order_status")


# Phase 2 stage 2.5a: cancellation (S13, S14) and address change (S15, S16) join the scope when --transactions is on.
TRANSACTION_SCENARIOS = ("S13", "S14", "S15", "S16")


def in_scope(label: dict, transactions: bool = False) -> bool:
    """The Phase 1 slice, plus the transactional scenarios when the run used --transactions."""
    return in_slice(label) or (transactions and (label["scenario_id"] in TRANSACTION_SCENARIOS or
                                                  (label["scenario_id"] == "S24" and label["category"] in ("cancellation", "address_change"))))