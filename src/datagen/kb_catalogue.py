"""Knowledge-base article IDs referenced by ground-truth labels.

The article text is written in stage 0.5 and must use exactly these IDs. Stage 0.4d adds a check that
every ID listed here has a matching file. New IDs are added as scenario families are implemented.
"""

KB_ARTICLES = {
    "KB-SHP-01": "Delivery times and tracking your order",
    "KB-SHP-02": "Delayed orders",
    "KB-SHP-03": "Delivery deadlines and expedited requests",
    "KB-ORD-01": "Order processing and dispatch",
    "KB-ORD-02": "Finding your order number",
    "KB-RET-01": "Return policy and the 30-day return window",
    "KB-RET-02": "How to start a return (free return label)",
    "KB-RET-03": "Final-sale items cannot be returned",
    "KB-RET-04": "Exchanging an item for a different size",
    "KB-REF-01": "When you will receive your refund",
    "KB-REF-02": "Duplicate or unauthorised charges",
    "KB-REF-03": "Damaged or wrong items",
    "KB-REF-04": "Payment disputes and chargebacks",
}