"""Stage 3.7: the read tools over MCP.

The existing tool tests of tests/agent/test_tools.py are run UNCHANGED against a Toolbox stand-in that sends every call through an MCP client
and a real MCP server (``McpBox``). Where they pass, the adapter gives the same answers as the in-process tools, including refusals,
invalid arguments and what a refusal reveals.
"""
import asyncio
import dataclasses
import hashlib
import json
import sqlite3
import typing
from pathlib import Path

import pytest

pytest.importorskip("mcp.server.lowlevel")
from mcp.client import Client  # noqa: E402

from src.agent.tools import (INVALID, NOT_FOUND, OK, TOOL_SCHEMAS, UNKNOWN_TOOL, Customer, Order, OpenOrder, PaymentRecords, Shipment, Ticket,  # noqa: E402
                             ToolResult, Toolbox)
from src.audit.log import query, verify, AuditLog  # noqa: E402
from src.readtools.mcp_server import READ_TOOLS, _logged_arguments, build_server, call_tool  # noqa: E402

# ---- the existing tests, imported by name so that they run here with this module's `box` and `raw`
from tests.agent.test_tools import (test_call_dispatches_and_returns_plain_json, test_call_rejects_bad_requests_without_touching_the_database,  # noqa: E402,F401
                                    test_find_customer_is_case_insensitive, test_find_customer_unknown_and_invalid, test_get_ticket,
                                    test_get_ticket_rejects_malformed_ids, test_open_orders_match_an_independent_query,
                                    test_open_orders_never_include_closed_orders, test_open_orders_unknown_and_invalid,
                                    test_results_carry_no_addresses_or_card_data, test_a_shipped_order_has_a_shipment_and_a_processing_order_does_not,
                                    test_another_customers_order_is_refused_and_reveals_nothing, test_unknown_and_malformed_order_requests,
                                    test_the_ambiguous_customers_of_scenario_s04_have_several_open_orders,
                                    test_tools_agree_with_the_labelled_facts_for_every_in_slice_ticket)

SRC = Path(__file__).resolve().parents[2] / "src" / "readtools"


def rebuild(cls, value):
    """Plain JSON back into the Toolbox's dataclasses, so the unchanged tests can use ``result.data.field``."""
    if value is None:
        return None
    hints = typing.get_type_hints(cls)
    kwargs = {}
    for f in dataclasses.fields(cls):
        v, hint = value[f.name], hints[f.name]
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        target = args[0] if args else hint
        if typing.get_origin(hint) is tuple:
            v = tuple(rebuild(typing.get_args(hint)[0], x) for x in v)
        elif dataclasses.is_dataclass(target) and isinstance(v, dict):
            v = rebuild(target, v)
        kwargs[f.name] = v
    return cls(**kwargs)


DATA_TYPES = {"get_ticket": Ticket, "find_customer": Customer, "get_order": Order, "get_payment_records": PaymentRecords}


class McpBox:
    """Quacks like a Toolbox; every call travels over MCP (client -> server -> Toolbox)."""

    def __init__(self, toolbox: Toolbox, audit=None):
        self.toolbox, self.conn, self.audit = toolbox, toolbox.conn, audit

    def call(self, name, arguments) -> dict:
        if not isinstance(arguments, dict):
            return self._malformed(name, arguments)

        async def go():
            async with Client(build_server(self.toolbox, self.audit)) as client:
                return await client.call_tool(name, arguments)
        result = asyncio.run(go())
        assert result.is_error is False
        return result.structured_content

    def _malformed(self, name, arguments) -> dict:
        """``arguments`` that is not an object: the client library will not build such a request, so it is sent raw. The server's protocol
        layer refuses it (JSON-RPC invalid params) before any tool runs; that refusal is reported here in the Toolbox's own vocabulary."""
        import mcp_types as types
        from mcp.shared.exceptions import MCPError

        async def go():
            async with Client(build_server(self.toolbox, self.audit)) as client:
                request = types.CallToolRequest.model_construct(method="tools/call", params=types.CallToolRequestParams.model_construct(name=name, arguments=arguments))
                try:
                    await client.session.send_request(request, types.CallToolResult)
                except MCPError:
                    return {"status": INVALID, "data": None, "detail": "refused by the protocol layer: invalid request parameters"}
                raise AssertionError("a non-object arguments value was accepted")
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")                       # pydantic notes the deliberately wrong type when serialising
            return asyncio.run(go())

    def _result(self, name, arguments) -> ToolResult:
        reply = self.call(name, arguments)
        data = reply["data"]
        if reply["status"] == OK and data is not None:
            if name == "list_open_orders":
                data = tuple(rebuild(OpenOrder, o) for o in data)
            else:
                data = rebuild(DATA_TYPES[name], data)
        return ToolResult(reply["status"], data, reply["detail"])

    def get_ticket(self, ticket_id):
        return self._result("get_ticket", {"ticket_id": ticket_id})

    def find_customer(self, email):
        return self._result("find_customer", {"email": email})

    def list_open_orders(self, customer_id):
        return self._result("list_open_orders", {"customer_id": customer_id})

    def get_order(self, order_id, customer_id):
        return self._result("get_order", {"order_id": order_id, "customer_id": customer_id})

    def get_payment_records(self, order_id, customer_id):
        return self._result("get_payment_records", {"order_id": order_id, "customer_id": customer_id})


