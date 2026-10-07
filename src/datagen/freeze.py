"""Dataset manifest and freeze (stage 0.4d-3).

Commands (from the repository root):
    python -m src.datagen.freeze write     # build both splits, run all checks, write the manifest
    python -m src.datagen.freeze verify    # rebuild both splits and compare with the committed manifest

The manifest records, for each split, SHA-256 digests of the labels file and of every database table
(the database is hashed by content, not as a file, so SQLite file layout cannot cause false alarms).
`verify` is the freeze: any change to the generator, a phrasing pool, a seed or the Python version's
random behaviour that alters the dataset makes it fail until the dataset is deliberately re-frozen.
"""
import argparse
import hashlib
import json
import platform
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

from src.datagen import config
from src.datagen.domain import labels as label_io
from src.datagen.scenarios.registry import SCENARIOS
from src.datagen.store import checks
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.tickets import create_ticket_dataset

SPLITS = {"dev": config.DEFAULT_SEED_DEV, "heldout": config.DEFAULT_SEED_HELDOUT}
DEFAULT_MANIFEST = Path("data/manifest.json")
DEFAULT_DOC = Path("docs/dataset-manifest.md")


# ------------------------------------------------------------------ hashing
def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def table_digest(conn: sqlite3.Connection, table: str) -> tuple[int, str]:
    """Row count and SHA-256 of a table's rows in insertion order."""
    digest, rows = hashlib.sha256(), 0
    for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid"):
        digest.update(json.dumps(list(row), ensure_ascii=False).encode("utf-8") + b"\n")
        rows += 1
    return rows, digest.hexdigest()


def describe_split(split: str, seed: int, conn: sqlite3.Connection, labels_path: Path) -> dict:
    tables = {}
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        rows, digest = table_digest(conn, name)
        tables[name] = {"rows": rows, "sha256": digest}
    labs = label_io.read_labels(labels_path)
    by_scenario: dict[str, int] = {}
    for lab in labs:
        by_scenario[lab["scenario_id"]] = by_scenario.get(lab["scenario_id"], 0) + 1
    return {
        "seed": seed,
        "tickets": len(labs),
        "scenario_counts": dict(sorted(by_scenario.items())),
        "labels": {"records": len(labs), "sha256": sha256_bytes(Path(labels_path).read_bytes())},
        "database_tables": tables,
    }


# ------------------------------------------------------------------ checks that must pass before a freeze
def dataset_problems(conn: sqlite3.Connection, labs: list[dict], split: str, seed: int) -> list[str]:
    """Dataset-level checks on top of the per-label and database integrity checks."""
    problems: list[str] = []
    ticket_ids = [r[0] for r in conn.execute("SELECT ticket_id FROM tickets ORDER BY ticket_id")]
    label_ids = sorted(lab["ticket_id"] for lab in labs)
    if ticket_ids != label_ids:
        problems.append("ticket ids in the database and in the labels differ")
    if ticket_ids != [f"T-{n:06d}" for n in range(1, len(ticket_ids) + 1)]:
        problems.append("ticket ids are not contiguous from T-000001")
    expected = {s.scenario_id: s.count for s in SCENARIOS}
    actual: dict[str, int] = {}
    for lab in labs:
        actual[lab["scenario_id"]] = actual.get(lab["scenario_id"], 0) + 1
    if actual != expected:
        problems.append(f"scenario counts differ from the registry: {actual} vs {expected}")
    order_ids = {r[0] for r in conn.execute("SELECT order_id FROM orders")}
    for lab in labs:
        for issue in label_io.label_problems(lab):
            problems.append(f"{lab['ticket_id']}: {issue}")
        if lab["split"] != split or lab["seed"] != seed:
            problems.append(f"{lab['ticket_id']}: split or seed does not match the dataset")
        if lab["generator_version"] != config.GENERATOR_VERSION:
            problems.append(f"{lab['ticket_id']}: generator version does not match")
        if lab["referenced_order_id"] is not None and lab["referenced_order_id"] not in order_ids:
            problems.append(f"{lab['ticket_id']}: referenced order does not exist")
    bodies = [r[0] for r in conn.execute("SELECT body FROM tickets")]
    if len(set(bodies)) != len(bodies):
        problems.append("duplicate ticket bodies within the split")
    return problems


# ------------------------------------------------------------------ build and compare
def build_and_describe(workdir: Path) -> tuple[dict, list[str]]:
    """Build both splits under workdir; return the manifest content and every problem found."""
    splits, problems, all_bodies = {}, [], {}
    for split, seed in SPLITS.items():
        db_path, labels_dir = workdir / split / "support.db", workdir / "labels"
        conn = create_database(db_path, force=True)
        try:
            load_base_data(conn, seed)
            load_orders(conn, seed)
            summary = create_ticket_dataset(conn, seed, split, labels_dir)
            labs = label_io.read_labels(summary["labels_path"])
            problems += [f"[{split}] {p}" for p in checks.run_checks(conn)]
            problems += [f"[{split}] {p}" for p in dataset_problems(conn, labs, split, seed)]
            splits[split] = describe_split(split, seed, conn, Path(summary["labels_path"]))
            all_bodies[split] = {r[0] for r in conn.execute("SELECT body FROM tickets")}
        finally:
            conn.close()
    if all_bodies["dev"] & all_bodies["heldout"]:
        problems.append("ticket text is shared between the development and held-out splits")
    content = {"dataset_version": config.DATASET_VERSION, "generator_version": config.GENERATOR_VERSION,
               "splits": splits}
    return content, problems


