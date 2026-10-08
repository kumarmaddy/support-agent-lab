"""Command-line entry point for the manual baseline.

    python -m src.baseline.cli prepare            # choose the sample (once)
    python -m src.baseline.cli run                # time yourself on the tickets; resumable
    python -m src.baseline.cli report             # score against labels and write the baseline report
    python -m src.baseline.cli review             # classify each disagreement; writes the review document
"""
import argparse
import json
import sys
from pathlib import Path

from src.baseline import lookups
from src.baseline.report import DEFAULT_HOURLY_RATES, render_report
from src.baseline.review import DRAFT_DEFAULT, LOG_DEFAULT, ReviewSession, load_drafts, render_review
from src.baseline.sampling import select_sample
from src.baseline.scoring import summarise
from src.baseline.session import Session
from src.datagen import config
from src.datagen.domain import labels as label_io
from src.kb.articles import load_articles

BASE = Path("data/baseline")


def read_results(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def cmd_prepare(args) -> int:
    if args.sample.exists() and not args.force:
        print(f"{args.sample} exists: the sample is fixed once chosen. Use --force only before any results exist.")
        return 1
    if args.results.exists() and args.results.stat().st_size and args.force:
        print(f"{args.results} already has results; changing the sample now would invalidate them.")
        return 1
    sample = select_sample(label_io.read_labels(args.labels), args.size, args.seed)
    args.sample.parent.mkdir(parents=True, exist_ok=True)
    args.sample.write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Sample of {sample['size']} tickets (+{len(sample['practice_ids'])} practice) written to {args.sample}")
    return 0


def cmd_run(args) -> int:
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    conn = lookups.open_readonly(args.db)
    try:
        Session(conn, load_articles(args.kb), sample, args.results).run()
    finally:
        conn.close()
    return 0


def cmd_report(args) -> int:
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    results = read_results(args.results)
    handled = {r["ticket_id"] for r in results if not r["practice"]}
    missing = [t for t in sample["ticket_ids"] if t not in handled]
    if missing and not args.allow_partial:
        print(f"{len(missing)} of {len(sample['ticket_ids'])} tickets not handled yet. Finish the run, or pass --allow-partial.")
        return 1
    labels_by_id = {lab["ticket_id"]: lab for lab in label_io.read_labels(args.labels)}
    summary = summarise(results, labels_by_id)
    rates = tuple(args.hourly_rate) if args.hourly_rate else DEFAULT_HOURLY_RATES
    args.report.parent.mkdir(parents=True, exist_ok=True)
    version = None
    if args.manifest.exists():
        version = json.loads(args.manifest.read_text(encoding="utf-8")).get("dataset_version")
    args.report.write_text(render_report(summary, sample, results, rates, version), encoding="utf-8", newline="\n")
    print(f"Wrote {args.report}: {summary['tickets']} tickets, median {summary['time']['median']:.0f} s")
    return 0


def cmd_review(args) -> int:
    from datetime import date
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    results = read_results(args.results)
    labels_by_id = {lab["ticket_id"]: lab for lab in label_io.read_labels(args.labels)}
    summary = summarise(results, labels_by_id)
    handled = {r["ticket_id"] for r in results if not r["practice"]}
    if len(handled) < len(sample["ticket_ids"]):
        print("The run is not finished. Review the disagreements after all tickets are handled.")
        return 1
    conn = lookups.open_readonly(args.db)
    try:
        session = ReviewSession(conn, load_articles(args.kb), results, labels_by_id, summary["disagreements"], args.review_log,
                                input_fn=lambda prompt="": input(prompt))
        redo = set(args.redo or ())
        session.confirm_drafts(load_drafts(args.drafts), redo)
        session.run(redo=redo)
    finally:
        conn.close()
    records = session.records()
    left = [d for d in summary["disagreements"] if d["ticket_id"] not in records]
    if left and not args.allow_partial:
        print(f"{len(left)} disagreement(s) not reviewed yet; run the command again, or pass --allow-partial to write a partial review.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_review(records, summary["disagreements"], summary["tickets"], date.today().isoformat()),
                           encoding="utf-8", newline="\n")
    print(f"Wrote {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual-handling baseline.")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sample", type=Path, default=BASE / "sample.json")
    common.add_argument("--results", type=Path, default=BASE / "results.jsonl")
    labels_default = Path("data/labels/dev/labels.jsonl")

    p = sub.add_parser("prepare", parents=[common])
    p.add_argument("--labels", type=Path, default=labels_default)
    p.add_argument("--size", type=int, default=40)
    p.add_argument("--seed", type=int, default=config.DEFAULT_SEED_DEV)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("run", parents=[common])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))

    p = sub.add_parser("report", parents=[common])
    p.add_argument("--labels", type=Path, default=labels_default)
    p.add_argument("--report", type=Path, default=Path("docs/project/baseline-report.md"))
    p.add_argument("--hourly-rate", type=float, action="append", help="repeat for several rates")
    p.add_argument("--allow-partial", action="store_true")
    p.add_argument("--manifest", type=Path, default=Path("data/manifest.json"), help="source of the dataset version")

    p = sub.add_parser("review", parents=[common])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--labels", type=Path, default=labels_default)
    p.add_argument("--review-log", type=Path, default=LOG_DEFAULT)
    p.add_argument("--drafts", type=Path, default=DRAFT_DEFAULT, help="proposed decisions to confirm one by one")
    p.add_argument("--output", type=Path, default=Path("docs/project/baseline-disagreement-review.md"))
    p.add_argument("--redo", action="append", metavar="TICKET", help="re-review a ticket (repeatable)")
    p.add_argument("--allow-partial", action="store_true")

    args = parser.parse_args(argv)
    return {"prepare": cmd_prepare, "run": cmd_run, "report": cmd_report, "review": cmd_review}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())