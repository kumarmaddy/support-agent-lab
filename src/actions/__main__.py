"""Set up and inspect the sandbox.

    python -m src.actions init [--source data/generated/dev/support.db] [--dest data/sandbox/support.db] [--force]
    python -m src.actions ledger [--sandbox data/sandbox/support.db]
"""
import argparse
import sys
from pathlib import Path

from src.actions.config import DEFAULT_SANDBOX
from src.actions.sandbox import SandboxError, create_sandbox, open_sandbox

DEFAULT_SOURCE = Path("data/generated/dev/support.db")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    init = sub.add_parser("init", help="copy the development database into a writable sandbox")
    init.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    init.add_argument("--dest", type=Path, default=DEFAULT_SANDBOX)
    init.add_argument("--force", action="store_true")
    led = sub.add_parser("ledger", help="show approvals and executed actions")
    led.add_argument("--sandbox", type=Path, default=DEFAULT_SANDBOX)
    args = p.parse_args(argv)
    try:
        if args.cmd == "init":
            print(f"sandbox created: {create_sandbox(args.source, args.dest, args.force)} (source left untouched)")
            return 0
        conn = open_sandbox(args.sandbox)
    except SandboxError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for r in conn.execute("SELECT * FROM approvals ORDER BY approval_id"):
        print(f"approval {r['approval_id']} {r['status']:<8} {r['action']:<14} {r['ticket_id']} {r['order_id']} by {r['approver']}")
    for r in conn.execute("SELECT * FROM action_ledger ORDER BY executed_at"):
        print(f"executed {r['action']:<14} {r['ticket_id']} {r['order_id']} approval {r['approval_id']} key {r['idempotency_key'][:12]}… {r['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())