"""Score manual-baseline results against ground-truth labels and summarise time and accuracy."""
import math
import statistics

CONSEQUENTIAL_ACTIONS = {"propose_refund", "propose_replacement", "propose_exchange", "propose_return_label",
                         "propose_cancellation", "propose_address_change"}


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile (p in 0-100); defined for any non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def score_ticket(result: dict, label: dict) -> dict:
    handled, expected = set(result["actions"]), set(label["expected_actions"])
    required_kb = set(label["required_kb_ids"])
    cited = set(result["kb_ids"])
    return {
        "ticket_id": result["ticket_id"], "scenario_id": label["scenario_id"], "difficulty": label["difficulty"],
        "category": label["category"], "seconds": result["seconds"], "position": result["position"],
        "category_ok": result["category"] == label["category"],
        "actions_ok": handled == expected,
        "escalate_ok": ("escalate_human" in handled) == label["expected_escalate"],
        "consequential_ok": (handled & CONSEQUENTIAL_ACTIONS) == (expected & CONSEQUENTIAL_ACTIONS),
        "kb_ok": required_kb <= cited,
    }


def rate(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows) / len(rows) if rows else float("nan")


def time_stats(seconds: list[float]) -> dict:
    return {"n": len(seconds), "mean": statistics.fmean(seconds), "median": statistics.median(seconds),
            "p90": percentile(seconds, 90), "min": min(seconds), "max": max(seconds), "total": sum(seconds)}


def summarise(results: list[dict], labels_by_id: dict[str, dict]) -> dict:
    """Statistics for the scored (non-practice) results."""
    scored = [r for r in results if not r["practice"]]
    if not scored:
        raise ValueError("no scored results yet")
    rows = [score_ticket(r, labels_by_id[r["ticket_id"]]) for r in scored]
    rows.sort(key=lambda r: r["position"])
    third = max(1, len(rows) // 3)
    by_difficulty = {}
    for difficulty in ("standard", "edge", "adversarial"):
        subset = [r for r in rows if r["difficulty"] == difficulty]
        if subset:
            by_difficulty[difficulty] = {**time_stats([r["seconds"] for r in subset]),
                                         "actions_ok": rate(subset, "actions_ok")}
    return {
        "tickets": len(rows),
        "time": time_stats([r["seconds"] for r in rows]),
        "accuracy": {k: rate(rows, k) for k in ("category_ok", "actions_ok", "escalate_ok", "consequential_ok", "kb_ok")},
        "by_difficulty": by_difficulty,
        "learning": {"first_third_median": statistics.median(r["seconds"] for r in rows[:third]),
                     "last_third_median": statistics.median(r["seconds"] for r in rows[-third:]), "third": third},
        "misses": [{"ticket_id": r["ticket_id"], "scenario_id": r["scenario_id"]}
                   for r in rows if not (r["actions_ok"] and r["category_ok"])],
        "pauses": sum(r["pauses"] for r in scored),
    }
