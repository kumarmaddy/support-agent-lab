import json

import pytest

from src.evaluation import review as rv


def write_run(path, rows):
    path.mkdir(parents=True)
    (path / "resolutions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def res(tid, source, reply, action="provide_info", reason="shipped_on_time"):
    return {"ticket_id": tid, "action": action, "reason": reason, "reply_source": source, "reply": reply,
            "facts": {"order_id": "O-1", "status": "shipped", "ignored": "x"}}


@pytest.fixture
def runs(tmp_path):
    ids = [f"T-{i:06d}" for i in range(1, 9)]
    model = write_run(tmp_path / "m", [res(t, "model" if i % 4 else "template", f"model reply {t}") for i, t in enumerate(ids, 1)])
    template = write_run(tmp_path / "t", [res(t, "template", f"template reply {t}") for t in ids])
    return model, template, ids


def test_only_model_written_replies_are_paired_and_both_sides_are_used(runs):
    items, key = rv.build_items(*runs[:2])
    assert len(items) == 6 and all(i["ticket_id"] in key for i in items)
    sides = {key[i["ticket_id"]]["model"] for i in items}
    assert sides == {"a", "b"}
    for i in items:
        assert i[key[i["ticket_id"]]["model"]].startswith("model reply") and "ignored" not in i["facts"]


def test_the_assignment_is_fixed_by_seed_and_the_sheet_does_not_say_which_side_is_which(runs):
    one, key_one = rv.build_items(*runs[:2], seed=1)
    again, _ = rv.build_items(*runs[:2], seed=1)
    other_seed, key_other = rv.build_items(*runs[:2], seed=2)
    assert one == again and key_one != key_other
    assert not any("model" in k or "template" in k for i in one for k in i)


def test_runs_that_disagree_or_cover_other_tickets_are_refused(runs, tmp_path):
    model, template, ids = runs
    with pytest.raises(SystemExit):
        rv.build_items(model, write_run(tmp_path / "x", [res(ids[0], "template", "t")]))
    changed = write_run(tmp_path / "y", [res(t, "template", "t", reason="shipped_late") for t in ids])
    with pytest.raises(SystemExit):
        rv.build_items(model, changed)
    not_template = write_run(tmp_path / "z", [res(t, "model", "t") for t in ids])
    with pytest.raises(SystemExit):
        rv.build_items(model, not_template)


def answers(*given):
    it = iter(given)
    return lambda prompt: next(it)


def test_ratings_are_saved_at_once_and_a_session_can_be_resumed(runs, tmp_path):
    items, _ = rv.build_items(*runs[:2])
    path = tmp_path / "r" / "ratings.jsonl"
    shown = []
    n = rv.run_review(items, path, answers("a", "n", "y", "", "", "q"), shown.append)      # rates one pair, then quits on the second
    assert n == 1 and len(rv.load_ratings(path)) == 1
    row = next(iter(rv.load_ratings(path).values()))
    assert row["better"] == "a" and row["a_fact_error"] is False and row["b_fact_error"] is True and row["a_awkward"] is False
    assert not any("model" in line.lower() and "reply" not in line.lower() for line in shown if "REPLY" in line)
    rest = rv.run_review(items, path, answers(*(["t", "", "", "", ""] * 10)), lambda s: None)
    assert rest == 5 and len(rv.load_ratings(path)) == 6


def test_an_invalid_choice_is_asked_again(runs, tmp_path):
    items, _ = rv.build_items(*runs[:2])
    rv.run_review(items[:1], tmp_path / "r.jsonl", answers("x", "?", "b", "", "", "", ""), lambda s: None)
    assert rv.load_ratings(tmp_path / "r.jsonl")[items[0]["ticket_id"]]["better"] == "b"


def test_the_report_joins_ratings_and_key(runs):
    items, key = rv.build_items(*runs[:2])
    sides = {i["ticket_id"]: key[i["ticket_id"]]["model"] for i in items}
    ids = list(sides)
    other = {"a": "b", "b": "a"}
    ratings = {}
    for n, tid in enumerate(ids):
        better = [sides[tid], sides[tid], other[sides[tid]], "t", sides[tid], other[sides[tid]]][n]
        ratings[tid] = {"ticket_id": tid, "better": better, "a_fact_error": False, "b_fact_error": False, "a_awkward": False, "b_awkward": False}
    ratings[ids[0]][f"{other[sides[ids[0]]]}_fact_error"] = True          # a fault on the template side of the first pair
    ratings[ids[1]][f"{sides[ids[1]]}_awkward"] = True                    # awkward wording on the model side of the second
    rep = rv.report(items, key, ratings)
    assert (rep["model_better"], rep["template_better"], rep["tie"]) == (3, 2, 1) and rep["pairs_rated"] == 6
    assert rep["fact_errors"]["template"]["flagged"] == 1 and rep["fact_errors"]["model"]["flagged"] == 0
    assert rep["awkward"]["model"]["flagged"] == 1 and rep["awkward"]["template"]["flagged"] == 0
    assert "model 3, template 2, tie 1" in rv.render(rep)


def test_an_empty_report_is_safe():
    rep = rv.report([], {}, {})
    assert rep["pairs_rated"] == 0 and "n/a" in rv.render(rep)


def test_make_never_overwrites_a_sheet(runs, tmp_path):
    args = ["make", "--model-run", str(runs[0]), "--template-run", str(runs[1]), "--name", "s", "--root", str(tmp_path / "reviews")]
    assert rv.main(args) == 0 and (tmp_path / "reviews" / "s" / "key.json").exists()
    with pytest.raises(SystemExit):
        rv.main(args)