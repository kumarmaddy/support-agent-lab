import pytest

from src.evaluation import retrieval
from src.kb.retrieve import build_index
from tests.kb.test_retrieve import SMALL


def test_evaluate_counts_hits_ranks_and_unanswerable_scores():
    index = build_index(SMALL)
    result = retrieval.evaluate(index, [
        ("returns", "can I return it within 30 days", {"KB-A"}),
        ("sizing", "do sizes run small", {"KB-A"}),          # wrong on purpose: required article is not the best match
        ("other", "zebra quartz", set()),
    ])
    row = result["by_category"]["returns"]
    assert (row["n"], row["hit1"], row["hitk"], row["rr"]) == (1, 1, 1, 1.0)
    assert result["by_category"]["sizing"]["hit1"] == 0
    assert result["no_answer_scores"] == [0.0] and len(result["misses"]) == 1


def test_render_has_an_all_row_and_refuses_heldout(tmp_path):
    index = build_index(SMALL)
    text = retrieval.render(retrieval.evaluate(index, [("returns", "return within 30 days", {"KB-A"})]), 3)
    assert "ALL" in text and "hit@1" in text
    with pytest.raises(SystemExit):
        retrieval.main(["--db", str(tmp_path / "heldout" / "support.db")])


# ------------------------------------------------------------------ probes
def test_threshold_table_trades_answers_against_wrong_answers():
    rows = [{"id": "a", "answerable": True, "required": {"K1"}, "ranked": ["K1"], "best": 9.0},
            {"id": "b", "answerable": True, "required": {"K1"}, "ranked": ["K2"], "best": 3.0},
            {"id": "c", "answerable": False, "required": set(), "ranked": ["K1"], "best": 5.0}]
    table = {row["threshold"]: row for row in retrieval.threshold_table(rows, points=3)}
    assert table[3.0]["right"] == 0.5 and table[3.0]["wrong"] == 0.5 and table[3.0]["answers_unanswerable"] == 1.0
    assert table[9.0]["right"] == 0.5 and table[9.0]["wrong"] == 0.0 and table[9.0]["answers_unanswerable"] == 0.0


def test_probe_file_is_well_formed_and_points_at_real_articles():
    from pathlib import Path
    from src.kb.articles import load_articles
    probes = retrieval.load_probes(Path("data/probes/knowledge_questions.jsonl"))
    ids = [p["id"] for p in probes]
    articles = load_articles()
    assert len(ids) == len(set(ids)) and len(probes) == 48
    assert all(set(p["required_kb_ids"]) <= set(articles) for p in probes)
    assert all(bool(p["required_kb_ids"]) == p["answerable"] for p in probes)
    assert {i for p in probes for i in p["required_kb_ids"]} == set(articles)   # every article has a probe


def test_evaluate_probes_reports_best_score_and_ranking():
    result = retrieval.evaluate_probes(build_index(SMALL), [{"id": "p", "question": "return within 30 days", "required_kb_ids": ["KB-A"], "answerable": True}])
    row = result["rows"][0]
    assert row["ranked"][0] == "KB-A" and row["best"] > 0