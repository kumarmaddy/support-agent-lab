"""Run the fixed pipeline over development tickets and write a trace.

    python -m src.agent.run --limit 10
    python -m src.agent.run --ids-file ids.txt --model qwen2.5:7b

The runner reads tickets through the read-only tools and never reads labels; which tickets to run is chosen by the caller (the
evaluation harness passes an explicit list). Nothing is sent to a customer. It refuses the held-out split.
"""
import argparse
import hashlib
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.agent.model import ModelClient, OllamaClient
from src.agent.pipeline import Resolution, internal_guidance, run_ticket
from src.agent.prompting import Prompt, load_prompt
from src.agent.tools import Toolbox
from src.agent.tracing import TraceWriter, new_run_id
from src.kb.articles import load_articles

HELDOUT_REFUSAL = "Refusing to run on the held-out split (it is opened once, in Phase 4)."


def check_not_heldout(db_path: Path) -> None:
    if "heldout" in str(db_path).lower():
        raise SystemExit(HELDOUT_REFUSAL)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def code_version() -> dict:
    """Git commit and whether the working tree has uncommitted changes; unknown if git is unavailable."""
    def git(*args):
        return subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    try:
        return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def build_meta(model: ModelClient, read_prompt: Prompt, reply_prompt: Prompt, db_path: Path, seed: int, ticket_ids: list,
               argv: Optional[list] = None, digest: str = "") -> dict:
    return {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {"tag": model.model, "digest": digest},
        "prompts": {"read": {"label": read_prompt.label, "sha256": read_prompt.sha256},
                    "reply": {"label": reply_prompt.label, "sha256": reply_prompt.sha256}},
        "seed": seed,
        "dataset": {"db_file": Path(db_path).name, "db_sha256": file_sha256(db_path)},
        "tickets": len(ticket_ids),
        "code": code_version(),
        "python": platform.python_version(),
        "argv": argv or [],
    }


def run_tickets(box: Toolbox, model: ModelClient, read_prompt: Prompt, reply_prompt: Prompt, internal: frozenset,
                ticket_ids: list, writer: TraceWriter, seed: int = 0,
                progress: Optional[Callable[[int, int, Resolution], None]] = None) -> list:
    results = []
    for index, ticket_id in enumerate(ticket_ids, 1):
        resolution = run_ticket(box, model, read_prompt, reply_prompt, internal, ticket_id, seed)
        writer.write(resolution)
        results.append(resolution)
        if progress:
            progress(index, len(ticket_ids), resolution)
    return results


def select_ids(box: Toolbox, limit: int = 0, ids_file: Optional[Path] = None) -> list:
    if ids_file:
        return [line.strip() for line in Path(ids_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = box.conn.execute("SELECT ticket_id FROM tickets ORDER BY ticket_id").fetchall()
    ids = [r[0] for r in rows]
    return ids[:limit] if limit else ids


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--out", type=Path, default=Path("data/runs"))
    p.add_argument("--model", default="llama3.2:3b")
    p.add_argument("--read-prompt", default="v3")
    p.add_argument("--reply-prompt", default="v1")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--limit", type=int, default=0, help="first N tickets by id (0 = all)")
    p.add_argument("--ids-file", type=Path, help="text file with one ticket id per line")
    args = p.parse_args(argv)
    check_not_heldout(args.db)

    box = Toolbox.from_path(args.db)
    model = OllamaClient(model=args.model)
    read_prompt, reply_prompt = load_prompt("read_ticket", args.read_prompt), load_prompt("reply", args.reply_prompt)
    ids = select_ids(box, args.limit, args.ids_file)
    meta = build_meta(model, read_prompt, reply_prompt, args.db, args.seed, ids, argv if argv is not None else sys.argv[1:], model.digest())
    with TraceWriter(args.out, new_run_id(), meta) as writer:
        run_tickets(box, model, read_prompt, reply_prompt, internal_guidance(load_articles(args.kb)), ids, writer, args.seed,
                    progress=lambda i, n, r: print(f"[{i}/{n}] {r.ticket_id} {r.action} ({r.reason}) reply by {r.reply_source}", flush=True))
        summary = writer.close()
    print(f"\nrun {writer.run_id}: {summary['tickets']} tickets, {summary['model_calls']} model calls")
    print(f"actions {summary['actions']}")
    print(f"template fallbacks {summary['template_fallbacks']}/{summary['drafts_by_model']} model-drafted replies; rejected drafts {summary['rejected_draft_codes']}")
    lat = summary["latency_ms"]["per_ticket"]
    print(f"latency per ticket: median {lat['p50']} ms, p90 {lat['p90']} ms, max {lat['max']} ms")
    print(f"written to {writer.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())