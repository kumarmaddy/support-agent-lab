"""Stage 3.5: sandbox, approvals, the four write tools, idempotency and the audit trail, on a copy of the development data."""
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from src.actions.approvals import ApprovalError
from src.actions.config import ActionsConfig
from src.actions.sandbox import SandboxError, create_sandbox, file_sha256, open_sandbox
from src.actions.service import ActionsService, call_from_proposal, idempotency_key
from src.agent.policy import load_policy, parse_policy
from src.audit.log import query, verify, AuditLog

ALL_ON = ActionsConfig(frozenset({"refund", "replace", "change_address", "cancel"}))
POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.toml")
NEW_ADDRESS = "451 Maple Way, Missoula 81259"


@pytest.fixture
def env(dev_dataset, tmp_path):
    source = dev_dataset[0]
    frozen_before = file_sha256(source)
    dest = create_sandbox(source, tmp_path / "sandbox" / "support.db")
    audit = AuditLog(tmp_path / "audit.jsonl")
    conn = open_sandbox(dest)
    yield type("Env", (), {"source": source, "frozen_before": frozen_before, "dest": dest, "audit": audit, "conn": conn,
                           "service": ActionsService(conn, ALL_ON, audit, POLICY, clock=lambda: "2026-10-12T00:00:00+00:00")})
    conn.close()
    assert file_sha256(source) == frozen_before                       # the frozen data was never written to


def one(conn, sql, *args):
    return conn.execute(sql, args).fetchone()


def processing_order(conn):
    return one(conn, "SELECT order_id FROM orders WHERE status='processing' ORDER BY order_id")[0]


def duplicate(conn):
    r = one(conn, "SELECT payment_id, order_id, amount_cents FROM payments WHERE status='duplicate_flagged' ORDER BY payment_id")
    return r["payment_id"], r["order_id"], r["amount_cents"]


def approve(env, action, order_id, **kw):
    return env.service.approvals.grant("T-000001", action, order_id, "A. Reviewer", **kw).approval_id


# ------------------------------------------------------------------ sandbox
def test_the_sandbox_is_a_copy_with_a_marker_and_the_source_is_untouched(env):
    assert env.dest != env.source and one(env.conn, "SELECT COUNT(*) FROM tickets")[0] == 150
    assert one(env.conn, "SELECT value FROM sandbox_meta WHERE key='source_sha256'")[0] == env.frozen_before


def test_the_frozen_database_cannot_be_opened_as_a_sandbox_or_overwritten(env, tmp_path):
    with pytest.raises(SandboxError):
        open_sandbox(env.source)
    with pytest.raises(SandboxError):
        create_sandbox(env.source, env.source, force=True)
    with pytest.raises(SandboxError):
        create_sandbox(env.source, env.dest)                               # exists, no force
    with pytest.raises(SandboxError):
        open_sandbox(tmp_path / "missing.db")


def test_replacing_a_sandbox_needs_it_closed_and_says_so_when_it_is_in_use(env, monkeypatch):
    original = Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(PermissionError("in use")))   # what Windows does for an open file
    with pytest.raises(SandboxError, match="in use"):
        create_sandbox(env.source, env.dest, force=True)
    monkeypatch.setattr(Path, "unlink", original)
    env.conn.close()                                                  # an open connection blocks the delete on Windows
    create_sandbox(env.source, env.dest, force=True)
    assert open_sandbox(env.dest).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


# ------------------------------------------------------------------ the gate
def test_nothing_runs_while_a_tool_is_switched_off(env):
    off = ActionsService(env.conn, ActionsConfig(), env.audit, POLICY)
    order = processing_order(env.conn)
    r = off.execute("cancel", "T-000001", order, approve(env, "cancel", order))
    assert (r.status, r.code) == ("refused", "action_disabled")
    assert one(env.conn, "SELECT status FROM orders WHERE order_id=?", order)[0] == "processing"


def test_a_call_without_an_approval_is_refused_and_logged(env):
    order = processing_order(env.conn)
    for approval_id in ("AP-000099", "garbage"):
        r = env.service.execute("cancel", "T-000001", order, approval_id)
        assert r.status == "refused" and r.code in ("no_approval", "invalid_argument")
    assert one(env.conn, "SELECT status FROM orders WHERE order_id=?", order)[0] == "processing"
    events = [e for e in query(env.audit.path, "T-000001") if e["event"] == "execution"]
    assert [e["data"]["status"] for e in events] == ["refused", "refused"]


