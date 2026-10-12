"""Stage 3.6: the approval page: what it shows, what it refuses, and what a decision leaves behind."""
import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from src.actions.config import ActionsConfig
from src.actions.sandbox import open_sandbox
from src.agent.policy import parse_policy
from src.approval.app import ApprovalApp, parse_dollars, serve
from src.audit.log import query, verify
from tests.agent.test_handover import world  # noqa: F401  (the fixture)
from tests.approval.support_approval import ALL_ON, POLICY, build_run, get, headers, make_app, post


@pytest.fixture(scope="module")
def run_dir(world, tmp_path_factory):
    return build_run(world, tmp_path_factory.mktemp("app"))


@pytest.fixture
def app(run_dir, dev_dataset, tmp_path):
    return make_app(dev_dataset[0], run_dir, tmp_path)


@pytest.fixture
def senior(run_dir, dev_dataset, tmp_path):
    (tmp_path / "senior").mkdir()
    return make_app(dev_dataset[0], run_dir, tmp_path / "senior", role="senior")


def db(app):
    return open_sandbox(app.sandbox)


def call_of(app, ticket):
    return app.items[ticket].call


# ------------------------------------------------------------------ what it shows
def test_the_list_shows_the_senior_queue_first_and_marks_manual_items(app):
    r = get(app, "/")
    assert r.status == 200
    order = [m.group(1) for m in re.finditer(r'href="/ticket/(T-\d{6})"', r.body)]
    assert order[0] == "T-000149" and "T-000009" in order
    assert "manual" in r.body and "needs senior approver" in r.body and "A. Reviewer" in r.body


def test_the_detail_page_shows_the_reason_the_ticket_the_reply_and_the_rule(app):
    r = get(app, "/ticket/T-000029")
    assert r.status == 200
    for needle in ("Why this was proposed", "Customer ticket", "Draft reply", "DEFAULT-APPROVAL", "Approve", "Reject", 'name="token"'):
        assert needle in r.body
    assert "$" in r.body and "PM-" in r.body


def test_hostile_text_is_escaped_and_the_page_has_no_script(app):
    conn = db(app)
    evil = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    conn.execute("UPDATE tickets SET subject=?, body=? WHERE ticket_id='T-000001'", (evil, evil + '"><b>'))
    r = get(app, "/ticket/T-000001")
    assert "<script" not in r.body.lower() and "<img" not in r.body.lower() and "onerror=alert" not in r.body.replace("&amp;", "&").split("&lt;")[0]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in r.body and "<b>" not in r.body
    assert "style=" not in r.body and "<style" not in r.body.lower()


def test_security_headers_are_on_every_response(app):
    for r in (get(app, "/"), get(app, "/style.css"), get(app, "/ticket/T-999999")):
        csp = r.headers["Content-Security-Policy"]
        assert "default-src 'none'" in csp and "script-src" not in csp and "frame-ancestors 'none'" in csp
        assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Cache-Control"] == "no-store"
    assert get(app, "/style.css").content_type.startswith("text/css")


def test_unknown_paths_and_wrong_methods(app):
    assert get(app, "/ticket/T-999999").status == 404 and get(app, "/ticket/../etc").status == 404 and get(app, "/nope").status == 404
    assert app.handle("DELETE", "/", headers(app)).status == 405 and app.handle("PUT", "/ticket/T-000029", headers(app)).status == 405
    assert app.handle("GET", "/ticket/T-000029/decide", headers(app)).status == 405 and app.handle("POST", "/", headers(app)).status == 405


# ------------------------------------------------------------------ who may call it
@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1:1", "127.0.0.1", "", "localhost:9999"])
def test_a_request_for_another_host_is_refused(app, host):
    assert app.handle("GET", "/", {"Host": host}).status == 403


def test_localhost_by_name_is_accepted(app):
    assert app.handle("GET", "/", {"Host": f"localhost:{app.port}"}).status == 200


@pytest.mark.parametrize("fields", [{}, {"token": "wrong"}])
def test_a_post_without_the_right_token_does_nothing(app, fields):
    from urllib.parse import urlencode
    body = urlencode({"verb": "reject", "reason": "x", **fields}).encode()
    r = app.handle("POST", "/ticket/T-000011/decide", headers(app), body)
    assert r.status == 403 and db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def _body(app, verb="reject"):
    from urllib.parse import urlencode
    return urlencode({"token": app.token, "verb": verb, "reason": "x"}).encode()


