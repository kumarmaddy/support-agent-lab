"""Command-line entry point.

Example (from the repository root):
    python -m src.datagen.cli --seed 20261006 --out data/generated/dev --force
"""
import argparse
import sys
from pathlib import Path

from . import checks, config
from .db import create_database, load_base_data, load_orders


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic support dataset.")
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED_DEV)
    parser.add_argument("--out", type=Path, default=Path("data/generated/dev"))
    parser.add_argument("--force", action="store_true", help="overwrite an existing database")
    args = parser.parse_args()

    db_path = args.out / "support.db"
    conn = create_database(db_path, force=args.force)
    try:
        counts = load_base_data(conn, args.seed)
        counts.update(load_orders(conn, args.seed))
        status_mix = conn.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY 2 DESC").fetchall()
        duplicates = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status = 'duplicate_flagged'").fetchone()[0]
        violations = checks.run_checks(conn)
    finally:
        conn.close()

    print(f"Generator version {config.GENERATOR_VERSION}, seed {args.seed}")
    print(f"Database written to {db_path}")
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print("  order status mix: " + ", ".join(f"{s}={n}" for s, n in status_mix))
    print(f"  duplicate-charge payments: {duplicates}")
    if violations:
        print(f"INTEGRITY CHECKS FAILED ({len(violations)}):")
        for v in violations:
            print("  - " + v)
        return 1
    print(f"Integrity checks: PASS ({len(checks.CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
