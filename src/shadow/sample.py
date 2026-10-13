"""The shadow-mode sample: 40 held-out tickets, stratified by scenario, drawn with a recorded seed (phase-4-design-and-acceptance.md section 6).

Same allocation as the manual baseline (every scenario at least once, the rest in proportion to the dataset's mix). Only the scenario ids of the
labels are read here, never the expected answers, and the handler is not told a scenario. There are no practice tickets: the handler has done the
practice in the baseline, and each held-out ticket is used once.
"""
import random

from src.baseline.sampling import allocate

DEFAULT_SEED = 40404
DEFAULT_SIZE = 40
RATER_TICKETS = 20


def select_shadow_sample(labels: list, n: int = DEFAULT_SIZE, seed: int = DEFAULT_SEED, raters: int = RATER_TICKETS) -> dict:
    if not labels or any(lab["split"] != "heldout" for lab in labels):
        raise ValueError("the shadow sample is drawn from the held-out split only")
    by_scenario: dict = {}
    for lab in sorted(labels, key=lambda x: x["ticket_id"]):
        by_scenario.setdefault(lab["scenario_id"], []).append(lab["ticket_id"])
    allocation = allocate({s: len(ids) for s, ids in by_scenario.items()}, n)
    chosen = []
    for scenario, ids in sorted(by_scenario.items()):
        chosen += random.Random(f"{seed}:shadow:{scenario}").sample(ids, allocation[scenario])
    random.Random(f"{seed}:shadow:order").shuffle(chosen)                       # the order for Step A
    review_order = list(chosen)
    random.Random(f"{seed}:shadow:review-order").shuffle(review_order)           # a different order for Step B, so position does not carry over
    rater_ids = sorted(random.Random(f"{seed}:shadow:rater").sample(chosen, min(raters, n)))
    return {"seed": seed, "size": n, "split": "heldout", "practice_ids": [], "ticket_ids": chosen, "review_order": review_order,
            "rater_ids": rater_ids}