def test_a_post_from_another_origin_is_refused(app):
    assert app.handle("POST", "/ticket/T-000011/decide", headers(app, Origin="http://evil.example"), _body(app)).status == 403
    assert db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert app.handle("POST", "/ticket/T-000011/decide", headers(app, Origin=f"http://127.0.0.1:{app.port}"), _body(app)).status == 200


@pytest.mark.parametrize("site", ["cross-site", "same-site", "bogus"])
def test_fetch_metadata_blocks_cross_site_posts_even_with_a_matching_origin(app, site):
    r = app.handle("POST", "/ticket/T-000011/decide", headers(app, **{"Sec-Fetch-Site": site, "Origin": f"http://127.0.0.1:{app.port}"}), _body(app))
    assert r.status == 403 and db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


@pytest.mark.parametrize("origin", ["null", "vscode-file://vscode-app", "http://evil.example"])
def test_a_same_origin_request_from_an_embedded_browser_is_accepted_whatever_origin_it_reports(app, origin):
    """An embedded browser (an editor's built-in pane) can report an Origin of its own; Sec-Fetch-Site says the request is same-origin."""
    r = app.handle("POST", "/ticket/T-000011/decide", headers(app, **{"Sec-Fetch-Site": "same-origin", "Origin": origin}), _body(app))
    assert r.status == 200 and db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_the_token_is_still_needed_for_a_same_origin_post(app):
    from urllib.parse import urlencode
    body = urlencode({"verb": "reject", "reason": "x"}).encode()
    assert app.handle("POST", "/ticket/T-000011/decide", headers(app, **{"Sec-Fetch-Site": "same-origin"}), body).status == 403


def test_the_refusal_says_what_it_saw_and_escapes_it(app):
    r = app.handle("POST", "/ticket/T-000011/decide", headers(app, Origin="<script>x</script>"), _body(app))
    assert r.status == 403 and "Origin: &lt;script&gt;x&lt;/script&gt;" in r.body and "<script>" not in r.body


def test_a_big_or_broken_body_is_refused(app):
    assert app.handle("POST", "/ticket/T-000011/decide", headers(app), b"x" * 20000).status == 413
    assert app.handle("POST", "/ticket/T-000011/decide", headers(app), b"\xff\xfe").status == 400


# ------------------------------------------------------------------ decisions
def test_approve_then_execute_changes_the_sandbox_once(app):
    r = post(app, "/ticket/T-000011/decide", verb="approve", reason="Order not yet dispatched")
    assert r.status == 200 and "Approved (AP-000001)" in r.body and "Execute" in r.body
    r = post(app, "/ticket/T-000011/execute")
    assert r.status == 200 and "Executed in the sandbox" in r.body
    assert db(app).execute("SELECT status FROM orders WHERE order_id=?", (call_of(app, "T-000011")["order_id"],)).fetchone()[0] == "cancelled"
    assert "Already executed" in post(app, "/ticket/T-000011/execute").body
    kinds = [e["event"] for e in query(app.audit.path, "T-000011")]
    assert kinds == ["approval", "execution", "execution"] and verify(app.audit.path).ok
    assert get(app, "/ticket/T-000011").body.count("executed") >= 1


def test_the_approval_records_who_why_and_which_rule(app):
    post(app, "/ticket/T-000011/decide", verb="approve", reason="Checked the order")
    row = db(app).execute("SELECT * FROM approvals").fetchone()
    assert (row["approver"], row["note"], row["rule_id"], row["status"]) == ("A. Reviewer", "Checked the order", "DEFAULT-APPROVAL", "approved")


def test_execute_is_refused_when_the_tool_is_off_or_nothing_is_approved(run_dir, dev_dataset, tmp_path):
    off = make_app(dev_dataset[0], run_dir, tmp_path, config=ActionsConfig())
    assert post(off, "/ticket/T-000011/execute").status == 409                                   # nothing approved yet
    post(off, "/ticket/T-000011/decide", verb="approve", reason="ok")
    page = get(off, "/ticket/T-000011").body
    assert "disabled" in page and "switched off" in page and "Set cancel = true in config/actions.toml" in page
    assert "button:disabled" in get(off, "/style.css").body                      # a disabled button must look disabled
    r = post(off, "/ticket/T-000011/execute")
    assert r.status == 422 and "action_disabled" in r.body
    assert db(off).execute("SELECT COUNT(*) FROM action_ledger").fetchone()[0] == 0


