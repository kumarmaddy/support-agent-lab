"""HTML for the approval page. Every dynamic value goes through ``esc``; there is no script and no inline style (ticket text is untrusted)."""
from html import escape

from src.approval.queue import APPROVED, EXECUTED, PENDING, REJECTED

STYLE = """
:root{color-scheme:light dark;--bg:#f6f7f9;--fg:#1c2330;--muted:#5b6678;--card:#fff;--line:#d5dae3;--accent:#1f5fbf;--warn:#9a5b00;--bad:#a4262c;--good:#1b6e3c}
@media (prefers-color-scheme:dark){:root{--bg:#14181f;--fg:#e6e9ef;--muted:#9aa4b5;--card:#1d232d;--line:#333c4a;--accent:#6ea2ff;--warn:#f0b04a;--bad:#ff8a8f;--good:#6fd39a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px 60px}h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:26px 0 8px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin:10px 0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
a{color:var(--accent)}.tag{display:inline-block;padding:1px 8px;border-radius:10px;border:1px solid var(--line);font-size:12px}
.senior{border-color:var(--warn);color:var(--warn)}.pending{border-color:var(--accent);color:var(--accent)}.approved,.executed{border-color:var(--good);color:var(--good)}.rejected{border-color:var(--bad);color:var(--bad)}
.banner{border-left:4px solid var(--accent);padding:8px 12px;margin:12px 0;background:var(--card)}.banner.bad{border-color:var(--bad)}.banner.good{border-color:var(--good)}
pre{white-space:pre-wrap;word-wrap:break-word;background:var(--bg);border:1px solid var(--line);padding:10px;border-radius:6px;margin:6px 0}
label{display:block;margin:10px 0 3px;font-weight:600}input[type=text],textarea,select{width:100%;padding:7px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}
button{font:inherit;padding:7px 16px;border-radius:6px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;margin:10px 8px 0 0}button:disabled{opacity:.4;cursor:not-allowed;background:var(--line);border-color:var(--line);color:var(--muted)}button.reject{background:transparent;color:var(--bad);border-color:var(--bad)}button.edit{background:transparent;color:var(--accent)}
dl{display:grid;grid-template-columns:170px 1fr;gap:4px 12px;margin:0}dt{color:var(--muted)}dd{margin:0}
"""
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
}


def esc(value) -> str:
    return escape("" if value is None else str(value), quote=True)


def money(cents) -> str:
    return "" if cents is None else f"${cents / 100:,.2f}"


def page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><link rel="stylesheet" href="/style.css"></head><body><main>{body}</main></body></html>')


def tag(text: str, cls: str = "") -> str:
    return f'<span class="tag {esc(cls)}">{esc(text)}</span>'


def banner(message: str, kind: str = "") -> str:
    return f'<div class="banner {esc(kind)}" role="status">{esc(message)}</div>' if message else ""


def list_page(items, statuses, approver: str, role: str, run_id: str, notice: str = "") -> str:
    def row(item):
        status = statuses[item.ticket_id]
        name = item.action.replace("propose_", "").replace("_", " ")
        link = f'<a href="/ticket/{esc(item.ticket_id)}">{esc(item.ticket_id)}</a>'
        locked = item.queue == "senior" and role != "senior"
        return (f"<tr><td>{link}</td><td>{esc(name)}</td><td>{esc(item.order_id)}</td><td>{tag(item.queue, 'senior' if item.queue == 'senior' else '')}</td>"
                f"<td>{esc(item.rule_id)}</td><td>{tag(status if item.call else 'manual', status if item.call else '')}"
                f"{' ' + tag('needs senior approver') if locked and status == PENDING else ''}</td></tr>")
    body = "".join(row(i) for i in items) or '<tr><td colspan="6" class="muted">No proposals in this run.</td></tr>'
    pending = sum(1 for i in items if i.call and statuses[i.ticket_id] == PENDING)
    return page("Approvals", f'<h1>Approvals</h1><p class="muted">Run {esc(run_id)} · signed in as {esc(approver)} ({esc(role)} approver) · {pending} pending</p>'
                f'{banner(notice)}<div class="card"><table><thead><tr><th>Ticket</th><th>Proposal</th><th>Order</th><th>Queue</th><th>Policy rule</th><th>Status</th></tr></thead>'
                f'<tbody>{body}</tbody></table></div><p class="muted">Senior-queue proposals are listed first. Proposals marked manual have no write tool and are handled outside this page. '
                f'Nothing is executed until you approve a proposal and then press Execute, and only when that tool is switched on in config/actions.toml.</p>')


def _facts(rows) -> str:
    return "<dl>" + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in rows if v not in (None, "")) + "</dl>"


