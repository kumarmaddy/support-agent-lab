"""Ticket categories and their definitions, as shown to the model (data design, section 5).

The agent package does not import the dataset generator (the agent must not depend on the test data), so the category
list is restated here. A test compares it with the generator's taxonomy so the two cannot drift apart.
"""

CATEGORIES = (
    "order_status", "return_exchange", "refund", "cancellation",
    "address_change", "account", "product_info", "other",
)

DEFINITIONS = {
    "order_status": "Where is my order, delivery timing, tracking.",
    "return_exchange": "Sending an item back or swapping it.",
    "refund": "Money-related requests: refund status, duplicate or incorrect charge, refund for a damaged item.",
    "cancellation": "Cancelling an order.",
    "address_change": "Changing a delivery address.",
    "account": "Login, password, profile, suspected compromise.",
    "product_info": "General questions answerable from published policies (shipping, sizing, care, returns, refunds).",
    "other": "Out of scope, unanswerable, or about an order that does not belong to the sender.",
}

BOUNDARY_RULES = (
    "If the customer wants to send an item back, the category is return_exchange. If the request concerns money "
    "without sending an item back (duplicate charge, refund status), it is refund.",
    "A damaged or wrong item is refund when the customer asks for money back, and return_exchange when the "
    "customer asks for a replacement.",
    "If a ticket raises several issues, choose the most consequential one.",
    "Mentioning an order number does not by itself make a ticket order_status.",
    "A general policy question with no order or transaction involved (for example \"how long do refunds take?\") "
    "is product_info, even when the topic is refunds, returns or shipping.",
    "A request about an order that belongs to someone else is other.",
)