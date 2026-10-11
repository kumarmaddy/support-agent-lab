import json

import pytest

from src.agent.handover import Handover
from src.evaluation import review_notes as rn


def note(tid, action="propose_refund"):
    return Handover(tid, "2026-10-01T09:00:00", "standard", action, "duplicate_charge", "why", "next", "KB-REF-02", "refund", False, "found", "C-1",
                    ("O-1",), ("Order O-1 is delivered.",), True, "template").to_dict()


def res(tid, action="propose_refund", with_note=True):
    return {"ticket_id": tid, "action": action, "reply": "Hello", "handover": note(tid, action) if with_note else None}


def rows():
    return ([res(f"T-{i:06d}", "propose_refund") for i in range(1, 9)] + [res(f"T-{i:06d}", "escalate_human") for i in range(9, 12)]
            + [res("T-000012", "route_to_human")] + [res(f"T-{i:06d}", "provide_info", False) for i in range(13, 20)])


def test_sample_covers_every_action_with_a_note_and_skips_resolutions_without_one():
    chosen = rn.sample(rows(), 5, seed=1)
    assert len(chosen) == 5 and {r["action"] for r in chosen} == {"propose_refund", "escalate_human", "route_to_human"}
    assert all(r["handover"] for r in chosen)


def test_sample_is_fixed_by_seed_and_never_larger_than_what_exists():
    assert [r["ticket_id"] for r in rn.sample(rows(), 6, 0)] == [r["ticket_id"] for r in rn.sample(rows(), 6, 0)]
    assert len(rn.sample(rows(), 100, 0)) == 12


def test_rendered_note_has_no_label_fields_and_round_trips():
    text = rn.note_text(note("T-000001"))
    assert "Ticket T-000001" in text and "Order: O-1" in text and "expected" not in text.lower()


def answers(*given):
    it = iter(given)
    return lambda prompt: next(it)


def test_ratings_are_saved_and_resumed(tmp_path):
    items = [{"ticket_id": f"T-{i}", "action": "propose_refund", "subject": "s", "body": "b", "reply": "r", "note": "n"} for i in range(3)]
    path = tmp_path / "r.jsonl"
    shown = []
    assert rn.run_review(items, path, answers("n", "y", "n", "n", "n", "bad", "p", "n", "y", "", "n", "q"), shown.append) == 2
    assert rn.run_review(items, path, answers("n", "y", "n", "n"), shown.append) == 1
    got = rn.load_ratings(path)
    assert len(got) == 3 and got["T-1"]["reply_problem"] is False and got["T-0"]["actionable"] == "y" and got["T-1"]["missing"] is True and got["T-1"]["actionable"] == "p"


def test_report_counts_and_lists_follow_ups():
    items = [{"ticket_id": f"T-{i}", "action": "propose_refund" if i < 3 else "escalate_human", "subject": "", "body": "", "reply": "", "note": ""} for i in range(4)]
    ratings = {f"T-{i}": {"ticket_id": f"T-{i}", "reply_problem": a == "n", "actionable": a, "wrong": w, "missing": False, "comment": ""} for i, (a, w) in enumerate(
        [("y", False), ("y", False), ("p", False), ("n", True)])}
    rep = rn.report(items, ratings)
    assert (rep["actionable_yes"]["count"], rep["actionable_partly"]["count"], rep["actionable_no"]["count"], rep["wrong"]["count"]) == (2, 1, 1, 1) and rep["reply_problem"]["count"] == 1
    assert rep["by_action"]["escalate_human"] == {"rated": 1, "actionable_yes": 0} and [t["ticket_id"] for t in rep["to_follow_up"]] == ["T-2", "T-3"]
    assert "could act on it: yes 2/4" in rn.render(rep)


def test_empty_report_is_safe_and_heldout_is_refused(tmp_path):
    assert "n/a" in rn.render(rn.report([], {}))
    with pytest.raises(SystemExit):
        rn.main(["make", "--run", str(tmp_path), "--db", "data/generated/heldout/support.db", "--name", "x", "--root", str(tmp_path)])


def test_make_writes_a_sheet_from_a_run_and_never_overwrites(dev_dataset, tmp_path):
    db = dev_dataset[0]
    run = tmp_path / "run"
    run.mkdir()
    (run / "resolutions.jsonl").write_text("\n".join(json.dumps(res(f"T-{i:06d}")) for i in range(1, 6)) + "\n", encoding="utf-8")
    args = ["make", "--run", str(run), "--db", str(db), "--count", "3", "--name", "n", "--root", str(tmp_path / "rev")]
    assert rn.main(args) == 0
    items = json.loads((tmp_path / "rev" / "n" / "items.json").read_text(encoding="utf-8"))
    assert len(items) == 3 and all(i["subject"] and i["note"] and i["reply"] for i in items)
    with pytest.raises(SystemExit):
        rn.main(args)


def test_a_reply_problem_alone_puts_the_case_on_the_follow_up_list():
    items = [{"ticket_id": "T-1", "action": "propose_refund", "subject": "", "body": "", "reply": "", "note": ""}]
    rep = rn.report(items, {"T-1": {"ticket_id": "T-1", "reply_problem": True, "actionable": "y", "wrong": False, "missing": False, "comment": ""}})
    assert [t["ticket_id"] for t in rep["to_follow_up"]] == ["T-1"] and "reply wrong or inappropriate: 1/1" in rn.render(rep)


def test_a_reply_problem_asks_for_a_comment_even_when_the_note_is_fine():
    item = {"ticket_id": "T-1", "action": "x", "subject": "s", "body": "b", "reply": "r", "note": "n"}
    asked = []
    given = iter(["y", "y", "n", "n", "reply never names the order"])
    rating = rn.ask_case(item, "1/1", lambda p: (asked.append(p), next(given))[1], lambda t: None)
    assert rating["reply_problem"] is True and rating["comment"] == "reply never names the order" and asked[-1].startswith("Comment")


def test_amend_appends_a_new_rating_that_replaces_the_old_one_and_keeps_the_old_line(tmp_path):
    items = [{"ticket_id": "T-1", "action": "x", "subject": "s", "body": "b", "reply": "r", "note": "n"}]
    path = tmp_path / "r.jsonl"
    rn.run_review(items, path, answers("n", "n", "n", "n", ""), lambda t: None)
    assert rn.amend(items, path, "T-1", answers("n", "y", "n", "n"), lambda t: None) is True
    assert rn.load_ratings(path)["T-1"]["actionable"] == "y" and len(path.read_text().splitlines()) == 2
    assert json.loads(path.read_text().splitlines()[1])["amended"] is True
    rep = rn.report(items, rn.load_ratings(path))
    assert rep["notes_rated"] == 1 and rep["actionable_yes"]["count"] == 1


def test_amend_can_be_quit_and_refuses_an_unknown_ticket(tmp_path):
    items = [{"ticket_id": "T-1", "action": "x", "subject": "s", "body": "b", "reply": "r", "note": "n"}]
    path = tmp_path / "r.jsonl"
    assert rn.amend(items, path, "T-1", answers("n", "q"), lambda t: None) is False and not path.exists()
    with pytest.raises(SystemExit):
        rn.amend(items, path, "T-9", answers(), lambda t: None)