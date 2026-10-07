import json

import pytest

from src.baseline import lookups
from src.baseline.session import Session


class Script:
    """Scripted keyboard and a clock that advances 10 s on every input call."""
    def __init__(self, answers):
        self.answers, self.prompts, self.output, self.time = list(answers), [], [], 0.0

    def input(self, prompt=""):
        self.prompts.append(prompt)
        self.time += 10
        return self.answers.pop(0)

    def print(self, text=""):
        self.output.append(str(text))

    def clock(self):
        return self.time


@pytest.fixture
def conn(dev_dataset):
    c = lookups.open_readonly(dev_dataset[0])
    yield c
    c.close()


def make_session(conn, articles, tmp_path, script, tickets=("T-000001",), practice=()):
    sample = {"seed": 1, "size": len(tickets), "split": "dev", "practice_ids": list(practice), "ticket_ids": list(tickets)}
    return Session(conn, articles, sample, tmp_path / "results.jsonl", input_fn=script.input, output_fn=script.print,
                   clock=script.clock)


FLOW = ["", "orders", "order O-000001", "kb KB-RET-01", "done",       # start, lookups, finish
        "1", "1", "KB-SHP-01", "Your order is on its way.", "a note"]   # category, actions, kb, reply, note


def test_records_decision_time_and_lookups(conn, articles, tmp_path):
    script = Script(FLOW)
    session = make_session(conn, articles, tmp_path, script)
    assert session.run() == 1
    (line,) = (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(line)
    assert rec["ticket_id"] == "T-000001" and rec["practice"] is False and rec["position"] == 1
    assert rec["category"] == "order_status" and rec["actions"] == ["provide_info"]
    assert rec["kb_ids"] == ["KB-SHP-01"] and rec["reply"] == "Your order is on its way."
    assert rec["lookups"] == {"orders": 1, "order": 1, "kb": 1} and rec["escalation_reason"] is None
    # timer starts after the first Enter and stops when the reply is submitted: 8 inputs x 10 s
    assert rec["seconds"] == 80.0 and rec["note"] == "a note"


def test_pause_time_is_excluded(conn, articles, tmp_path):
    answers = ["", "pause", "", "done", "1", "1", "", "Reply.", ""]
    script = Script(answers)
    make_session(conn, articles, tmp_path, script).run()
    rec = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))
    # inputs after the start: pause, resume, done, category, actions, kb, reply = 7 x 10 s, minus the 10 s paused
    assert rec["seconds"] == 60.0 and rec["pauses"] == 1


def test_escalation_asks_for_a_reason_only_when_escalating(conn, articles, tmp_path):
    escalate = ["", "done", "other", "escalate_human", "not covered", "", "Passing this to a colleague.", ""]
    make_session(conn, articles, tmp_path, Script(escalate)).run()
    rec = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))
    assert rec["actions"] == ["escalate_human"] and rec["escalation_reason"] == "not covered"


def test_invalid_entries_are_asked_again(conn, articles, tmp_path):
    answers = ["", "bogus", "done", "99", "order_status", "", "provide_info, provide_info", "KB-NOPE-99", "KB-SHP-01",
               "Reply.", ""]
    script = Script(answers)
    make_session(conn, articles, tmp_path, script).run()
    rec = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))
    assert rec["category"] == "order_status" and rec["actions"] == ["provide_info"] and rec["kb_ids"] == ["KB-SHP-01"]
    assert any("Unknown command" in o for o in script.output) and any("Unknown article" in o for o in script.output)


def test_quit_saves_nothing_and_resume_skips_completed(conn, articles, tmp_path):
    first = Script(FLOW + ["quit"])
    session = make_session(conn, articles, tmp_path, first, tickets=("T-000001", "T-000002"))
    assert session.run() == 1                                    # ticket 1 done, quit at ticket 2
    assert session.completed_ids() == {"T-000001"}
    second = Script(FLOW)
    assert make_session(conn, articles, tmp_path, second, tickets=("T-000001", "T-000002")).run() == 1
    ids = [json.loads(l)["ticket_id"] for l in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ids == ["T-000001", "T-000002"]


def test_practice_tickets_come_first_and_are_flagged(conn, articles, tmp_path):
    script = Script(FLOW + FLOW)
    make_session(conn, articles, tmp_path, script, tickets=("T-000002",), practice=("T-000001",)).run()
    recs = [json.loads(l) for l in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["ticket_id"], r["practice"], r["position"]) for r in recs] == [("T-000001", True, None), ("T-000002", False, 1)]


def test_lookups_show_account_holder_and_are_read_only(conn, dev_dataset):
    text = lookups.order_summary(conn, "O-000001")
    assert "account holder:" in text and "ships to:" in text
    assert "No order O-999999" in lookups.order_summary(conn, "O-999999")
    with pytest.raises(Exception):
        conn.execute("DELETE FROM tickets")


def test_unknown_ticket_is_an_error(conn, articles, tmp_path):
    with pytest.raises(ValueError):
        make_session(conn, articles, tmp_path, Script([]), tickets=("T-999999",)).run()
