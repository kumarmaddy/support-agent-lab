"""Which labelled tickets belong to the Phase 1 slice (order status): scenarios S01-S04 and S22, and S24 when it is about an order."""

IN_SLICE = ("S01", "S02", "S03", "S04", "S22")


def in_slice(label: dict) -> bool:
    return label["scenario_id"] in IN_SLICE or (label["scenario_id"] == "S24" and label["category"] == "order_status")