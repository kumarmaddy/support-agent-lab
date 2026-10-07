"""Central configuration for the synthetic data generator."""
from datetime import datetime

GENERATOR_VERSION = "0.5.0"

# Fixed reference date so generated data does not depend on the day it is run.
AS_OF_DATETIME = datetime(2026, 10, 6, 12, 0, 0)
AS_OF_DATE = AS_OF_DATETIME.date()

DEFAULT_SEED_DEV = 20261006
DEFAULT_SEED_HELDOUT = 20261007

N_CUSTOMERS = 200
N_PRODUCTS = 60
N_LOCKED_CUSTOMERS = 6      # about 3%; needed for locked-out account scenarios
N_FINAL_SALE_PRODUCTS = 6   # 10% of the catalogue

# ---- Orders (stage 0.4b) ----
N_ORDERS = 600
PROMISE_DAYS = 10            # promised_date = placed date + 10 calendar days
RETURN_WINDOW_DAYS = 30      # returns accepted up to 30 days after delivery (inclusive)
P_DUPLICATE_CHARGE = 0.02    # share of eligible background orders with a duplicate charge

# Background order mix (weights sum to 1.0). See docs/design/data-design.md section 4.
ORDER_STATE_WEIGHTS = {
    "processing": 0.06,
    "in_transit": 0.08,
    "in_transit_late": 0.04,
    "delivered": 0.62,
    "cancelled": 0.04,
    "return_in_progress": 0.04,
    "returned_refund_pending": 0.03,
    "returned_refunded": 0.09,
}