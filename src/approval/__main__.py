"""Run the approval page on this computer only.

    python -m src.approval --run data/runs/<run folder> --approver "Your Name" [--role standard|senior] [--port 8765]

Open http://127.0.0.1:8765/ in a browser. Needs a sandbox (python -m src.actions init). Stop with Ctrl+C.
"""
import argparse
from pathlib import Path

from src.actions.config import DEFAULT_CONFIG_PATH, load_config
from src.agent.policy import DEFAULT_POLICY_PATH, load_policy
from src.approval.app import ApprovalApp, serve
from src.approval.queue import QueueError
from src.audit.log import AuditLog


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run", type=Path, required=True, help="a run folder holding resolutions.jsonl")
    p.add_argument("--approver", required=True, help="your name, recorded on every decision")
    p.add_argument("--role", choices=["standard", "senior"], default="standard", help="a standard approver cannot decide senior-queue proposals")
    p.add_argument("--sandbox", type=Path, help="sandbox database (default: from config/actions.toml)")
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    p.add_argument("--audit", type=Path, default=Path("data/audit/audit.jsonl"))
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args(argv)
    config = load_config(args.config)
    try:
        app = ApprovalApp(args.run, args.sandbox or config.sandbox, args.approver, args.role, config, load_policy(args.policy), AuditLog(args.audit))
    except (QueueError, ValueError) as exc:
        raise SystemExit(f"Error: {exc}")
    server = serve(app, port=args.port)
    print(f"Approval page for run {app.run_id}: http://127.0.0.1:{app.port}/  (approver {app.approver}, {app.role}; Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())