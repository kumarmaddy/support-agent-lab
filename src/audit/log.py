"""Append-only, hash-chained audit log (phase-3-design.md, section 5.3).

One JSON object per line. Every event carries the hash of the event before it, so changing or removing a line breaks the chain from that
point on and ``verify`` reports where. The first event chains to ``GENESIS``. Removing lines from the END of the file leaves a valid chain;
that is only detectable against a head hash noted elsewhere, which is why a run prints its head and ``verify`` accepts ``expected_head``.

Event fields: schema, seq, ts, event, ticket_id, run_id, actor, data, prev, hash. ``hash`` is the sha256 of the canonical JSON of the
other fields. ``data`` is redacted by ``append`` itself (redact.py), so no caller can forget to do it; if anything identifiable is still
visible afterwards the data is replaced by a marker (fail closed) rather than written.

This log is separate from the operational database: the empty ``audit_log`` table in the frozen dev database stays untouched (ADR-005).
"""
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from src.audit.redact import IDENTIFIER_KEYS, leftovers, redact

SCHEMA_VERSION = 1
GENESIS = "0" * 64
POLICY_DECISION, DECISION, HAND_OVER = "policy_decision", "decision", "hand_over"
APPROVAL, REJECTION, EDIT, EXECUTION = "approval", "rejection", "edit", "execution"      # written by stages 3.5 and 3.6
TOOL_READ = "tool_read"                                                                       # stage 3.7: a read through the MCP adapter
EVENTS = (DECISION, POLICY_DECISION, HAND_OVER, APPROVAL, REJECTION, EDIT, EXECUTION, TOOL_READ)
LOCK_STALE_SECONDS = 30.0
_THREAD_LOCK = threading.Lock()


class AuditError(Exception):
    pass


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def event_hash(event: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in event.items() if k != "hash"}).encode("utf-8")).hexdigest()


def _strings(value, key: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, k)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v, key)
    elif isinstance(value, str) and key not in IDENTIFIER_KEYS:
        yield value


def clean(data):
    """Redact ``data`` and check the result. Returns (data, kinds_still_visible)."""
    data = redact(data)
    kinds = sorted({k for s in _strings(data) for k in leftovers(s)})
    return data, kinds


def _last_line(path: Path) -> Optional[bytes]:
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        block, buf = 4096, b""
        while end > 0:
            start = max(0, end - block)
            fh.seek(start)
            buf = fh.read(end - start) + buf
            lines = [x for x in buf.split(b"\n") if x.strip()]
            if len(lines) > 1 or (start == 0 and lines):
                return lines[-1]
            end = start
            block *= 2
    return None


class _FileLock:
    """Exclusive lock through a lock file created with O_EXCL (works across processes on Windows and Linux). A lock older than
    LOCK_STALE_SECONDS is taken to belong to a crashed writer and is removed."""

    def __init__(self, path: Path, timeout: float = 10.0):
        self.path, self.timeout = Path(str(path) + ".lock"), timeout

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE_SECONDS:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                if time.monotonic() > deadline:
                    raise AuditError(f"could not lock {self.path} within {self.timeout}s")
                time.sleep(0.01)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


class AuditLog:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))

    def head(self) -> tuple:
        """(seq, hash) of the last event; (0, GENESIS) for an empty or missing log."""
        if not self.path.exists():
            return 0, GENESIS
        line = _last_line(self.path)
        if line is None:
            return 0, GENESIS
        last = json.loads(line)
        return last["seq"], last["hash"]

    def append(self, event: str, ticket_id: str, data: dict, run_id: str = "", actor: str = "agent") -> dict:
        if event not in EVENTS:
            raise AuditError(f"unknown event type {event!r}")
        data, kinds = clean(data)
        if kinds:                                                    # fail closed: never write what could not be cleaned
            data = {"redaction_failed": kinds}
        with _THREAD_LOCK, _FileLock(self.path):
            seq, prev = self.head()
            record = {"schema": SCHEMA_VERSION, "seq": seq + 1, "ts": self._clock(), "event": event, "ticket_id": ticket_id,
                      "run_id": run_id, "actor": actor, "data": data, "prev": prev}
            record["hash"] = event_hash(record)
            with open(self.path, "ab") as fh:
                fh.write((canonical(record) + "\n").encode("utf-8"))
                fh.flush()
                os.fsync(fh.fileno())
        return record

    def record_resolution(self, resolution, run_id: str, context: Optional[dict] = None) -> list:
        """Write the events for one ticket: the policy decision (if any), the decision, and the hand-over note (if any)."""
        context = context or {}
        written = []
        if resolution.policy:
            written.append(self.append(POLICY_DECISION, resolution.ticket_id, dict(resolution.policy), run_id))
        reading = next((s.get("reading") for s in resolution.steps if s.get("step") == "read_ticket"), None)
        data = {"action": resolution.action, "reason": resolution.reason, "article": resolution.article, "reply_source": resolution.reply_source,
                "reply_sha256": hashlib.sha256(resolution.reply.encode("utf-8")).hexdigest(), "reply": resolution.reply,
                "facts": resolution.facts, "reading": reading, "steps": [s["step"] for s in resolution.steps], "context": context}
        written.append(self.append(DECISION, resolution.ticket_id, data, run_id))
        if resolution.handover:
            written.append(self.append(HAND_OVER, resolution.ticket_id, dict(resolution.handover), run_id))
        return written


# ------------------------------------------------------------------ reading and checking
def read_events(path) -> list:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def query(path, ticket_id: str) -> list:
    return [e for e in read_events(path) if e["ticket_id"] == ticket_id]


@dataclass(frozen=True)
class Verification:
    ok: bool
    events: int
    head: str
    problem: str = ""


def verify(path, expected_head: Optional[str] = None) -> Verification:
    """Walk the chain. Reports the first bad line (not JSON, wrong seq, wrong prev, wrong hash). With ``expected_head`` it also catches
    events removed from the end."""
    path = Path(path)
    if not path.exists():
        return Verification(False, 0, GENESIS, "log file not found")
    prev, count = GENESIS, 0
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
            fields_ok = all(k in e for k in ("seq", "prev", "hash"))
        except ValueError:
            return Verification(False, count, prev, f"line {number}: not valid JSON")
        if not fields_ok:
            return Verification(False, count, prev, f"line {number}: missing chain fields")
        if e["seq"] != count + 1:
            return Verification(False, count, prev, f"line {number}: sequence {e['seq']}, expected {count + 1} (an event was removed or inserted)")
        if e["prev"] != prev:
            return Verification(False, count, prev, f"line {number}: does not follow the event before it")
        if event_hash(e) != e["hash"]:
            return Verification(False, count, prev, f"line {number}: content does not match its hash (the event was changed)")
        prev, count = e["hash"], count + 1
    if expected_head and expected_head != prev:
        return Verification(False, count, prev, "last event differs from the expected head (events were removed from the end, or added)")
    return Verification(True, count, prev)