import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.agent import run as runner
from src.agent.pipeline import internal_guidance, run_ticket
from src.agent.prompting import load_prompt
from src.agent.tools import Toolbox
from src.agent.tracing import RESOLUTIONS, RUN, SUMMARY, TRACE, TraceWriter, new_run_id, percentile, read_jsonl, summarise_run
from tests.agent.support import ScriptedModel, in_slice, oracle_read

READ, REPLY = load_prompt("read_ticket", "v3"), load_prompt("reply", "v1")
KB_DIR = Path(__file__).resolve().parents[2] / "data" / "seed" / "kb"
BAD_BODY = {"body": "We will refund you $10."}


@pytest.fixture(scope="module")
def world(dev_dataset, articles):
    db, _, labels = dev_dataset
    box = Toolbox.from_path(db)
    by_id = {lab["ticket_id"]: lab for lab in labels}
    yield db, box, by_id, internal_guidance(articles)
    box.conn.close()


class ModelTicket:                       # the scripted reader needs to know which ticket it is reading
    current = None


def run_many(world, tmp_path, ids, reply=None, run_id="run-test"):
    db, box, by_id, internal = world
    model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ModelTicket.current), reply=reply)
    writer = TraceWriter(tmp_path, run_id, {"model": {"tag": "scripted"}})
    for tid in ids:
        ModelTicket.current = tid
        writer.write(run_ticket(box, model, READ, REPLY, internal, tid))
    return writer


def slice_ids(world, n):
    return [t for t, l in world[2].items() if in_slice(l)][:n]


# ------------------------------------------------------------------ run ids and the writer
def test_run_id_format_and_uniqueness():
    fixed = new_run_id(datetime(2026, 10, 8, 14, 30, 5, tzinfo=timezone.utc), "ab12")
    assert fixed == "run-20261008-143005-ab12"
    assert len({new_run_id() for _ in range(50)}) == 50


def test_a_run_directory_is_never_reused(tmp_path):
    TraceWriter(tmp_path, "run-a", {}).close()
    with pytest.raises(FileExistsError):
        TraceWriter(tmp_path, "run-a", {})


def test_run_json_records_the_meta(tmp_path):
    TraceWriter(tmp_path, "run-a", {"seed": 3, "model": {"tag": "x:1b"}}).close()
    meta = json.loads((tmp_path / "run-a" / RUN).read_text(encoding="utf-8"))
    assert meta["run_id"] == "run-a" and meta["seed"] == 3 and meta["schema"] == 1


def test_lines_are_written_and_flushed_before_the_run_closes(world, tmp_path):
    ids = slice_ids(world, 3)
    writer = run_many(world, tmp_path, ids)
    assert len(read_jsonl(writer.dir / RESOLUTIONS)) == 3             # readable while the run is still open
    steps = read_jsonl(writer.dir / TRACE)
    assert {s["ticket_id"] for s in steps} == set(ids)
    for tid in ids:
        mine = [s for s in steps if s["ticket_id"] == tid]
        assert [s["seq"] for s in mine] == list(range(len(mine))) and mine[0]["step"] == "get_ticket"
        assert all(s["run_id"] == "run-test" and s["schema"] == 1 and len(s["input_hash"]) == 16 for s in mine)
    writer.close()


def test_an_interrupted_run_still_leaves_a_readable_trace_and_summary(world, tmp_path):
    ids = slice_ids(world, 2)
    with pytest.raises(RuntimeError):
        with TraceWriter(tmp_path, "run-x", {}) as writer:
            db, box, by_id, internal = world
            model = ScriptedModel(read=lambda s, u, seed: oracle_read(by_id, box, ids[0]))
            writer.write(run_ticket(box, model, READ, REPLY, internal, ids[0]))
            raise RuntimeError("crash")
    assert json.loads((tmp_path / "run-x" / SUMMARY).read_text(encoding="utf-8"))["tickets"] == 1


