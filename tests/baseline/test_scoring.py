import ast
from pathlib import Path

import pytest

import math

from src.baseline.scoring import CONSEQUENTIAL_ACTIONS, escalation_matrix, percentile, score_ticket, summarise, wilson_interval

SRC = Path(__file__).resolve().parents[2] / "src" / "baseline"


def label(**kw):
    base = {"ticket_id": "T-1", "scenario_id": "S01", "difficulty": "standard", "category": "refund",
            "expected_actions": ["propose_refund"], "expected_escalate": False, "required_kb_ids": ["KB-REF-02"]}
    return {**base, **kw}


def result(**kw):
    base = {"ticket_id": "T-1", "practice": False, "position": 1, "seconds": 60.0, "pauses": 0, "category": "refund",
            "actions": ["propose_refund"], "kb_ids": ["KB-REF-02"], "started_at": "2026-10-08T09:00:00"}
    return {**base, **kw}


def test_perfect_answer_scores_everything_right():
    row = score_ticket(result(), label())
    assert all(row[k] for k in ("category_ok", "actions_ok", "escalate_ok", "consequential_ok", "kb_ok"))


def test_each_measure_fails_independently():
    assert not score_ticket(result(category="other"), label())["category_ok"]
    assert not score_ticket(result(actions=["propose_refund", "provide_info"]), label())["actions_ok"]
    wrong = score_ticket(result(actions=["escalate_human"]), label())
    assert not wrong["escalate_ok"] and not wrong["consequential_ok"]
    assert not score_ticket(result(kb_ids=[]), label())["kb_ok"]
    extra = score_ticket(result(kb_ids=["KB-REF-02", "KB-RET-01"]), label())
    assert extra["kb_ok"]                                         # citing more than required is not an error here


def test_extra_information_action_is_not_a_consequential_error():
    row = score_ticket(result(actions=["propose_refund", "provide_info"]), label())
    assert row["consequential_ok"] and not row["actions_ok"]
    assert "provide_info" not in CONSEQUENTIAL_ACTIONS


def test_percentile_is_nearest_rank():
    assert percentile([10, 20, 30, 40, 50], 90) == 50
    assert percentile([10, 20, 30, 40, 50], 50) == 30
    assert percentile([7], 90) == 7


def test_summary_excludes_practice_and_reports_learning_effect():
    results = [result(ticket_id=f"T-{i}", position=i, seconds=float(100 - i * 10)) for i in range(1, 7)]
    results.append(result(ticket_id="T-99", position=None, practice=True, seconds=999.0))
    labels = {f"T-{i}": label(ticket_id=f"T-{i}") for i in [*range(1, 7), 99]}
    summary = summarise(results, labels)
    assert summary["tickets"] == 6 and summary["time"]["max"] == 90.0
    assert summary["learning"]["first_third_median"] > summary["learning"]["last_third_median"]
    assert summary["accuracy"]["actions_ok"] == 1.0 and summary["misses"] == []


def test_summary_lists_misses():
    results = [result(), result(ticket_id="T-2", position=2, category="other")]
    labels = {"T-1": label(), "T-2": label(ticket_id="T-2", scenario_id="S02")}
    assert summarise(results, labels)["misses"] == [{"ticket_id": "T-2", "scenario_id": "S02"}]


def test_summary_needs_scored_results():
    with pytest.raises(ValueError):
        summarise([result(practice=True, position=None)], {"T-1": label()})


# ------------------------------------------------------------------ added at the exit review: intervals, escalation, detail
def test_wilson_interval_known_values():
    low, high = wilson_interval(37, 40)
    assert 0.80 < low < 0.81 and 0.97 < high < 0.98            # 92.5% of 40: about 80.1% to 97.4%
    assert wilson_interval(40, 40)[1] == 1.0 and wilson_interval(0, 40)[0] == 0.0
    assert all(math.isnan(x) for x in wilson_interval(0, 0))
    assert wilson_interval(37, 40)[0] < wilson_interval(370, 400)[0]  # more tickets, narrower interval


def test_escalation_matrix_counts_all_four_cells():
    rows = [score_ticket(result(actions=a), label(expected_escalate=e, expected_actions=ea))
            for a, e, ea in ((["escalate_human"], True, ["escalate_human"]),      # true positive
                             (["escalate_human"], False, ["provide_info"]),       # false positive
                             (["provide_info"], True, ["escalate_human"]),        # false negative
                             (["provide_info"], False, ["provide_info"]))]        # true negative
    m = escalation_matrix(rows)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == 0.5 and m["recall"] == 0.5
    assert math.isnan(escalation_matrix(rows[3:])["recall"])   # nothing should be escalated: recall undefined


def test_score_ticket_keeps_detail_for_review():
    row = score_ticket(result(category="other", actions=["propose_refund"], kb_ids=[]), label(required_kb_ids=["KB-REF-02"]))
    assert row["handled_category"] == "other" and row["handled_actions"] == ["propose_refund"]
    assert row["missing_kb"] == ["KB-REF-02"] and row["consequential_relevant"] is True


def test_summary_lists_every_failed_measure_as_a_disagreement():
    results = [result(), result(ticket_id="T-2", position=2, kb_ids=[]),
               result(ticket_id="T-3", position=3, actions=["provide_info"]),
               result(ticket_id="T-4", position=4, actions=["provide_info"], category="refund")]       # missed refund
    labels = {"T-1": label(), "T-2": label(ticket_id="T-2"), "T-3": label(ticket_id="T-3", expected_actions=["provide_info"]),
              "T-4": label(ticket_id="T-4")}
    summary = summarise(results, labels)
    assert [d["ticket_id"] for d in summary["disagreements"]] == ["T-2", "T-4"]    # knowledge-base miss; missed refund
    assert [m["ticket_id"] for m in summary["misses"]] == ["T-4"]                  # the older list: category or actions only
    assert summary["counts"]["kb_ok"] == {"correct": 3, "n": 4}
    # T-3 involves no consequential action either way; T-4 expected one and the handler took none, so it counts as relevant
    assert summary["consequential_relevant"] == {"correct": 2, "n": 3}


# ------------------------------------------------------------------ the handler must not be able to see labels
@pytest.mark.parametrize("module", ["session.py", "lookups.py"])
def test_interactive_modules_cannot_reach_labels(module):
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "labels" not in (node.module or "") and all("labels" not in a.name for a in node.names)
        if isinstance(node, ast.Import):
            assert all("labels" not in a.name for a in node.names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and not node.value.startswith(" "):
            assert "labels.jsonl" not in node.value and "data/labels" not in node.value