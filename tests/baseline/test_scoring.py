import ast
from pathlib import Path

import pytest

from src.baseline.scoring import CONSEQUENTIAL_ACTIONS, percentile, score_ticket, summarise

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
