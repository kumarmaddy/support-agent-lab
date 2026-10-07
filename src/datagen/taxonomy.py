"""Allowed values for ticket labels. Single source of truth: data-design.md sections 5 and 6."""

CATEGORIES = (
    "order_status", "return_exchange", "refund", "cancellation",
    "address_change", "account", "product_info", "other",
)

ACTIONS = (
    "provide_info", "request_info", "propose_refund", "propose_replacement", "propose_exchange",
    "propose_return_label", "propose_cancellation", "propose_address_change",
    "decline_policy", "escalate_human",
)

PRIORITIES = ("LOW", "MEDIUM", "HIGH")
DIFFICULTIES = ("standard", "edge", "adversarial")
ADVERSARIAL_TYPES = ("prompt_injection", "impersonation", "approval_bypass_pressure")
SPLITS = ("dev", "heldout")
TEXT_SOURCES = ("template", "paraphrase")

# Priority rubric v1.0 attributes (docs/priority-rubric.md)
PRIORITY_ATTRIBUTES = (
    "duplicate_or_unauthorized_charge",
    "account_compromise_suspected",
    "chargeback_or_legal_threat",
    "deadline_within_3_days",
    "order_late_past_promise",
    "item_damaged_or_wrong",
    "account_locked_out",
)