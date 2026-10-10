"""Compare two scored runs of the same tickets (for example 3B against 7B, or model-written against template replies).

    python -m src.evaluation.compare data/runs/<run_a> data/runs/<run_b>

Both runs must have been scored (``score.json``) over the same dataset and the same tickets. Because both runs answer the same
tickets the comparison is paired: for each measure the tickets that only A got right and the tickets that only B got right are
counted, and an exact sign test says whether the split could be chance. With few tickets most differences are not reliable; the
report says so instead of ranking the runs.
"""
import argparse
import json
from math import comb
from pathlib import Path

MEASURES = (("category agreement (all tickets)", "all", "category_ok"),
            ("Set A end to end", "a", "end_to_end_ok"),
            ("Set A action", "a", "action_ok"),
            ("Set A facts", "a", "facts_ok"),
            ("Set B handed to a person", "b", "handed_to_person"))
CONFIG_KEYS = ("model", "reply_mode", "prompts", "code")


def sign_test(only_a: int, only_b: int) -> float:
    """Two-sided exact binomial (McNemar) p-value for the tickets on which exactly one run was right."""
    n = only_a + only_b
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(only_a, only_b) + 1)) / 2 ** n)


def load_score(run_dir: Path) -> dict:
    path = Path(run_dir) / "score.json"
    if not path.exists():
        raise SystemExit(f"{path} not found; score the run first (python -m src.evaluation.score {run_dir})")
    return json.loads(path.read_text(encoding="utf-8"))


def _rows(score: dict, subset: str) -> dict:
    keep = {"all": lambda r: True, "a": lambda r: r["in_slice"], "b": lambda r: not r["in_slice"]}[subset]
    return {r["ticket_id"]: r for r in score["rows"] if keep(r)}


def compare(a: dict, b: dict) -> dict:
    if (a.get("dataset") or {}).get("db_sha256") != (b.get("dataset") or {}).get("db_sha256") or not (a.get("dataset") or {}).get("db_sha256"):
        raise SystemExit("The runs were not made on the same dataset file (or the dataset hash is missing).")
    if {r["ticket_id"] for r in a["rows"]} != {r["ticket_id"] for r in b["rows"]}:
        raise SystemExit("The runs cover different tickets; compare runs of the same ticket list.")
    measures = []
    for name, subset, key in MEASURES:
        ra, rb = _rows(a, subset), _rows(b, subset)
        ra = {t: r for t, r in ra.items() if t in rb}           # a ticket is compared only if both runs put it in the same set
        rb = {t: r for t, r in rb.items() if t in ra}
        if not ra:
            continue
        only_a = sorted(t for t in ra if ra[t][key] and not rb[t][key])
        only_b = sorted(t for t in ra if rb[t][key] and not ra[t][key])
        measures.append({"measure": name, "n": len(ra), "a": sum(bool(r[key]) for r in ra.values()), "b": sum(bool(r[key]) for r in rb.values()),
                         "only_a": only_a, "only_b": only_b, "p": sign_test(len(only_a), len(only_b))})
    set_a_a, set_a_b = set(_rows(a, "a")), set(_rows(b, "a"))
    moved = sorted(set_a_a ^ set_a_b)                           # tickets whose in-scope status differs between the runs (a wider scope)
    changed = sorted(t for t in _rows(a, "all") if _rows(a, "all")[t]["action"] != _rows(b, "all")[t]["action"])
    return {"a": a["run_id"], "b": b["run_id"], "measures": measures, "tickets_with_a_different_action": changed, "tickets_in_scope_in_only_one_run": moved,
            "configuration": {k: {"a": a.get(k), "b": b.get(k)} for k in CONFIG_KEYS if a.get(k) != b.get(k)},
            "replies": {"a": a["replies"], "b": b["replies"]}, "latency_ms": {"a": a["latency_ms"], "b": b["latency_ms"]}}


def render(result: dict) -> str:
    lines = [f"A = {result['a']}", f"B = {result['b']}", "differences in configuration:"]
    for key, pair in result["configuration"].items():
        lines.append(f"  {key}: A {pair['a']}  |  B {pair['b']}")
    lines.append("paired comparison (same tickets):")
    for m in result["measures"]:
        verdict = "no reliable difference" if m["p"] >= 0.05 else ("A better" if len(m["only_a"]) > len(m["only_b"]) else "B better")
        lines.append(f"  {m['measure']}: A {m['a']}/{m['n']}, B {m['b']}/{m['n']}; only A right {len(m['only_a'])}, only B right {len(m['only_b'])}; "
                     f"p = {m['p']:.3f} ({verdict})")
    if result["tickets_in_scope_in_only_one_run"]:
        lines.append(f"not compared (in scope in only one run): {len(result['tickets_in_scope_in_only_one_run'])} tickets")
    lines.append(f"tickets with a different action: {result['tickets_with_a_different_action'] or 'none'}")
    lines.append(f"template fallbacks: A {result['replies']['a']['template_fallbacks']}/{result['replies']['a']['drafts_by_model']}, "
                 f"B {result['replies']['b']['template_fallbacks']}/{result['replies']['b']['drafts_by_model']}")
    lines.append(f"latency per ticket (ms): A {result['latency_ms']['a']}  |  B {result['latency_ms']['b']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("run_a", type=Path)
    p.add_argument("run_b", type=Path)
    args = p.parse_args(argv)
    print(render(compare(load_score(args.run_a), load_score(args.run_b))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())