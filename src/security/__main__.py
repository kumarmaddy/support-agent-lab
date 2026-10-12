"""Run the injection and misuse suite.

    python -m src.security [--cases data/security/cases.jsonl] [--db data/generated/dev/support.db] [--out data/security/runs] [--only P-001,A-003]

Prints one line per failed case and the summary; writes results.jsonl and summary.json to a new folder under --out. Exit code 1 when any attack
is not neutralised, any control fails, or any unapproved write is seen.
"""
import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.security.cases import DEFAULT_PATH, MIN_CASES, cases_sha256, load_cases
from src.security.runner import REPO, run_case
from src.security.score import judge, summarise


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--cases", type=Path, default=DEFAULT_PATH)
    p.add_argument("--db", type=Path, default=REPO / "data" / "generated" / "dev" / "support.db")
    p.add_argument("--out", type=Path, default=REPO / "data" / "security" / "runs")
    p.add_argument("--only", help="comma-separated case ids (a partial run is not a result)")
    args = p.parse_args(argv)
    logging.getLogger("mcp").setLevel(logging.CRITICAL)        # the SDK logs every refused tool call; the suite makes refused calls on purpose
    cases = load_cases(args.cases)
    if len(cases) < MIN_CASES:
        print(f"the case file holds {len(cases)} cases; the design requires at least {MIN_CASES}", file=sys.stderr)
        return 2
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]
    db_sha = hashlib.sha256(args.db.read_bytes()).hexdigest()
    verdicts, rows = [], []
    for case in cases:
        v = run_case(case, args.db, judge)
        verdicts.append(v)
        rows.append(v.to_dict() | {"title": case.title})
        if not v.neutralised:
            print(f"FAIL {case.id} [{case.layer}/{case.family}] {case.title}", file=sys.stderr)
            for f in v.failures:
                print(f"       {f}", file=sys.stderr)
    summary = summarise(verdicts) | {"cases_sha256": cases_sha256(args.cases), "database_sha256": db_sha,
                                     "partial_run": bool(args.only), "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    run_dir = args.out / f"security-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8", newline="\n")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    o6 = summary["o6_rate"]
    print(f"\nrun folder: {run_dir.name}\ncases: {summary['cases']} ({summary['attacks']} attacks, {summary['controls']} controls)")
    print(f"O6 attacks neutralised: {summary['o6_neutralised']}/{summary['attacks']} = {o6:.1%} (95% Wilson {summary['o6_wilson_95'][0]:.1%} to {summary['o6_wilson_95'][1]:.1%})")
    print(f"O2 attack cases ending in a wrong action: {summary['o2_wrong_action_cases']}")
    print(f"unapproved writes: {summary['unapproved_writes']}")
    print(f"controls behaving as expected: {summary['controls_as_expected']}/{summary['controls']}")
    for layer, row in summary["by_layer"].items():
        print(f"  {layer:9s} attacks {row['neutralised']}/{row['attacks']}   controls {row['controls_ok']}/{row['controls']}")
    for family, row in summary["by_family"].items():
        print(f"  {family:22s} {row['neutralised']}/{row['attacks']}")
    clean = (summary["o6_neutralised"] == summary["attacks"] and summary["o2_wrong_action_cases"] == 0 and summary["unapproved_writes"] == 0
             and summary["controls_as_expected"] == summary["controls"])
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())