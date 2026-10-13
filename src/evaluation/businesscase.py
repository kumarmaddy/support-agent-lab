"""Stage 4.6: the business case (criterion P11). Method and fixed choices: docs/project/stage-4.6-business-case-method.md.

    python -m src.evaluation.businesscase --run data\\runs\\run-20261012-145613-97bb60

All inputs are read from files; the labour-cost and volume grids and the review-share grid are the only assumptions.
Run-rate handling cost only. Not an ROI.
"""
import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path

from src.baseline.scoring import wilson_interval
from src.evaluation.score import HAND_OVERS, PROPOSALS

RATES = (15, 25, 40, 60)
VOLUMES = (1000, 5000, 20000)
REVIEW_SHARES = (0.25, 0.50, 0.75, 1.00)
BASE = {"f": 0.50, "rate": 25, "volume": 5000}
ELIGIBLE_SWING = 0.10


# ------------------------------------------------------------------ pure arithmetic
def s0(t: float) -> float:
    return t


def s1(t: float, f: float, h: float) -> float:
    return f * t + h * t


def s2(t: float, f: float, h: float, e: float) -> float:
    return f * t * (1 - e) + h * t


def cost(seconds: float, rate: float) -> float:
    return seconds / 3600 * rate


def break_even_f(h: float) -> float:
    """S1 costs the same as S0 when f*T + h*T = T."""
    return 1 - h


def monthly_saving(seconds_saved: float, rate: float, volume: int) -> float:
    return cost(seconds_saved, rate) * volume


