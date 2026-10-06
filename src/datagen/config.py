"""Central configuration for the synthetic data generator."""
from datetime import date

GENERATOR_VERSION = "0.1.0"

# Fixed reference date so generated data does not depend on the day it is run.
AS_OF_DATE = date(2026, 10, 6)

DEFAULT_SEED_DEV = 20261006
DEFAULT_SEED_HELDOUT = 20261007

N_CUSTOMERS = 200
N_PRODUCTS = 60
N_LOCKED_CUSTOMERS = 6      # about 3%; needed for locked-out account scenarios
N_FINAL_SALE_PRODUCTS = 6   # 10% of the catalogue
