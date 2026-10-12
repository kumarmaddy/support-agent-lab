"""Query and check the audit log.

    python -m src.audit --ticket T-000070 [--log data/audit/audit.jsonl]
    python -m src.audit --verify [--head HASH]
"""
import argparse
import json
import sys
from pathlib import Path

from src.audit.log import query, verify

DEFAULT_LOG = Path("data/audit/audit.jsonl")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--log", type=Path, default=DEFAULT_LOG)
    p.add_argument("--ticket", help="show every event for this ticket id")
    p.add_argument("--verify", action="store_true", help="check the hash chain")
    p.add_argument("--head", help="with --verify: the head hash noted at the end of a run")
    p.add_argument("--json", action="store_true", help="print events as JSON lines")
    args = p.parse_args(argv)
    if not args.ticket and not args.verify:
        p.error("give --ticket or --verify")
    status = 0
    if args.verify:
        v = verify(args.log, args.head)
        print(f"{'OK' if v.ok else 'FAILED'}: {v.events} events, head {v.head}" + ("" if v.ok else f"\n  {v.problem}"))
        status = 0 if v.ok else 2
    if args.ticket:
        events = query(args.log, args.ticket)
        if not events:
            print(f"No events for {args.ticket} in {args.log}", file=sys.stderr)
            return 1
        for e in events:
            if args.json:
                print(json.dumps(e, sort_keys=True, ensure_ascii=False))
                continue
            d = e["data"]
            line = {"decision": f"action {d.get('action')} ({d.get('reason')}), reply by {d.get('reply_source')}",
                    "policy_decision": f"rule {d.get('rule_id')} -> {d.get('outcome')}",
                    "hand_over": f"queue {d.get('queue')}: {d.get('why')}"}.get(e["event"], json.dumps(d, sort_keys=True, ensure_ascii=False)[:200])
            print(f"#{e['seq']:>5} {e['ts']} {e['event']:<15} {e['actor']:<6} {line}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())