# ------------------------------------------------------------------ inputs
def read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def comparators(baseline: list, manual: list) -> dict:
    """The three values of T (mean seconds per ticket), from the files."""
    scored = sorted((r for r in baseline if not r["practice"]), key=lambda r: r["position"])
    third = max(1, len(scored) // 3)
    held = [r["seconds"] for r in manual if not r["practice"]]
    return {"untrained": {"seconds": statistics.fmean(r["seconds"] for r in scored), "n": len(scored), "label": "Untrained handler (dev baseline, mean of 40)"},
            "trained": {"seconds": statistics.fmean(r["seconds"] for r in scored[-third:]), "n": third, "label": f"Trained handler (dev baseline, last {third})"},
            "heldout": {"seconds": statistics.fmean(held), "n": len(held), "label": "Held-out Step A (mean of 40)"}}


def agent_shares(score: dict, autoresolve: dict) -> dict:
    rows = score["rows"]
    n = len(rows)
    handed = sum(1 for r in rows if r["action"] in HAND_OVERS)
    wrong_proposals = [r["ticket_id"] for r in rows if r["action"] in PROPOSALS and (not r["in_slice"] or not r.get("end_to_end_ok", False))]
    proposals = sum(1 for r in rows if r["action"] in PROPOSALS)
    e = autoresolve["eligible_of_all"]
    lo, hi = wilson_interval(handed, n)
    return {"n": n, "h": handed / n, "h_interval": (lo, hi), "handed": handed, "e": e["k"] / e["n"], "e_interval": (e["low"], e["high"]), "eligible": e["k"],
            "proposals": proposals, "wrong_proposals": sorted(wrong_proposals),
            "missed_escalations": sorted(r["ticket_id"] for r in rows if r["label_escalate"] and r["action"] != "escalate_human")}


# ------------------------------------------------------------------ the case
def build(comp: dict, shares: dict, build_hours=None) -> dict:
    h, e = shares["h"], shares["e"]
    out = {"shares": shares, "break_even_f": break_even_f(h), "base": BASE, "comparators": {}}
    for key, c in comp.items():
        t = c["seconds"]
        f, r, v = BASE["f"], BASE["rate"], BASE["volume"]
        base = {"S0": s0(t), "S1": s1(t, f, h), "S2": s2(t, f, h, e)}
        entry = {"label": c["label"], "T": t, "n": c["n"], "base_seconds": base,
                 "base_cost": {k: cost(x, r) for k, x in base.items()},
                 "s1_saving_per_ticket": {f"{int(fs * 100)}%": {rt: cost(s0(t) - s1(t, fs, h), rt) for rt in RATES} for fs in REVIEW_SHARES},
                 "monthly": {rt: {vol: {"S1": monthly_saving(s0(t) - s1(t, f, h), rt, vol), "S2": monthly_saving(s0(t) - s2(t, f, h, e), rt, vol)} for vol in VOLUMES} for rt in RATES},
                 "s2_by_eligible_share": {f"{x:.0%}": {"seconds": s2(t, f, h, max(0.0, min(1.0, x))), "monthly_saving": monthly_saving(s0(t) - s2(t, f, h, max(0.0, min(1.0, x))), r, v)}
                                          for x in (max(0.0, e - ELIGIBLE_SWING), e, min(1.0, e + ELIGIBLE_SWING))}}
        if build_hours is not None:
            m = entry["monthly"][r][v]["S1"]
            entry["payback_months_s1_base"] = None if m <= 0 else build_hours * r / m
        out["comparators"][key] = entry
    return out


def cents(x: float) -> str:
    """Per-ticket costs are a few cents to a few dollars; whole dollars would hide the comparison."""
    return f"${x:,.2f}"


def money(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def render(case: dict, run_id: str, day: str, build_hours=None) -> str:
    sh, b = case["shares"], case["base"]
    L = ["# Phase 4 Business Case (stage 4.6, criterion P11)", "",
         f"Generated by `python -m src.evaluation.businesscase` on {day}. Method and fixed choices: `stage-4.6-business-case-method.md`, written before any figure was computed. Agent figures from `{run_id}` and `phase-4-autoresolve-results.md`.", "",
         "**This is a run-rate handling-cost comparison under stated assumptions, not a return on investment.** It excludes build effort, hardware, maintenance, model upgrades, monitoring, training and the cost of wrong actions. Compute cost is $0.", "",
         "## 1. What the agent contributes (measured)", "", "| Measure | Value |", "|---|---|",
         f"| Tickets handed to a person (h) | {sh['handed']} of {sh['n']} = {sh['h']:.1%} (95% interval {sh['h_interval'][0]:.1%} to {sh['h_interval'][1]:.1%}) |",
         f"| Eligible for auto-resolve (e), from the simulation | {sh['eligible']} of {sh['n']} = {sh['e']:.1%} (95% interval {sh['e_interval'][0]:.1%} to {sh['e_interval'][1]:.1%}) |",
         f"| Wrong proposals (not monetised) | {len(sh['wrong_proposals'])} of {sh['proposals']}" + (f" ({', '.join(sh['wrong_proposals'])})" if sh["wrong_proposals"] else "") + " |",
         f"| Escalations missed (not monetised) | {len(sh['missed_escalations'])}" + (f" ({', '.join(sh['missed_escalations'])})" if sh["missed_escalations"] else "") + " |", "",
         "## 2. The number that matters most: break-even review time", "",
         f"Drafting and approving costs the same as handling by hand when a person reviews a draft in **{case['break_even_f']:.0%} of the time** of handling a ticket by hand (1 minus the hand-over share, because hand-overs need the full manual handling as well). Faster than that saves time; slower costs more.", "",
         "**No review time was measured in this project.** The shadow-mode review timings were not valid (median 2 s, below the time needed to read a ticket and its draft). Every saving below depends on the review share f, which is a grid, not a result.", "",
         f"## 3. Base case ({b['f']:.0%} review share, ${b['rate']} per hour, {b['volume']:,} tickets per month)", "",
         "The base case is a mid-grid point to show one set of numbers. It is not a forecast.", "",
         "| Time to handle by hand (T) | T (s) | S0 per ticket | S1 per ticket | S2 per ticket | Time saved S1 / S2 | S1 saving per month | S2 saving per month |", "|---|---|---|---|---|---|---|---|"]
    for c in case["comparators"].values():
        m = c["monthly"][b["rate"]][b["volume"]]
        L.append(f"| {c['label']} | {c['T']:.0f} | {cents(c['base_cost']['S0'])} | {cents(c['base_cost']['S1'])} | {cents(c['base_cost']['S2'])} | {1 - c['base_seconds']['S1'] / c['T']:.0%} / {1 - c['base_seconds']['S2'] / c['T']:.0%} | {money(m['S1'])} | {money(m['S2'])} |")
    L += ["", "Costs per ticket are in dollars. S0 = handled by hand. S1 = a person reviews every draft and handles the hand-overs. S2 = S1, with eligible tickets sent without review.", "",
          "## 4. Sensitivity: saving per ticket, S1, by review share and labour cost", ""]
    for c in case["comparators"].values():
        L += [f"**{c['label']}** (T = {c['T']:.0f} s)", "", "| Review share f | " + " | ".join(f"${r}/h" for r in RATES) + " |", "|---|" + "---|" * len(RATES)]
        for fs, row in c["s1_saving_per_ticket"].items():
            L.append(f"| {fs} | " + " | ".join(f"{'-' if row[r] < 0 else ''}${abs(row[r]):.2f}" for r in RATES) + " |")
        L.append("")
    L += [f"## 5. Monthly saving by labour cost and volume (review share {b['f']:.0%})", ""]
    for c in case["comparators"].values():
        L += [f"**{c['label']}**", "", "| Labour cost | " + " | ".join(f"{v:,}/month: S1 / S2" for v in VOLUMES) + " |", "|---|" + "---|" * len(VOLUMES)]
        for r in RATES:
            L.append(f"| ${r}/h | " + " | ".join(f"{money(c['monthly'][r][v]['S1'])} / {money(c['monthly'][r][v]['S2'])}" for v in VOLUMES) + " |")
        L.append("")
    L += ["## 6. Sensitivity of S2 to the eligible share (±10 percentage points)", "", "| T | " + " | ".join(next(iter(case["comparators"].values()))["s2_by_eligible_share"]) + " |",
          "|---|" + "---|" * 3]
    for c in case["comparators"].values():
        L.append(f"| {c['label']} | " + " | ".join(f"{money(v['monthly_saving'])} per month" for v in c["s2_by_eligible_share"].values()) + " |")
    L += ["", f"Base case rate and volume. The eligible share in the middle column is the measured one ({sh['e']:.1%})."]
    if build_hours is not None:
        L += ["", "## 7. Payback (build effort supplied by the project lead)", "",
              f"Build effort entered: {build_hours:,.0f} hours, valued at the base labour cost. This line excludes everything listed at the top of this document.", "",
              "| Time to handle by hand | Months of S1 saving to cover the build effort |", "|---|---|"]
        for c in case["comparators"].values():
            p = c.get("payback_months_s1_base")
            L.append(f"| {c['label']} | {'no saving at this review share' if p is None else f'{p:.1f}'} |")
    L += ["", "## Limits", "",
          "- One handler, who also built the system; synthetic tickets; the learning effect is shown by the three comparators.",
          "- h and e come from one temperature-0 run on 150 tickets; the intervals above are wide.",
          "- The production mix is assumed equal to the held-out mix (25 of 150 tickets outside the agent's scope).",
          "- Labour cost, volume and review time are assumptions to confirm with Finance and Support Operations.",
          "- S2 rests on the stage 4.5 simulation, which is \"not yet acceptable\". It shows what a pilot could save, not that one is approved.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run-rate business case from stored evaluation files.")
    p.add_argument("--run", type=Path, required=True, help="the gated held-out 7B run folder (needs score.json and autoresolve.json)")
    p.add_argument("--baseline", type=Path, default=Path("data/baseline/results.jsonl"))
    p.add_argument("--manual", type=Path, default=Path("data/shadow/manual.jsonl"))
    p.add_argument("--build-hours", type=float, default=None, help="optional one-off build effort for a simple payback line")
    p.add_argument("--report", type=Path, default=Path("docs/project/phase-4-business-case.md"))
    args = p.parse_args(argv)
    for name in ("score.json", "autoresolve.json"):
        if not (args.run / name).exists():
            print(f"{args.run / name} not found; run the held-out scoring and `python -m src.evaluation.autoresolve` first.")
            return 2
    score = json.loads((args.run / "score.json").read_text(encoding="utf-8"))
    auto = json.loads((args.run / "autoresolve.json").read_text(encoding="utf-8"))
    case = build(comparators(read_jsonl(args.baseline), read_jsonl(args.manual)), agent_shares(score, auto), args.build_hours)
    text = render(case, args.run.name, date.today().isoformat(), args.build_hours)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(text, encoding="utf-8", newline="\n")
    (args.run / "businesscase.json").write_text(json.dumps(case, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())