def test_reject_needs_a_reason_and_blocks_execution(app):
    assert post(app, "/ticket/T-000011/decide", verb="reject", reason="  ").status == 422
    assert post(app, "/ticket/T-000011/decide", verb="reject", reason="x" * 301).status == 422
    r = post(app, "/ticket/T-000011/decide", verb="reject", reason="Customer withdrew")
    assert r.status == 200 and "Rejected" in r.body
    assert post(app, "/ticket/T-000011/execute").status == 409
    assert [e["event"] for e in query(app.audit.path, "T-000011")] == ["rejection"]


def test_a_second_decision_is_refused(app):
    assert post(app, "/ticket/T-000011/decide", verb="approve", reason="ok").status == 200
    for verb in ("approve", "reject"):
        r = post(app, "/ticket/T-000011/decide", verb=verb, reason="again")
        assert r.status == 409 and "already been decided" in r.body
    assert db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_two_simultaneous_decisions_leave_one_approval(app):
    results, lock = [], threading.Lock()

    def work():
        r = post(app, "/ticket/T-000011/decide", verb="approve", reason="ok")
        with lock:
            results.append(r.status)
    threads = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [200] + [409] * 5 and db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 1


def test_a_missing_or_unknown_verb_is_refused(app):
    assert post(app, "/ticket/T-000011/decide", reason="x").status == 400
    assert post(app, "/ticket/T-000011/decide", verb="delete", reason="x").status == 400


def test_a_proposal_with_no_write_tool_cannot_be_decided_here(app):
    assert post(app, "/ticket/T-000009/decide", verb="approve", reason="ok").status == 409
    assert "no write tool" in get(app, "/ticket/T-000009").body


# ------------------------------------------------------------------ edits
def test_an_edited_refund_is_rechecked_saved_as_labelled_data_and_audited(app):
    call = call_of(app, "T-000029")
    smaller = call["amount_cents"] - 100
    assert smaller > 0
    dollars = "%.2f" % (smaller / 100)
    r = post(app, "/ticket/T-000029/decide", verb="approve", reason="Agreed a goodwill split", payment_id=call["payment_id"], amount=dollars)
    assert r.status == 422 and "Approve with my change" in r.body                                # approve means as proposed
    r = post(app, "/ticket/T-000029/decide", verb="edit", reason="Agreed a goodwill split", payment_id=call["payment_id"], amount=dollars)
    assert r.status == 200
    assert db(app).execute("SELECT amount_cents FROM approvals").fetchone()[0] == smaller
    line = json.loads(app.edits_file.read_text(encoding="utf-8").splitlines()[0])
    assert (line["field"], line["proposed"], line["final"], line["reason"], line["approver"]) == ("amount_cents", call["amount_cents"], smaller, "Agreed a goodwill split", "A. Reviewer")
    assert [e["event"] for e in query(app.audit.path, "T-000029")] == ["approval", "edit"]


def test_an_edit_that_changes_nothing_is_refused(app):
    call = call_of(app, "T-000029")
    r = post(app, "/ticket/T-000029/decide", verb="edit", reason="x", payment_id=call["payment_id"], amount="%.2f" % (call["amount_cents"] / 100))
    assert r.status == 422 and "Nothing was changed" in r.body and not app.edits_file.exists()


def test_a_refund_above_the_payment_is_denied_by_the_policy(app):
    call = call_of(app, "T-000029")
    r = post(app, "/ticket/T-000029/decide", verb="edit", reason="x", payment_id=call["payment_id"], amount="%.2f" % (call["amount_cents"] / 100 + 5))
    assert r.status == 422 and "DENY-REFUND-EXCEEDS-PAYMENT" in r.body
    assert db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


@pytest.mark.parametrize("amount", ["", "abc", "0", "-5", "1.234", "1e3", "100000.01", "nan"])
def test_bad_amounts_are_refused(app, amount):
    call = call_of(app, "T-000029")
    assert post(app, "/ticket/T-000029/decide", verb="edit", reason="x", payment_id=call["payment_id"], amount=amount).status == 422


def test_parse_dollars():
    assert parse_dollars("119.99") == 11999 and parse_dollars("$1,250.5") == 125050 and parse_dollars(" 5 ") == 500
    with pytest.raises(ValueError):
        parse_dollars("12.345")


def test_an_item_refund_has_no_amount_so_the_approver_chooses_the_payment_and_amount(app):
    page = get(app, "/ticket/T-000046").body
    assert "<select" in page and "no amount was proposed" in page and "Approve with my change" not in page
    order = call_of(app, "T-000046")["order_id"]
    payment = db(app).execute("SELECT payment_id, amount_cents FROM payments WHERE order_id=? ORDER BY payment_id", (order,)).fetchone()
    assert post(app, "/ticket/T-000046/decide", verb="approve", reason="x", payment_id="PM-999999", amount="5.00").status == 422
    r = post(app, "/ticket/T-000046/decide", verb="approve", reason="Damaged item confirmed", payment_id=payment["payment_id"], amount="5.00")
    assert r.status == 200 and not app.edits_file.exists()
    assert db(app).execute("SELECT amount_cents FROM approvals").fetchone()[0] == 500


