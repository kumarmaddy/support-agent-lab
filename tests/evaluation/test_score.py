import json
from copy import deepcopy

import pytest

from src.agent.pipeline import internal_guidance, run_ticket
from src.agent.prompting import load_prompt
from src.agent.tools import Toolbox
from src.agent.tracing import TraceWriter
from src.evaluation import score as sc
from src.evaluation.slice import in_slice
from tests.agent.support import ScriptedModel, oracle_read

READ, REPLY = load_prompt("read_ticket", "v3"), load_prompt("reply", "v1")


@pytest.fixture(scope="module")
def world(dev_dataset, articles):
    db, _, labels = dev_dataset
    box = Toolbox.from_path(db)
    yield box, labels, internal_guidance(articles)
    box.conn.close()


def make_run(world, tmp_path, name="run-t", reader=None, mode="template"):
    box, labels, internal = world
    current = {}
    model = ScriptedModel(read=lambda s, u, seed: (reader or (lambda lab: oracle_read({lab["ticket_id"]: lab}, box, lab["ticket_id"])))(current["label"]))
    with TraceWriter(tmp_path, name, {"model": {"tag": "scripted"}, "reply_mode": mode}) as writer:
        for lab in labels:
            current["label"] = lab
            writer.write(run_ticket(box, model, READ, REPLY, internal, lab["ticket_id"], reply_mode=mode))
    return tmp_path / name


def test_a_perfect_reader_scores_every_in_slice_ticket_and_hands_over_the_rest(world, tmp_path):
    run = make_run(world, tmp_path)
    s = sc.score_run(run, world[1])
    assert s["tickets"] == 150 and s["set_a"]["tickets"] == 35 and s["set_b"]["tickets"] == 115
    assert s["set_a"]["end_to_end"]["successes"] == 35, s["misses"]
    assert s["set_b"]["wrongly_answered"]["successes"] == 0 and s["set_b"]["handed_to_person"]["successes"] == 115
    assert s["read"]["category_agreement"]["successes"] == 150 and s["read"]["valid_readings"]["n"] == 150
    assert s["misses"] == []
    assert sc.render(s).startswith("run run-t")


def test_a_wrong_category_is_counted_and_an_answered_out_of_slice_ticket_is_a_miss(world, tmp_path):
    box, labels, _ = world
    out = next(lab for lab in labels if not in_slice(lab) and lab["priority_attributes"]["chargeback_or_legal_threat"] is False
               and box.get_ticket(lab["ticket_id"]).data and lab["referenced_order_id"] and lab["order_identifiable"])

    def reader(lab):
        read = oracle_read({lab["ticket_id"]: lab}, box, lab["ticket_id"])
        if lab["ticket_id"] == out["ticket_id"]:
            read["category"] = "order_status"
        return read
    run = make_run(world, tmp_path, "run-w", reader)
    s = sc.score_run(run, labels)
    assert s["read"]["category_agreement"]["successes"] == 149
    answered = [m for m in s["misses"] if not m["in_slice"]]
    assert [m["ticket_id"] for m in answered] == [out["ticket_id"]] and s["set_b"]["wrongly_answered"]["successes"] == 1


def test_a_wrong_fact_or_article_fails_end_to_end(world):
    _, labels, _ = world
    label = next(lab for lab in labels if in_slice(lab) and lab["expected_facts"].get("tracking_no"))
    good = {"ticket_id": label["ticket_id"], "action": "provide_info", "reason": "shipped_on_time", "article": label["required_kb_ids"][0],
            "reply_source": "model", "facts": {"status": "shipped", "promised_date": label["expected_facts"]["promised_date"],
                                               "carrier": label["expected_facts"]["carrier"], "tracking_no": label["expected_facts"]["tracking_no"],
                                               "last_status": label["expected_facts"]["last_status"]}}
    assert sc.score_ticket(good, label, label["category"])["end_to_end_ok"] if label["expected_actions"][0] == "provide_info" else True
    bad_fact = deepcopy(good)
    bad_fact["facts"]["tracking_no"] = "TR000000000000"
    bad_article = {**good, "article": "KB-SHP-02" if good["article"] != "KB-SHP-02" else "KB-SHP-01"}
    assert not sc.score_ticket(bad_fact, label, label["category"])["facts_ok"]
    assert not sc.score_ticket(bad_article, label, label["category"])["article_ok"]
    assert not sc.score_ticket({**good, "facts": {}}, label, label["category"])["facts_ok"]


