"""Measure knowledge-base retrieval against the development labels (phase-2-design.md, section 3).

    python -m src.evaluation.retrieval [--top 3]

Every labelled ticket that names the articles it needs (``required_kb_ids``) is a retrieval test: the query is the ticket's subject
and body, the right answer is the labelled article set. This evaluation reads labels, so it lives outside ``src/agent``.
Reported: hit@k (a required article is among the first k), recall@k (share of the required articles among the first k), the reciprocal
rank of the first required article, by category, and the score distribution for tickets with no required article (the "I don't know"
cases). It refuses the held-out split.
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

from src.kb.articles import load_articles
from src.kb.retrieve import build_index


def evaluate(index, tickets: list, top: int = 3) -> dict:
    """``tickets`` is a list of (category, query text, required ids). Returns counts by category and the scores of unanswerable tickets."""
    by_category = collections.defaultdict(lambda: {"n": 0, "hit1": 0, "hitk": 0, "recallk": 0.0, "rr": 0.0})
    no_answer_scores = []
    misses = []
    for category, text, required in tickets:
        hits = index.search(text, top)
        if not required:
            no_answer_scores.append(hits[0].score if hits else 0.0)
            continue
        ranked = [h.kb_id for h in hits]
        row = by_category[category]
        row["n"] += 1
        row["hit1"] += bool(ranked[:1] and ranked[0] in required)
        row["hitk"] += any(r in required for r in ranked)
        row["recallk"] += sum(r in ranked for r in required) / len(required)
        first = next((i for i, r in enumerate(ranked, 1) if r in required), None)
        row["rr"] += 1 / first if first else 0.0
        if not (ranked and ranked[0] in required):
            misses.append((category, sorted(required), ranked))
    return {"by_category": dict(by_category), "no_answer_scores": no_answer_scores, "misses": misses}


def render(result: dict, top: int) -> str:
    lines = [f"{'category':<16}{'n':>4}{'hit@1':>8}{f'hit@{top}':>8}{f'recall@{top}':>10}{'MRR':>7}"]
    total = collections.Counter()
    for category, r in sorted(result["by_category"].items()):
        lines.append(f"{category:<16}{r['n']:>4}{r['hit1'] / r['n']:>8.0%}{r['hitk'] / r['n']:>8.0%}{r['recallk'] / r['n']:>10.0%}{r['rr'] / r['n']:>7.2f}")
        for key, value in r.items():
            total[key] += value
    if total["n"]:
        n = total["n"]
        lines.append(f"{'ALL':<16}{n:>4}{total['hit1'] / n:>8.0%}{total['hitk'] / n:>8.0%}{total['recallk'] / n:>10.0%}{total['rr'] / n:>7.2f}")
    scores = sorted(result["no_answer_scores"])
    if scores:
        lines.append(f"\ntickets with no required article: {len(scores)}; best-hit score min {scores[0]:.2f}, median {scores[len(scores) // 2]:.2f}, max {scores[-1]:.2f}")
    lines.append(f"\nfirst-place misses ({len(result['misses'])}): category, required, ranked")
    lines += [f"  {c} {r} -> {k}" for c, r, k in result["misses"][:25]]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--labels", type=Path, default=Path("data/labels/dev/labels.jsonl"))
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--top", type=int, default=3)
    args = p.parse_args(argv)
    if "heldout" in str(args.db).lower() or "heldout" in str(args.labels).lower():
        raise SystemExit("Refusing to run on the held-out split.")
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    tickets = []
    for line in args.labels.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        label = json.loads(line)
        subject, body = conn.execute("SELECT subject, body FROM tickets WHERE ticket_id=?", (label["ticket_id"],)).fetchone()
        tickets.append((label["category"], f"{subject}\n{body}", set(label["required_kb_ids"])))
    print(render(evaluate(build_index(load_articles(args.kb)), tickets, args.top), args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())