def test_a_rejected_approval_does_not_allow_the_action(env):
    order = processing_order(env.conn)
    rejected = env.service.approvals.reject("T-000001", "cancel", order, "A. Reviewer", note="customer changed mind")
    r = env.service.execute("cancel", "T-000001", order, rejected.approval_id)
    assert (r.status, r.code) == ("refused", "not_approved")
    assert one(env.conn, "SELECT status FROM orders WHERE order_id=?", order)[0] == "processing"


@pytest.mark.parametrize("field,value", [("ticket_id", "T-000002"), ("order_id", "O-000001"), ("action", "replace"), ("amount_cents", 1),
                                         ("payment_id", "PM-000001"), ("address", "1 Other Road, Elsewhere 11111")])
def test_the_call_must_match_the_approval_exactly(env, field, value):
    pay, order, amount = duplicate(env.conn)
    ap = approve(env, "refund", order, payment_id=pay, amount_cents=amount)
    args = {"action": "refund", "ticket_id": "T-000001", "order_id": order, "payment_id": pay, "amount_cents": amount, "address": ""}
    args[field] = value
    r = env.service.execute(args.pop("action"), args.pop("ticket_id"), args.pop("order_id"), ap, **args)
    assert r.status == "refused" and r.code in ("approval_mismatch",)
    assert one(env.conn, "SELECT COUNT(*) FROM refunds WHERE payment_id=?", pay)[0] == 0


def test_approval_records_are_validated(env):
    store = env.service.approvals
    for bad in (dict(action="refund", order_id="O-000001"), dict(action="delete", order_id="O-000001"), dict(action="cancel", order_id="bad"),
                dict(action="change_address", order_id="O-000001")):
        with pytest.raises(ApprovalError):
            store.grant("T-000001", bad["action"], bad["order_id"], "A. Reviewer")
    with pytest.raises(ApprovalError):
        store.grant("T-000001", "cancel", "O-000001", "  ")


# ------------------------------------------------------------------ the four tools
def test_cancel_changes_a_processing_order_once(env):
    order = processing_order(env.conn)
    ap = approve(env, "cancel", order)
    r = env.service.execute("cancel", "T-000001", order, ap)
    assert (r.status, r.code) == ("executed", "ok") and one(env.conn, "SELECT status FROM orders WHERE order_id=?", order)[0] == "cancelled"
    assert one(env.conn, "SELECT COUNT(*) FROM action_ledger")[0] == 1


def test_cancel_is_refused_after_dispatch(env):
    order = one(env.conn, "SELECT order_id FROM orders WHERE status='shipped' LIMIT 1")[0]
    r = env.service.execute("cancel", "T-000001", order, approve(env, "cancel", order))
    assert (r.status, r.code) == ("refused", "order_not_open")


def test_change_address_adds_an_address_and_points_the_order_at_it(env):
    order = processing_order(env.conn)
    ap = approve(env, "change_address", order, address=NEW_ADDRESS)
    r = env.service.execute("change_address", "T-000001", order, ap, address=NEW_ADDRESS)
    assert r.status == "executed"
    row = one(env.conn, "SELECT a.* FROM orders o JOIN addresses a ON a.address_id = o.shipping_address_id WHERE o.order_id=?", order)
    assert (row["line1"], row["city"], row["postal_code"]) == ("451 Maple Way", "Missoula", "81259")


def test_change_address_refuses_text_it_cannot_split(env):
    order = processing_order(env.conn)
    odd = "somewhere near the big tree"
    r = env.service.execute("change_address", "T-000001", order, approve(env, "change_address", order, address=odd), address=odd)
    assert (r.status, r.code) == ("refused", "address_not_parseable")


def test_refund_records_the_refund_and_marks_the_payment(env):
    pay, order, amount = duplicate(env.conn)
    ap = approve(env, "refund", order, payment_id=pay, amount_cents=amount)
    r = env.service.execute("refund", "T-000001", order, ap, payment_id=pay, amount_cents=amount)
    assert r.status == "executed" and r.effect["payment_status"] == "refunded"
    assert one(env.conn, "SELECT amount_cents FROM refunds WHERE payment_id=?", pay)[0] == amount
    assert one(env.conn, "SELECT status FROM payments WHERE payment_id=?", pay)[0] == "refunded"