def test_candidate_orders_must_match_the_labelled_set(world):
    _, labels, _ = world
    label = next(lab for lab in labels if "candidate_order_ids" in lab["expected_facts"])
    ids = label["expected_facts"]["candidate_order_ids"]
    res = {"ticket_id": label["ticket_id"], "action": "request_info", "reason": "needs_order_number", "article": "KB-ORD-02",
           "reply_source": "model", "facts": {"candidates": [{"order_id": i} for i in ids]}}
    assert sc.facts_agree(res, label)
    assert not sc.facts_agree({**res, "facts": {"candidates": [{"order_id": ids[0]}]}}, label)


def test_the_held_out_split_is_refused(world, tmp_path):
    _, labels, _ = world
    with pytest.raises(SystemExit):
        sc.check_labels([{**labels[0], "split": "heldout"}], tmp_path / "labels.jsonl")
    with pytest.raises(SystemExit):
        sc.check_labels(labels, tmp_path / "heldout" / "labels.jsonl")
    sc.check_labels(labels, tmp_path / "labels.jsonl")


def test_a_run_with_unlabelled_tickets_is_refused(world, tmp_path):
    run = make_run(world, tmp_path, "run-u")
    with pytest.raises(SystemExit):
        sc.score_run(run, world[1][1:])


def test_main_writes_score_json_beside_the_run(world, tmp_path, capsys):
    run = make_run(world, tmp_path, "run-m")
    labels = tmp_path / "labels.jsonl"
    labels.write_text("\n".join(json.dumps(x) for x in world[1]), encoding="utf-8")
    assert sc.main([str(run), "--labels", str(labels)]) == 0
    assert json.loads((run / "score.json").read_text(encoding="utf-8"))["set_a"]["end_to_end"]["n"] == 35
    assert "Set A" in capsys.readouterr().out


def test_wilson_interval_is_reported_and_n_zero_is_safe():
    assert sc.rate(35, 35)["low"] > 0.9 and sc.rate(0, 0)["rate"] is None and sc.fmt(sc.rate(0, 0)) == "n/a"


def test_the_agent_package_does_not_import_the_evaluation_package():
    import ast
    from pathlib import Path
    for path in Path("src/agent").glob("*.py"):
        names = [n.module for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.ImportFrom) and n.module]
        assert not any(m.startswith("src.evaluation") for m in names), path


def test_a_far_deadline_is_not_a_fact_the_information_reply_must_carry(world):
    _, labels, _ = world
    far = next(lab for lab in labels if lab["scenario_id"] == "S03" and lab["expected_actions"] == ["provide_info"] and "deadline_date" in lab["expected_facts"])
    res = {"action": "provide_info", "reason": "order_processing", "facts": {"status": "processing", "promised_date": far["expected_facts"]["promised_date"]}}
    assert sc.facts_agree(res, far)
    near = next(lab for lab in labels if "deadline_date" in lab["expected_facts"] and lab["expected_escalate"])
    handover = {"action": "escalate_human", "reason": "delivery_deadline_cannot_be_guaranteed",
                "facts": {"status": "processing", "promised_date": near["expected_facts"]["promised_date"], "deadline_date": "2020-01-01"}}
    assert not sc.facts_agree(handover, near)


def test_end_to_end_needs_action_escalation_article_and_facts_together(world):
    _, labels, _ = world
    label = next(lab for lab in labels if in_slice(lab) and lab["expected_actions"] == ["provide_info"] and lab["expected_facts"].get("tracking_no"))
    f = label["expected_facts"]
    good = {"ticket_id": label["ticket_id"], "action": "provide_info", "reason": "shipped_on_time", "article": label["required_kb_ids"][0],
            "reply_source": "model", "facts": {"status": f["order_status"], "promised_date": f["promised_date"], "carrier": f["carrier"],
                                               "tracking_no": f["tracking_no"], "last_status": f["last_status"]}}
    assert sc.score_ticket(good, label, label["category"])["end_to_end_ok"]
    for broken in ({**good, "article": "KB-XXX-00"}, {**good, "facts": {**good["facts"], "tracking_no": "TR1"}}, {**good, "action": "request_info"}):
        row = sc.score_ticket(broken, label, label["category"])
        assert not row["end_to_end_ok"]
    flipped = {**label, "expected_escalate": True}
    row = sc.score_ticket(good, flipped, label["category"])
    assert not row["escalation_ok"] and not row["end_to_end_ok"] and row["action_ok"]