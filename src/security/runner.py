"""Run one case against the real code in a throw-away world and return what was observed. The runner judges nothing (see score.py)."""
import asyncio
import dataclasses
import hashlib
import json
import tempfile
from pathlib import Path
from urllib.parse import urlencode

from src.actions.approvals import ApprovalError
from src.actions.config import ACTIONS, ActionsConfig
from src.actions.sandbox import open_sandbox
from src.actions.service import ActionsService
from src.agent import decide as d
from src.agent.pipeline import internal_guidance, run_ticket
from src.agent.policy import load_policy
from src.agent.prompting import load_prompt
from src.agent.tools import Toolbox
from src.agent.tracing import TraceWriter
from src.agent.transactions import Transactions
from src.approval.app import ApprovalApp
from src.audit.log import AuditLog
from src.kb.articles import SECTION_KEY_FACTS, load_articles
from src.readtools.mcp_server import READ_TOOLS, call_tool
from src.agent.knowledge import Knowledge
from src.security.cases import resolve
from src.security.hostile import FixedRetriever, HostileModel
from src.security.world import World, load_roles, snapshot

REPO = Path(__file__).resolve().parents[2]
READ, REPLY = load_prompt("read_ticket", "v5"), load_prompt("reply", "v1")
CHECK, KREPLY = load_prompt("knowledge_check", "v1"), load_prompt("knowledge_reply", "v1")
TX = Transactions(load_prompt("extract_address", "v1"), load_prompt("read_request", "v1"), load_prompt("read_refund", "v1"))
POLICY = load_policy(REPO / "config" / "policy.toml")
ARTICLES = load_articles(REPO / "data" / "seed" / "kb")
INTERNAL = internal_guidance(ARTICLES)
PORT = 8765


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _model(spec: dict) -> HostileModel:
    return HostileModel(spec.get("read"), spec.get("topic"), spec.get("request"), spec.get("address", ""), spec.get("reply"), spec.get("check", True))


def _body(spec: dict) -> str:
    return spec["body"] + (" " + "A" * spec["body_pad"] if spec.get("body_pad") else "")


def _knowledge(spec: dict):
    kb = spec.get("kb")
    if not kb:
        return None
    article = ARTICLES[kb["article"]]
    sections = {**article.sections, SECTION_KEY_FACTS: article.sections.get(SECTION_KEY_FACTS, "") + "\n- " + kb["fact"]}
    return Knowledge(FixedRetriever(kb["article"], error=bool(kb.get("error"))), {**ARTICLES, kb["article"]: dataclasses.replace(article, sections=sections)}, CHECK, KREPLY, 0.65)


# ------------------------------------------------------------------ pipeline
def run_pipeline(case, world: World, roles: dict) -> dict:
    spec = resolve(case.spec, roles)
    sender = spec["sender"]
    tid = world.add_ticket(1, sender, spec["subject"], _body(spec))
    before = _sha(world.ops_db)
    box = Toolbox.from_path(world.ops_db)
    try:
        res = run_ticket(box, _model(spec), READ, REPLY, INTERNAL, tid, 0, "model", _knowledge(spec), TX, POLICY)
    finally:
        box.conn.close()
    owner = world.customer_of(sender)
    text = f"{spec['subject']} {_body(spec)}".lower()
    leak = [t for r in roles.values() if r["customer"] != owner for t in (r["email"], r["name"], r["order"], r["tracking"]) if t.lower() not in text]
    return {"resolution": {"action": res.action, "reason": res.reason, "reply": res.reply, "reply_source": res.reply_source, "facts": res.facts,
                   "policy_outcome": (res.policy or {}).get("outcome", "")},
            "note_text": json.dumps(res.handover or {}, ensure_ascii=False), "sender_customer": owner, "db_path": str(world.ops_db),
            "db_changed": _sha(world.ops_db) != before, "leak_terms": leak}


# ------------------------------------------------------------------ actions service (direct and over MCP)
def _grant(service: ActionsService, g: dict) -> str:
    try:
        if g.get("status", "approved") == "rejected":
            return service.approvals.reject(g["ticket"], g["action"], g["order"], "A. Reviewer", note="rejected").approval_id
        return service.approvals.grant(g["ticket"], g["action"], g["order"], "A. Reviewer", payment_id=g.get("payment", ""),
                                       amount_cents=g.get("amount"), address=g.get("address", ""), rule_id=g.get("rule", ""), note="approved").approval_id
    except ApprovalError as exc:
        return f"AP-ERR:{exc}"


MCP_TOOL = {"cancel": "cancel", "change_address": "change_address", "refund": "refund", "replace": "replace"}


def _call(service: ActionsService, call: dict, via: str) -> dict:
    if via == "direct":
        names = {"payment": "payment_id", "amount": "amount_cents"}
        args = {names.get(k, k): v for k, v in call.items() if k not in ("action", "ticket", "order", "approval")}
        return service.execute(call["action"], call["ticket"], call["order"], call["approval"], **args).to_dict()
    from mcp.client import Client
    from src.actions.mcp_server import build_server
    arguments = {k: v for k, v in call.items() if k not in ("action", "tool")}
    arguments = {("ticket_id" if k == "ticket" else "order_id" if k == "order" else "approval_id" if k == "approval" else "payment_id" if k == "payment"
                  else "amount_cents" if k == "amount" else k): v for k, v in arguments.items()}

    async def go():
        async with Client(build_server(service)) as client:
            return await client.call_tool(MCP_TOOL.get(call["action"], call["action"]), arguments)
    try:
        out = asyncio.run(go())
    except Exception as exc:                                                            # the protocol layer refused the call before the service saw it
        return {"status": "refused", "code": "protocol_error", "detail": type(exc).__name__}
    if getattr(out, "is_error", False):
        return {"status": "refused", "code": "protocol_error", "detail": "the tool call was refused by the protocol layer"}
    structured = getattr(out, "structured_content", None)
    if structured:
        return structured.get("result", structured) if set(structured) == {"result"} else structured
    return json.loads(out.content[0].text)


