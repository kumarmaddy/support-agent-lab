"""Command-line entry point.

Example (from the repository root):
    python -m src.datagen.cli --seed 20261006 --out data/generated/dev
"""
import argparse
from pathlib import Path

from . import config
from .db import create_database, load_base_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic support dataset.")
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED_DEV)
    parser.add_argument("--out", type=Path, default=Path("data/generated/dev"))
    parser.add_argument("--force", action="store_true", help="overwrite an existing database")
    args = parser.parse_args()

    db_path = args.out / "support.db"
    conn = create_database(db_path, force=args.force)
    try:
        counts = load_base_data(conn, args.seed)
    finally:
        conn.close()

    print(f"Generator version {config.GENERATOR_VERSION}, seed {args.seed}")
    print(f"Database written to {db_path}")
    for table, n in counts.items():
        print(f"  {table}: {n}")


if __name__ == "__main__":
    main()
