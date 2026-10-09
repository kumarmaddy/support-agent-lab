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