def test_a_partial_refund_leaves_the_payment_open_but_a_second_refund_is_refused(env):
    pay, order, amount = duplicate(env.conn)
    half = amount // 2
    first = env.service.execute("refund", "T-000001", order, approve(env, "refund", order, payment_id=pay, amount_cents=half), payment_id=pay, amount_cents=half)
    assert first.status == "executed" and first.effect["payment_status"] == "partly_refunded"
    assert one(env.conn, "SELECT status FROM payments WHERE payment_id=?", pay)[0] == "duplicate_flagged"      # not marked refunded
    second = env.service.execute("refund", "T-000001", order, approve(env, "refund", order, payment_id=pay, amount_cents=half), payment_id=pay, amount_cents=half)
    assert (second.status, second.code) == ("refused", "already_refunded")


def test_a_refund_above_the_payment_or_on_another_order_is_refused(env):
    pay, order, amount = duplicate(env.conn)
    over = env.service.execute("refund", "T-000001", order, approve(env, "refund", order, payment_id=pay, amount_cents=amount + 1), payment_id=pay, amount_cents=amount + 1)
    assert (over.status, over.code) == ("refused", "amount_exceeds_payment")
    other = one(env.conn, "SELECT order_id FROM orders WHERE order_id != ? LIMIT 1", order)[0]
    wrong = env.service.execute("refund", "T-000001", other, approve(env, "refund", other, payment_id=pay, amount_cents=amount), payment_id=pay, amount_cents=amount)
    assert (wrong.status, wrong.code) == ("refused", "payment_not_on_order")
    assert one(env.conn, "SELECT COUNT(*) FROM action_ledger")[0] == 0


def test_replace_needs_a_delivered_order_and_happens_once_per_order(env):
    delivered = one(env.conn, "SELECT order_id FROM orders WHERE status='delivered' ORDER BY order_id LIMIT 1")[0]
    r = env.service.execute("replace", "T-000001", delivered, approve(env, "replace", delivered))
    assert r.status == "executed" and one(env.conn, "SELECT COUNT(*) FROM replacements WHERE order_id=?", delivered)[0] == 1
    again = env.service.execute("replace", "T-000001", delivered, approve(env, "replace", delivered))
    assert (again.status, again.code) == ("refused", "replacement_exists")
    processing = processing_order(env.conn)
    assert env.service.execute("replace", "T-000001", processing, approve(env, "replace", processing)).code == "order_not_delivered"


def test_the_policy_rules_are_applied_again_at_execution(env):
    deny = parse_policy(b'[engine]\nversion = "t"\nauto_execute_enabled = false\n[[rule]]\nid = "NO-CANCEL"\noutcome = "deny"\nreason = "frozen"\n'
                        b'[rule.when]\naction = ["cancel_order"]\n')
    service = ActionsService(env.conn, ALL_ON, env.audit, deny)
    order = processing_order(env.conn)
    r = service.execute("cancel", "T-000001", order, approve(env, "cancel", order))
    assert (r.status, r.code) == ("refused", "policy_denied") and "NO-CANCEL" in r.detail


# ------------------------------------------------------------------ idempotency
def test_a_repeat_returns_the_first_result_and_writes_nothing(env):
    pay, order, amount = duplicate(env.conn)
    ap = approve(env, "refund", order, payment_id=pay, amount_cents=amount)
    first = env.service.execute("refund", "T-000001", order, ap, payment_id=pay, amount_cents=amount)
    before = [tuple(r) for r in env.conn.execute("SELECT * FROM refunds ORDER BY refund_id")]
    for _ in range(3):
        again = env.service.execute("refund", "T-000001", order, ap, payment_id=pay, amount_cents=amount)
        assert again.status == "replayed" and again.effect == first.effect and again.idempotency_key == first.idempotency_key
    assert [tuple(r) for r in env.conn.execute("SELECT * FROM refunds ORDER BY refund_id")] == before
    assert one(env.conn, "SELECT COUNT(*) FROM action_ledger")[0] == 1


def test_the_key_changes_with_every_input():
    base = ("T-000001", "refund", "O-000001", "PM-000001", 100, "", "AP-000001")
    keys = {idempotency_key(*base)}
    for i, other in enumerate(["T-000002", "cancel", "O-000002", "PM-000002", 101, "x", "AP-000002"]):
        changed = list(base)
        changed[i] = other
        keys.add(idempotency_key(*changed))
    assert len(keys) == 8


