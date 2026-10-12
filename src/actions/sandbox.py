"""The sandbox database: a writable copy of the development data plus the approval, ledger and replacement tables.

The frozen development database is never opened for writing (ADR-005). ``open_sandbox`` refuses any file that does not carry the
``sandbox_meta`` marker table, so a path to the frozen database cannot be used by mistake: it has no such table.
"""
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MARKER = "sandbox_meta"
SCHEMA = f"""
CREATE TABLE {MARKER} (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE approvals (
    approval_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, action TEXT NOT NULL, order_id TEXT NOT NULL,
    payment_id TEXT NOT NULL DEFAULT '', amount_cents INTEGER, address TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('approved', 'rejected')), approver TEXT NOT NULL, rule_id TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '', decided_at TEXT NOT NULL);
CREATE TABLE action_ledger (
    idempotency_key TEXT PRIMARY KEY, approval_id TEXT NOT NULL, ticket_id TEXT NOT NULL, action TEXT NOT NULL, order_id TEXT NOT NULL,
    result TEXT NOT NULL, executed_at TEXT NOT NULL);
CREATE TABLE replacements (
    replacement_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, ticket_id TEXT NOT NULL, approval_id TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class SandboxError(Exception):
    pass


def file_sha256(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def create_sandbox(source, dest, force: bool = False) -> Path:
    """Copy ``source`` (opened read-only) to ``dest`` and add the sandbox tables. Refuses to overwrite unless ``force``."""
    source, dest = Path(source), Path(dest)
    if not source.exists():
        raise SandboxError(f"source database not found: {source}")
    if dest.resolve() == source.resolve():
        raise SandboxError("the sandbox may not be the source database")
    if dest.exists() and not force:
        raise SandboxError(f"{dest} already exists (use --force to replace it)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            dest.unlink()
        except PermissionError:                                      # Windows: another process (for example the actions server) has the file open
            raise SandboxError(f"{dest} is in use by another process; stop the actions server and try again")
    sha = file_sha256(source)
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
        out.executescript(SCHEMA)
        out.executemany(f"INSERT INTO {MARKER} VALUES (?, ?)",
                        [("source_file", source.name), ("source_sha256", sha), ("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))])
        out.commit()
    finally:
        src.close()
        out.close()
    return dest


def open_sandbox(path) -> sqlite3.Connection:
    path = Path(path)
    if not path.exists():
        raise SandboxError(f"sandbox database not found: {path} (create it with: python -m src.actions init)")
    conn = sqlite3.connect(path, timeout=10, isolation_level=None, check_same_thread=False)   # explicit transactions; the MCP SDK runs sync tools in a worker thread, so the service serialises use of the connection
    conn.row_factory = sqlite3.Row
    has_marker = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (MARKER,)).fetchone()
    if not has_marker:
        conn.close()
        raise SandboxError(f"{path} is not a sandbox database (no {MARKER} table); the frozen data is never opened for writing")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn