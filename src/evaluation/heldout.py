"""Freeze record and the gate to the held-out split (stage 4.2).

Commands (from the repository root):
    python -m src.evaluation.heldout create              # write docs/evidence/phase-4-freeze-record.json (once)
    python -m src.evaluation.heldout check               # compare the working tree with the record
    python -m src.evaluation.heldout run --tag 7b        # the single scored run for a model (tag 7b or 3b)
    python -m src.evaluation.heldout score data/runs/<run folder>

Why a separate module: ``src.agent.run`` and ``src.evaluation.score`` refuse the held-out split, and they are left unchanged so
that this stage cannot alter the agent or the scorer it freezes. This module is the only way in. It opens the split only when
(1) every frozen file still matches the freeze record, (2) the model has not already had its held-out run, and (3) for scoring, the
run was made by this gate on the frozen held-out database. Scoring logic is the unchanged ``score_run`` and ``render``.
"""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from src.agent import run as run_mod
from src.datagen.freeze import table_digest
from src.evaluation import score as sc

FREEZE_PATH = Path("docs/evidence/phase-4-freeze-record.json")
REGISTRY_PATH = Path("data/audit/heldout-registry.json")      # git-ignored with the audit logs, so a run never starts from a dirty tree
HELDOUT_DB = Path("data/generated/heldout/support.db")
HELDOUT_LABELS = Path("data/labels/heldout/labels.jsonl")
MARKER = "heldout_run.json"
RECORD_VERSION = 1

# What the freeze covers. Tests are not frozen: they do not change a result.
FROZEN_GLOBS = ("src/**/*.py", "src/agent/prompts/*.md", "config/*.toml", "data/seed/kb/**/*",
                "data/security/cases.jsonl", "data/manifest.json")
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".jsonl", ".txt"}

# One configuration per model: the one of the final Phase 3 development run (docs/evidence/phase-3-final-run.txt).
MODELS = {"7b": "qwen2.5:7b", "3b": "llama3.2:3b"}
RUN_FLAGS = ["--read-prompt", "v5", "--knowledge", "--knowledge-first", "--transactions"]


class GateError(SystemExit):
    """Raised for every refusal so that the message reaches the user and the exit code is non-zero."""


# ------------------------------------------------------------------ hashing
def file_digest(path: Path) -> str:
    """SHA-256 of a file. Text files are hashed with Windows line endings folded to LF, so a checkout setting cannot change the digest."""
    data = Path(path).read_bytes()
    if Path(path).suffix.lower() in TEXT_SUFFIXES:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def frozen_files(root: Path) -> list:
    found = set()
    for pattern in FROZEN_GLOBS:
        for path in Path(root).glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                found.add(path.relative_to(root).as_posix())
    return sorted(found)


def database_content_digest(path: Path) -> str:
    """Digest of the rows of every table (the method of the dataset manifest), not of the file layout."""
    conn = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        tables = {name: list(table_digest(conn, name)) for name in names}
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(tables, sort_keys=True).encode("utf-8")).hexdigest()


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def label_line_count(path: Path) -> int:
    """Number of labelled tickets, counted as non-empty lines. The label content is not parsed."""
    return sum(1 for line in Path(path).read_bytes().splitlines() if line.strip())


def git_state(root: Path) -> dict:
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except Exception:
        return {"commit": "unknown", "dirty": None}


def canonical(record: dict) -> bytes:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def record_digest(record: dict) -> str:
    return hashlib.sha256(canonical({k: v for k, v in record.items() if k != "record_sha256"})).hexdigest()


# ------------------------------------------------------------------ freeze record
def build_record(root: Path = Path(".")) -> dict:
    root = Path(root)
    record = {
        "record_version": RECORD_VERSION,
        "created": date.today().isoformat(),
        "git": git_state(root),
        "scope": list(FROZEN_GLOBS),
        "files": {rel: file_digest(root / rel) for rel in frozen_files(root)},
        "heldout": {
            "db_file": HELDOUT_DB.as_posix(),
            "db_file_sha256": raw_sha256(root / HELDOUT_DB),
            "db_content_sha256": database_content_digest(root / HELDOUT_DB),
            "labels_file": HELDOUT_LABELS.as_posix(),
            "labels_sha256": file_digest(root / HELDOUT_LABELS),
            "tickets": label_line_count(root / HELDOUT_LABELS),
        },
    }
    record["record_sha256"] = record_digest(record)
    return record


