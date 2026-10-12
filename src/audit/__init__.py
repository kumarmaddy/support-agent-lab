"""Audit log and redaction (phase-3-design.md, section 5.3; stage 3.4).

``redact`` removes personal identifiers from anything before it is written. ``log`` is an append-only, hash-chained JSONL file with one
event per decision, queryable by ticket id: ``python -m src.audit --ticket T-000070``.
"""