"""Blind review of hand-over notes, for the question code cannot answer: could a person act on the note?

    python -m src.evaluation.review_notes make   --run data/runs/<run> --name dev-notes [--count 24] [--seed 0]
    python -m src.evaluation.review_notes rate   --name dev-notes
    python -m src.evaluation.review_notes report --name dev-notes

``make`` draws a seeded sample of the notes in a run, spread over the actions that carry a note (escalations, routings and each kind
of proposal), and writes the sheet with the ticket text beside each note. Labels, scenarios and expected actions are never shown.
``rate`` asks three questions per note and can be stopped and resumed. The scorer already counts whether a note is present and names
the labelled order; this review is about usefulness and correctness. One reviewer, so there is no measure of agreement.
"""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Callable

from src.agent.handover import Handover
from src.agent.tools import Toolbox
from src.baseline.scoring import wilson_interval
from src.evaluation.score import read_jsonl

ROOT = Path("data/reviews")
DB = Path("data/generated/dev/support.db")
ANSWERS = ("y", "p", "n")


def note_text(note: dict) -> str:
    return Handover(**{**note, "order_ids": tuple(note["order_ids"]), "records": tuple(note["records"])}).render()


def _rank(ticket_id: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{ticket_id}".encode()).hexdigest()


def sample(resolutions: list, count: int, seed: int = 0) -> list:
    """Resolutions that carry a note, taken in turn from each action (a seeded order inside each), until `count` are chosen."""
    groups = defaultdict(list)
    for r in resolutions:
        if r.get("handover"):
            groups[r["action"]].append(r)
    for rows in groups.values():
        rows.sort(key=lambda r: _rank(r["ticket_id"], seed))
    chosen, names = [], sorted(groups)
    while len(chosen) < count and any(groups[n] for n in names):
        for name in names:
            if groups[name] and len(chosen) < count:
                chosen.append(groups[name].pop(0))
    return sorted(chosen, key=lambda r: _rank(r["ticket_id"], seed))


def build_items(run: Path, db: Path, count: int, seed: int = 0) -> list:
    box = Toolbox.from_path(db)
    try:
        items = []
        for r in sample(read_jsonl(run / "resolutions.jsonl"), count, seed):
            t = box.get_ticket(r["ticket_id"]).data
            items.append({"ticket_id": r["ticket_id"], "action": r["action"], "subject": t.subject, "body": t.body, "note": note_text(r["handover"])})
        return items
    finally:
        box.conn.close()


def load_ratings(path: Path) -> dict:
    return {r["ticket_id"]: r for r in read_jsonl(path)} if path.exists() else {}


def run_review(items: list, ratings_path: Path, ask: Callable[[str], str] = input, show: Callable[[str], None] = print) -> int:
    done, rated = load_ratings(ratings_path), 0
    ratings_path.parent.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(items, 1):
        if item["ticket_id"] in done:
            continue
        show(f"\n--- {index}/{len(items)}  {item['ticket_id']} ---\nTICKET: {item['subject']}\n{item['body']}\n\nNOTE\n{item['note']}\n")
        actionable = ""
        while actionable not in ANSWERS + ("q",):
            actionable = ask("Could you act on this without opening anything else? y / p (partly) / n / q (quit and save): ").strip().lower()
        if actionable == "q":
            break
        wrong = ask("Anything in the note wrong compared with the ticket? [y/N]: ").strip().lower() == "y"
        missing = ask("Anything you needed that is missing? [y/N]: ").strip().lower() == "y"
        comment = ask("Comment (optional, Enter to skip): ").strip() if (wrong or missing or actionable != "y") else ""
        with open(ratings_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ticket_id": item["ticket_id"], "actionable": actionable, "wrong": wrong, "missing": missing, "comment": comment}, sort_keys=True) + "\n")
        rated += 1
    return rated


def report(items: list, ratings: dict) -> dict:
    rows = [(i, ratings[i["ticket_id"]]) for i in items if i["ticket_id"] in ratings]
    n = len(rows)

    def rate(hits):
        low, high = wilson_interval(hits, n)
        return {"n": n, "count": hits, "low": None if not n else round(low, 4), "high": None if not n else round(high, 4)}
    by_action = defaultdict(lambda: [0, 0])
    for item, r in rows:
        by_action[item["action"]][0] += 1
        by_action[item["action"]][1] += r["actionable"] == "y"
    return {"notes_in_sheet": len(items), "notes_rated": n,
            "actionable_yes": rate(sum(r["actionable"] == "y" for _, r in rows)), "actionable_partly": rate(sum(r["actionable"] == "p" for _, r in rows)),
            "actionable_no": rate(sum(r["actionable"] == "n" for _, r in rows)),
            "wrong": rate(sum(r["wrong"] for _, r in rows)), "missing": rate(sum(r["missing"] for _, r in rows)),
            "by_action": {a: {"rated": c[0], "actionable_yes": c[1]} for a, c in sorted(by_action.items())},
            "to_follow_up": [{"ticket_id": i["ticket_id"], "actionable": r["actionable"], "wrong": r["wrong"], "missing": r["missing"], "comment": r["comment"]}
                             for i, r in rows if r["wrong"] or r["missing"] or r["actionable"] != "y"]}


def render(rep: dict) -> str:
    def f(x):
        return "n/a" if not x["n"] else f"{x['count']}/{x['n']} (95% interval {100 * x['low']:.0f}-{100 * x['high']:.0f}%)"
    lines = [f"notes rated {rep['notes_rated']} of {rep['notes_in_sheet']}",
             f"could act on it: yes {f(rep['actionable_yes'])}; partly {f(rep['actionable_partly'])}; no {f(rep['actionable_no'])}",
             f"something wrong flagged: {f(rep['wrong'])}; something missing flagged: {f(rep['missing'])}",
             "by action: " + ", ".join(f"{a} {v['actionable_yes']}/{v['rated']}" for a, v in rep["by_action"].items())]
    lines += [f"  follow up {t['ticket_id']}: actionable={t['actionable']} wrong={t['wrong']} missing={t['missing']} {t['comment']}" for t in rep["to_follow_up"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make")
    make.add_argument("--run", type=Path, required=True)
    make.add_argument("--db", type=Path, default=DB)
    make.add_argument("--count", type=int, default=24)
    make.add_argument("--seed", type=int, default=0)
    for cmd in (make, sub.add_parser("rate"), sub.add_parser("report")):
        cmd.add_argument("--name", required=True)
        cmd.add_argument("--root", type=Path, default=ROOT)
    args = p.parse_args(argv)
    folder = args.root / args.name
    if args.command == "make":
        if (folder / "items.json").exists():
            raise SystemExit(f"{folder} already exists; choose another name (a review sheet is never overwritten).")
        if "heldout" in str(args.db).lower():
            raise SystemExit("The held-out split is not reviewed before Phase 4.")
        items = build_items(args.run, args.db, args.count, args.seed)
        folder.mkdir(parents=True)
        (folder / "items.json").write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "key.json").write_text(json.dumps({"run": args.run.name, "seed": args.seed, "count": args.count}, indent=2) + "\n", encoding="utf-8")
        print(f"{len(items)} notes written to {folder}")
        return 0
    items = json.loads((folder / "items.json").read_text(encoding="utf-8"))
    if args.command == "rate":
        print(f"rated {run_review(items, folder / 'ratings.jsonl')} notes this session")
        return 0
    rep = report(items, load_ratings(folder / "ratings.jsonl"))
    (folder / "report.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())