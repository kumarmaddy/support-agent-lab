"""Registry of all scenario families, in a fixed order.

Order matters for reproducibility: order and ticket ids are allocated in this sequence, so a new
family must be appended, never inserted before existing ones, while a dataset version is in use.
"""
from src.datagen.scenarios import accounts, adversarial, changes, order_status, returns
from src.datagen.scenarios.base import ScenarioDef

SCENARIOS: list[ScenarioDef] = [
    *order_status.SCENARIOS,
    *returns.SCENARIOS,
    *changes.SCENARIOS,
    *accounts.SCENARIOS,
    *adversarial.SCENARIOS,
]


def get_scenarios(scenario_ids: set[str] | None = None) -> list[ScenarioDef]:
    if scenario_ids is None:
        return list(SCENARIOS)
    unknown = scenario_ids - {s.scenario_id for s in SCENARIOS}
    if unknown:
        raise ValueError(f"unknown scenario ids: {sorted(unknown)}")
    return [s for s in SCENARIOS if s.scenario_id in scenario_ids]