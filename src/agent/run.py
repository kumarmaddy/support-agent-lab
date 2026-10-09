"""Run the fixed pipeline over development tickets and write a trace.

    python -m src.agent.run --limit 10
    python -m src.agent.run --ids-file ids.txt --model llama3.2:3b --read-prompt v3

The runner reads tickets through the read-only tools and never reads labels; which tickets to run is chosen by the caller (the
evaluation harness passes an explicit list). Nothing is sent to a customer. It refuses the held-out split.
"""
import argparse
import hashlib
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.agent.knowledge import DEFAULT_MIN_SCORE, Knowledge
from src.agent.model import ModelClient, OllamaClient
from src.agent.pipeline import Resolution, internal_guidance, run_ticket
from src.agent.prompting import Prompt, load_prompt
from src.agent.reading import MAX_TOKENS, READ_SCHEMA, render_system, render_user
from src.agent.tools import Toolbox
from src.agent.transactions import Transactions
from src.agent.tracing import TraceWriter, new_run_id
from src.kb.embed import model_digest
from src.kb.articles import load_articles

# ADR-007: qwen2.5:7b with read prompt v4 is the default. llama3.2:3b is the fast development model and needs --read-prompt v3
# (v4 makes it invent a deadline phrase on three address-change tickets; the check rejects them and they go to a person).
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_READ_PROMPT = "v4"

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


def warm_up(model: ModelClient, read_prompt: Prompt) -> int:
    """One throwaway call on the real read prompt and schema, so that loading the model and compiling the output grammar are
    not counted in any ticket's latency. Returns milliseconds."""
    started = time.perf_counter()
    model.chat(render_system(read_prompt), render_user("Warm-up", "Where is my order?"), READ_SCHEMA, seed=0, max_tokens=MAX_TOKENS)
    return int((time.perf_counter() - started) * 1000)


def build_meta(model: ModelClient, read_prompt: Prompt, reply_prompt: Prompt, db_path: Path, seed: int, ticket_ids: list,
               argv: Optional[list] = None, digest: str = "", warmup_ms: int = 0, reply_mode: str = "model", knowledge: Optional[Knowledge] = None,
               embed_model: str = "", embed_digest: str = "", transactions: Optional[Transactions] = None) -> dict:
    return {
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {"tag": model.model, "digest": digest},
        "prompts": {"read": {"label": read_prompt.label, "sha256": read_prompt.sha256},
                    "reply": {"label": reply_prompt.label, "sha256": reply_prompt.sha256}},
        "seed": seed,
        "reply_mode": reply_mode,
        "warmup_ms": warmup_ms,
        "dataset": {"db_file": Path(db_path).name, "db_sha256": file_sha256(db_path)},
        "tickets": len(ticket_ids),
        "code": code_version(),
        "knowledge": None if knowledge is None else {"embed_model": embed_model, "embed_digest": embed_digest, "min_score": knowledge.min_score,
                                                       "check_prompt": {"label": knowledge.check_prompt.label, "sha256": knowledge.check_prompt.sha256},
                                                       "reply_prompt": {"label": knowledge.reply_prompt.label, "sha256": knowledge.reply_prompt.sha256}},
        "transactions": None if transactions is None else {"address_prompt": {"label": transactions.address_prompt.label,
                                                                             "sha256": transactions.address_prompt.sha256}},
        "python": platform.python_version(),
        "argv": argv or [],
    }


def run_tickets(box: Toolbox, model: ModelClient, read_prompt: Prompt, reply_prompt: Prompt, internal: frozenset,
                ticket_ids: list, writer: TraceWriter, seed: int = 0, reply_mode: str = "model", knowledge: Optional[Knowledge] = None,
                transactions: Optional[Transactions] = None, progress: Optional[Callable[[int, int, Resolution], None]] = None) -> list:
    results = []
    for index, ticket_id in enumerate(ticket_ids, 1):
        resolution = run_ticket(box, model, read_prompt, reply_prompt, internal, ticket_id, seed, reply_mode, knowledge, transactions)
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
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--read-prompt", default=DEFAULT_READ_PROMPT)
    p.add_argument("--reply-prompt", default="v1")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--reply-mode", choices=["model", "template"], default="model",
                   help="template: every reply is built by code (the comparison baseline for model-written replies)")
    p.add_argument("--knowledge", action="store_true", help="answer policy questions from the knowledge base (needs the embedding model; ADR-009)")
    p.add_argument("--transactions", action="store_true", help="handle cancellation and address-change tickets (read-only; proposals go to a person)")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--check-prompt", default="v1", help="version of the knowledge check prompt (v1 default)")
    p.add_argument("--limit", type=int, default=0, help="first N tickets by id (0 = all)")
    p.add_argument("--ids-file", type=Path, help="text file with one ticket id per line")
    args = p.parse_args(argv)
    check_not_heldout(args.db)

    box = Toolbox.from_path(args.db)
    model = OllamaClient(model=args.model)
    read_prompt, reply_prompt = load_prompt("read_ticket", args.read_prompt), load_prompt("reply", args.reply_prompt)
    ids = select_ids(box, args.limit, args.ids_file)
    warmup_ms = warm_up(model, read_prompt)
    articles = load_articles(args.kb)
    knowledge = None
    if args.knowledge:
        from src.kb.embed import EmbeddingIndex
        knowledge = Knowledge(EmbeddingIndex(articles, args.embed_model), articles, load_prompt("knowledge_check", args.check_prompt),
                              load_prompt("knowledge_reply", "v1"), args.min_score)
    transactions = Transactions(load_prompt("extract_address", "v1")) if args.transactions else None
    meta = build_meta(model, read_prompt, reply_prompt, args.db, args.seed, ids, argv if argv is not None else sys.argv[1:], model.digest(), warmup_ms,
                      args.reply_mode, knowledge, args.embed_model if knowledge else "",
                      model_digest(args.embed_model) if knowledge else "", transactions)
    with TraceWriter(args.out, new_run_id(), meta) as writer:
        run_tickets(box, model, read_prompt, reply_prompt, internal_guidance(articles), ids, writer, args.seed, args.reply_mode, knowledge, transactions,
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