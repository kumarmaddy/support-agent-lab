"""Score manual-baseline results against ground-truth labels and summarise time and accuracy."""
import math
import statistics

CONSEQUENTIAL_ACTIONS = {"propose_refund", "propose_replacement", "propose_exchange", "propose_return_label",
                         "propose_cancellation", "propose_address_change"}


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile (p in 0-100); defined for any non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion; (nan, nan) when n is 0.

    Preferred over the normal approximation because it stays inside 0-1 and behaves at small n and near 0% or 100%.
    """
    if n == 0:
        return float("nan"), float("nan")
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


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
        # detail kept for the disagreement review
        "handled_category": result["category"], "handled_actions": sorted(handled),
        "expected_actions": sorted(expected), "handled_escalate": "escalate_human" in handled,
        "expected_escalate": label["expected_escalate"], "missing_kb": sorted(required_kb - cited),
        "consequential_relevant": bool((handled | expected) & CONSEQUENTIAL_ACTIONS),
    }


def rate(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows) / len(rows) if rows else float("nan")


MEASURES = ("category_ok", "actions_ok", "escalate_ok", "consequential_ok", "kb_ok")


def escalation_matrix(rows: list[dict]) -> dict:
    """Escalation as a binary decision: positive = the ticket should be (or was) escalated to a human."""
    tp = sum(r["handled_escalate"] and r["expected_escalate"] for r in rows)
    fp = sum(r["handled_escalate"] and not r["expected_escalate"] for r in rows)
    fn = sum(not r["handled_escalate"] and r["expected_escalate"] for r in rows)
    tn = sum(not r["handled_escalate"] and not r["expected_escalate"] for r in rows)
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else float("nan"),
            "recall": tp / (tp + fn) if tp + fn else float("nan")}


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
    relevant = [r for r in rows if r["consequential_relevant"]]
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
        "accuracy": {k: rate(rows, k) for k in MEASURES},
        "counts": {k: {"correct": sum(r[k] for r in rows), "n": len(rows)} for k in MEASURES},
        "consequential_relevant": {"correct": sum(r["consequential_ok"] for r in relevant), "n": len(relevant)},
        "escalation": escalation_matrix(rows),
        "by_difficulty": by_difficulty,
        "learning": {"first_third_median": statistics.median(r["seconds"] for r in rows[:third]),
                     "last_third_median": statistics.median(r["seconds"] for r in rows[-third:]), "third": third,
                     "first_third_mean": statistics.fmean(r["seconds"] for r in rows[:third]),
                     "last_third_mean": statistics.fmean(r["seconds"] for r in rows[-third:])},
        "misses": [{"ticket_id": r["ticket_id"], "scenario_id": r["scenario_id"]}
                   for r in rows if not (r["actions_ok"] and r["category_ok"])],
        "disagreements": [r for r in rows if not all(r[k] for k in MEASURES)],
        "pauses": sum(r["pauses"] for r in scored),
    }