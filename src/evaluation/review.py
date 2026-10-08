"""Blind review of model-written replies against template replies, for the checks a validator cannot make (wording, tone, meaning).

    python -m src.evaluation.review make   --model-run data/runs/<a> --template-run data/runs/<b> --name dev-3b
    python -m src.evaluation.review rate   --name dev-3b
    python -m src.evaluation.review report --name dev-3b

``make`` pairs the reply the model wrote with the template reply for the same ticket, in a seeded random order, and writes the
sheet (``items.json``) apart from the key that says which side is which (``key.json``). ``rate`` asks about each pair and can be
stopped and resumed. ``report`` joins ratings and key. Only replies that passed the validator are reviewed (a fallback is the
template in both runs); the share of fallbacks is reported by the scorer, so a good result here is about accepted drafts only.
The review is made by one reviewer; that is a scope limitation, not a measure of inter-rater agreement.
"""
import argparse
import hashlib
import json
from pathlib import Path
from typing import Callable, Optional

from src.baseline.scoring import wilson_interval
from src.evaluation.compare import sign_test
from src.evaluation.score import read_jsonl

ROOT = Path("data/reviews")
FACT_FIELDS = ("order_id", "status", "promised_date", "carrier", "tracking_no", "last_status", "candidates")


def side_of_model(ticket_id: str, seed: int) -> str:
    """'a' or 'b': which side the model reply is shown on (fixed by seed and ticket id, roughly half and half)."""
    return "a" if int(hashlib.sha256(f"{seed}:{ticket_id}".encode()).hexdigest(), 16) % 2 == 0 else "b"


def build_items(model_run: Path, template_run: Path, seed: int = 0) -> tuple:
    """Returns (items, key, excluded). A ticket is excluded when the two runs decided differently (a template for another decision is
    not a fair comparison); a template run that is not template-only, or runs over different tickets, are refused."""
    model = {r["ticket_id"]: r for r in read_jsonl(model_run / "resolutions.jsonl")}
    template = {r["ticket_id"]: r for r in read_jsonl(template_run / "resolutions.jsonl")}
    if set(model) != set(template):
        raise SystemExit("The two runs cover different tickets.")
    if any(t["reply_source"] != "template" for t in template.values()):
        raise SystemExit("The template run is not template-only (run it with --reply-mode template).")
    items, key, excluded = [], {}, []
    for tid in sorted(model):
        m, t = model[tid], template[tid]
        if m["reply_source"] != "model":
            continue
        if m["action"] != t["action"] or m["reason"] != t["reason"]:
            excluded.append(tid)
            continue
        side = side_of_model(tid, seed)
        replies = {side: m["reply"], other(side): t["reply"]}
        facts = {k: v for k, v in (m.get("facts") or {}).items() if k in FACT_FIELDS}
        items.append({"ticket_id": tid, "facts": facts, "a": replies["a"], "b": replies["b"]})
        key[tid] = {"model": side}
    return items, key, excluded


def other(side: str) -> str:
    return "b" if side == "a" else "a"


def load_ratings(path: Path) -> dict:
    return {r["ticket_id"]: r for r in read_jsonl(path)} if path.exists() else {}


