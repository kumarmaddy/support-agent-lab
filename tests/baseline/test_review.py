import ast
import json
from pathlib import Path

import pytest

from src.baseline import cli
from src.baseline.lookups import open_readonly
from src.baseline.review import DEFAULT_H_ACTION, ReviewSession, evidence_text, render_review
from src.baseline.sampling import select_sample
from src.baseline.scoring import summarise
from tests.baseline.test_cli import perfect_results, write_results

SRC = Path(__file__).resolve().parents[2] / "src" / "baseline"


@pytest.fixture()
def setup(tmp_path, dev_dataset, articles):
    """A 30-ticket run with two known disagreements: a wrong category and a missed knowledge-base article."""
    db, labels_path, labs = dev_dataset
    by_id = {l["ticket_id"]: l for l in labs}
    sample = select_sample(labs, 30, 1)
    wrong_category = next(t for t in sample["ticket_ids"] if by_id[t]["category"] != "other")
    missed_kb = next(t for t in sample["ticket_ids"] if by_id[t]["required_kb_ids"] and t != wrong_category)
    results = perfect_results(sample, labs, flaw=wrong_category)
    next(r for r in results if r["ticket_id"] == missed_kb)["kb_ids"] = []
    (tmp_path / "sample.json").write_text(json.dumps(sample), encoding="utf-8")
    write_results(tmp_path / "results.jsonl", results)
    summary = summarise(results, by_id)
    conn = open_readonly(db)
    yield {"tmp": tmp_path, "db": db, "labels_path": labels_path, "by_id": by_id, "results": results, "conn": conn,
           "summary": summary, "articles": articles, "wrong_category": wrong_category, "missed_kb": missed_kb}
    conn.close()


def scripted(answers):
    queue = iter(answers)
    return lambda prompt="": next(queue)


def make_session(s, answers, out=None):
    return ReviewSession(s["conn"], s["articles"], s["results"], s["by_id"], s["summary"]["disagreements"],
                         s["tmp"] / "review.jsonl", input_fn=scripted(answers), output_fn=(out.append if out is not None else lambda *_: None),
                         now=lambda: __import__("datetime").datetime(2026, 10, 8, 9, 0, 0))


def test_the_run_has_exactly_the_two_planted_disagreements(setup):
    assert {d["ticket_id"] for d in setup["summary"]["disagreements"]} == {setup["wrong_category"], setup["missed_kb"]}


def test_evidence_shows_ticket_records_both_answers_and_article_facts(setup):
    row = next(d for d in setup["summary"]["disagreements"] if d["ticket_id"] == setup["missed_kb"])
    label = setup["by_id"][setup["missed_kb"]]
    text = evidence_text(setup["conn"], setup["articles"], next(r for r in setup["results"] if r["ticket_id"] == setup["missed_kb"]), label, row)
    for expected in ("TICKET", "RECORDS", "HANDLER'S ANSWER", "LABEL", "WHERE TO LOOK", "From:", label["required_kb_ids"][0],
                     f"category: {label['category']}", "articles relied on: none"):
        assert expected in text
    first_fact = setup["articles"][label["required_kb_ids"][0]].key_facts[0]
    assert first_fact in text                                              # the required article's key facts are shown
    assert "kb:" in text and "category:" not in text.split("WHERE TO LOOK")[1]   # only the failed measure gets a hint


def test_classifications_are_saved_and_the_review_resumes(setup):
    first, second = (d["ticket_id"] for d in setup["summary"]["disagreements"])
    answers = ["h", "the ticket asks for the bank card, not the order", "",                 # H: default action
               "k", "", "Article REF-02 says five days but the policy says seven", "Correct KB-REF-02 key fact"]   # empty evidence re-asked
    assert make_session(setup, answers).run() == 2
    records = make_session(setup, []).records()
    assert records[first]["code"] == "H" and records[first]["action"] == DEFAULT_H_ACTION
    assert records[second]["code"] == "K" and records[second]["evidence"].startswith("Article REF-02")
    assert make_session(setup, []).run() == 0                               # nothing left to ask


def test_skip_quit_and_redo(setup):
    first, second = (d["ticket_id"] for d in setup["summary"]["disagreements"])
    assert make_session(setup, ["s", "q"]).run() == 0                       # skipped one, quit on the next
    assert make_session(setup, []).records() == {}
    assert make_session(setup, ["x", "L", "label has the wrong category", "Open an ADR and bump the dataset", "q"]).run() == 1
    assert make_session(setup, ["h", "handler slip", "", "q"]).run(redo={first}) == 1       # redo replaces the earlier decision
    assert make_session(setup, []).records()[first]["code"] == "H"


def test_non_h_codes_must_state_an_action(setup):
    answers = ["l", "label wrong", "", "Bump the dataset version", "q"]
    session = make_session(setup, answers)
    assert session.run() == 1
    assert next(iter(session.records().values()))["action"] == "Bump the dataset version"


