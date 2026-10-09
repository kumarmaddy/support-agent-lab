"""Measure the knowledge-question path on the probe questions (phase-2-design.md, section 4).

    python -m src.evaluation.knowledge --probes data/probes/knowledge_questions.jsonl [--model qwen2.5:7b] [--reply-mode model|template]

Each probe goes through the same gates as a ticket would (score, model check, reply validation) without the read step or any
order lookup. For answerable questions it reports whether the answer cited a required or acceptable article, a different article,
or was handed over (and at which gate); for unanswerable questions it reports whether the agent answered (a failure) or handed over.
This reads labels, so it lives outside ``src/agent``.
"""
import argparse
import collections
from pathlib import Path

from src.agent.knowledge import DEFAULT_MIN_SCORE, KNOWLEDGE_ANSWER, Knowledge, answer_or_hand_over
from src.agent.model import OllamaClient
from src.agent.pipeline import internal_guidance
from src.agent.prompting import load_prompt
from src.agent.reply import draft_knowledge_reply
from src.baseline.scoring import wilson_interval
from src.evaluation.retrieval import load_probes
from src.kb.articles import load_articles


def run_probes(knowledge: Knowledge, model, probes: list, internal: frozenset, use_model: bool = True) -> list:
    rows = []
    for probe in probes:
        outcome = answer_or_hand_over(knowledge, model, probe["question"], "")
        row = {"id": probe["id"], "answerable": probe["answerable"], "gate": outcome.gate, "article": outcome.decision.article,
               "score": outcome.hits[0]["score"] if outcome.hits else None, "ranked": [h["kb_id"] for h in outcome.hits],
               "required": set(probe["required_kb_ids"]) | set(probe.get("also_acceptable_kb_ids", [])), "reply_source": None, "failures": []}
        if outcome.decision.reason == KNOWLEDGE_ANSWER:
            reply = draft_knowledge_reply(model, knowledge.reply_prompt, outcome.decision, internal, use_model=use_model)
            row["reply_source"], row["failures"] = reply.source, [c for codes in reply.failures for c in codes]
        rows.append(row)
    return rows


def summarise(rows: list) -> dict:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    answered = [r for r in answerable if r["article"]]
    return {
        "answerable": len(answerable), "unanswerable": len(unanswerable),
        "right": sum(1 for r in answered if r["article"] in r["required"]),
        "wrong": sum(1 for r in answered if r["article"] not in r["required"]),
        "handed_over": {gate: sum(1 for r in answerable if not r["article"] and r["gate"] == gate) for gate in ("score", "check", "unavailable")},
        "unanswerable_answered": sum(1 for r in unanswerable if r["article"]),
        "unanswerable_handed_over": {gate: sum(1 for r in unanswerable if not r["article"] and r["gate"] == gate) for gate in ("score", "check", "unavailable")},
        "reply_sources": dict(collections.Counter(r["reply_source"] for r in rows if r["reply_source"])),
        "rejected_codes": dict(collections.Counter(c for r in rows for c in r["failures"])),
    }


def render(rows: list) -> str:
    s = summarise(rows)
    n, m = s["answerable"], s["unanswerable"]

    def share(k, total):
        low, high = wilson_interval(k, total)
        return f"{k}/{total} = {k / total:.0%} ({low:.0%}-{high:.0%})" if total else "0/0"
    lines = [f"answerable questions {n}:",
             f"  answered with a required or acceptable article {share(s['right'], n)}",
             f"  answered with a different article (a wrong answer) {share(s['wrong'], n)}",
             f"  handed over: at the score gate {s['handed_over']['score']}, at the model check {s['handed_over']['check']}, unavailable {s['handed_over']['unavailable']}",
             f"unanswerable questions {m}:",
             f"  answered (a failure) {share(s['unanswerable_answered'], m)}",
             f"  handed over: at the score gate {s['unanswerable_handed_over']['score']}, at the model check {s['unanswerable_handed_over']['check']}",
             f"replies by source {s['reply_sources']}; rejected draft codes {s['rejected_codes']}", "", "wrong answers and failures (id, required, cited, score):"]
    lines += [f"  {r['id']} {sorted(r['required'])} -> {r['article']} {r['score']:.3f}" for r in rows
              if r["answerable"] and r["article"] and r["article"] not in r["required"]]
    lines += [f"  {r['id']} (unanswerable) -> {r['article']} {r['score']:.3f}" for r in rows if not r["answerable"] and r["article"]]
    lines += ["", "answerable questions handed over (id, required, best article, score, gate):"]
    lines += [f"  {r['id']} {sorted(r['required'])} {r['ranked'][:1]} {r['score'] if r['score'] is None else round(r['score'], 3)} {r['gate']}"
              for r in rows if r["answerable"] and not r["article"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--probes", type=Path, required=True)
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--model", default="qwen2.5:7b")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--reply-mode", choices=["model", "template"], default="model")
    args = p.parse_args(argv)
    from src.kb.embed import EmbeddingIndex
    articles = load_articles(args.kb)
    knowledge = Knowledge(EmbeddingIndex(articles, args.embed_model), articles, load_prompt("knowledge_check", "v1"),
                          load_prompt("knowledge_reply", "v1"), args.min_score)
    model = OllamaClient(model=args.model)
    print(f"model {args.model} (digest {model.digest()[:12] or 'unknown'}), embeddings {args.embed_model}, minimum score {args.min_score}, reply mode {args.reply_mode}")
    print(render(run_probes(knowledge, model, load_probes(args.probes), internal_guidance(articles), args.reply_mode == "model")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())