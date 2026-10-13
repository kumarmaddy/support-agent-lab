"""Shadow mode (stage 4.4): sample, guard, Step A/B sessions, second reviewer, report and command line.

Nothing here touches the real held-out split: labels are synthetic, the stand-in database is the development split, and the guard is tested
against a small fake tree.
"""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.baseline import lookups
from src.datagen import config
from src.datagen.domain import labels as label_io
from src.datagen.store.db import create_database, load_base_data, load_orders
from src.datagen.tickets import create_ticket_dataset
from src.evaluation import heldout as h
from src.kb.articles import load_articles
from src.shadow import __main__ as cli
from src.shadow import report as rep
from src.shadow import review as rv
from src.shadow.guard import require_heldout_intact
from src.shadow.sample import select_shadow_sample

REPO = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ fixtures
@pytest.fixture(scope="session")
def dev_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("shadow_data")
    conn = create_database(folder / "support.db")
    load_base_data(conn, config.DEFAULT_SEED_DEV)
    load_orders(conn, config.DEFAULT_SEED_DEV)
    summary = create_ticket_dataset(conn, config.DEFAULT_SEED_DEV, "dev", folder / "labels")
    conn.close()
    return folder / "support.db", label_io.read_labels(summary["labels_path"])


@pytest.fixture(scope="session")
def articles():
    return load_articles(REPO / "data" / "seed" / "kb")


@pytest.fixture
def conn(dev_db):
    c = lookups.open_readonly(dev_db[0])
    yield c
    c.close()


class Script:
    """Scripted keyboard; the clock advances 10 s on every input call."""
    def __init__(self, answers):
        self.answers, self.output, self.time = list(answers), [], 0.0

    def input(self, prompt=""):
        self.time += 10
        return self.answers.pop(0)

    def print(self, text=""):
        self.output.append(str(text))

    def clock(self):
        return self.time

    def kw(self):
        return {"input_fn": self.input, "output_fn": self.print, "clock": self.clock}


def synthetic_labels(per_scenario=15, scenarios=10):
    return [{"ticket_id": f"T-{s:02d}{i:03d}", "scenario_id": f"S{s:02d}", "split": "heldout"}
            for s in range(1, scenarios + 1) for i in range(per_scenario)]


def resolution(tid, action="provide_info"):
    return {"ticket_id": tid, "action": action, "reason": "r", "article": "KB-SHP-01", "reply": "Your order is on its way.",
            "reply_source": "model", "handover": {"policy_outcome": "allow", "policy_rule": "R1"}}


# ------------------------------------------------------------------ sample
def test_sample_has_the_right_size_is_unique_and_covers_every_scenario():
    labels = synthetic_labels()
    s = select_shadow_sample(labels)
    assert s["size"] == 40 and len(s["ticket_ids"]) == 40 == len(set(s["ticket_ids"])) and s["practice_ids"] == [] and s["split"] == "heldout"
    scenarios = {lab["ticket_id"]: lab["scenario_id"] for lab in labels}
    assert {scenarios[t] for t in s["ticket_ids"]} == {f"S{n:02d}" for n in range(1, 11)}


def test_sample_is_repeatable_and_depends_on_the_seed():
    labels = synthetic_labels()
    assert select_shadow_sample(labels) == select_shadow_sample(labels)
    assert select_shadow_sample(labels, seed=1)["ticket_ids"] != select_shadow_sample(labels, seed=2)["ticket_ids"]


def test_review_order_is_a_different_permutation_and_raters_are_a_subset():
    s = select_shadow_sample(synthetic_labels())
    assert sorted(s["review_order"]) == sorted(s["ticket_ids"]) and s["review_order"] != s["ticket_ids"]
    assert len(s["rater_ids"]) == 20 and set(s["rater_ids"]) <= set(s["ticket_ids"])


def test_sample_refuses_labels_that_are_not_heldout():
    labels = synthetic_labels()
    labels[3]["split"] = "dev"
    with pytest.raises(ValueError):
        select_shadow_sample(labels)
    with pytest.raises(ValueError):
        select_shadow_sample([])