def load_record(root: Path = Path("."), path: Path = FREEZE_PATH) -> dict:
    full = Path(root) / path
    if not full.exists():
        raise GateError(f"No freeze record at {path}. Run: python -m src.evaluation.heldout create")
    return json.loads(full.read_text(encoding="utf-8"))


def verify_record(record: dict, root: Path = Path(".")) -> list:
    """Every way the working tree differs from the record. An empty list means the freeze holds."""
    root, problems = Path(root), []
    if record.get("record_sha256") != record_digest(record):
        problems.append("the freeze record itself has been edited (its own digest does not match)")
    recorded, current = record.get("files", {}), frozen_files(root)
    for rel in sorted(set(recorded) - set(current)):
        problems.append(f"frozen file missing: {rel}")
    for rel in sorted(set(current) - set(recorded)):
        problems.append(f"file added since the freeze: {rel}")
    for rel in sorted(set(recorded) & set(current)):
        if file_digest(root / rel) != recorded[rel]:
            problems.append(f"frozen file changed: {rel}")
    held = record.get("heldout", {})
    db, labels = root / HELDOUT_DB, root / HELDOUT_LABELS
    if not db.exists() or not labels.exists():
        problems.append("held-out database or labels file is missing")
    else:
        if raw_sha256(db) != held.get("db_file_sha256"):
            problems.append("held-out database file changed")
        if database_content_digest(db) != held.get("db_content_sha256"):
            problems.append("held-out database content changed")
        if file_digest(labels) != held.get("labels_sha256"):
            problems.append("held-out labels file changed")
    return problems


def require_freeze(root: Path) -> dict:
    record = load_record(root)
    problems = verify_record(record, root)
    if problems:
        raise GateError("The freeze does not hold, so the held-out split stays closed:\n  - " + "\n  - ".join(problems))
    return record


# ------------------------------------------------------------------ registry: one run per model
def load_registry(root: Path) -> dict:
    full = Path(root) / REGISTRY_PATH
    return json.loads(full.read_text(encoding="utf-8")) if full.exists() else {"entries": []}


def save_registry(root: Path, registry: dict) -> None:
    full = Path(root) / REGISTRY_PATH
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def begin_entry(root: Path, tag: str, model: str, record_sha: str, reason: Optional[str]) -> dict:
    registry = load_registry(root)
    earlier = [e for e in registry["entries"] if e["tag"] == tag]
    if earlier and not reason:
        raise GateError(f"The held-out split has already been opened for the {tag} model (status: {earlier[-1]['status']}). "
                        "It is run once. After a crash before the results were complete, an unchanged re-run is allowed with "
                        "--rerun-reason \"what happened\"; the reason is recorded.")
    entry = {"tag": tag, "model": model, "status": "started", "run_id": None, "freeze_record_sha256": record_sha,
             "started": date.today().isoformat(), "rerun_reason": reason or None}
    registry["entries"].append(entry)
    save_registry(root, registry)
    return entry


def finish_entry(root: Path, entry: dict, run_id: str) -> None:
    registry = load_registry(root)
    for stored in registry["entries"]:
        if stored["tag"] == entry["tag"] and stored["status"] == "started" and stored["started"] == entry["started"] and stored["run_id"] is None:
            stored["status"], stored["run_id"] = "complete", run_id
    save_registry(root, registry)


def drop_entry(root: Path, entry: dict) -> None:
    """Remove an entry whose run never started a run folder, so a failed start (model server down) does not use up the single run."""
    registry = load_registry(root)
    registry["entries"] = [e for e in registry["entries"] if e is not entry and e != entry]
    save_registry(root, registry)


# ------------------------------------------------------------------ commands
def cmd_create(root: Path) -> int:
    root = Path(root)
    if (root / FREEZE_PATH).exists():
        raise GateError("A freeze record already exists. It is created once, before the run, and is never replaced.")
    if load_registry(root)["entries"]:
        raise GateError("The held-out split has already been opened; a new freeze record would not mean anything.")
    record = build_record(root)
    if record["git"]["dirty"]:
        raise GateError("The working tree has uncommitted changes. Commit and tag phase-3-complete first, then create the record.")
    (root / FREEZE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / FREEZE_PATH).write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"freeze record written to {FREEZE_PATH}")
    print(f"  commit {record['git']['commit']}  files {len(record['files'])}  held-out tickets {record['heldout']['tickets']}")
    print(f"  record sha256 {record['record_sha256']}")
    print("Next: commit the record, then tag phase-4-frozen.")
    return 0


