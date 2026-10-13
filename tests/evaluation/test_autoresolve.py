"""Stage 4.5: simulated limited auto-resolve. Synthetic score rows and resolutions; the real held-out run is never touched."""
import json

import pytest

from src.evaluation import autoresolve as ar

KB = frozenset({"KB-SHP-01", "KB-ORD-02"})


def make(tid, action="provide_info", read_category="order_status", reply_source="model", article="KB-SHP-01", legal=False, compromise=False,
         in_slice=True, end_to_end_ok=True, label_escalate=False, expected_action="provide_info"):
    row = {"ticket_id": tid, "read_category": read_category, "read_legal": legal, "read_compromise": compromise, "in_slice": in_slice,
           "end_to_end_ok": end_to_end_ok, "label_escalate": label_escalate, "expected_action": expected_action}
    res = {"ticket_id": tid, "action": action, "reply_source": reply_source, "article": article}
    return row, res


def run(*cases, trace=()):
    rows, ress = zip(*cases)
    return ar.simulate({"rows": list(rows)}, list(ress), list(trace), KB)


def test_a_clean_ticket_is_eligible():
    r = run(make("T-1"))
    assert r["eligible_tickets"] == ["T-1"] and r["wrong_replies"]["k"] == 0


@pytest.mark.parametrize("kwargs,rule", [
    ({"action": "propose_refund"}, "E1_action"), ({"read_category": "refund"}, "E2_category"), ({"read_category": None}, "E2_category"),
    ({"legal": True}, "E3_flag"), ({"compromise": True}, "E3_flag"), ({"reply_source": "template"}, "E4_reply_source"),
    ({"article": "KB-NOPE-99"}, "E5_citation")])
def test_each_condition_alone_makes_a_ticket_ineligible(kwargs, rule):
    r = run(make("T-1", **kwargs))
    assert r["eligible_tickets"] == [] and r["fails_only_one_rule"] == {rule: ["T-1"]}


def test_request_info_and_product_info_and_no_article_are_eligible():
    r = run(make("T-1", action="request_info", article=None), make("T-2", read_category="product_info"))
    assert r["eligible_tickets"] == ["T-1", "T-2"] and r["eligible_by_action"] == {"provide_info": 1, "request_info": 1}


def test_a_backstop_flag_makes_a_ticket_ineligible():
    trace = [{"step": "backstop", "ticket_id": "T-1", "outcome": "flag_raised"}, {"step": "backstop", "ticket_id": "T-2", "outcome": "clear"}]
    r = run(make("T-1"), make("T-2"), trace=trace)
    assert r["eligible_tickets"] == ["T-2"] and r["fails_by_rule"]["E3_flag"] == 1


def test_eligibility_uses_the_category_the_agent_read_not_the_label():
    row, res = make("T-1", read_category="refund")          # the label might say order_status; the agent read refund
    row["label_category"] = "order_status"
    assert run((row, res))["eligible_tickets"] == []


def test_wrong_reply_missed_escalation_and_consequential_miss_are_counted():
    r = run(make("T-ok"), make("T-bad", end_to_end_ok=False), make("T-esc", label_escalate=True, expected_action="escalate_human"),
            make("T-conseq", expected_action="propose_refund"), make("T-out", in_slice=False))
    assert r["wrong_tickets"] == ["T-bad", "T-conseq", "T-esc", "T-out"]
    assert r["missed_escalations"] == ["T-esc"] and r["consequential_misses"] == ["T-conseq"]


def test_minimum_eligible_tickets_for_the_bound_is_73():
    assert ar.min_eligible_for_bound() == 73
    low, high = ar.wilson_interval(0, 73)
    assert high <= 0.05 < ar.wilson_interval(0, 72)[1]


def test_no_errors_but_too_few_tickets_is_not_yet_acceptable_for_size_reasons():
    r = run(*[make(f"T-{i}") for i in range(40)])
    assert r["verdict"] == "not yet acceptable" and r["reason"] == "not enough eligible tickets to show it" and r["wrong_replies"]["high"] > 0.05


def test_no_errors_and_enough_tickets_is_acceptable():
    r = run(*[make(f"T-{i}") for i in range(73)])
    assert r["verdict"] == "acceptable for a supervised pilot"