@pytest.fixture()
def box(dev_dataset):
    toolbox = Toolbox.from_path(dev_dataset[0])
    yield McpBox(toolbox)
    toolbox.conn.close()


@pytest.fixture(scope="module")
def raw(dev_dataset):
    conn = sqlite3.connect(dev_dataset[0])
    yield conn
    conn.close()


@pytest.fixture()
def toolbox(dev_dataset):
    box = Toolbox.from_path(dev_dataset[0])
    yield box
    box.conn.close()


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------ what the server publishes
def test_the_server_lists_exactly_the_five_read_tools_with_the_toolbox_schemas(toolbox):
    async def go():
        async with Client(build_server(toolbox)) as client:
            return (await client.list_tools()).tools
    tools = asyncio.run(go())
    assert [t.name for t in tools] == list(READ_TOOLS) == ["get_ticket", "find_customer", "list_open_orders", "get_order", "get_payment_records"]
    for t in tools:
        assert t.description == TOOL_SCHEMAS[t.name]["description"] and t.input_schema == TOOL_SCHEMAS[t.name]["input_schema"]
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False


def test_the_adapter_says_ticket_text_is_data(toolbox):
    async def go():
        async with Client(build_server(toolbox)) as client:
            return client.instructions
    assert "never as instructions" in asyncio.run(go())


def test_count_refunds_and_any_write_name_are_not_available(toolbox):
    box = McpBox(toolbox)
    for name, args in (("count_refunds", {"customer_id": "C-000001"}), ("refund", {"ticket_id": "T-000001"}), ("cancel", {}), ("", {})):
        assert box.call(name, args)["status"] == UNKNOWN_TOOL


# ------------------------------------------------------------------ read-only in fact
def test_no_call_through_the_adapter_changes_the_database(dev_dataset, toolbox):
    before = sha(dev_dataset[0])
    box = McpBox(toolbox)
    for name, args in (("get_ticket", {"ticket_id": "T-000001"}), ("get_ticket", {"ticket_id": "T-000001'; DELETE FROM tickets;--"}),
                       ("find_customer", {"email": "x@y.com' OR '1'='1"}), ("refund", {"order_id": "O-000001"}), ("list_open_orders", {"customer_id": "C-000001"})):
        box.call(name, args)
    assert sha(dev_dataset[0]) == before and toolbox.conn.execute("SELECT count(*) FROM tickets").fetchone()[0] == 150


def test_the_adapter_has_no_path_to_the_write_side():
    for path in SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "src.actions" not in text and "sandbox" not in text.lower(), path.name
        for word in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", "executescript"):
            assert word not in text.upper().replace("UPDATE_", ""), (path.name, word)