def cmd_check(root: Path) -> int:
    record = load_record(root)
    problems = verify_record(record, root)
    if problems:
        print("The freeze does NOT hold:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"The freeze holds: {len(record['files'])} files and the held-out database and labels match. record sha256 {record['record_sha256']}")
    return 0


def cmd_run(root: Path, tag: str, reason: Optional[str]) -> int:
    root = Path(root)
    record = require_freeze(root)
    entry = begin_entry(root, tag, MODELS[tag], record["record_sha256"], reason)
    runs_dir = root / "data" / "runs"
    before = {p.name for p in runs_dir.iterdir()} if runs_dir.exists() else set()
    argv = ["--db", str(root / HELDOUT_DB), "--kb", str(root / "data" / "seed" / "kb"), "--out", str(runs_dir), "--model", MODELS[tag],
            "--policy", str(root / "config" / "policy.toml"), "--audit", str(root / "data" / "audit" / f"heldout-{tag}.jsonl"), *RUN_FLAGS]
    original, allowed = run_mod.check_not_heldout, (root / HELDOUT_DB).resolve()
    # The runner's own guard is lifted for this one database only, and restored afterwards (even after a failure).
    run_mod.check_not_heldout = lambda db: None if Path(db).resolve() == allowed else original(db)
    try:
        code = run_mod.main(argv)
    except BaseException:
        created = sorted({p.name for p in runs_dir.iterdir()} - before) if runs_dir.exists() else []
        if not created:                                    # nothing was run (for example Ollama is not running): the split was not used
            drop_entry(root, entry)
        raise
    finally:
        run_mod.check_not_heldout = original
    created = sorted({p.name for p in runs_dir.iterdir()} - before) if runs_dir.exists() else []
    if code != 0 or len(created) != 1:
        raise GateError(f"The run did not produce exactly one new run folder (found {created}); the registry entry stays 'started'.")
    run_id = created[0]
    (runs_dir / run_id / MARKER).write_text(json.dumps({"tag": tag, "model": MODELS[tag], "freeze_record_sha256": record["record_sha256"],
                                                         "status": "complete"}, indent=2) + "\n", encoding="utf-8")
    finish_entry(root, entry, run_id)
    print(f"held-out run recorded: {run_id}. Score it with: python -m src.evaluation.heldout score data/runs/{run_id}")
    return 0


def cmd_score(root: Path, run_dir: Path) -> int:
    root, run_dir = Path(root), Path(run_dir)
    record = require_freeze(root)
    marker_path = run_dir / MARKER
    if not marker_path.exists():
        raise GateError("This run was not made by the held-out gate (no heldout_run.json), so it is not scored against held-out labels.")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("status") != "complete" or marker.get("freeze_record_sha256") != record["record_sha256"]:
        raise GateError("The run is not complete, or was made under a different freeze record.")
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if meta.get("dataset", {}).get("db_sha256") != record["heldout"]["db_file_sha256"]:
        raise GateError("The run was not made on the frozen held-out database.")
    labels = sc.read_jsonl(root / HELDOUT_LABELS)
    if len(labels) != record["heldout"]["tickets"] or any(lab.get("split") != "heldout" for lab in labels):
        raise GateError("The held-out labels do not match the freeze record.")
    result = sc.score_run(run_dir, labels, root / "data" / "seed" / "kb")
    (run_dir / "score.json").write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(sc.render(result))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("create", help="write the freeze record (once, from a clean tree)")
    sub.add_parser("check", help="compare the working tree with the freeze record")
    run = sub.add_parser("run", help="the single scored run for one model")
    run.add_argument("--tag", choices=sorted(MODELS), required=True)
    run.add_argument("--rerun-reason", help="only after a crash before the results were complete; recorded in the registry")
    score = sub.add_parser("score", help="score a run made by this gate against the held-out labels")
    score.add_argument("run_dir", type=Path)
    args = p.parse_args(argv)
    root = Path(".")
    if args.command == "create":
        return cmd_create(root)
    if args.command == "check":
        return cmd_check(root)
    if args.command == "run":
        return cmd_run(root, args.tag, args.rerun_reason)
    return cmd_score(root, args.run_dir)


if __name__ == "__main__":
    raise SystemExit(main())