# ------------------------------------------------------------------ guard
def fake_tree(root: Path, with_run=True):
    db = root / h.HELDOUT_DB
    db.parent.mkdir(parents=True)
    sqlite3.connect(db).close()
    labels = root / h.HELDOUT_LABELS
    labels.parent.mkdir(parents=True)
    labels.write_text(json.dumps({"ticket_id": "T-1", "split": "heldout"}) + "\n", encoding="utf-8", newline="\n")
    record = {"heldout": {"db_file_sha256": h.raw_sha256(db), "labels_sha256": h.file_digest(labels)}}
    (root / h.FREEZE_PATH).parent.mkdir(parents=True)
    (root / h.FREEZE_PATH).write_text(json.dumps(record), encoding="utf-8")
    h.save_registry(root, {"entries": [{"tag": "7b", "status": "complete" if with_run else "started", "run_id": "run-x"}]})
    return root


def test_guard_accepts_an_intact_tree(tmp_path):
    assert require_heldout_intact(fake_tree(tmp_path))["heldout"]


def test_guard_refuses_a_changed_database(tmp_path):
    fake_tree(tmp_path)
    with open(tmp_path / h.HELDOUT_DB, "ab") as f:
        f.write(b"x")
    with pytest.raises(h.GateError):
        require_heldout_intact(tmp_path)


def test_guard_refuses_changed_labels(tmp_path):
    fake_tree(tmp_path)
    (tmp_path / h.HELDOUT_LABELS).write_text("{}\n", encoding="utf-8")
    with pytest.raises(h.GateError):
        require_heldout_intact(tmp_path)


def test_guard_needs_a_complete_7b_run(tmp_path):
    with pytest.raises(h.GateError):
        require_heldout_intact(fake_tree(tmp_path, with_run=False))


# ------------------------------------------------------------------ Step B and the second reviewer
def make_review(conn, articles, tmp_path, script, tickets, resolutions, **kw):
    sample = {"seed": 1, "size": len(tickets), "split": "heldout", "practice_ids": [], "ticket_ids": list(tickets),
              "review_order": list(tickets), "rater_ids": list(tickets)}
    return rv.DraftReview(conn, articles, sample, tmp_path / "review.jsonl", resolutions, **kw, **script.kw()), sample


