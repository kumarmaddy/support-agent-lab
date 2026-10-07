"""Priority rubric v1.0 as code (docs/priority-rubric.md).

Priority is computed from ticket attributes. The highest matching level wins.
"""
from .taxonomy import PRIORITY_ATTRIBUTES

HIGH_ATTRIBUTES = (
    "duplicate_or_unauthorized_charge",
    "account_compromise_suspected",
    "chargeback_or_legal_threat",
    "deadline_within_3_days",
)
MEDIUM_ATTRIBUTES = (
    "order_late_past_promise",
    "item_damaged_or_wrong",
    "account_locked_out",
)


def make_attributes(**true_flags: bool) -> dict[str, bool]:
    """Build a complete attribute dict; any attribute not named is False."""
    unknown = set(true_flags) - set(PRIORITY_ATTRIBUTES)
    if unknown:
        raise ValueError(f"unknown priority attributes: {sorted(unknown)}")
    return {name: bool(true_flags.get(name, False)) for name in PRIORITY_ATTRIBUTES}


def compute_priority(attributes: dict[str, bool]) -> str:
    if set(attributes) != set(PRIORITY_ATTRIBUTES):
        raise ValueError("attributes must contain exactly the rubric attributes")
    if any(attributes[a] for a in HIGH_ATTRIBUTES):
        return "HIGH"
    if any(attributes[a] for a in MEDIUM_ATTRIBUTES):
        return "MEDIUM"
    return "LOW"