# ------------------------------------------------------------------ what is (and is not) stored
def test_traces_hold_fingerprints_not_ticket_text_or_email_addresses(world, tmp_path):
    db, box, by_id, internal = world
    ids = slice_ids(world, 5)
    writer = run_many(world, tmp_path, ids)
    writer.close()
    trace_text = (writer.dir / TRACE).read_text(encoding="utf-8")
    for tid in ids:
        ticket = box.get_ticket(tid).data
        assert ticket.body not in trace_text and ticket.subject not in trace_text and ticket.customer_email not in trace_text
        assert ticket.customer_email not in (writer.dir / RESOLUTIONS).read_text(encoding="utf-8")


def test_the_same_input_gives_the_same_fingerprint(world, tmp_path):
    ids = slice_ids(world, 2)
    a = run_many(world, tmp_path, ids, run_id="run-a")
    b = run_many(world, tmp_path, ids, run_id="run-b")
    a.close(), b.close()
    key = lambda w: {(s["ticket_id"], s["step"]): s["input_hash"] for s in read_jsonl(w.dir / TRACE)}
    assert key(a) == key(b)
    hashes = [h for (tid, step), h in key(a).items() if step == "read_ticket"]
    assert len(set(hashes)) == len(hashes)                          # different tickets, different fingerprints


def test_model_attempts_are_traced_with_seed_and_answer(world, tmp_path):
    writer = run_many(world, tmp_path, slice_ids(world, 1))
    writer.close()
    read = next(s for s in read_jsonl(writer.dir / TRACE) if s["step"] == "read_ticket")
    assert read["prompt"] == "read_ticket.v3" and len(read["prompt_sha256"]) == 64
    assert read["attempts"][0]["seed"] == 0 and read["attempts"][0]["content"]["category"] == "order_status"


# ------------------------------------------------------------------ summaries
def test_percentiles_use_nearest_rank():
    assert percentile(list(range(1, 11)), 50) == 5 and percentile(list(range(1, 11)), 90) == 9
    assert percentile([7], 90) == 7 and percentile([], 50) is None
    assert percentile(list(range(1, 8)), 50) == 4 and percentile([3, 1, 2], 50) == 2         # rounds the rank up; input need not be sorted


def test_summary_counts_and_template_fallbacks(world, tmp_path):
    ids = [t for t, l in world[2].items() if in_slice(l) and l["expected_actions"][0] in ("provide_info", "request_info")][:6]
    good = run_many(world, tmp_path, ids, reply=lambda s, u, seed: {"body": "x"}, run_id="run-bad")        # every draft invalid
    summary = good.close()
    assert summary["tickets"] == 6 and summary["drafts_by_model"] == 6 and summary["template_fallbacks"] == 6
    assert summary["template_fallback_share"] == 1.0 and summary["reply_sources"] == {"template": 6}
    assert summary["model_calls"] == 6 * 3                           # one read call and two draft attempts each
    assert summary["actions"]["provide_info"] + summary["actions"].get("request_info", 0) == 6
    assert summary["rejected_draft_codes"]["missing_fact"] >= 6
    assert summary["read_outcomes"] == {"ok": 6}


def test_a_promising_draft_is_counted_by_rule_code(world, tmp_path):
    ids = [t for t, l in world[2].items() if l["scenario_id"] == "S01"][:2]
    summary = run_many(world, tmp_path, ids, reply=lambda s, u, seed: BAD_BODY).close()
    assert summary["rejected_draft_codes"].get("promise") == 4 and summary["rejected_draft_codes"].get("amount") == 4


def test_the_summary_can_be_rebuilt_from_the_files(world, tmp_path):
    writer = run_many(world, tmp_path, slice_ids(world, 4))
    written = writer.close()
    assert summarise_run(writer.dir) == written == json.loads((writer.dir / SUMMARY).read_text(encoding="utf-8"))
    assert written["latency_ms"]["per_ticket"]["p50"] is not None and "decide" in written["latency_ms"]["per_step"]


def test_hand_overs_make_no_draft_calls_and_are_not_counted_as_fallbacks(world, tmp_path):
    ids = [t for t, l in world[2].items() if l["scenario_id"] == "S22"][:3]
    summary = run_many(world, tmp_path, ids).close()
    assert summary["drafts_by_model"] == 0 and summary["template_fallback_share"] is None and summary["model_calls"] == 3


