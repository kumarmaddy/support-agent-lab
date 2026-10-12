"""Stage 3.5: the same service over MCP (official SDK 2.x), through an in-memory client. Skipped when the SDK is not installed."""
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.mcpserver")
from mcp.client import Client  # noqa: E402

from src.actions.config import ActionsConfig  # noqa: E402
from src.actions.mcp_server import build_server  # noqa: E402
from src.actions.sandbox import create_sandbox, open_sandbox  # noqa: E402
from src.actions.service import ActionsService  # noqa: E402
from src.agent.policy import load_policy  # noqa: E402
from src.audit.log import AuditLog  # noqa: E402

POLICY = load_policy(Path(__file__).resolve().parents[2] / "config" / "policy.toml")


def payload(result) -> dict:
    structured = getattr(result, "structured_content", None)
    if structured:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    return json.loads(result.content[0].text)


def call(service, name, args):
    async def go():
        async with Client(build_server(service)) as client:
            return await client.call_tool(name, args)
    return payload(asyncio.run(go()))


@pytest.fixture
def service(dev_dataset, tmp_path):
    conn = open_sandbox(create_sandbox(dev_dataset[0], tmp_path / "s.db"))
    yield ActionsService(conn, ActionsConfig(frozenset({"cancel", "refund", "replace", "change_address"})), AuditLog(tmp_path / "a.jsonl"), POLICY)
    conn.close()


def test_the_four_write_tools_are_listed():
    service = ActionsService(None, ActionsConfig())

    async def go():
        async with Client(build_server(service)) as client:
            return await client.list_tools()
    tools = asyncio.run(go()).tools
    assert sorted(t.name for t in tools) == ["cancel", "change_address", "refund", "replace"]
    assert "approval_id" in next(t for t in tools if t.name == "cancel").input_schema["properties"]


def test_a_call_without_an_approval_is_refused_over_mcp(service):
    out = call(service, "cancel", {"ticket_id": "T-000001", "order_id": "O-000001", "approval_id": "AP-000001"})
    assert out["status"] == "refused" and out["code"] == "no_approval"


def test_an_approved_call_executes_and_its_repeat_is_a_replay(service):
    order = service.conn.execute("SELECT order_id FROM orders WHERE status='processing' LIMIT 1").fetchone()[0]
    ap = service.approvals.grant("T-000001", "cancel", order, "A. Reviewer").approval_id
    args = {"ticket_id": "T-000001", "order_id": order, "approval_id": ap}
    assert call(service, "cancel", args)["status"] == "executed"
    assert call(service, "cancel", args)["status"] == "replayed"
    assert service.conn.execute("SELECT status FROM orders WHERE order_id=?", (order,)).fetchone()[0] == "cancelled"


def test_a_switched_off_tool_is_refused_over_mcp(service):
    service.config = ActionsConfig()
    out = call(service, "replace", {"ticket_id": "T-000001", "order_id": "O-000001", "approval_id": "AP-000001"})
    assert out["code"] == "action_disabled"


def test_the_approval_id_given_over_mcp_is_the_one_checked(service):
    orders = [r[0] for r in service.conn.execute("SELECT order_id FROM orders WHERE status='processing' LIMIT 2")]
    first = service.approvals.grant("T-000001", "cancel", orders[0], "A. Reviewer").approval_id
    second = service.approvals.grant("T-000001", "cancel", orders[1], "A. Reviewer").approval_id
    assert call(service, "cancel", {"ticket_id": "T-000001", "order_id": orders[1], "approval_id": first})["code"] == "approval_mismatch"
    assert call(service, "cancel", {"ticket_id": "T-000001", "order_id": orders[1], "approval_id": second})["status"] == "executed"