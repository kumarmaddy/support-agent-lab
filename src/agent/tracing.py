"""Run traces (phase-1-design.md, section 7).

One directory per run, ``<root>/<run_id>/``, holding:

    run.json          what was run: model tag and digest, prompt versions and hashes, seed, dataset file hash, code version
    trace.jsonl       one line per pipeline step per ticket (outcome, timings, tokens, model answers, input fingerprint)
    resolutions.jsonl one line per ticket: the action, reason, article and reply
    summary.json      counts and timings derived from the two files above (written when the run is closed)

Files are written line by line and flushed, so an interrupted run still leaves a readable trace. A run directory is never
reused or overwritten. Traces hold fingerprints of inputs rather than the inputs: no ticket text and no email address. They are
kept outside the operational database so every tool can keep opening it read-only (ADR-005).
"""
import json
import math
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1
TRACE, RESOLUTIONS, RUN, SUMMARY = "trace.jsonl", "resolutions.jsonl", "run.json", "summary.json"


def new_run_id(now: Optional[datetime] = None, token: Optional[str] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"run-{now:%Y%m%d-%H%M%S}-{token or secrets.token_hex(3)}"


def _line(record: dict) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"


class TraceWriter:
    """Create a run directory and append trace lines to it. Use as a context manager."""

    def __init__(self, root: Path, run_id: str, meta: dict):
        self.run_id = run_id
        self.dir = Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=False)                 # a run id is never reused
        self.meta = {"schema": SCHEMA_VERSION, "run_id": run_id, **meta}
        (self.dir / RUN).write_text(json.dumps(self.meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        self._trace = open(self.dir / TRACE, "a", encoding="utf-8", newline="\n")
        self._resolutions = open(self.dir / RESOLUTIONS, "a", encoding="utf-8", newline="\n")
        self.tickets = 0

    def write(self, resolution) -> None:
        for seq, step in enumerate(resolution.steps):
            self._trace.write(_line({"schema": SCHEMA_VERSION, "run_id": self.run_id, "ticket_id": resolution.ticket_id, "seq": seq, **step}))
        self._resolutions.write(_line({
            "schema": SCHEMA_VERSION, "run_id": self.run_id, "ticket_id": resolution.ticket_id, "action": resolution.action,
            "reason": resolution.reason, "article": resolution.article, "reply_source": resolution.reply_source,
            "reply": resolution.reply, "facts": resolution.facts}))
        self._trace.flush()
        self._resolutions.flush()
        self.tickets += 1

    def close(self) -> dict:
        self._trace.close()
        self._resolutions.close()
        summary = summarise_run(self.dir)
        (self.dir / SUMMARY).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return summary

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self._trace.closed:
            self.close()


# ------------------------------------------------------------------ reading a run back
def read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def percentile(values: list, pct: float) -> Optional[int]:
    """Nearest-rank percentile of a list of numbers; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def summarise_run(run_dir: Path) -> dict:
    """Counts and timings derived from the trace files only (so a summary can be rebuilt at any time)."""
    run_dir = Path(run_dir)
    steps, resolutions = read_jsonl(run_dir / TRACE), read_jsonl(run_dir / RESOLUTIONS)
    by = lambda key: {k: sum(1 for r in resolutions if r[key] == k) for k in sorted({r[key] for r in resolutions}, key=str)}
    per_step, per_ticket = {}, {}
    for st in steps:
        per_step.setdefault(st["step"], []).append(st["latency_ms"])
        per_ticket[st["ticket_id"]] = per_ticket.get(st["ticket_id"], 0) + st["latency_ms"]
    drafts = [st for st in steps if st["step"] == "draft_reply" and st.get("model_calls", 0) > 0]
    rejected: dict = {}
    for st in steps:
        if st["step"] == "draft_reply":
            for codes in st.get("rejected_drafts", []):
                for code in codes:
                    rejected[code] = rejected.get(code, 0) + 1
    reads = [st for st in steps if st["step"] == "read_ticket"]
    fallbacks = sum(1 for st in drafts if st["source"] == "template")
    return {
        "schema": SCHEMA_VERSION,
        "tickets": len(resolutions),
        "actions": by("action"),
        "reasons": by("reason"),
        "reply_sources": by("reply_source"),
        "read_outcomes": {k: sum(1 for st in reads if st["outcome"] == k) for k in sorted({st["outcome"] for st in reads})},
        "drafts_by_model": len(drafts),
        "template_fallbacks": fallbacks,
        "template_fallback_share": (fallbacks / len(drafts)) if drafts else None,
        "rejected_draft_codes": dict(sorted(rejected.items())),
        "model_calls": sum(st.get("model_calls", 0) for st in steps),
        "tokens_in": sum(st.get("tokens_in", 0) for st in steps),
        "tokens_out": sum(st.get("tokens_out", 0) for st in steps),
        "latency_ms": {
            "per_step": {name: {"p50": percentile(v, 50), "p90": percentile(v, 90), "max": max(v)} for name, v in sorted(per_step.items())},
            "per_ticket": {"p50": percentile(list(per_ticket.values()), 50), "p90": percentile(list(per_ticket.values()), 90),
                           "max": max(per_ticket.values()) if per_ticket else None},
        },
    }