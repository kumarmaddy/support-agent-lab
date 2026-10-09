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


def verdict(check) -> str:
    """What the model check said: yes, no, or error:<code> (a failed call is not the same as a no)."""
    if check is None:
        return "-"
    if not check.ok:
        return f"error:{check.error}"
    return {True: "yes", False: "no"}.get(check.content.get("answers_question"), "invalid")


def run_probes(knowledge: Knowledge, model, probes: list, internal: frozenset, use_model: bool = True) -> list:
    rows = []
    for probe in probes:
        outcome = answer_or_hand_over(knowledge, model, probe["question"], "")
        row = {"id": probe["id"], "answerable": probe["answerable"], "gate": outcome.gate, "article": outcome.decision.article,
               "score": outcome.hits[0]["score"] if outcome.hits else None, "ranked": [h["kb_id"] for h in outcome.hits],
               "required": set(probe["required_kb_ids"]) | set(probe.get("also_acceptable_kb_ids", [])), "reply_source": None, "failures": [],
               "question": probe["question"], "verdict": verdict(outcome.check), "raw": outcome.check.raw if outcome.check else "", "reply": ""}
        if outcome.decision.reason == KNOWLEDGE_ANSWER:
            reply = draft_knowledge_reply(model, knowledge.reply_prompt, outcome.decision, internal, use_model=use_model)
            row["reply_source"], row["failures"], row["reply"] = reply.source, [c for codes in reply.failures for c in codes], reply.text
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
        "check_verdicts": dict(collections.Counter(r["verdict"] for r in rows if r["verdict"] != "-")),
        "reply_sources": dict(collections.Counter(r["reply_source"] for r in rows if r["reply_source"])),
        "rejected_codes": dict(collections.Counter(c for r in rows for c in r["failures"])),
    }


def render(rows: list, show_replies: int = 0) -> str:
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
             f"model check verdicts {s['check_verdicts']}",
             f"replies by source {s['reply_sources']}; rejected draft codes {s['rejected_codes']}", "", "wrong answers and failures (id, required, cited, score):"]
    lines += [f"  {r['id']} {sorted(r['required'])} -> {r['article']} {r['score']:.3f}" for r in rows
              if r["answerable"] and r["article"] and r["article"] not in r["required"]]
    lines += [f"  {r['id']} (unanswerable) -> {r['article']} {r['score']:.3f}" for r in rows if not r["answerable"] and r["article"]]
    lines += ["", "answerable questions handed over (id, required, best article, score, gate):"]
    lines += [f"  {r['id']} {sorted(r['required'])} {r['ranked'][:1]} {r['score'] if r['score'] is None else round(r['score'], 3)} {r['gate']} {r['verdict']}"
              for r in rows if r["answerable"] and not r["article"]]
    if show_replies:
        lines += ["", "answered questions, for reading (question, article, reply):"]
        for r in [r for r in rows if r["article"]][:show_replies]:
            lines += [f"[{r['id']}] {r['question']}", f"  cited {r['article']}, reply by {r['reply_source']}"] + [f"    {line}" for line in r["reply"].splitlines()]
    return "\n".join(lines)


def check_only(knowledge: Knowledge, model, probes: list, articles: dict) -> dict:
    """Test the model check on its own, without retrieval. Right article: the labelled article for an answerable question (should say
    yes). Wrong article: for every probe, an article that does not answer it (should say no): the best retrieved article that is not
    a required or acceptable one."""
    from src.agent.knowledge import CHECK_MAX_TOKENS, CHECK_SCHEMA, clean_fact, render_check_system
    from src.agent.reading import render_user

    def ask(question, kb_id):
        facts = [clean_fact(f) for f in articles[kb_id].key_facts]
        return verdict(model.chat(render_check_system(knowledge.check_prompt, facts), render_user(question, ""), CHECK_SCHEMA, max_tokens=CHECK_MAX_TOKENS))
    right, wrong = [], []
    for probe in probes:
        acceptable = set(probe["required_kb_ids"]) | set(probe.get("also_acceptable_kb_ids", []))
        if probe["answerable"]:
            right.append((probe["id"], ask(probe["question"], probe["required_kb_ids"][0])))
        other = next((h.kb_id for h in knowledge.retriever.search(probe["question"], 5) if h.kb_id not in acceptable), None)
        if other:
            wrong.append((probe["id"], other, ask(probe["question"], other)))
    return {"right": right, "wrong": wrong}


def render_check_only(result: dict) -> str:
    rc, wc = collections.Counter(v for _, v in result["right"]), collections.Counter(v for _, _, v in result["wrong"])
    lines = [f"model check on the labelled article (should say yes): {dict(rc)}",
             f"model check on an article that does not answer the question (should say no): {dict(wc)}",
             "", "labelled article but not 'yes' (id, verdict):"]
    lines += [f"  {i} {v}" for i, v in result["right"] if v != "yes"]
    lines += ["", "wrong article but not 'no' (id, article, verdict):"]
    lines += [f"  {i} {a} {v}" for i, a, v in result["wrong"] if v != "no"]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--probes", type=Path, required=True)
    p.add_argument("--kb", type=Path, default=Path("data/seed/kb"))
    p.add_argument("--model", default="qwen2.5:7b")
    p.add_argument("--embed-model", default="nomic-embed-text")
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--reply-mode", choices=["model", "template"], default="model")
    p.add_argument("--show-replies", type=int, default=0, metavar="N", help="print the first N answered replies for reading")
    p.add_argument("--check-only", action="store_true", help="test the model check on its own, with the labelled and with a wrong article")
    args = p.parse_args(argv)
    from src.kb.embed import EmbeddingIndex, model_digest
    articles = load_articles(args.kb)
    knowledge = Knowledge(EmbeddingIndex(articles, args.embed_model), articles, load_prompt("knowledge_check", "v1"),
                          load_prompt("knowledge_reply", "v1"), args.min_score)
    model = OllamaClient(model=args.model)
    print(f"model {args.model} (digest {model.digest()[:12] or 'unknown'}), embeddings {args.embed_model} (digest {model_digest(args.embed_model)[:12] or 'unknown'}), minimum score {args.min_score}, reply mode {args.reply_mode}")
    probes = load_probes(args.probes)
    if args.check_only:
        print(render_check_only(check_only(knowledge, model, probes, articles)))
        return 0
    print(render(run_probes(knowledge, model, probes, internal_guidance(articles), args.reply_mode == "model"), args.show_replies))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())