def test_concurrent_calls_execute_exactly_once(env):
    pay, order, amount = duplicate(env.conn)
    ap = approve(env, "refund", order, payment_id=pay, amount_cents=amount)
    results, lock = [], threading.Lock()

    def work():
        conn = open_sandbox(env.dest)
        r = ActionsService(conn, ALL_ON, env.audit, POLICY).execute("refund", "T-000001", order, ap, payment_id=pay, amount_cents=amount)
        conn.close()
        with lock:
            results.append(r.status)
    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["executed"] + ["replayed"] * 7
    assert one(env.conn, "SELECT COUNT(*) FROM refunds WHERE payment_id=?", pay)[0] == 1


def test_a_failure_inside_the_transaction_leaves_nothing_behind(env, monkeypatch):
    order = processing_order(env.conn)
    ap = approve(env, "cancel", order)
    monkeypatch.setattr(env.service, "_apply", lambda *a, **k: (env.conn.execute("UPDATE orders SET status='cancelled' WHERE order_id=?", (order,)), 1 / 0))
    r = env.service.execute("cancel", "T-000001", order, ap)
    assert (r.status, r.code) == ("refused", "execution_error")
    assert one(env.conn, "SELECT status FROM orders WHERE order_id=?", order)[0] == "processing" and one(env.conn, "SELECT COUNT(*) FROM action_ledger")[0] == 0


# ------------------------------------------------------------------ audit trail
def test_approval_and_execution_are_in_the_audit_chain_with_the_address_redacted(env):
    order = processing_order(env.conn)
    ap = approve(env, "change_address", order, address=NEW_ADDRESS)
    env.service.execute("change_address", "T-000001", order, ap, address=NEW_ADDRESS)
    env.service.execute("change_address", "T-000001", order, ap, address=NEW_ADDRESS)
    events = query(env.audit.path, "T-000001")
    assert [e["event"] for e in events] == ["approval", "execution", "execution"] and [e["data"]["status"] for e in events[1:]] == ["executed", "replayed"]
    assert NEW_ADDRESS not in env.audit.path.read_text(encoding="utf-8") and events[0]["actor"] == "A. Reviewer" and events[1]["actor"] == "actions-server"
    assert verify(env.audit.path).ok


# ------------------------------------------------------------------ proposals to calls
def test_call_from_proposal_maps_each_write_action():
    facts = {"order_id": "O-000001", "requested_address": NEW_ADDRESS, "duplicate_payment_id": "PM-000001", "duplicate_amount_cents": 500}
    line = lambda action: {"ticket_id": "T-000001", "action": action, "facts": facts}
    assert call_from_proposal(line("propose_cancellation")) == {"action": "cancel", "ticket_id": "T-000001", "order_id": "O-000001"}
    assert call_from_proposal(line("propose_address_change"))["address"] == NEW_ADDRESS
    assert call_from_proposal(line("propose_refund"))["amount_cents"] == 500 and call_from_proposal(line("propose_replacement"))["action"] == "replace"
    assert call_from_proposal(line("propose_return_label")) is None and call_from_proposal(line("propose_exchange")) is None
    item = {"ticket_id": "T-000001", "action": "propose_refund", "facts": {"order_id": "O-000001"}}
    assert call_from_proposal(item, amount_cents=900)["amount_cents"] == 900


def test_a_payment_marked_refunded_is_refused_even_without_a_refund_row(env):
    pay, order, amount = duplicate(env.conn)
    env.conn.execute("UPDATE payments SET status='refunded' WHERE payment_id=?", (pay,))
    r = env.service.execute("refund", "T-000001", order, approve(env, "refund", order, payment_id=pay, amount_cents=amount), payment_id=pay, amount_cents=amount)
    assert (r.status, r.code) == ("refused", "already_refunded")


def test_one_service_shared_by_threads_executes_once(env):
    order = processing_order(env.conn)
    ap = approve(env, "cancel", order)
    results, lock = [], threading.Lock()

    def work():
        r = env.service.execute("cancel", "T-000001", order, ap)
        with lock:
            results.append(r.status)
    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == ["executed"] + ["replayed"] * 7