def run_actions(case, world: World, roles: dict) -> dict:
    spec = case.spec
    conn = world.make_sandbox()
    try:
        audit = AuditLog(world.root / "audit.jsonl")
        service = ActionsService(conn, ActionsConfig(frozenset(spec.get("tools_on", ACTIONS))), audit, POLICY)
        extra = {}
        for i, g in enumerate(resolve(spec.get("setup", []), roles), 1):
            extra[f"ap{i}"] = _grant(service, g)
        for prior in resolve(spec.get("prior", []), roles, extra):
            _call(service, prior, "direct")
        before = snapshot(world.sandbox)
        call = resolve(spec["call"], roles, extra)
        via = spec.get("via", "direct")
        result = _call(service, call, via)
        out = {"result": result}
        if spec.get("repeat"):
            out["repeat"] = _call(service, call, via)
    finally:
        conn.close()
    return {**out, "before": before, "after": snapshot(world.sandbox)}


# ------------------------------------------------------------------ approval page
def run_approval(case, world: World, roles: dict) -> dict:
    spec = resolve(case.spec, roles)
    ids = [world.add_ticket(i + 1, t["sender"], t["subject"], _body(t)) for i, t in enumerate(spec["tickets"])]
    box = Toolbox.from_path(world.ops_db)
    try:
        with TraceWriter(world.root / "runs", "run-security", {}) as writer:
            for tid, t in zip(ids, spec["tickets"]):
                writer.write(run_ticket(box, _model(t), READ, REPLY, INTERNAL, tid, 0, "template", None, TX, POLICY))
    finally:
        box.conn.close()
    world.make_sandbox().close()
    on = frozenset(spec.get("tools_on", ACTIONS))
    app = ApprovalApp(writer.dir, world.sandbox, spec.get("approver", "A. Reviewer"), spec.get("role", "standard"), ActionsConfig(on), POLICY,
                      AuditLog(world.root / "audit.jsonl"), edits_file=world.root / "edits.jsonl", port=PORT)
    before, steps = snapshot(world.sandbox), []
    for step in spec["steps"]:
        t = {f"t{i}": tid for i, tid in enumerate(ids)}
        path = step["path"]
        for key, value in t.items():
            path = path.replace("{" + key + "}", value)
        headers = {"Host": f"127.0.0.1:{PORT}", **step.get("headers", {})}
        token = {"good": app.token, "bad": "not-the-token", "none": None}[step.get("token", "good")]
        fields = {**({"token": token} if token is not None else {}), **step.get("fields", {})}
        raw = urlencode(fields).encode("utf-8") + (b"&pad=" + b"x" * step["pad"] if step.get("pad") else b"")
        if "content_type" in step or step.get("method", "GET") == "POST":
            headers.setdefault("Content-Type", step.get("content_type", "application/x-www-form-urlencoded"))
        r = app.handle(step.get("method", "GET"), path, headers, raw if step.get("method", "GET") in ("POST", "PUT") else b"")
        steps.append({"status": r.status, "body": r.body if isinstance(r.body, str) else r.body.decode("utf-8", "replace"), "headers": dict(r.headers)})
    return {"steps": steps, "before": before, "after": snapshot(world.sandbox)}


# ------------------------------------------------------------------ read-only tools
def run_read(case, world: World, roles: dict) -> dict:
    spec = resolve(case.spec, roles)
    box = Toolbox.from_path(world.ops_db)
    try:
        out = {"result": call_tool(box, spec["tool"], spec["arguments"])}
        if spec.get("list_tools"):
            from mcp.client import Client
            from src.readtools.mcp_server import build_server

            async def go():
                async with Client(build_server(box)) as client:
                    return [t.name for t in (await client.list_tools()).tools]
            out["tools_listed"] = asyncio.run(go())
    finally:
        box.conn.close()
    return out


RUNNERS = {"pipeline": run_pipeline, "actions": run_actions, "approval": run_approval, "read": run_read}


def run_case(case, source_db, judge, scratch=None):
    """A fresh world per case, so no case can affect another. Any exception is reported as an error observation, never as a pass.
    ``judge(case, observation)`` is the scorer's function; it is called before the world is deleted and its verdict is returned."""
    roles = load_roles(source_db)
    with tempfile.TemporaryDirectory(dir=scratch, ignore_cleanup_errors=True) as tmp:
        try:
            obs = RUNNERS[case.layer](case, World(Path(tmp), Path(source_db), roles), roles)
            obs["expect"] = resolve(case.spec.get("expect", {}), roles)
        except Exception as exc:                                                           # noqa: BLE001  (an unexpected crash must score as a failure)
            obs = {"error": f"{type(exc).__name__}: {exc}"}
        return judge(case, obs)                       # judged while the throw-away world still exists (the scorer reads its database)