def environment() -> dict:
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "sqlite": sqlite3.sqlite_version, "platform": platform.system()}


def differences(expected: dict, actual: dict) -> list[str]:
    """Human-readable list of what differs between two manifest contents."""
    out = []
    for key in ("dataset_version", "generator_version"):
        if expected.get(key) != actual.get(key):
            out.append(f"{key}: manifest {expected.get(key)} vs rebuilt {actual.get(key)}")
    for split in sorted(set(expected["splits"]) | set(actual["splits"])):
        e, a = expected["splits"].get(split), actual["splits"].get(split)
        if e is None or a is None:
            out.append(f"{split}: present in only one of manifest / rebuild")
            continue
        for key in ("seed", "tickets", "scenario_counts"):
            if e[key] != a[key]:
                out.append(f"{split}.{key}: manifest {e[key]} vs rebuilt {a[key]}")
        if e["labels"] != a["labels"]:
            out.append(f"{split}.labels: digest differs")
        for table in sorted(set(e["database_tables"]) | set(a["database_tables"])):
            if e["database_tables"].get(table) != a["database_tables"].get(table):
                out.append(f"{split}.database.{table}: content differs")
    return out


def render_markdown(manifest: dict) -> str:
    env = manifest["environment"]
    lines = [
        "# Dataset Manifest", "",
        "Generated by `python -m src.datagen.freeze write`. Do not edit by hand; the machine-readable source is",
        "`data/manifest.json`, and `python -m src.datagen.freeze verify` checks the dataset against it.", "",
        "| | |", "|---|---|",
        f"| Dataset version | {manifest['dataset_version']} |",
        f"| Generator version | {manifest['generator_version']} |",
        f"| Frozen on | {manifest['frozen_on']} |",
        f"| Built with | Python {env['python']} ({env['implementation']}), SQLite {env['sqlite']}, {env['platform']} |",
        "", "The held-out split is not used for tuning before Phase 4 (charter, section 7).", "",
    ]
    for split, info in manifest["splits"].items():
        lines += [f"## Split: {split}", "", f"Seed {info['seed']}; {info['tickets']} tickets.", "",
                  "| Artifact | Rows | SHA-256 |", "|---|---|---|",
                  f"| labels.jsonl | {info['labels']['records']} | `{info['labels']['sha256']}` |"]
        for table, t in info["database_tables"].items():
            lines.append(f"| table `{table}` | {t['rows']} | `{t['sha256']}` |")
        counts = ", ".join(f"{k}={v}" for k, v in info["scenario_counts"].items())
        lines += ["", f"Tickets by scenario: {counts}", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ commands
def cmd_write(args) -> int:
    if args.manifest.exists() and not args.force:
        print(f"{args.manifest} already exists: the dataset is frozen. Re-freezing needs a version bump and a "
              "recorded decision (data-design.md section 13); pass --force only after that.")
        return 1
    with tempfile.TemporaryDirectory() as tmp:
        content, problems = build_and_describe(Path(tmp))
    if problems:
        print(f"Cannot freeze: {len(problems)} problem(s)")
        for p in problems[:20]:
            print("  - " + p)
        return 1
    manifest = {**content, "frozen_on": args.frozen_on, "environment": environment()}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(render_markdown(manifest), encoding="utf-8", newline="\n")
    print(f"Frozen dataset {manifest['dataset_version']} (generator {manifest['generator_version']}).")
    print(f"Wrote {args.manifest} and {args.doc}")
    return 0


def cmd_verify(args) -> int:
    if not args.manifest.exists():
        print(f"No manifest at {args.manifest}. Run: python -m src.datagen.freeze write")
        return 1
    expected = json.loads(args.manifest.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        content, problems = build_and_describe(Path(tmp))
    diffs = differences(expected, content)
    now, then = environment(), expected.get("environment", {})
    if now["python"].split(".")[:2] != str(then.get("python", "")).split(".")[:2]:
        print(f"WARNING: frozen with Python {then.get('python')}, running Python {now['python']}. "
              "Random sequences are not guaranteed identical across Python versions.")
    for p in problems:
        print("PROBLEM: " + p)
    if diffs:
        print(f"Dataset differs from the frozen manifest ({len(diffs)} difference(s)):")
        for d in diffs:
            print("  - " + d)
    if problems or diffs:
        return 1
    print(f"Verified: dataset {expected['dataset_version']} matches the manifest (all hashes identical).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze and verify the synthetic dataset.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        p.add_argument("--doc", type=Path, default=DEFAULT_DOC)
        if name == "write":
            p.add_argument("--force", action="store_true")
            p.add_argument("--frozen-on", default=date.today().isoformat())
    args = parser.parse_args(argv)
    return cmd_write(args) if args.command == "write" else cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())