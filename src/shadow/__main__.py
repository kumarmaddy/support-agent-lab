"""Shadow mode (stage 4.4): the lead handles held-out tickets blind (Step A), later reviews the agent's drafts (Step B).

    python -m src.shadow prepare     # draw the 40-ticket sample (once)
    python -m src.shadow handle      # Step A: handle each ticket by hand, blind and timed; resumable
    python -m src.shadow review      # Step B: at least 24 hours after Step A, review the agent's drafts, timed; resumable
    python -m src.shadow rate --rater NAME   # second reviewer: rate 20 drafts on a four-question rubric (untimed)
    python -m src.shadow report      # score and write docs/project/phase-4-shadow-report.md

Every command first runs the guard (``guard.require_heldout_intact``): the held-out data must still match the freeze record and the gated
7B run must be complete. Only ``prepare`` and ``report`` read labels; the handler never sees them.
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from src.baseline import lookups
from src.baseline.session import Session
from src.datagen.domain import labels as label_io
from src.evaluation import heldout
from src.kb.articles import load_articles
from src.shadow import report as rep
from src.shadow import review as rv
from src.shadow.guard import require_heldout_intact
from src.shadow.sample import DEFAULT_SEED, DEFAULT_SIZE, RATER_TICKETS, select_shadow_sample

BASE = Path("data/shadow")
MIN_GAP_HOURS = 24.0


def ask(prompt=""):
    """Read at call time (not bound at definition), so the keyboard can be replaced in tests."""
    return input(prompt)


def read_jsonl(path: Path) -> list:
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_sample(path: Path) -> dict:
    if not Path(path).exists():
        raise FileNotFoundError(f"{path} not found; run `python -m src.shadow prepare` first")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def agent_run_dir(root: Path) -> Path:
    entries = [e for e in heldout.load_registry(root)["entries"] if e["tag"] == "7b" and e["status"] == "complete"]
    return Path(root) / "data" / "runs" / entries[-1]["run_id"]


def step_a_finished_at(manual: list, sample: dict):
    """The time Step A ended: the start of the last ticket plus its duration. None when Step A is not complete."""
    done = [r for r in manual if not r["practice"]]
    if {r["ticket_id"] for r in done} != set(sample["ticket_ids"]):
        return None
    ends = [datetime.fromisoformat(r["started_at"]) + timedelta(seconds=r["seconds"]) for r in done]
    return max(ends)


def gap_hours(manual: list, sample: dict, now: datetime):
    ended = step_a_finished_at(manual, sample)
    return None if ended is None else (now - ended).total_seconds() / 3600


# ------------------------------------------------------------------ commands
def cmd_prepare(args, root) -> int:
    if args.sample.exists():
        print(f"{args.sample} exists: the sample is fixed once chosen.")
        return 1
    sample = select_shadow_sample(label_io.read_labels(root / args.labels), args.size, args.seed, args.raters)
    args.sample.parent.mkdir(parents=True, exist_ok=True)
    args.sample.write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Sample of {sample['size']} held-out tickets written to {args.sample} (seed {sample['seed']}; {len(sample['rater_ids'])} for the second reviewer).")
    return 0


def cmd_handle(args, root) -> int:
    sample = load_sample(args.sample)
    if args.review.exists() and args.review.stat().st_size:
        print("Step B has started; Step A can no longer change.")
        return 1
    conn = lookups.open_readonly(root / args.db)
    try:
        Session(conn, load_articles(root / args.kb), sample, args.manual, input_fn=ask).run()
    finally:
        conn.close()
    return 0


def cmd_review(args, root, now=datetime.now) -> int:
    sample = load_sample(args.sample)
    manual = read_jsonl(args.manual)
    hours = gap_hours(manual, sample, now())
    if hours is None:
        print("Step A is not finished. Handle all tickets by hand first (python -m src.shadow handle).")
        return 1
    if hours < MIN_GAP_HOURS and not args.allow_short_gap:
        print(f"Only {hours:.1f} hours since Step A ended; the plan requires at least {MIN_GAP_HOURS:.0f} so that memory of the tickets has faded. "
              "Wait, or pass --allow-short-gap (the gap is recorded in the report).")
        return 1
    resolutions = rv.load_resolutions(agent_run_dir(root))
    conn = lookups.open_readonly(root / args.db)
    try:
        rv.DraftReview(conn, load_articles(root / args.kb), sample, args.review, resolutions, gap_hours=round(hours, 1), now=now, input_fn=ask).run()
    finally:
        conn.close()
    return 0


def cmd_rate(args, root) -> int:
    sample = load_sample(args.sample)
    resolutions = rv.load_resolutions(agent_run_dir(root))
    conn = lookups.open_readonly(root / args.db)
    try:
        rv.RaterSession(conn, load_articles(root / args.kb), sample, args.ratings, resolutions, args.rater, input_fn=ask).run()
    finally:
        conn.close()
    return 0


def cmd_report(args, root) -> int:
    sample = load_sample(args.sample)
    manual, review, ratings = read_jsonl(args.manual), read_jsonl(args.review), read_jsonl(args.ratings)
    labels_by_id = {lab["ticket_id"]: lab for lab in label_io.read_labels(root / args.labels)}
    run_dir = agent_run_dir(root)
    score = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
    summary = rep.summarise_shadow(sample, manual, review, ratings, labels_by_id, score)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(rep.render(summary, sample, run_dir.name, date.today().isoformat()), encoding="utf-8", newline="\n")
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {args.report}: {summary['n']} tickets, review median {summary['review_seconds']['median']:.0f} s, "
          f"manual median {summary['manual_seconds']['median']:.0f} s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.shadow", description="Shadow mode on the held-out tickets.")
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--sample", type=Path, default=BASE / "sample.json")
    common.add_argument("--manual", type=Path, default=BASE / "manual.jsonl")
    common.add_argument("--review", type=Path, default=BASE / "review.jsonl")
    common.add_argument("--ratings", type=Path, default=BASE / "ratings.jsonl")
    common.add_argument("--db", type=Path, default=heldout.HELDOUT_DB)
    common.add_argument("--labels", type=Path, default=heldout.HELDOUT_LABELS)
    common.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p = sub.add_parser("prepare", parents=[common])
    p.add_argument("--size", type=int, default=DEFAULT_SIZE)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--raters", type=int, default=RATER_TICKETS)
    sub.add_parser("handle", parents=[common])
    p = sub.add_parser("review", parents=[common])
    p.add_argument("--allow-short-gap", action="store_true")
    p = sub.add_parser("rate", parents=[common])
    p.add_argument("--rater", required=True, help="the second reviewer's name or initials")
    p = sub.add_parser("report", parents=[common])
    p.add_argument("--report", type=Path, default=Path("docs/project/phase-4-shadow-report.md"))
    p.add_argument("--summary", type=Path, default=BASE / "summary.json")
    return parser


def main(argv=None, guard=require_heldout_intact, root: Path = Path("."), now=datetime.now) -> int:
    args = build_parser().parse_args(argv)
    try:
        guard(root)
    except heldout.GateError as err:
        print(err)
        return 2
    if args.command == "review":
        return cmd_review(args, root, now)
    return {"prepare": cmd_prepare, "handle": cmd_handle, "rate": cmd_rate, "report": cmd_report}[args.command](args, root)


if __name__ == "__main__":
    sys.exit(main())