# ------------------------------------------------------------------ the runner
def test_the_runner_refuses_the_heldout_split():
    with pytest.raises(SystemExit):
        runner.check_not_heldout(Path("data/generated/heldout/support.db"))
    with pytest.raises(SystemExit):
        runner.main(["--db", "data/generated/heldout/support.db"])
    runner.check_not_heldout(Path("data/generated/dev/support.db"))


def test_select_ids_by_limit_and_by_file(world, tmp_path):
    box = world[1]
    assert runner.select_ids(box, 3) == sorted(world[2])[:3] and len(runner.select_ids(box)) == 150
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("T-000010\n\nT-000005\n", encoding="utf-8")
    assert runner.select_ids(box, ids_file=ids_file) == ["T-000010", "T-000005"]


def test_meta_names_the_model_prompts_dataset_and_seed(world):
    db = world[0]
    meta = runner.build_meta(ScriptedModel(), READ, REPLY, db, 7, ["T-000001"], ["--limit", "1"], digest="abc")
    assert meta["model"] == {"tag": "scripted:1b", "digest": "abc"} and meta["seed"] == 7 and meta["tickets"] == 1
    assert meta["prompts"]["read"] == {"label": "read_ticket.v3", "sha256": READ.sha256}
    assert meta["dataset"]["db_sha256"] == runner.file_sha256(db) and len(meta["dataset"]["db_sha256"]) == 64
    assert set(meta["code"]) == {"commit", "dirty"} and meta["argv"] == ["--limit", "1"]
    json.dumps(meta)


def test_run_tickets_writes_one_resolution_per_ticket_and_reports_progress(world, tmp_path):
    db, box, by_id, internal = world
    ids, seen = slice_ids(world, 3), []
    model = ScriptedModel(read=lambda s, u, seed: {"category": "order_status", "deadline_phrase": "", "mentions_chargeback_or_legal": False})
    with TraceWriter(tmp_path, "run-r", {}) as writer:
        results = runner.run_tickets(box, model, READ, REPLY, internal, ids, writer, progress=lambda i, n, r: seen.append((i, n, r.ticket_id)))
    assert [r.ticket_id for r in results] == ids and seen == [(1, 3, ids[0]), (2, 3, ids[1]), (3, 3, ids[2])]


def test_main_runs_end_to_end_with_a_fake_client(world, tmp_path, monkeypatch, capsys):
    class FakeClient(ScriptedModel):
        def __init__(self, model):
            super().__init__(read=lambda s, u, seed: {"category": "order_status", "deadline_phrase": "", "mentions_chargeback_or_legal": False},
                             reply=lambda s, u, seed: "request_failed")
            self.model = model
        def digest(self):
            return "fakedigest"
    monkeypatch.setattr(runner, "OllamaClient", FakeClient)
    code = runner.main(["--db", str(world[0]), "--kb", str(KB_DIR), "--out", str(tmp_path), "--limit", "4", "--model", "fake:1b"])
    assert code == 0
    run_dir = next(tmp_path.iterdir())
    meta = json.loads((run_dir / RUN).read_text(encoding="utf-8"))
    assert meta["model"] == {"tag": "fake:1b", "digest": "fakedigest"} and meta["tickets"] == 4
    assert json.loads((run_dir / SUMMARY).read_text(encoding="utf-8"))["tickets"] == 4
    assert "written to" in capsys.readouterr().out


def test_the_read_fingerprint_is_a_hash_of_the_ticket_text_not_its_id(world, tmp_path):
    from src.agent.pipeline import _hash
    db, box, by_id, internal = world
    tid = slice_ids(world, 1)[0]
    writer = run_many(world, tmp_path, [tid])
    writer.close()
    ticket = box.get_ticket(tid).data
    read = next(s for s in read_jsonl(writer.dir / TRACE) if s["step"] == "read_ticket")
    assert read["input_hash"] == _hash(ticket.subject, ticket.body) != _hash(tid)