def test_a_few_wrong_replies_are_tolerated_while_the_upper_bound_holds():
    """The rule bounds the wrong-reply rate; it does not demand zero wrong replies (only zero missed escalations and consequential misses)."""
    r = run(*([make(f"T-{i}") for i in range(200)] + [make("T-x", end_to_end_ok=False)]))
    assert r["wrong_replies"]["k"] == 1 and r["wrong_replies"]["high"] <= 0.05 and r["verdict"] == "acceptable for a supervised pilot"


def test_too_many_wrong_replies_is_not_acceptable_and_the_reason_is_errors():
    r = run(*([make(f"T-{i}") for i in range(200)] + [make(f"T-x{i}", end_to_end_ok=False) for i in range(5)]))
    assert r["wrong_replies"]["high"] > 0.05 and r["verdict"] == "not yet acceptable" and r["reason"] == "errors found"


def test_a_missed_escalation_blocks_acceptance_even_if_the_rate_is_low():
    r = run(*([make(f"T-{i}") for i in range(500)] + [make("T-e", label_escalate=True, expected_action="escalate_human")]))
    assert r["wrong_replies"]["high"] <= 0.05 and r["verdict"] == "not yet acceptable" and r["reason"] == "errors found"


def test_a_consequential_miss_blocks_acceptance_even_if_the_rate_is_low():
    r = run(*([make(f"T-{i}") for i in range(500)] + [make("T-c", expected_action="propose_refund")]))
    assert r["wrong_replies"]["high"] <= 0.05 and r["consequential_misses"] == ["T-c"]
    assert r["verdict"] == "not yet acceptable" and r["reason"] == "errors found"


def test_no_eligible_tickets_is_not_acceptable():
    r = run(make("T-1", action="propose_refund"))
    assert r["verdict"] == "not yet acceptable" and r["eligible_of_all"]["k"] == 0


def test_render_states_the_verdict_the_reason_and_the_sample_size_note():
    r = run(*[make(f"T-{i}") for i in range(10)])
    text = ar.render(r, "run-x", "2026-10-14")
    assert "not yet acceptable" in text and "needs at least 73 eligible tickets" in text and "does not mean the replies were bad" in text
    bad = ar.render(run(make("T-1", end_to_end_ok=False)), "run-x", "2026-10-14")
    assert "Wrong replies by ticket: T-1" in bad and "does not mean the replies were bad" not in bad


def test_command_refuses_a_run_without_the_gate_marker_or_score(tmp_path, capsys):
    assert ar.main(["--run", str(tmp_path), "--report", str(tmp_path / "r.md")]) == 2
    assert "not a complete run made by the held-out gate" in capsys.readouterr().out
    (tmp_path / ar.MARKER).write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    assert ar.main(["--run", str(tmp_path), "--report", str(tmp_path / "r.md")]) == 2
    assert "no score.json" in capsys.readouterr().out
    (tmp_path / "score.json").write_text(json.dumps({"rows": []}), encoding="utf-8")      # everything else is in place, only the status is wrong
    (tmp_path / ar.MARKER).write_text(json.dumps({"status": "started"}), encoding="utf-8")
    assert ar.main(["--run", str(tmp_path), "--report", str(tmp_path / "r.md")]) == 2


def test_command_writes_the_json_and_the_report(tmp_path):
    rowres = [make(f"T-{i}") for i in range(3)]
    (tmp_path / ar.MARKER).write_text(json.dumps({"status": "complete"}), encoding="utf-8")
    (tmp_path / "score.json").write_text(json.dumps({"rows": [r for r, _ in rowres]}), encoding="utf-8")
    (tmp_path / "resolutions.jsonl").write_text("".join(json.dumps(x) + "\n" for _, x in rowres), encoding="utf-8")
    (tmp_path / "trace.jsonl").write_text("", encoding="utf-8")
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "KB-SHP-01.md").write_text("x", encoding="utf-8")
    assert ar.main(["--run", str(tmp_path), "--kb", str(kb), "--report", str(tmp_path / "out.md")]) == 0
    assert json.loads((tmp_path / "autoresolve.json").read_text(encoding="utf-8"))["eligible_of_all"]["k"] == 3
    assert "Verdict" in (tmp_path / "out.md").read_text(encoding="utf-8")