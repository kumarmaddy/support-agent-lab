"""Stage 3.4: the hash chain, tamper detection, locking and the query command."""
import json
import threading

import pytest

from src.audit import __main__ as cli
from src.audit.log import DECISION, GENESIS, AuditError, AuditLog, _FileLock, query, verify


@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit" / "audit.jsonl", clock=lambda: "2026-10-11T00:00:00.000+00:00")


def fill(log, n=5):
    for i in range(n):
        log.append(DECISION, f"T-{i % 2 + 1:06d}", {"action": "reply", "reason": f"r{i}"}, run_id="run-1")


def lines(log):
    return log.path.read_text(encoding="utf-8").splitlines()


def test_a_new_log_starts_at_genesis_and_chains(log):
    assert log.head() == (0, GENESIS)
    fill(log, 3)
    events = [json.loads(x) for x in lines(log)]
    assert [e["seq"] for e in events] == [1, 2, 3] and events[0]["prev"] == GENESIS
    assert events[1]["prev"] == events[0]["hash"] and log.head() == (3, events[2]["hash"])
    assert verify(log.path).ok and verify(log.path).events == 3


def test_a_second_writer_resumes_the_chain(log):
    fill(log, 2)
    AuditLog(log.path).append(DECISION, "T-000009", {"action": "reply"})
    assert verify(log.path).ok and verify(log.path).events == 3


def test_unknown_event_types_are_refused(log):
    with pytest.raises(AuditError):
        log.append("invented", "T-000001", {})


def test_a_changed_line_is_detected_at_that_line(log):
    fill(log)
    rows = lines(log)
    rows[2] = rows[2].replace('"r2"', '"r9"')
    log.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    v = verify(log.path)
    assert not v.ok and "line 3" in v.problem and "changed" in v.problem


def test_a_removed_middle_line_is_detected(log):
    fill(log)
    rows = lines(log)
    del rows[1]
    log.path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    v = verify(log.path)
    assert not v.ok and "line 2" in v.problem


def test_a_rehashed_edit_still_breaks_the_next_link(log):
    from src.audit.log import event_hash
    fill(log)
    rows = [json.loads(x) for x in lines(log)]
    rows[1]["data"]["reason"] = "forged"
    rows[1]["hash"] = event_hash(rows[1])
    log.path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    v = verify(log.path)
    assert not v.ok and "line 3" in v.problem


def test_removing_the_tail_needs_the_head_to_be_noticed(log):
    fill(log)
    head = log.head()[1]
    log.path.write_text("\n".join(lines(log)[:-1]) + "\n", encoding="utf-8")
    assert verify(log.path).ok                                   # disclosed limit: a shorter chain is still a valid chain
    assert not verify(log.path, expected_head=head).ok


def test_garbage_and_missing_files_fail(log, tmp_path):
    assert not verify(tmp_path / "nope.jsonl").ok
    fill(log, 1)
    with open(log.path, "a", encoding="utf-8") as fh:
        fh.write("not json\n")
    assert "not valid JSON" in verify(log.path).problem


def test_data_is_redacted_by_the_log_itself(log):
    e = log.append(DECISION, "T-000001", {"reply": "Hello Ana,\nwrite to ana@example.com", "facts": {"requested_address": "12 Oak Lane"}})
    assert "ana@example.com" not in json.dumps(e) and e["data"]["facts"]["requested_address"] == "[ADDRESS]"


def test_data_that_cannot_be_cleaned_is_not_written(log, monkeypatch):
    import src.audit.log as mod
    monkeypatch.setattr(mod, "redact", lambda value, key="": value)          # a redaction layer that does nothing
    e = log.append(DECISION, "T-000001", {"reply": "mail ana@example.com"})
    assert e["data"] == {"redaction_failed": ["email"]} and "ana@example.com" not in log.path.read_text(encoding="utf-8")


def test_concurrent_writers_keep_one_unbroken_chain(log):
    def work(k):
        for i in range(15):
            AuditLog(log.path).append(DECISION, f"T-{k:06d}", {"action": "reply", "i": i})
    threads = [threading.Thread(target=work, args=(k,)) for k in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    v = verify(log.path)
    assert v.ok and v.events == 90


def test_a_stale_lock_is_cleared_and_a_live_one_times_out(log):
    lock = log.path.with_name(log.path.name + ".lock")
    lock.write_text("")
    import os, time
    os.utime(lock, (time.time() - 3600, time.time() - 3600))
    fill(log, 1)                                                  # stale lock removed
    lock.write_text("")
    with pytest.raises(AuditError):
        with _FileLock(log.path, timeout=0.1):
            pass
    lock.unlink()


def test_query_and_the_command(log, capsys):
    fill(log, 4)
    assert [e["seq"] for e in query(log.path, "T-000001")] == [1, 3]
    assert cli.main(["--log", str(log.path), "--ticket", "T-000001"]) == 0
    assert "decision" in capsys.readouterr().out
    assert cli.main(["--log", str(log.path), "--ticket", "T-999999"]) == 1
    assert cli.main(["--log", str(log.path), "--verify", "--head", log.head()[1]]) == 0
    assert cli.main(["--log", str(log.path), "--verify", "--head", "0" * 64]) == 2
    log.path.write_text(lines(log)[0].replace("r0", "rX") + "\n", encoding="utf-8")
    assert cli.main(["--log", str(log.path), "--verify"]) == 2