def detail_page(item, status: str, approval, ticket, payments, token: str, role: str, tool_on: bool, notice: str = "", notice_kind: str = "") -> str:
    rec, handover, policy = item.record, item.record.get("handover") or {}, item.record.get("policy") or {}
    facts = rec.get("facts", {})
    locked = item.queue == "senior" and role != "senior"
    parts = [f'<p><a href="/">&larr; All proposals</a></p><h1>{esc(item.ticket_id)} · {esc(item.action.replace("propose_", "").replace("_", " "))}</h1>',
             f'<p>{tag(item.queue, "senior" if item.queue == "senior" else "")} {tag(status, status)} <span class="muted">policy rule {esc(item.rule_id)}</span></p>',
             banner(notice, notice_kind)]
    parts.append(f'<div class="card"><h2>Why this was proposed</h2><p>{esc(handover.get("why", item.reason))}</p><p><strong>Suggested next step:</strong> {esc(handover.get("next_step", ""))}</p>'
                 + "".join(f"<div>{esc(r)}</div>" for r in handover.get("records", [])) + "</div>")
    if ticket:
        parts.append(f'<div class="card"><h2>Customer ticket <span class="muted">(untrusted text, shown as data)</span></h2><p><strong>{esc(ticket["subject"])}</strong></p><pre>{esc(ticket["body"])}</pre></div>')
    parts.append(f'<div class="card"><h2>Draft reply to the customer <span class="muted">(not sent by this page)</span></h2><pre>{esc(rec.get("reply", ""))}</pre></div>')
    if not item.call:
        parts.append('<div class="card">This proposal has no write tool. A person carries it out outside this page.</div>')
        return page(item.ticket_id, "".join(parts))
    call = item.call
    parts.append('<div class="card"><h2>What would be done</h2>' + _facts([("Action", call["action"]), ("Order", call["order_id"]), ("Payment", call.get("payment_id")),
                 ("Amount", money(call.get("amount_cents"))), ("New address", call.get("address")), ("Policy outcome", policy.get("outcome")), ("Policy reason", policy.get("reason"))]) + "</div>")
    if approval is not None:
        parts.append('<div class="card"><h2>Decision</h2>' + _facts([("Status", approval["status"]), ("Decided by", approval["approver"]), ("At", approval["decided_at"]), ("Approval id", approval["approval_id"]),
                     ("Payment", approval["payment_id"]), ("Amount", money(approval["amount_cents"])), ("Address", approval["address"]), ("Reason", approval["note"])]) + "</div>")
        if status == APPROVED:
            parts.append(f'<form method="post" action="/ticket/{esc(item.ticket_id)}/execute"><input type="hidden" name="token" value="{esc(token)}">'
                         f'<button type="submit"{"" if tool_on else " disabled"}>Execute</button>'
                         f'{"" if tool_on else f" <span class=muted>Execute is unavailable: the {esc(item.tool)} tool is switched off. Set {esc(item.tool)} = true in config/actions.toml and restart this page.</span>"}</form>')
        return page(item.ticket_id, "".join(parts))
    if locked:
        parts.append('<div class="card">This proposal is in the senior queue. Start the page with <code>--role senior</code> as a senior approver to decide it.</div>')
        return page(item.ticket_id, "".join(parts))
    token_field = f'<input type="hidden" name="token" value="{esc(token)}">'
    fields = ['<label for="reason">Reason (required)</label><textarea id="reason" name="reason" rows="2" maxlength="300" required></textarea>']
    if call["action"] == "refund":
        if call.get("payment_id"):
            fields.insert(0, f'<input type="hidden" name="payment_id" value="{esc(call["payment_id"])}">'
                             f'<label for="amount">Refund amount in dollars (change it to edit)</label><input type="text" id="amount" name="amount" value="{esc("%.2f" % (call["amount_cents"] / 100))}" inputmode="decimal">')
        else:
            options = "".join(f'<option value="{esc(p["payment_id"])}">{esc(p["payment_id"])} · {esc(money(p["amount_cents"]))} · {esc(p["status"])}</option>' for p in payments)
            fields.insert(0, f'<label for="payment_id">Payment to refund</label><select id="payment_id" name="payment_id">{options}</select>'
                             f'<label for="amount">Refund amount in dollars (no amount was proposed; you set it)</label><input type="text" id="amount" name="amount" inputmode="decimal">')
    if call["action"] == "change_address":
        fields.insert(0, f'<label for="address">New address as street, city 12345 (change it to edit)</label><input type="text" id="address" name="address" value="{esc(call.get("address"))}" maxlength="200">')
    parts.append(f'<form method="post" action="/ticket/{esc(item.ticket_id)}/decide" class="card"><h2>Your decision</h2>{token_field}{"".join(fields)}'
                 '<button type="submit" name="verb" value="approve">Approve</button>'
                 + ('<button type="submit" name="verb" value="edit" class="edit">Approve with my change</button>'
                    if call["action"] == "change_address" or (call["action"] == "refund" and call.get("payment_id")) else "")
                 + '<button type="submit" name="verb" value="reject" class="reject">Reject</button></form>')
    return page(item.ticket_id, "".join(parts))


def message_page(title: str, message: str) -> str:
    return page(title, f'<h1>{esc(title)}</h1><p>{esc(message)}</p><p><a href="/">Back to the list</a></p>')