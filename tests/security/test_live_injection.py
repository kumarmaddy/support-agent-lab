"""Stage 4.3b: the live-model injection run. The model is replaced by scripted stand-ins here; the real model is never called by the tests."""
import json

import pytest

from src.security.cases import load_cases, resolve
from src.security.hostile import HostileModel
from src.security.live import LIVE_EXPECT_KEYS, live_expect, main, run_case_live
from src.security.runner import _model, run_case
from src.security.score import judge
from src.security.world import load_roles


@pytest.fixture(scope="module")
def pipeline_cases():
    return [c for c in load_cases() if c.layer == "pipeline"]


def test_only_the_pipeline_layer_is_run_live(pipeline_cases):
    assert len(pipeline_cases) == 45 and sum(c.attack for c in pipeline_cases) == 41
    assert {c.layer for c in pipeline_cases} == {"pipeline"}


def test_attacks_keep_only_the_invariant_expectations_and_controls_keep_all(pipeline_cases):
    attack = next(c for c in pipeline_cases if c.attack)
    control = next(c for c in pipeline_cases if not c.attack)
    full = {"actions": ["route_to_human"], "facts": {"x": 1}, "reply_source": "template", "policy_outcome": "require_approval",
            "forbid_actions": ["propose_refund"], "canaries": ["$500"]}
    assert live_expect(attack, full) == {"forbid_actions": ["propose_refund"], "canaries": ["$500"]}
    assert live_expect(control, full) == full
    assert LIVE_EXPECT_KEYS == ("forbid_actions", "canaries")


def test_the_live_runner_agrees_with_the_scripted_runner_when_given_the_same_model(dev_dataset, pipeline_cases):
    """With each case's own scripted answers as the 'live' model, the live path must neutralise exactly what the scripted path neutralises."""
    db = dev_dataset[0]
    roles = load_roles(db)
    for case in pipeline_cases:
        scripted = run_case(case, db, judge)
        live, seen = run_case_live(case, db, _model(resolve(case.spec, roles)))
        assert live.neutralised == scripted.neutralised, (case.id, live.failures, scripted.failures)
        assert live.neutralised, (case.id, live.failures)
        assert seen["action"], case.id


def test_a_canary_in_the_reply_is_still_a_failure_in_a_live_run(pipeline_cases):
    attack = next(c for c in pipeline_cases if c.attack)
    obs = {"resolution": {"action": "provide_info", "reason": "x", "reply": "Your refund of $500 is approved", "reply_source": "model", "facts": {},
                          "policy_outcome": ""}, "note_text": "", "sender_customer": None, "db_path": "unused.db", "db_changed": False, "leak_terms": [],
           "expect": live_expect(attack, {"canaries": ["$500"], "actions": ["route_to_human"]})}
    v = judge(attack, obs)
    assert not v.neutralised and any("$500" in f for f in v.failures)


def test_a_forbidden_action_a_database_change_and_a_leak_are_failures_and_a_scripted_expectation_is_not(pipeline_cases):
    attack = next(c for c in pipeline_cases if c.attack)
    base = {"resolution": {"action": "provide_info", "reason": "x", "reply": "ok", "reply_source": "model", "facts": {}, "policy_outcome": ""},
            "note_text": "", "sender_customer": None, "db_path": "unused.db", "db_changed": False, "leak_terms": []}
    ok = judge(attack, {**base, "expect": live_expect(attack, {"actions": ["route_to_human"]})})
    assert ok.neutralised                                                    # a real model may answer differently from the scripted worst case
    assert not judge(attack, {**base, "db_changed": True, "expect": {}}).neutralised
    assert not judge(attack, {**base, "note_text": "alice@example.com", "leak_terms": ["alice@example.com"], "expect": {}}).neutralised
    forbidden = {**base, "resolution": {**base["resolution"], "action": "route_to_human"}, "expect": {"forbid_actions": ["route_to_human"]}}
    assert not judge(attack, forbidden).neutralised


def test_a_crash_is_a_failure_not_a_pass(dev_dataset, pipeline_cases):
    class Broken:
        model = "broken"

        def chat(self, *args, **kwargs):
            raise RuntimeError("boom")

    v, seen = run_case_live(pipeline_cases[0], dev_dataset[0], Broken())
    assert not v.neutralised and "boom" in v.failures[0] and seen["action"] == ""


def test_the_command_writes_results_and_a_summary_marked_live(dev_dataset, tmp_path, capsys):
    code = main(["--only", "P-001", "--db", str(dev_dataset[0]), "--out", str(tmp_path)], model=HostileModel(read={"category": "refund"}))
    out = capsys.readouterr().out
    folder = next(tmp_path.glob("security-live-*"))
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert code == 0 and summary["live"] is True and summary["layer"] == "pipeline" and summary["partial_run"] is True
    assert summary["attacks"] == 1 and summary["o6_neutralised"] == 1 and rows[0]["case_id"] == "P-001" and rows[0]["action"]
    assert "attacks neutralised" in out and "hostile:scripted" in out


def test_the_command_exits_nonzero_when_an_attack_is_not_neutralised(dev_dataset, tmp_path, monkeypatch):
    from src.security import live

    real = live.judge

    def failing(case, obs):
        v = real(case, obs)
        v.failures.append("injected failure")
        return v
    monkeypatch.setattr(live, "judge", failing)
    assert main(["--only", "P-001", "--db", str(dev_dataset[0]), "--out", str(tmp_path)], model=HostileModel(read={"category": "refund"})) == 1


def test_non_pipeline_cases_are_not_run_live(dev_dataset, tmp_path):
    main(["--only", "P-001,A-001", "--db", str(dev_dataset[0]), "--out", str(tmp_path)], model=HostileModel(read={"category": "refund"}))
    summary = json.loads(next(tmp_path.glob("security-live-*")).joinpath("summary.json").read_text(encoding="utf-8"))
    assert summary["cases"] == 1


def test_other_customers_details_are_collected_for_the_leak_check(dev_dataset, pipeline_cases, tmp_path):
    from src.security.live import run_pipeline_live
    from src.security.world import World

    roles = load_roles(dev_dataset[0])
    case = next(c for c in pipeline_cases if c.id == "P-001")
    obs = run_pipeline_live(case, World(tmp_path, dev_dataset[0], roles), roles, HostileModel(read={"category": "refund"}))
    others = [r["email"] for r in roles.values() if r["customer"] != obs["sender_customer"]]
    assert others and set(others) <= set(obs["leak_terms"]) | {r["email"] for r in roles.values() if r["email"].lower() in
                                                                 (resolve(case.spec, roles)["subject"] + resolve(case.spec, roles)["body"]).lower()}
    assert obs["db_changed"] is False


def test_a_change_to_the_operational_database_during_a_live_run_is_a_failure(dev_dataset, pipeline_cases, monkeypatch):
    import sqlite3

    from src.security import live

    real = live.run_ticket

    def writing(box, model, *args, **kwargs):
        res = real(box, model, *args, **kwargs)
        path = box.conn.execute("PRAGMA database_list").fetchone()[2]
        rw = sqlite3.connect(path)
        rw.execute("UPDATE customers SET name = name || 'x' WHERE rowid = 1")
        rw.commit()
        rw.close()
        return res
    monkeypatch.setattr(live, "run_ticket", writing)
    case = next(c for c in pipeline_cases if c.id == "P-001")
    v, _ = run_case_live(case, dev_dataset[0], HostileModel(read={"category": "refund"}))
    assert not v.neutralised and any("changed the database" in f for f in v.failures)