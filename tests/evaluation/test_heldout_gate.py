"""The held-out gate (stage 4.2): freeze record, one run per model, scoring only for runs made by the gate.

Every test builds a small fake project tree in a temporary folder. The real held-out split is never touched.
"""
import json
import sqlite3
from pathlib import Path

import pytest

from src.evaluation import heldout as h


def make_tree(root: Path) -> Path:
    files = {
        "src/a.py": "x = 1\n", "src/agent/prompts/p.md": "prompt\n", "config/policy.toml": "[engine]\nversion = \"1.0\"\n",
        "data/seed/kb/KB-1.md": "article\n", "data/security/cases.jsonl": "{}\n", "data/manifest.json": "{}\n",
    }
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    db = root / h.HELDOUT_DB
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE tickets (ticket_id TEXT)")
    conn.executemany("INSERT INTO tickets VALUES (?)", [("T-1",), ("T-2",), ("T-3",)])
    conn.commit()
    conn.close()
    labels = root / h.HELDOUT_LABELS
    labels.parent.mkdir(parents=True, exist_ok=True)
    labels.write_text("".join(json.dumps({"ticket_id": f"T-{i}", "split": "heldout"}) + "\n" for i in (1, 2, 3)), encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def tree(tmp_path):
    return make_tree(tmp_path)


@pytest.fixture
def frozen(tree):
    record = h.build_record(tree)
    (tree / h.FREEZE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tree / h.FREEZE_PATH).write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    return tree, record


# ------------------------------------------------------------------ the freeze record
def test_a_fresh_record_verifies(frozen):
    tree, record = frozen
    assert h.verify_record(record, tree) == []
    assert record["heldout"]["tickets"] == 3 and len(record["record_sha256"]) == 64


def test_the_record_covers_source_prompts_config_kb_security_cases_and_manifest(frozen):
    _, record = frozen
    assert set(record["files"]) == {"src/a.py", "src/agent/prompts/p.md", "config/policy.toml", "data/seed/kb/KB-1.md",
                                    "data/security/cases.jsonl", "data/manifest.json"}


def test_a_changed_source_file_breaks_the_freeze(frozen):
    tree, record = frozen
    (tree / "src/a.py").write_text("x = 2\n", encoding="utf-8")
    assert h.verify_record(record, tree) == ["frozen file changed: src/a.py"]


def test_a_changed_prompt_or_policy_breaks_the_freeze(frozen):
    tree, record = frozen
    (tree / "src/agent/prompts/p.md").write_text("other\n", encoding="utf-8")
    (tree / "config/policy.toml").write_text("[engine]\nversion = \"2.0\"\n", encoding="utf-8")
    assert sorted(h.verify_record(record, tree)) == ["frozen file changed: config/policy.toml", "frozen file changed: src/agent/prompts/p.md"]


def test_an_added_and_a_removed_file_are_both_reported(frozen):
    tree, record = frozen
    (tree / "src/b.py").write_text("y = 1\n", encoding="utf-8")
    (tree / "data/seed/kb/KB-1.md").unlink()
    assert sorted(h.verify_record(record, tree)) == ["file added since the freeze: src/b.py", "frozen file missing: data/seed/kb/KB-1.md"]


def test_windows_line_endings_do_not_change_a_digest(frozen):
    tree, record = frozen
    (tree / "src/a.py").write_bytes(b"x = 1\r\n")
    (tree / h.HELDOUT_LABELS).write_bytes((tree / h.HELDOUT_LABELS).read_bytes().replace(b"\n", b"\r\n"))
    assert h.verify_record(record, tree) == []


def test_pycache_is_ignored(frozen):
    tree, record = frozen
    (tree / "src/__pycache__").mkdir()
    (tree / "src/__pycache__/a.cpython-313.pyc").write_bytes(b"\x00")
    assert h.verify_record(record, tree) == []


def test_a_changed_heldout_database_or_labels_break_the_freeze(frozen):
    tree, record = frozen
    conn = sqlite3.connect(tree / h.HELDOUT_DB)
    conn.execute("INSERT INTO tickets VALUES ('T-4')")
    conn.commit()
    conn.close()
    (tree / h.HELDOUT_LABELS).write_text('{"ticket_id": "T-1", "split": "heldout"}\n', encoding="utf-8")
    problems = h.verify_record(record, tree)
    assert "held-out database file changed" in problems and "held-out database content changed" in problems
    assert "held-out labels file changed" in problems


def test_an_edited_record_is_detected(frozen):
    tree, record = frozen
    record["git"]["commit"] = "0" * 40
    assert h.verify_record(record, tree)[0].startswith("the freeze record itself has been edited")


def test_create_writes_once_and_refuses_to_replace(tree, monkeypatch):
    monkeypatch.setattr(h, "git_state", lambda root: {"commit": "abc", "dirty": False})
    assert h.cmd_create(tree) == 0
    with pytest.raises(h.GateError, match="already exists"):
        h.cmd_create(tree)


def test_create_refuses_a_dirty_tree(tree, monkeypatch):
    monkeypatch.setattr(h, "git_state", lambda root: {"commit": "abc", "dirty": True})
    with pytest.raises(h.GateError, match="uncommitted"):
        h.cmd_create(tree)
    assert not (tree / h.FREEZE_PATH).exists()


def test_create_refuses_after_the_split_was_opened(tree, monkeypatch):
    monkeypatch.setattr(h, "git_state", lambda root: {"commit": "abc", "dirty": False})
    h.begin_entry(tree, "7b", "qwen2.5:7b", "x", None)
    with pytest.raises(h.GateError, match="already been opened"):
        h.cmd_create(tree)


def test_without_a_record_nothing_opens(tree):
    with pytest.raises(h.GateError, match="No freeze record"):
        h.cmd_run(tree, "7b", None)


# ------------------------------------------------------------------ one run per model
def test_second_run_for_a_model_is_refused_but_another_model_is_allowed(tree):
    h.begin_entry(tree, "7b", "qwen2.5:7b", "x", None)
    with pytest.raises(h.GateError, match="run once"):
        h.begin_entry(tree, "7b", "qwen2.5:7b", "x", None)
    h.begin_entry(tree, "3b", "llama3.2:3b", "x", None)


def test_a_rerun_needs_a_reason_and_the_reason_is_kept(tree):
    h.begin_entry(tree, "7b", "qwen2.5:7b", "x", None)
    h.begin_entry(tree, "7b", "qwen2.5:7b", "x", "power cut at ticket 90")
    entries = h.load_registry(tree)["entries"]
    assert [e["rerun_reason"] for e in entries] == [None, "power cut at ticket 90"]


def fake_main_factory(tree, produce=True, db_sha=None):
    def fake_main(argv):
        assert argv[argv.index("--model") + 1] == "qwen2.5:7b"
        assert "--knowledge-first" in argv and "--transactions" in argv and argv[argv.index("--read-prompt") + 1] == "v5"
        h.run_mod.check_not_heldout(Path(argv[argv.index("--db") + 1]))       # the gate lets the frozen database through
        with pytest.raises(SystemExit):
            h.run_mod.check_not_heldout(Path("elsewhere/heldout/support.db"))   # but not any other held-out path
        if produce:
            run = tree / "data/runs/run-1"
            run.mkdir(parents=True)
            (run / "run.json").write_text(json.dumps({"dataset": {"db_sha256": db_sha or h.raw_sha256(tree / h.HELDOUT_DB)}}), encoding="utf-8")
        return 0
    return fake_main


def test_run_marks_the_run_and_the_registry_and_restores_the_guard(frozen, monkeypatch):
    tree, record = frozen
    original = h.run_mod.check_not_heldout
    monkeypatch.setattr(h.run_mod, "main", fake_main_factory(tree))
    assert h.cmd_run(tree, "7b", None) == 0
    assert h.run_mod.check_not_heldout is original
    with pytest.raises(SystemExit):
        h.run_mod.check_not_heldout(tree / h.HELDOUT_DB)                         # the ordinary runner still refuses
    marker = json.loads((tree / "data/runs/run-1" / h.MARKER).read_text(encoding="utf-8"))
    assert marker["status"] == "complete" and marker["freeze_record_sha256"] == record["record_sha256"]
    entry = h.load_registry(tree)["entries"][0]
    assert entry["status"] == "complete" and entry["run_id"] == "run-1"


def test_run_is_refused_when_a_frozen_file_changed(frozen, monkeypatch):
    tree, _ = frozen
    (tree / "src/a.py").write_text("x = 99\n", encoding="utf-8")
    monkeypatch.setattr(h.run_mod, "main", lambda argv: pytest.fail("the runner must not start"))
    with pytest.raises(h.GateError, match="stays closed"):
        h.cmd_run(tree, "7b", None)
    assert h.load_registry(tree)["entries"] == []


def test_a_failed_start_does_not_use_up_the_single_run(frozen, monkeypatch):
    tree, _ = frozen
    def broken(argv):
        raise SystemExit("Ollama is not running")
    monkeypatch.setattr(h.run_mod, "main", broken)
    original = h.run_mod.check_not_heldout
    with pytest.raises(SystemExit):
        h.cmd_run(tree, "7b", None)
    assert h.load_registry(tree)["entries"] == [] and h.run_mod.check_not_heldout is original


def test_a_crash_after_the_run_folder_exists_keeps_the_entry(frozen, monkeypatch):
    tree, _ = frozen
    def crash(argv):
        (tree / "data/runs/run-x").mkdir(parents=True)
        raise RuntimeError("power cut")
    monkeypatch.setattr(h.run_mod, "main", crash)
    with pytest.raises(RuntimeError):
        h.cmd_run(tree, "7b", None)
    assert h.load_registry(tree)["entries"][0]["status"] == "started"
    with pytest.raises(h.GateError, match="run once"):
        h.cmd_run(tree, "7b", None)


# ------------------------------------------------------------------ scoring
def completed_run(frozen, monkeypatch):
    tree, _ = frozen
    monkeypatch.setattr(h.run_mod, "main", fake_main_factory(tree))
    h.cmd_run(tree, "7b", None)
    return tree, tree / "data/runs/run-1"


def test_score_passes_labels_and_writes_score_json(frozen, monkeypatch, capsys):
    tree, run = completed_run(frozen, monkeypatch)
    seen = {}
    def fake_score(run_dir, labels, kb):
        seen.update(run=run_dir, count=len(labels), kb=kb)
        return {"ok": True}
    monkeypatch.setattr(h.sc, "score_run", fake_score)
    monkeypatch.setattr(h.sc, "render", lambda s: "RENDERED")
    assert h.cmd_score(tree, run) == 0
    assert seen["count"] == 3 and json.loads((run / "score.json").read_text(encoding="utf-8")) == {"ok": True}
    assert "RENDERED" in capsys.readouterr().out


def test_score_refuses_a_run_the_gate_did_not_make(frozen, monkeypatch):
    tree, _ = frozen
    (tree / "data/runs/other").mkdir(parents=True)
    with pytest.raises(h.GateError, match="not made by the held-out gate"):
        h.cmd_score(tree, tree / "data/runs/other")


def test_score_refuses_a_run_on_another_database(frozen, monkeypatch):
    tree, run = completed_run(frozen, monkeypatch)
    (run / "run.json").write_text(json.dumps({"dataset": {"db_sha256": "0" * 64}}), encoding="utf-8")
    with pytest.raises(h.GateError, match="frozen held-out database"):
        h.cmd_score(tree, run)


def test_score_refuses_an_incomplete_marker(frozen, monkeypatch):
    tree, run = completed_run(frozen, monkeypatch)
    marker = json.loads((run / h.MARKER).read_text(encoding="utf-8"))
    marker["status"] = "started"
    (run / h.MARKER).write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(h.GateError, match="not complete"):
        h.cmd_score(tree, run)


def test_score_refuses_when_the_freeze_no_longer_holds(frozen, monkeypatch):
    tree, run = completed_run(frozen, monkeypatch)
    (tree / "config/policy.toml").write_text("[engine]\nversion = \"9\"\n", encoding="utf-8")
    with pytest.raises(h.GateError, match="stays closed"):
        h.cmd_score(tree, run)


# ------------------------------------------------------------------ the ordinary tools stay closed
def test_the_ordinary_runner_and_scorer_still_refuse_the_heldout_split():
    from src.agent import run as runner
    from src.evaluation import score
    with pytest.raises(SystemExit):
        runner.check_not_heldout(Path("data/generated/heldout/support.db"))
    with pytest.raises(SystemExit):
        score.check_labels([{"split": "heldout"}], Path("data/labels/heldout/labels.jsonl"))


def test_check_reports_a_broken_freeze(frozen, capsys):
    tree, _ = frozen
    assert h.cmd_check(tree) == 0
    (tree / "src/a.py").write_text("x = 3\n", encoding="utf-8")
    assert h.cmd_check(tree) == 1
    assert "frozen file changed: src/a.py" in capsys.readouterr().out


def test_score_refuses_labels_that_are_not_heldout_labels(tree, monkeypatch):
    (tree / h.HELDOUT_LABELS).write_text("".join(json.dumps({"ticket_id": f"T-{i}", "split": "dev"}) + "\n" for i in (1, 2, 3)), encoding="utf-8")
    record = h.build_record(tree)
    (tree / h.FREEZE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tree / h.FREEZE_PATH).write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    monkeypatch.setattr(h.run_mod, "main", fake_main_factory(tree))
    h.cmd_run(tree, "7b", None)
    with pytest.raises(h.GateError, match="labels do not match"):
        h.cmd_score(tree, tree / "data/runs/run-1")