def read(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def test_accept_is_timed_from_enter_to_the_decision(conn, articles, tmp_path):
    script = Script(["", "orders", "done", "1", "a note"])
    session, _ = make_review(conn, articles, tmp_path, script, ["T-000001"], {"T-000001": resolution("T-000001")}, gap_hours=26.5)
    assert session.run() == 1
    (rec,) = read(tmp_path / "review.jsonl")
    assert rec["outcome"] == "accept" and rec["replacement_actions"] is None and rec["replacement_reply"] is None
    assert rec["seconds"] == 30.0                       # orders, done, decision: 3 x 10 s after the start
    assert rec["gap_hours"] == 26.5 and rec["agent_action"] == "provide_info" and rec["lookups"] == {"orders": 1} and rec["note"] == "a note"
    assert any("Cited article: KB-SHP-01" in o and "Policy: allow (rule R1)" in o for o in script.output)


def test_reject_includes_the_time_to_give_the_replacement(conn, articles, tmp_path):
    script = Script(["", "done", "reject", "provide_info", "My own reply.", ""])
    session, _ = make_review(conn, articles, tmp_path, script, ["T-000001"], {"T-000001": resolution("T-000001")})
    session.run()
    (rec,) = read(tmp_path / "review.jsonl")
    assert rec["outcome"] == "reject" and rec["replacement_actions"] == ["provide_info"] and rec["replacement_reply"] == "My own reply."
    assert rec["seconds"] == 40.0                       # done, decision, actions, reply


def test_pause_is_excluded_and_invalid_outcome_asked_again(conn, articles, tmp_path):
    script = Script(["", "pause", "", "done", "9", "minor_edit", "provide_info", "Edited.", ""])
    session, _ = make_review(conn, articles, tmp_path, script, ["T-000001"], {"T-000001": resolution("T-000001")})
    session.run()
    (rec,) = read(tmp_path / "review.jsonl")
    assert rec["pauses"] == 1 and rec["outcome"] == "minor_edit"
    assert rec["seconds"] == 60.0                       # 7 inputs after the start (70 s) minus the 10 s pause


def test_rater_answers_the_rubric_and_overall_needs_all_four(conn, articles, tmp_path):
    script = Script(["", "done", "y", "maybe", "y", "y", "n", "", "", "done", "y", "y", "y", "y", ""])
    tickets = ["T-000001", "T-000002"]
    sample = {"seed": 1, "size": 2, "split": "heldout", "practice_ids": [], "ticket_ids": tickets, "review_order": tickets, "rater_ids": tickets}
    session = rv.RaterSession(conn, articles, sample, tmp_path / "ratings.jsonl", {t: resolution(t) for t in tickets}, "AB", **script.kw())
    assert session.run() == 2
    first, second = read(tmp_path / "ratings.jsonl")
    assert (first["correct_action"], first["policy_safe"], first["grounded"], first["tone"]) == (True, True, True, False)
    assert first["overall_ok"] is False and second["overall_ok"] is True and first["rater"] == "AB" and first["step"] == "rating"
    assert any("Answer y or n" in o for o in script.output)


def test_rater_only_sees_the_rater_tickets_and_never_a_label(conn, articles, tmp_path):
    script = Script(["", "done", "y", "y", "y", "y", ""])
    sample = {"seed": 1, "size": 2, "split": "heldout", "practice_ids": [], "ticket_ids": ["T-000001", "T-000002"],
              "review_order": ["T-000001", "T-000002"], "rater_ids": ["T-000002"]}
    rv.RaterSession(conn, articles, sample, tmp_path / "r.jsonl", {t: resolution(t) for t in sample["ticket_ids"]}, "AB", **script.kw()).run()
    assert [r["ticket_id"] for r in read(tmp_path / "r.jsonl")] == ["T-000002"]


def test_a_session_resumes_after_quit(conn, articles, tmp_path):
    res = {t: resolution(t) for t in ("T-000001", "T-000002")}
    session, _ = make_review(conn, articles, tmp_path, Script(["", "done", "1", "", "quit"]), ["T-000001", "T-000002"], res)
    assert session.run() == 1
    session, _ = make_review(conn, articles, tmp_path, Script(["", "done", "1", ""]), ["T-000001", "T-000002"], res)
    assert session.run() == 1
    assert [r["ticket_id"] for r in read(tmp_path / "review.jsonl")] == ["T-000001", "T-000002"]


def test_a_ticket_without_an_agent_resolution_is_refused(conn, articles, tmp_path):
    session, _ = make_review(conn, articles, tmp_path, Script([""]), ["T-000001"], {})
    with pytest.raises(ValueError):
        session.run()


# ------------------------------------------------------------------ report
IDS = ["T-A", "T-B", "T-C", "T-D"]


def report_inputs(with_ratings=True):
    labels = {t: {"ticket_id": t, "scenario_id": "S01", "difficulty": "standard", "category": "order_status", "expected_actions": ["provide_info"],
                  "required_kb_ids": [], "expected_escalate": False} for t in IDS}
    labels["T-D"].update(expected_actions=["escalate_human"], expected_escalate=True)
    sample = {"seed": 1, "size": 4, "ticket_ids": IDS, "review_order": IDS, "rater_ids": IDS[:2], "practice_ids": []}
    manual = [{"ticket_id": t, "practice": False, "position": i + 1, "seconds": s, "pauses": 0, "lookups": {}, "category": "order_status",
               "actions": labels[t]["expected_actions"], "kb_ids": []} for i, (t, s) in enumerate(zip(IDS, (60, 60, 100, 100)))]
    def rev(t, secs, outcome, repl=None):
        return {"ticket_id": t, "seconds": secs, "outcome": outcome, "replacement_actions": repl, "lookups": {"orders": 1}, "gap_hours": 30.0}
    review = [rev("T-A", 20, "accept"), rev("T-B", 30, "accept"), rev("T-C", 100, "major_edit", ["provide_info"]), rev("T-D", 80, "reject", ["escalate_human"])]
    actions = {"T-A": "provide_info", "T-B": "propose_refund", "T-C": "provide_info", "T-D": "escalate_human"}
    score = {"rows": [{"ticket_id": t, "category_ok": True, "escalated": actions[t] == "escalate_human", "label_escalate": t == "T-D",
                       "action": actions[t], "expected_action": labels[t]["expected_actions"][0]} for t in IDS]}
    ratings = [{"ticket_id": "T-A", "rater": "AB", "overall_ok": True, "correct_action": True, "policy_safe": True, "grounded": True, "tone": True},
               {"ticket_id": "T-B", "rater": "AB", "overall_ok": False, "correct_action": False, "policy_safe": True, "grounded": True, "tone": True}] if with_ratings else []
    return sample, manual, review, ratings, labels, score


def test_summary_counts_approved_errors_overruled_drafts_and_final_actions():
    s = rep.summarise_shadow(*report_inputs())
    assert s["outcomes"] == {"accept": 2, "minor_edit": 0, "major_edit": 1, "reject": 1} and s["accepted"] == 2
    assert s["approved_errors"] == ["T-B"]                       # accepted although the agent proposed a refund
    assert s["overruled_correct"] == ["T-C", "T-D"]              # the agent's action matched; the reviewer replaced it anyway
    assert s["final_ok"] == 3                                    # T-B is the only wrong final action
    assert s["agent"] == {"category_ok": 4, "escalation_ok": 4, "action_ok": 3}
    assert s["review_vs_manual_median_ratio"] == pytest.approx(0.65)
    assert s["review_seconds"]["median"] == 55 and s["manual_seconds"]["median"] == 80 and s["gap_hours"] == [30.0]


def test_summary_rater_agreement():
    s = rep.summarise_shadow(*report_inputs())
    assert s["rater"]["n"] == 2 and s["rater"]["agree"] == 1 and s["rater"]["disagreements"] == ["T-B"]   # the lead accepted T-B, the rater did not
    assert s["rater"]["items"]["overall_ok"] == 1 and s["rater"]["raters"] == ["AB"]
    assert rep.summarise_shadow(*report_inputs(with_ratings=False))["rater"] is None


def test_summary_refuses_incomplete_steps():
    sample, manual, review, ratings, labels, score = report_inputs()
    with pytest.raises(ValueError):
        rep.summarise_shadow(sample, manual[:3], review, ratings, labels, score)
    with pytest.raises(ValueError):
        rep.summarise_shadow(sample, manual, review[:3], ratings, labels, score)


def test_a_rejected_draft_with_the_wrong_replacement_is_not_final_ok():
    sample, manual, review, ratings, labels, score = report_inputs()
    review[3]["replacement_actions"] = ["provide_info"]
    assert rep.summarise_shadow(sample, manual, review, ratings, labels, score)["final_ok"] == 2


def test_report_states_limits_and_a_missing_second_reviewer():
    inputs = report_inputs(with_ratings=False)
    text = rep.render(rep.summarise_shadow(*inputs), inputs[0], "run-1", "2026-10-20")
    assert "No pass or miss is applied" in text and "No second reviewer took part" in text and "Approved errors" in text
    assert "run-1" in text and "30.0 hours" in text
    with_raters = report_inputs()
    text = rep.render(rep.summarise_shadow(*with_raters), with_raters[0], "run-1", "2026-10-20")
    assert "AB rated 2 drafts" in text and "disagreements: T-B" in text


# ------------------------------------------------------------------ command line
def no_guard(root):
    return {}


def cli_root(tmp_path, dev_db, ended_hours_ago=None):
    """A fake root with the dev database standing in for the held-out one, a registry entry and a run folder."""
    root = tmp_path / "root"
    db = root / h.HELDOUT_DB
    db.parent.mkdir(parents=True)
    db.write_bytes(dev_db[0].read_bytes())
    run = root / "data" / "runs" / "run-7b"
    run.mkdir(parents=True)
    (run / "resolutions.jsonl").write_text("".join(json.dumps(resolution(f"T-{n:06d}")) + "\n" for n in range(1, 4)), encoding="utf-8")
    h.save_registry(root, {"entries": [{"tag": "7b", "status": "complete", "run_id": "run-7b"}]})
    sample = {"seed": 1, "size": 2, "split": "heldout", "practice_ids": [], "ticket_ids": ["T-000001", "T-000002"],
              "review_order": ["T-000002", "T-000001"], "rater_ids": ["T-000001"]}
    (tmp_path / "sample.json").write_text(json.dumps(sample), encoding="utf-8")
    if ended_hours_ago is not None:
        end = NOW - timedelta(hours=ended_hours_ago)
        rows = [{"ticket_id": t, "practice": False, "started_at": (end - timedelta(seconds=100)).isoformat(timespec="seconds"), "seconds": 100.0}
                for t in sample["ticket_ids"]]
        (tmp_path / "manual.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return root


NOW = datetime(2026, 10, 21, 12, 0, 0)


def run_cli(tmp_path, root, command, *extra, guard=no_guard):
    paths = ["--sample", str(tmp_path / "sample.json"), "--manual", str(tmp_path / "manual.jsonl"), "--review", str(tmp_path / "review.jsonl"),
             "--ratings", str(tmp_path / "ratings.jsonl"), "--kb", str(REPO / "data" / "seed" / "kb")]
    return cli.main([command, *paths, *extra], guard=guard, root=root, now=lambda: NOW)


def test_a_failed_guard_stops_every_command(tmp_path, dev_db, capsys):
    root = cli_root(tmp_path, dev_db)
    def failing(_):
        raise h.GateError("closed")
    for command in ("prepare", "handle", "review", "report"):
        assert run_cli(tmp_path, root, command, guard=failing) == 2
    assert "closed" in capsys.readouterr().out


def test_review_needs_step_a_finished(tmp_path, dev_db, capsys):
    root = cli_root(tmp_path, dev_db)
    assert run_cli(tmp_path, root, "review") == 1
    assert "Step A is not finished" in capsys.readouterr().out


def test_review_refuses_a_gap_shorter_than_24_hours(tmp_path, dev_db, capsys):
    root = cli_root(tmp_path, dev_db, ended_hours_ago=23)
    assert run_cli(tmp_path, root, "review") == 1
    assert "at least 24" in capsys.readouterr().out and not (tmp_path / "review.jsonl").exists()


def test_review_runs_after_24_hours_and_records_the_gap(tmp_path, dev_db, monkeypatch):
    root = cli_root(tmp_path, dev_db, ended_hours_ago=25)
    answers = iter(["", "done", "1", "", "", "done", "1", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert run_cli(tmp_path, root, "review") == 0
    recs = read(tmp_path / "review.jsonl")
    assert [r["ticket_id"] for r in recs] == ["T-000002", "T-000001"] and all(r["gap_hours"] == 25.0 for r in recs)


def test_short_gap_can_be_allowed_and_is_recorded(tmp_path, dev_db, monkeypatch):
    root = cli_root(tmp_path, dev_db, ended_hours_ago=2)
    answers = iter(["quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert run_cli(tmp_path, root, "review", "--allow-short-gap") == 0


def test_step_a_cannot_change_once_step_b_has_started(tmp_path, dev_db, capsys):
    root = cli_root(tmp_path, dev_db)
    (tmp_path / "review.jsonl").write_text("{}\n", encoding="utf-8")
    assert run_cli(tmp_path, root, "handle") == 1
    assert "Step B has started" in capsys.readouterr().out


def test_prepare_never_overwrites_a_sample(tmp_path, dev_db, capsys):
    root = cli_root(tmp_path, dev_db)
    assert run_cli(tmp_path, root, "prepare") == 1
    assert "fixed once chosen" in capsys.readouterr().out


def test_prepare_writes_a_sample_from_the_heldout_labels(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli.label_io, "read_labels", lambda path: synthetic_labels())
    assert run_cli(tmp_path, tmp_path / "root", "prepare") == 0
    written = json.loads((tmp_path / "sample.json").read_text(encoding="utf-8"))
    assert written == select_shadow_sample(synthetic_labels()) and "40 held-out tickets" in capsys.readouterr().out


def test_a_minor_edit_counts_as_accepted_and_a_major_edit_does_not():
    sample, manual, review, ratings, labels, score = report_inputs()
    review[1]["outcome"] = "minor_edit"                        # T-B: wrong action, accepted with a wording change
    s = rep.summarise_shadow(sample, manual, review, ratings, labels, score)
    assert s["accepted"] == 2 and s["approved_errors"] == ["T-B"] and s["outcomes"]["minor_edit"] == 1
    review[1]["outcome"], review[1]["replacement_actions"] = "major_edit", ["provide_info"]
    s = rep.summarise_shadow(sample, manual, review, ratings, labels, score)
    assert s["accepted"] == 1 and s["approved_errors"] == [] and s["final_ok"] == 4


def test_review_order_comes_from_its_own_seeded_shuffle():
    import random
    s = select_shadow_sample(synthetic_labels())
    expected = list(s["ticket_ids"])
    random.Random("40404:shadow:review-order").shuffle(expected)
    assert s["review_order"] == expected