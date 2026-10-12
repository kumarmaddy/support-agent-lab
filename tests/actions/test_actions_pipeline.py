"""Stage 3.5: from a real proposal on a development ticket to an approved, executed and replayed action, and the frozen data untouched."""
from pathlib import Path

import pytest

from src.actions.config import ActionsConfig
from src.actions.sandbox import create_sandbox, file_sha256, open_sandbox
from src.actions.service import ActionsService, call_from_proposal
from src.agent.pipeline import run_ticket
from src.agent.policy import load_policy
from src.audit.log import AuditLog, query, verify
from tests.agent.support import ScriptedModel, oracle_read
from tests.agent.test_handover import READ, REPLY, TX, TOPIC, world  # noqa: F401  (the fixture)

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.toml")
ALL_ON = ActionsConfig(frozenset({"refund", "replace", "change_address", "cancel"}))


def propose(world, ticket_id):
    box, by_id, internal = world
    topic = {"topic": TOPIC.get(by_id[ticket_id]["scenario_id"], "duplicate_charge")}
    request = {"request": "return", "item": "", "requested_size": ""}
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ticket_id), extract=lambda s, u, seed: topic if '"topic"' in s else request)
    res = run_ticket(box, model, READ, REPLY, internal, ticket_id, 0, "template", None, TX, POLICY)
    return {"ticket_id": res.ticket_id, "action": res.action, "facts": res.facts}


@pytest.mark.parametrize("ticket_id", ["T-000011", "T-000029"])               # a cancellation and a duplicate-charge refund
def test_a_proposal_becomes_an_approved_executed_action_exactly_once(world, dev_dataset, tmp_path, ticket_id):
    source = dev_dataset[0]
    frozen = file_sha256(source)
    proposal = propose(world, ticket_id)
    call = call_from_proposal(proposal)
    assert call is not None
    conn = open_sandbox(create_sandbox(source, tmp_path / "s.db"))
    audit = AuditLog(tmp_path / "a.jsonl")
    service = ActionsService(conn, ALL_ON, audit, POLICY)

    refused = service.execute(**call, approval_id="AP-000001")                     # before any approval exists
    assert refused.code == "no_approval"
    grant = {k: v for k, v in call.items() if k in ("payment_id", "amount_cents", "address")}
    ap = service.approvals.grant(ticket_id, call["action"], call["order_id"], "A. Reviewer", **grant).approval_id
    first = service.execute(**call, approval_id=ap)
    assert first.status == "executed", first
    assert service.execute(**call, approval_id=ap).status == "replayed"
    assert conn.execute("SELECT COUNT(*) FROM action_ledger").fetchone()[0] == 1
    kinds = [(e["event"], e["data"].get("status")) for e in query(audit.path, ticket_id)]
    assert kinds == [("execution", "refused"), ("approval", None), ("execution", "executed"), ("execution", "replayed")]
    assert verify(audit.path).ok
    conn.close()
    assert file_sha256(source) == frozen