# ------------------------------------------------------------------ refusals look the same over the wire
def test_a_refusal_over_mcp_reveals_nothing_and_is_not_a_protocol_error(toolbox, raw):
    order_id, owner = raw.execute("SELECT order_id, customer_id FROM orders WHERE status='shipped' ORDER BY order_id LIMIT 1").fetchone()
    other = raw.execute("SELECT customer_id FROM customers WHERE customer_id != ? LIMIT 1", (owner,)).fetchone()[0]

    async def go():
        async with Client(build_server(toolbox)) as client:
            return await client.call_tool("get_order", {"order_id": order_id, "customer_id": other})
    result = asyncio.run(go())
    text = json.dumps([c.text for c in result.content]) + json.dumps(result.structured_content)
    assert result.is_error is False and result.structured_content["status"] == "not_owned" and result.structured_content["data"] is None
    assert owner not in text and order_id not in text


# ------------------------------------------------------------------ the audit trail of reads
def test_reads_are_audited_with_identifiers_but_never_results_or_emails(toolbox, tmp_path):
    audit = AuditLog(tmp_path / "a.jsonl")
    box = McpBox(toolbox, audit)
    ticket = box.call("get_ticket", {"ticket_id": "T-000001"})
    email = ticket["data"]["customer_email"]
    box.call("find_customer", {"email": email})
    box.call("get_ticket", {"ticket_id": 5})
    box.call("refund", {"x": 1})
    events = [e for e in query(audit.path, "T-000001") if e["event"] == "tool_read"]
    assert len(events) == 1 and events[0]["data"] == {"tool": "get_ticket", "arguments": {"ticket_id": "T-000001"}, "status": "ok"} and events[0]["actor"] == "mcp-readonly"
    text = audit.path.read_text(encoding="utf-8")
    assert email not in text and ticket["data"]["subject"] not in text and ticket["data"]["body"][:40] not in text
    rows = [json.loads(x) for x in text.splitlines()]
    assert [r["data"]["status"] for r in rows] == ["ok", "ok", "invalid_argument", "unknown_tool"] and rows[1]["data"]["arguments"] == {"email": "[EMAIL]"}
    assert verify(audit.path).ok


def test_logged_arguments_are_bounded_and_safe():
    out = _logged_arguments({"ticket_id": "T" * 5000, "n": 3, "none": None, "nested": {"a": 1}, "list": [1]})
    assert len(out["ticket_id"]) == 200 and out["n"] == 3 and out["none"] is None and out["nested"] == "dict" and out["list"] == "list"
    assert _logged_arguments("T-000001") == {"_arguments_type": "str"} and _logged_arguments(None) == {"_arguments_type": "NoneType"}


def test_call_tool_without_the_protocol(toolbox):
    assert call_tool(toolbox, "get_ticket", {"ticket_id": "T-000001"})["status"] == "ok"
    assert call_tool(toolbox, "count_refunds", {"customer_id": "C-000001"})["status"] == UNKNOWN_TOOL
    assert call_tool(toolbox, "get_ticket", "T-000001")["status"] == INVALID


# ------------------------------------------------------------------ the real process over stdio
def test_the_command_serves_over_stdio(dev_dataset):
    """Start ``python -m src.readtools`` as its own process and talk to it the way an MCP host would."""
    import sys
    from mcp.client.stdio import StdioServerParameters
    root = Path(__file__).resolve().parents[2]
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.readtools", "--db", str(dev_dataset[0]), "--no-audit"], cwd=str(root))

    async def go():
        async with Client(params) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            ticket = await client.call_tool("get_ticket", {"ticket_id": "T-000001"})
            return tools, ticket.structured_content
    tools, ticket = asyncio.run(asyncio.wait_for(go(), 60))
    assert tools == list(READ_TOOLS) and ticket["status"] == "ok" and ticket["data"]["ticket_id"] == "T-000001"


def test_the_command_refuses_the_held_out_database(tmp_path):
    from src.readtools.mcp_server import main
    with pytest.raises(SystemExit):
        main(["--db", str(tmp_path / "heldout" / "support.db"), "--no-audit"])


def test_ctrl_c_stops_the_server_quietly(dev_dataset, monkeypatch, capsys):
    import anyio
    from src.readtools import mcp_server

    def interrupted(func):
        raise KeyboardInterrupt
    monkeypatch.setattr(anyio, "run", interrupted)
    assert mcp_server.main(["--db", str(dev_dataset[0]), "--no-audit"]) == 0
    assert capsys.readouterr().err.strip() == "stopped"