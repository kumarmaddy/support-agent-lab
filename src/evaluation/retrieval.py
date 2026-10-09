"""Measure knowledge-base retrieval against the development labels (phase-2-design.md, section 3).

    python -m src.evaluation.retrieval [--top 3] [--method bm25|embed|hybrid]
    python -m src.evaluation.retrieval --probes data/probes/knowledge_questions.jsonl --method hybrid

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

from src.baseline.scoring import wilson_interval
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


# ------------------------------------------------------------------ probe questions and the "I don't know" threshold
def load_probes(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate_probes(index, probes: list, top: int = 3) -> dict:
    """Rank the articles for each probe question. ``rows`` keeps (id, answerable, required, ranked ids, best score)."""
    rows = []
    for probe in probes:
        hits = index.search(probe["question"], top)
        rows.append({"id": probe["id"], "answerable": probe["answerable"], "required": set(probe["required_kb_ids"]),
                     "ranked": [h.kb_id for h in hits], "best": hits[0].score if hits else 0.0})
    return {"rows": rows}


def threshold_table(rows: list, points: int = 8) -> list:
    """For a range of minimum scores: share of answerable questions answered with the right article, share answered with a wrong
    article, and share of unanswerable questions that would still get an answer. Scores are compared with >=."""
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    values = sorted({r["best"] for r in rows})
    chosen = sorted({values[min(int(i * (len(values) - 1) / (points - 1)), len(values) - 1)] for i in range(points)}) if values else []
    table = []
    for t in chosen:
        right = sum(1 for r in answerable if r["best"] >= t and r["ranked"][:1] and r["ranked"][0] in r["required"])
        wrong = sum(1 for r in answerable if r["best"] >= t and not (r["ranked"][:1] and r["ranked"][0] in r["required"]))
        table.append({"threshold": t, "right": right / max(len(answerable), 1), "wrong": wrong / max(len(answerable), 1),
                      "answers_unanswerable": sum(1 for r in unanswerable if r["best"] >= t) / max(len(unanswerable), 1)})
    return table


def render_probes(result: dict, top: int) -> str:
    rows = result["rows"]
    answerable = [r for r in rows if r["answerable"]]
    n = len(answerable)
    hit1 = sum(1 for r in answerable if r["ranked"][:1] and r["ranked"][0] in r["required"])
    hitk = sum(1 for r in answerable if any(x in r["required"] for x in r["ranked"]))
    lo1, hi1 = wilson_interval(hit1, n)
    lok, hik = wilson_interval(hitk, n)
    lines = [f"answerable probes {n}: hit@1 {hit1}/{n} = {hit1 / n:.0%} ({lo1:.0%}-{hi1:.0%}); hit@{top} {hitk}/{n} = {hitk / n:.0%} ({lok:.0%}-{hik:.0%})",
             f"unanswerable probes {len(rows) - n}", "", "minimum score -> right article | wrong article | unanswerable questions still answered"]
    for row in threshold_table(rows):
        lines.append(f"  {row['threshold']:>9.4f}  {row['right']:>6.0%}  {row['wrong']:>6.0%}  {row['answers_unanswerable']:>6.0%}")
    lines.append("\nfirst-place misses (id, required, ranked, best score):")
    lines += [f"  {r['id']} {sorted(r['required'])} -> {r['ranked']} {r['best']:.3f}" for r in answerable if not (r["ranked"][:1] and r["ranked"][0] in r["required"])]
    lines.append("\nunanswerable questions with the highest best score:")
    lines += [f"  {r['id']} {r['ranked'][:1]} {r['best']:.3f}" for r in sorted((r for r in rows if not r["answerable"]), key=lambda r: -r["best"])[:5]]
    return "\n".join(lines)


def make_index(method: str, articles: dict, embed_model: str):
    from src.kb.embed import EmbeddingIndex, HybridIndex
    if method == "bm25":
        return build_index(articles)
    embedded = EmbeddingIndex(articles, embed_model)
    return embedded if method == "embed" else HybridIndex(build_index(articles), embedded)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", type=Path, default=Path("data/generated/dev/support.db"))
    p.add_argument("--labels", type=Path, default=Path("data/labels/dev/labels.jsonl"))
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--method", choices=["bm25", "embed", "hybrid"], default="bm25")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--probes", type=Path, help="knowledge-question probe file; if given, only the probes are evaluated")
    args = p.parse_args(argv)
    if "heldout" in str(args.db).lower() or "heldout" in str(args.labels).lower():
        raise SystemExit("Refusing to run on the held-out split.")
    articles = load_articles(args.kb)
    index = make_index(args.method, articles, args.embed_model)
    print(f"method {args.method}" + (f" ({args.embed_model})" if args.method != "bm25" else ""))
    if args.probes:
        print(render_probes(evaluate_probes(index, load_probes(args.probes), args.top), args.top))
        return 0
    conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
    tickets = []
    for line in args.labels.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        label = json.loads(line)
        subject, body = conn.execute("SELECT subject, body FROM tickets WHERE ticket_id=?", (label["ticket_id"],)).fetchone()
        tickets.append((label["category"], f"{subject}\n{body}", set(label["required_kb_ids"])))
    print(render(evaluate(index, tickets, args.top), args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())