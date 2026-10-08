import json

import pytest

from src.evaluation import compare as cp


def score(run_id, a_ok, b_ok, db="abc", model="m1", n_a=None):
    rows = [{"ticket_id": f"A{i}", "in_slice": True, "category_ok": True, "end_to_end_ok": ok, "action_ok": ok, "facts_ok": ok, "action": "x"}
            for i, ok in enumerate(a_ok)]
    rows += [{"ticket_id": f"B{i}", "in_slice": False, "category_ok": True, "handed_to_person": ok, "action": "route_to_human"} for i, ok in enumerate(b_ok)]
    return {"run_id": run_id, "rows": rows, "dataset": {"db_sha256": db}, "model": {"tag": model}, "reply_mode": "model", "prompts": {}, "code": {},
            "replies": {"template_fallbacks": 1, "drafts_by_model": 4}, "latency_ms": {"p50": 1}}


def test_sign_test_values():
    assert cp.sign_test(0, 0) == 1.0 and cp.sign_test(5, 5) == 1.0
    assert cp.sign_test(10, 0) == pytest.approx(2 / 1024) and cp.sign_test(1, 0) == 1.0
    assert cp.sign_test(0, 3) == pytest.approx(0.25)


def test_paired_counts_and_the_verdict():
    a = score("A", [True] * 12 + [False] * 3, [True] * 5)
    b = score("B", [True] * 12 + [False] * 3, [True] * 5)
    b["rows"][12]["end_to_end_ok"] = True                       # B gets one more right
    res = cp.compare(a, b)
    m = next(x for x in res["measures"] if x["measure"] == "Set A end to end")
    assert (m["a"], m["b"], len(m["only_a"]), len(m["only_b"])) == (12, 13, 0, 1) and m["p"] == 1.0
    assert "no reliable difference" in cp.render(res)


def test_a_clear_difference_is_called_and_configuration_differences_listed():
    a = score("A", [True] * 15, [True] * 5)
    b = score("B", [False] * 10 + [True] * 5, [True] * 5, model="m2")
    res = cp.compare(a, b)
    assert "A better" in cp.render(res) and "model" in res["configuration"]


def test_runs_on_other_data_or_other_tickets_are_refused():
    with pytest.raises(SystemExit):
        cp.compare(score("A", [True], [True]), score("B", [True], [True], db="other"))
    with pytest.raises(SystemExit):
        cp.compare(score("A", [True], [True]), score("B", [True, True], [True]))
    with pytest.raises(SystemExit):
        cp.compare(score("A", [True], [True], db=""), score("B", [True], [True], db=""))


def test_an_unscored_run_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        cp.load_score(tmp_path)


def test_main_prints_the_comparison(tmp_path, capsys):
    for name in "ab":
        (tmp_path / name).mkdir()
        (tmp_path / name / "score.json").write_text(json.dumps(score(name, [True] * 3, [True] * 2)), encoding="utf-8")
    assert cp.main([str(tmp_path / "a"), str(tmp_path / "b")]) == 0
    assert "paired comparison" in capsys.readouterr().out