"""Stratified, seeded sample of development tickets for the manual baseline.

Every scenario appears at least once, so rare and difficult families (such as approval-pressure tickets) are
measured, and the rest of the sample follows the dataset's own mix. The held-out split is never sampled.
"""
import random

PRACTICE_TICKETS = 3


def allocate(counts: dict[str, int], n: int) -> dict[str, int]:
    """Split n sample slots across scenarios: at least one each, then in proportion to scenario size."""
    if not len(counts) <= n <= sum(counts.values()):
        raise ValueError(f"sample size must be between {len(counts)} and {sum(counts.values())}")
    total = sum(counts.values())
    ideal = {s: n * c / total for s, c in counts.items()}
    alloc = {s: 1 for s in counts}
    for _ in range(n - len(counts)):
        open_scenarios = [s for s in sorted(counts) if alloc[s] < counts[s]]
        alloc[max(open_scenarios, key=lambda s: ideal[s] - alloc[s])] += 1
    return alloc


def select_sample(labels: list[dict], n: int, seed: int) -> dict:
    """Pick n scored tickets plus a few practice tickets, in a random working order."""
    if any(lab["split"] != "dev" for lab in labels):
        raise ValueError("the baseline uses development tickets only")
    by_scenario: dict[str, list[str]] = {}
    for lab in sorted(labels, key=lambda x: x["ticket_id"]):
        by_scenario.setdefault(lab["scenario_id"], []).append(lab["ticket_id"])
    allocation = allocate({s: len(ids) for s, ids in by_scenario.items()}, n)
    chosen, leftover = [], []
    for scenario, ids in sorted(by_scenario.items()):
        rng = random.Random(f"{seed}:baseline:{scenario}")
        picked = rng.sample(ids, allocation[scenario])
        chosen += picked
        leftover += [i for i in ids if i not in picked]
    random.Random(f"{seed}:baseline:order").shuffle(chosen)
    practice = random.Random(f"{seed}:baseline:practice").sample(sorted(leftover), PRACTICE_TICKETS)
    return {"seed": seed, "size": n, "split": "dev", "practice_ids": practice, "ticket_ids": chosen}
