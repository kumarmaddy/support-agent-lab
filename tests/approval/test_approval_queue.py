"""Stage 3.6: reading proposals from a run and working out where each one stands."""
import json

import pytest

from src.actions.sandbox import create_sandbox, open_sandbox
from src.approval.queue import APPROVED, EXECUTED, PENDING, REJECTED, QueueError, load_items, status_of
from tests.agent.test_handover import world  # noqa: F401  (the fixture)
from tests.approval.support_approval import build_run


@pytest.fixture(scope="module")
def run_dir(world, tmp_path_factory):
    return build_run(world, tmp_path_factory.mktemp("queue"))


def test_only_proposals_are_listed_with_the_senior_queue_first(run_dir):
    items = load_items(run_dir)
    assert [i.ticket_id for i in items] == ["T-000149", "T-000001", "T-000009", "T-000011", "T-000029", "T-000046"]
    assert items[0].queue == "senior" and items[0].rule_id == "APPROVE-REFUND-SENIOR" and all(i.queue == "standard" for i in items[1:])


def test_each_proposal_carries_the_call_the_tool_would_receive(run_dir):
    by = {i.ticket_id: i for i in load_items(run_dir)}
    assert by["T-000011"].call["action"] == "cancel" and by["T-000001"].call["action"] == "change_address" and by["T-000001"].call["address"]
    assert by["T-000029"].call["action"] == "refund" and by["T-000029"].call["amount_cents"] > 0 and by["T-000029"].call["payment_id"].startswith("PM-")
    assert by["T-000009"].call is None and by["T-000009"].tool == ""                      # a return label has no write tool
    assert by["T-000046"].call["action"] == "refund" and by["T-000046"].call["payment_id"] == ""      # an item refund: the approver sets the amount


def test_status_follows_the_sandbox(run_dir, dev_dataset, tmp_path):
    from src.actions.config import ActionsConfig
    from src.actions.service import ActionsService
    conn = open_sandbox(create_sandbox(dev_dataset[0], tmp_path / "s.db"))
    service = ActionsService(conn, ActionsConfig(frozenset({"cancel"})))
    item = next(i for i in load_items(run_dir) if i.ticket_id == "T-000011")
    assert status_of(conn, item)[0] == PENDING
    ap = service.approvals.grant("T-000011", "cancel", item.order_id, "A. Reviewer")
    assert status_of(conn, item)[0] == APPROVED
    service.execute("cancel", "T-000011", item.order_id, ap.approval_id)
    assert status_of(conn, item)[0] == EXECUTED
    other = next(i for i in load_items(run_dir) if i.ticket_id == "T-000001")
    service.approvals.reject("T-000001", "change_address", other.order_id, "A. Reviewer")
    assert status_of(conn, other)[0] == REJECTED
    assert status_of(conn, next(i for i in load_items(run_dir) if i.ticket_id == "T-000009"))[0] == PENDING     # no tool: never decided here
    conn.close()


def test_a_missing_run_is_reported(tmp_path):
    with pytest.raises(QueueError):
        load_items(tmp_path)


def test_blank_lines_and_a_bom_are_tolerated(tmp_path):
    (tmp_path / "resolutions.jsonl").write_text("﻿" + json.dumps({"ticket_id": "T-000001", "action": "reply", "facts": {}}) + "\n\n", encoding="utf-8")
    assert load_items(tmp_path) == []