def test_render_summarises_counts_intervals_and_pending(setup):
    first, second = setup["summary"]["disagreements"]
    records = {first["ticket_id"]: {"ticket_id": first["ticket_id"], "scenario_id": first["scenario_id"], "failed": ["category"],
                                    "code": "K", "evidence": "pipe | and\nnewline", "action": "Fix KB-REF-02"}}
    text = render_review(records, setup["summary"]["disagreements"], 30, "2026-10-08")
    assert "(partial: 1 ticket(s) not yet reviewed)" in text and f"| {second['ticket_id']} | | | pending |" in text
    assert "pipe / and newline" in text                                     # cell text cannot break the table
    assert "| K knowledge-base defects | 1 |" in text and "| H handler errors | 0 |" in text
    assert "2 of 30 (6.7%" in text and "0 of 30 (0.0%" in text and "95% CI" in text
    assert "Fix KB-REF-02" in text.split("## 5. Decisions arising")[1]


def test_cli_review_end_to_end(setup, monkeypatch, capsys):
    s, tmp = setup, setup["tmp"]
    answers = iter(["h", "handler slip", "", "h", "handler slip", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    args = ["review", "--db", str(s["db"]), "--labels", str(s["labels_path"]), "--sample", str(tmp / "sample.json"),
            "--results", str(tmp / "results.jsonl"), "--review-log", str(tmp / "log.jsonl"), "--output", str(tmp / "review.md")]
    assert cli.main(args) == 0
    text = (tmp / "review.md").read_text(encoding="utf-8")
    assert "| H handler errors | 2 |" in text and "pending" not in text and "None: every reviewed" in text


def test_cli_review_waits_for_the_full_run(setup, capsys):
    s, tmp = setup, setup["tmp"]
    write_results(tmp / "results.jsonl", s["results"][:5])
    args = ["review", "--db", str(s["db"]), "--labels", str(s["labels_path"]), "--sample", str(tmp / "sample.json"),
            "--results", str(tmp / "results.jsonl"), "--output", str(tmp / "review.md")]
    assert cli.main(args) == 1 and not (tmp / "review.md").exists()


@pytest.mark.parametrize("module", ["session.py", "lookups.py"])
def test_the_timed_tool_cannot_import_the_review_module(module):
    tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "review" not in (node.module or "") and all("review" not in a.name for a in node.names)


def test_defects_in_project_artefacts_exclude_handler_errors(setup):
    first, second = setup["summary"]["disagreements"]
    def record(d, code):
        return {"ticket_id": d["ticket_id"], "scenario_id": d["scenario_id"], "failed": ["kb"], "code": code, "evidence": "e", "action": "a"}
    text = render_review({first["ticket_id"]: record(first, "K"), second["ticket_id"]: record(second, "H")},
                         setup["summary"]["disagreements"], 30, "2026-10-08")
    assert "Defects in the project's own artefacts (L, K, P): 1 ticket(s)." in text
    assert "handler errors only: 1 of 30" in text and "partial" not in text


# ------------------------------------------------------------------ drafts prepared outside the tool
def drafts_for(setup, code="H"):
    return {d["ticket_id"]: {"ticket_id": d["ticket_id"], "code": code, "evidence": "drafted reasoning", "action": "drafted action"}
            for d in setup["summary"]["disagreements"]}


def test_drafts_are_proposals_until_the_reviewer_accepts(setup):
    from src.baseline.review import DRAFT_SOURCE
    first, second = (d["ticket_id"] for d in setup["summary"]["disagreements"])
    session = make_session(setup, ["", "n"])                                  # accept the first, take the second back
    assert session.confirm_drafts(drafts_for(setup)) == 1
    records = session.records()
    assert list(records) == [first] and records[first]["source"] == DRAFT_SOURCE
    assert [d["ticket_id"] for d in session.pending()] == [second]            # still to be reviewed by hand


def test_quitting_confirmation_records_nothing_further(setup):
    session = make_session(setup, ["q"])
    assert session.confirm_drafts(drafts_for(setup)) == 0 and session.records() == {}


def test_rendered_review_discloses_assisted_decisions(setup):
    session = make_session(setup, ["", ""])
    session.confirm_drafts(drafts_for(setup))
    text = render_review(session.records(), setup["summary"]["disagreements"], 30, "2026-10-08")
    assert "2 of 2 decisions were drafted with AI assistance" in text
    manual = make_session(setup, ["h", "mine", "", "h", "mine", ""])
    manual_dir = setup["tmp"] / "other.jsonl"
    manual.log_path = manual_dir
    manual.run()
    assert "drafted with AI assistance" not in render_review(manual.records(), setup["summary"]["disagreements"], 30, "2026-10-08")


def test_malformed_drafts_are_rejected(tmp_path):
    from src.baseline.review import load_drafts
    (tmp_path / "d.jsonl").write_text('{"ticket_id": "T-1", "code": "Z", "evidence": "x", "action": "y"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_drafts(tmp_path / "d.jsonl")
    assert load_drafts(tmp_path / "missing.jsonl") == {}