def test_an_address_edit_is_used_by_the_tool(app):
    new = "88 Birch Court, Helena 59601"
    assert post(app, "/ticket/T-000001/decide", verb="edit", reason="Customer corrected the address by phone", address=new).status == 200
    assert post(app, "/ticket/T-000001/execute").status == 200
    order = call_of(app, "T-000001")["order_id"]
    row = db(app).execute("SELECT a.line1, a.city FROM orders o JOIN addresses a ON a.address_id=o.shipping_address_id WHERE o.order_id=?", (order,)).fetchone()
    assert (row["line1"], row["city"]) == ("88 Birch Court", "Helena")
    assert "88 Birch Court" not in app.audit.path.read_text(encoding="utf-8")                      # redacted in the audit log
    assert "88 Birch Court" in app.edits_file.read_text(encoding="utf-8")                           # kept in the labelled data


# ------------------------------------------------------------------ roles
def test_a_standard_approver_cannot_decide_a_senior_proposal(app, senior):
    assert "needs a senior approver" not in get(app, "/ticket/T-000149").body or "senior queue" in get(app, "/ticket/T-000149").body
    assert "Approve</button>" not in get(app, "/ticket/T-000149").body
    assert post(app, "/ticket/T-000149/decide", verb="approve", reason="ok").status == 403
    assert db(app).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert post(senior, "/ticket/T-000149/decide", verb="approve", reason="Duplicate confirmed on the payment record").status == 200


def test_a_value_that_moves_a_case_into_the_senior_queue_needs_a_senior(run_dir, dev_dataset, tmp_path):
    low = parse_policy(b'[engine]\nversion="t"\nauto_execute_enabled=false\n[[rule]]\nid="SENIOR-ANY-REFUND"\noutcome="require_approval"\nreason="x"\nqueue="senior"\n[rule.when]\naction=["refund"]\namount_cents_gte=1\n')
    standard = make_app(dev_dataset[0], run_dir, tmp_path, policy=low)
    call = call_of(standard, "T-000029")
    r = post(standard, "/ticket/T-000029/decide", verb="approve", reason="x", payment_id=call["payment_id"], amount="%.2f" % (call["amount_cents"] / 100))
    assert r.status == 403 and "senior approver" in r.body and db(standard).execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0


def test_setup_errors():
    with pytest.raises(ValueError):
        ApprovalApp(".", "x", "A", "admin", ALL_ON, POLICY)
    with pytest.raises(ValueError):
        ApprovalApp(".", "x", " ", "standard", ALL_ON, POLICY)


# ------------------------------------------------------------------ a real server
def test_the_server_binds_only_to_loopback_and_answers_over_a_socket(app):
    with pytest.raises(ValueError):
        serve(app, host="0.0.0.0")
    server = serve(app, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{app.port}"
        with urllib.request.urlopen(base + "/") as r:
            html = r.read().decode()
            assert r.status == 200 and "Content-Security-Policy" in r.headers and "Server" in r.headers and "Python" not in r.headers["Server"]
        with urllib.request.urlopen(base + "/ticket/T-000011") as r:
            token = re.search(r'name="token" value="([^"]+)"', r.read().decode()).group(1)
        data = ("token=" + token + "&verb=approve&reason=ok").encode()
        with urllib.request.urlopen(urllib.request.Request(base + "/ticket/T-000011/decide", data=data)) as r:
            assert r.status == 200 and "Approved" in r.read().decode()
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(urllib.request.Request(base + "/ticket/T-000011/decide", data=b"token=bad&verb=reject&reason=x"))
        assert err.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_the_queue_recorded_in_the_run_is_enforced_even_if_the_policy_has_since_changed(run_dir, dev_dataset, tmp_path):
    none = parse_policy(b'[engine]\nversion="t"\nauto_execute_enabled=false\n')                 # no rules: everything falls to the default queue
    standard = make_app(dev_dataset[0], run_dir, tmp_path, policy=none)
    assert standard.items["T-000149"].queue == "senior"
    assert post(standard, "/ticket/T-000149/decide", verb="approve", reason="ok").status == 403
    assert post(standard, "/ticket/T-000149/decide", verb="reject", reason="ok").status == 403