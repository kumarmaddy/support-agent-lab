"""Stage 3.4: the audit log written from real pipeline runs over the development tickets, and the leak test (design 5.3)."""
import json
import re
from pathlib import Path

import pytest

from src.agent import run as runner
from src.agent.pipeline import run_ticket
from src.agent.policy import load_policy
from src.agent.tracing import TraceWriter
from src.audit.log import AuditLog, _strings, query, read_events, verify
from src.audit.redact import STREET, leftovers
from tests.agent.support import ScriptedModel, oracle_read
from tests.agent.test_handover import READ, REPLY, TX, TOPIC, world  # noqa: F401  (the fixture)

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.toml")


def extractor(topic, request):
    """Scripted extraction steps: the address step copies the first street address found in the ticket text, as a careful reader would."""
    def handler(system, user, seed):
        if '"topic"' in system:
            return topic
        if "delivery address" in system:
            found = STREET.search(user)
            return {"address": found.group(0) if found else ""}
        return request
    return handler


def run_all(world, tmp_path, ids=None):
    box, by_id, internal = world
    audit = AuditLog(tmp_path / "audit.jsonl")
    request = {"request": "return", "item": "", "requested_size": ""}
    resolutions = []
    with TraceWriter(tmp_path / "runs", "run-test", {}) as writer:
        for tid in ids or sorted(by_id):
            topic = {"topic": TOPIC.get(by_id[tid]["scenario_id"], "duplicate_charge")}
            model = ScriptedModel(read=lambda s, u, seed, tid=tid: oracle_read(by_id, box, tid),
                                  extract=extractor(topic, request))
            res = run_ticket(box, model, READ, REPLY, internal, tid, 0, "template", None, TX, POLICY)
            writer.write(res)
            audit.record_resolution(res, "run-test", {"model": "scripted"})
            resolutions.append(res)
    return audit, resolutions


@pytest.fixture(scope="module")
def full(world, tmp_path_factory):
    return run_all(world, tmp_path_factory.mktemp("audit"))


def test_every_ticket_has_a_decision_and_the_chain_verifies(full):
    audit, resolutions = full
    assert verify(audit.path).ok
    for res in resolutions:
        events = query(audit.path, res.ticket_id)
        kinds = [e["event"] for e in events]
        assert kinds.count("decision") == 1
        assert kinds.count("policy_decision") == (1 if res.policy else 0) and kinds.count("hand_over") == (1 if res.handover else 0)
        decision = next(e for e in events if e["event"] == "decision")["data"]
        assert decision["action"] == res.action and decision["reason"] == res.reason


def test_a_proposal_records_the_policy_rule_before_the_decision(full):
    audit, resolutions = full
    proposal = next(r for r in resolutions if r.policy)
    events = query(audit.path, proposal.ticket_id)
    assert [e["event"] for e in events][:2] == ["policy_decision", "decision"]
    assert events[0]["data"]["rule_id"] == proposal.policy["rule_id"] and events[0]["data"]["policy_sha256"] == POLICY.sha256


def test_identifiers_survive_redaction_so_a_case_can_be_traced(full):
    audit, resolutions = full
    handed = next(r for r in resolutions if r.handover and r.handover["order_ids"])
    note = next(e for e in query(audit.path, handed.ticket_id) if e["event"] == "hand_over")["data"]
    assert note["ticket_id"] == handed.ticket_id and note["order_ids"] == handed.handover["order_ids"]


def test_no_personal_identifier_reaches_the_audit_file(world, full):
    """The leak test: take every email, full name, street line and requested address from the development data and the raw
    resolutions, and require that none of them appears in the audit file; then apply the broad pattern check to every line."""
    box, _, _ = world
    audit, resolutions = full
    text = audit.path.read_text(encoding="utf-8")
    secrets = {r[0] for r in box.conn.execute("SELECT email FROM customers")}
    secrets |= {r[0] for r in box.conn.execute("SELECT name FROM customers")}
    secrets |= {r[0] for r in box.conn.execute("SELECT line1 FROM addresses")}
    secrets |= {str(r.facts[k]) for r in resolutions for k in ("requested_address", "new_address") if r.facts.get(k)}
    firsts = {n.split()[0] for (n,) in box.conn.execute("SELECT name FROM customers")}
    assert len(secrets) > 100                                      # the check has something to look for
    leaked = sorted(s for s in secrets if s and s in text)
    assert leaked == []
    for first in firsts:
        assert not re.search(rf"\b(?:Hello|Hi|Dear)\s+{re.escape(first)}\b", text), first
    for event in read_events(audit.path):
        assert sorted({k for v in _strings(event["data"]) for k in leftovers(v)}) == [], event["ticket_id"]
    assert '"redaction_failed"' not in text


def test_the_raw_resolutions_do_hold_requested_addresses_so_the_test_above_is_meaningful(full):
    _, resolutions = full
    assert any(r.facts.get("requested_address") for r in resolutions)


def test_the_runner_writes_the_audit_and_the_head_file(world, tmp_path, monkeypatch):
    box, by_id, internal = world
    audit = AuditLog(tmp_path / "a.jsonl")
    ids = sorted(by_id)[:3]
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ids[0]), extract=lambda s, u, seed: {"topic": "status"} if '"topic"' in s else {"request": "return", "item": "", "requested_size": ""})
    with TraceWriter(tmp_path / "runs", "run-x", {}) as writer:
        runner.run_tickets(box, model, READ, REPLY, internal, ids[:1], writer, 0, "template", None, TX, policy=POLICY, audit=audit, audit_context={"model": "m"})
    assert verify(audit.path).ok and query(audit.path, ids[0])


def test_without_an_audit_object_nothing_is_written(world, tmp_path):
    box, by_id, internal = world
    tid = sorted(by_id)[0]
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, tid), extract=lambda s, u, seed: {"topic": "status"} if '"topic"' in s else {"request": "return", "item": "", "requested_size": ""})
    with TraceWriter(tmp_path / "runs", "run-y", {}) as writer:
        runner.run_tickets(box, model, READ, REPLY, internal, [tid], writer, 0, "template", None, TX, policy=POLICY)
    assert not list(tmp_path.glob("*.jsonl"))