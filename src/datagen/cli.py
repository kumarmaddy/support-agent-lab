"""Command-line entry point.

Example (from the repository root):
    python -m src.datagen.cli --split dev --force
"""
import argparse
import sys
from pathlib import Path

from src.datagen import config
from src.datagen.store import checks
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.scenarios.base import MissingHeldoutPhrasing
from src.datagen.tickets import create_ticket_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the synthetic support dataset.")
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--seed", type=int, default=None,
                        help="defaults to the configured seed for the chosen split")
    parser.add_argument("--out", type=Path, default=None, help="default: data/generated/<split>")
    parser.add_argument("--labels-dir", type=Path, default=Path("data/labels"),
                        help="labels are written outside the database folder on purpose")
    parser.add_argument("--force", action="store_true", help="overwrite an existing database")
    args = parser.parse_args(argv)

    seed = args.seed if args.seed is not None else (
        config.DEFAULT_SEED_DEV if args.split == "dev" else config.DEFAULT_SEED_HELDOUT)
    out = args.out if args.out is not None else Path("data/generated") / args.split
    db_path = out / "support.db"

    conn = create_database(db_path, force=args.force)
    try:
        counts = load_base_data(conn, seed)
        counts.update(load_orders(conn, seed))
        try:
            ticket_summary = create_ticket_dataset(conn, seed, args.split, args.labels_dir)
        except MissingHeldoutPhrasing as exc:
            print(f"Cannot build the held-out split yet: {exc}")
            return 2
        status_mix = conn.execute(
            "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY 2 DESC").fetchall()
        duplicates = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status = 'duplicate_flagged'").fetchone()[0]
        violations = checks.run_checks(conn)
    finally:
        conn.close()

    print(f"Generator version {config.GENERATOR_VERSION}, split {args.split}, seed {seed}")
    print(f"Database written to {db_path}")
    for table, n in counts.items():
        print(f"  {table}: {n}")
    print("  order status mix: " + ", ".join(f"{s}={n}" for s, n in status_mix))
    print(f"  duplicate-charge payments: {duplicates}")
    print(f"Tickets: {ticket_summary['tickets']} -> labels at {ticket_summary['labels_path']}")
    print("  by scenario: " + ", ".join(f"{k}={v}" for k, v in ticket_summary["by_scenario"].items()))
    if violations:
        print(f"INTEGRITY CHECKS FAILED ({len(violations)}):")
        for v in violations:
            print("  - " + v)
        return 1
    print(f"Integrity checks: PASS ({len(checks.CHECKS)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())