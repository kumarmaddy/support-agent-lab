"""Shared builders for the approval page tests: a run folder from real pipeline runs on development tickets, and an app on a fresh sandbox."""
import re
from pathlib import Path

from src.actions.config import ActionsConfig
from src.actions.sandbox import create_sandbox
from src.agent.pipeline import run_ticket
from src.agent.policy import load_policy
from src.agent.tracing import TraceWriter
from src.approval.app import ApprovalApp
from src.audit.log import AuditLog
from tests.agent.support import ScriptedModel, oracle_read
from tests.agent.test_handover import READ, REPLY, TX, TOPIC

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.toml")
ALL_ON = ActionsConfig(frozenset({"refund", "replace", "change_address", "cancel"}))
TICKETS = ["T-000001", "T-000009", "T-000011", "T-000029", "T-000046", "T-000149"]   # address, return label, cancel, refund, item refund, senior refund


def build_run(world, root: Path, ids=TICKETS) -> Path:
    box, by_id, internal = world
    request = {"request": "return", "item": "", "requested_size": ""}
    run_dir = None
    with TraceWriter(root / "runs", "run-approval", {}) as writer:
        for tid in ids:
            topic = {"topic": TOPIC.get(by_id[tid]["scenario_id"], "duplicate_charge")}
            from src.audit.log import AuditLog  # noqa: F401
            from tests.audit.test_audit_pipeline import extractor
            model = ScriptedModel(read=lambda s, u, seed, tid=tid: oracle_read(by_id, box, tid), extract=extractor(topic, request))
            writer.write(run_ticket(box, model, READ, REPLY, internal, tid, 0, "template", None, TX, POLICY))
        run_dir = writer.dir
    return run_dir


def make_app(source_db, run_dir, root: Path, role="standard", config=ALL_ON, policy=POLICY, approver="A. Reviewer", port=8765):
    sandbox = create_sandbox(source_db, root / "sandbox.db")
    app = ApprovalApp(run_dir, sandbox, approver, role, config, policy, AuditLog(root / "audit.jsonl"), edits_file=root / "edits.jsonl", port=port)
    return app


def headers(app, **extra):
    return {"Host": f"127.0.0.1:{app.port}", **extra}


def form(app, **fields) -> bytes:
    from urllib.parse import urlencode
    return urlencode({"token": app.token, **fields}).encode()


def post(app, path, **fields):
    return app.handle("POST", path, headers(app, **{"Content-Type": "application/x-www-form-urlencoded"}), form(app, **fields))


def get(app, path):
    return app.handle("GET", path, headers(app))