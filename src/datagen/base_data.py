"""Generates customers, addresses and the product catalogue (stage 0.4a).

Pure functions: a seed in, plain tuples out. No database access here, which keeps the logic easy to test.
"""
import random
from datetime import timedelta

from . import config, reference


def make_rng(seed: int, stream: str) -> random.Random:
    """Independent, reproducible random stream per entity type.

    Using a separate stream per entity means adding a new entity type later does not change the
    customers or products already generated from the same seed.
    """
    return random.Random(f"{seed}:{stream}")


def generate_products(seed: int) -> list[tuple]:
    rng = make_rng(seed, "products")
    rows: list[tuple] = []
    used_names: set[str] = set()
    n = 0
    for category, types, (lo, hi), count, _sizing in reference.CATALOGUE_SPEC:
        for i in range(count):
            n += 1
            ptype = types[i % len(types)]
            name = f"{rng.choice(reference.PRODUCT_ADJECTIVES)} {ptype}"
            if name in used_names:
                name = f"{name} {rng.randint(2, 9)}0"
            while name in used_names:  # extremely unlikely; guarantees uniqueness
                name = f"{name}X"
            used_names.add(name)
            price_dollars = rng.randrange(lo, hi + 1, 5)
            price_cents = price_dollars * 100 - 1  # e.g. 7999
            rows.append([f"P-{n:04d}", name, category, price_cents, 0])
    final_sale_idx = rng.sample(range(len(rows)), config.N_FINAL_SALE_PRODUCTS)
    for idx in final_sale_idx:
        rows[idx][4] = 1
    return [tuple(r) for r in rows]


def generate_customers_and_addresses(seed: int) -> tuple[list[tuple], list[tuple]]:
    rng = make_rng(seed, "customers")
    customers: list[tuple] = []
    addresses: list[tuple] = []
    used_emails: set[str] = set()
    locked_idx = set(rng.sample(range(config.N_CUSTOMERS), config.N_LOCKED_CUSTOMERS))
    tiers = ["standard", "silver", "gold"]
    tier_weights = [0.70, 0.20, 0.10]
    addr_n = 0

    for i in range(config.N_CUSTOMERS):
        first = rng.choice(reference.FIRST_NAMES)
        last = rng.choice(reference.LAST_NAMES)
        base = f"{first}.{last}".lower()
        email = f"{base}@example.com"
        suffix = 1
        while email in used_emails:
            suffix += 1
            email = f"{base}{suffix}@example.com"
        used_emails.add(email)

        days_ago = rng.randint(30, 3 * 365)
        created_at = (config.AS_OF_DATE - timedelta(days=days_ago)).isoformat()
        tier = rng.choices(tiers, weights=tier_weights, k=1)[0]
        status = "locked" if i in locked_idx else "active"
        customer_id = f"C-{i + 1:06d}"
        customers.append((customer_id, f"{first} {last}", email, tier, created_at, status))

        for _ in range(2 if rng.random() < 0.20 else 1):
            addr_n += 1
            line1 = (f"{rng.randint(10, 9899)} {rng.choice(reference.STREET_NAMES)} "
                     f"{rng.choice(reference.STREET_TYPES)}")
            addresses.append((
                f"A-{addr_n:06d}", customer_id, line1,
                rng.choice(reference.CITIES), f"{rng.randint(0, 99999):05d}", "US",
            ))
    return customers, addresses