def run_review(items: list, ratings_path: Path, ask: Callable[[str], str] = input, show: Callable[[str], None] = print) -> int:
    """Ask about every unrated pair; each answer is saved at once. Returns the number of pairs rated in this session."""
    done, rated = load_ratings(ratings_path), 0
    ratings_path.parent.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(items, 1):
        if item["ticket_id"] in done:
            continue
        show(f"\n--- {index}/{len(items)}  {item['ticket_id']} ---\nFacts the replies may state: {json.dumps(item['facts'], ensure_ascii=False)}")
        show(f"\nREPLY A\n{item['a']}\n\nREPLY B\n{item['b']}\n")
        better = ""
        while better not in ("a", "b", "t", "q"):
            better = ask("Better reply? a / b / t (tie) / q (quit and save): ").strip().lower()
        if better == "q":
            break
        flags = {}
        for name, question in (("a_fact_error", "A states something not in the facts or wrong?"), ("b_fact_error", "B states something not in the facts or wrong?"),
                               ("a_awkward", "A has awkward or incorrect wording?"), ("b_awkward", "B has awkward or incorrect wording?")):
            flags[name] = ask(f"{question} [y/N]: ").strip().lower() == "y"
        with open(ratings_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ticket_id": item["ticket_id"], "better": better, **flags}, sort_keys=True) + "\n")
        rated += 1
    return rated


def report(items: list, key: dict, ratings: dict) -> dict:
    rows = [(key[i["ticket_id"]]["model"], ratings[i["ticket_id"]]) for i in items if i["ticket_id"] in ratings]
    n = len(rows)

    def flagged(kind):
        out = {}
        for source in ("model", "template"):
            hits = sum(1 for model_side, r in rows if r[f"{model_side if source == 'model' else other(model_side)}_{kind}"])
            low, high = wilson_interval(hits, n)
            out[source] = {"n": n, "flagged": hits, "low": None if not n else round(low, 4), "high": None if not n else round(high, 4)}
        return out
    model_better = sum(1 for side, r in rows if r["better"] == side)
    template_better = sum(1 for side, r in rows if r["better"] not in (side, "t"))
    return {"pairs_in_sheet": len(items), "pairs_rated": n, "model_better": model_better, "template_better": template_better,
            "tie": n - model_better - template_better, "sign_test_p": sign_test(model_better, template_better),
            "fact_errors": flagged("fact_error"), "awkward": flagged("awkward")}


def render(rep: dict) -> str:
    def f(x):
        return "n/a" if not x["n"] else f"{x['flagged']}/{x['n']} (95% interval {100 * x['low']:.0f}-{100 * x['high']:.0f}%)"
    return "\n".join([f"pairs rated {rep['pairs_rated']} of {rep['pairs_in_sheet']}",
                      f"better reply: model {rep['model_better']}, template {rep['template_better']}, tie {rep['tie']} (sign test p = {rep['sign_test_p']:.3f}, ties excluded)",
                      f"factual error flagged: model {f(rep['fact_errors']['model'])}; template {f(rep['fact_errors']['template'])}",
                      f"awkward wording flagged: model {f(rep['awkward']['model'])}; template {f(rep['awkward']['template'])}"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make")
    make.add_argument("--model-run", type=Path, required=True)
    make.add_argument("--template-run", type=Path, required=True)
    make.add_argument("--seed", type=int, default=0)
    for cmd in (make, sub.add_parser("rate"), sub.add_parser("report")):
        cmd.add_argument("--name", required=True)
        cmd.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args(argv)
    folder = args.root / args.name
    if args.command == "make":
        if (folder / "items.json").exists():
            raise SystemExit(f"{folder} already exists; choose another name (a review sheet is never overwritten).")
        items, key, excluded = build_items(args.model_run, args.template_run, args.seed)
        folder.mkdir(parents=True)
        (folder / "items.json").write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "key.json").write_text(json.dumps({"model_run": args.model_run.name, "template_run": args.template_run.name, "seed": args.seed, "sides": key}, indent=2) + "\n", encoding="utf-8")
        print(f"{len(items)} pairs written to {folder}" + (f"; excluded because the runs decided differently: {', '.join(excluded)}" if excluded else ""))
        return 0
    items = json.loads((folder / "items.json").read_text(encoding="utf-8"))
    if args.command == "rate":
        print(f"rated {run_review(items, folder / 'ratings.jsonl')} pairs this session")
        return 0
    key = json.loads((folder / "key.json").read_text(encoding="utf-8"))["sides"]
    rep = report(items, key, load_ratings(folder / "ratings.jsonl"))
    (folder / "report.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())