"""Ground-truth label construction, validation and file output (docs/design/data-design.md section 6)."""
import json
from pathlib import Path

from src.datagen import config
from src.datagen.domain.kb_catalogue import KB_ARTICLES
from src.datagen.domain.priority import compute_priority
from src.datagen.domain.taxonomy import (
    ACTIONS,
    ADVERSARIAL_TYPES,
    CATEGORIES,
    DIFFICULTIES,
    PRIORITIES,
    PRIORITY_ATTRIBUTES,
    SPLITS,
    TEXT_SOURCES,
)

REQUIRED_KEYS = (
    "ticket_id", "scenario_id", "split", "category", "secondary_categories", "priority",
    "priority_attributes", "expected_actions", "expected_escalate", "escalation_reason",
    "required_kb_ids", "referenced_order_id", "order_identifiable", "expected_facts",
    "difficulty", "adversarial_type", "ambiguity_flag", "text_source", "generator_version", "seed",
)


def new_label(*, scenario_id: str, category: str, attributes: dict[str, bool],
              expected_actions: list[str], required_kb_ids: list[str],
              referenced_order_id: str | None, order_identifiable: bool = True,
              expected_escalate: bool = False, escalation_reason: str | None = None,
              expected_facts: dict | None = None, difficulty: str = "standard",
              adversarial_type: str | None = None, ambiguity_flag: bool = False,
              secondary_categories: tuple[str, ...] = ()) -> dict:
    """Create a label. ticket_id, split and seed are filled in when the dataset is assembled."""
    return {
        "ticket_id": None,
        "scenario_id": scenario_id,
        "split": None,
        "category": category,
        "secondary_categories": list(secondary_categories),
        "priority": compute_priority(attributes),
        "priority_attributes": dict(attributes),
        "expected_actions": list(expected_actions),
        "expected_escalate": expected_escalate,
        "escalation_reason": escalation_reason,
        "required_kb_ids": list(required_kb_ids),
        "referenced_order_id": referenced_order_id,
        "order_identifiable": order_identifiable,
        "expected_facts": expected_facts or {},
        "difficulty": difficulty,
        "adversarial_type": adversarial_type,
        "ambiguity_flag": ambiguity_flag,
        "text_source": "template",
        "generator_version": config.GENERATOR_VERSION,
        "seed": None,
    }


def label_problems(label: dict) -> list[str]:
    """Return a list of problems with a label; an empty list means the label is valid."""
    p: list[str] = []
    missing = [k for k in REQUIRED_KEYS if k not in label]
    if missing:
        return [f"missing keys: {missing}"]
    extra = [k for k in label if k not in REQUIRED_KEYS]
    if extra:
        p.append(f"unexpected keys: {extra}")

    if label["category"] not in CATEGORIES:
        p.append(f"invalid category: {label['category']}")
    for c in label["secondary_categories"]:
        if c not in CATEGORIES:
            p.append(f"invalid secondary category: {c}")
    if label["priority"] not in PRIORITIES:
        p.append(f"invalid priority: {label['priority']}")
    attrs = label["priority_attributes"]
    if set(attrs) != set(PRIORITY_ATTRIBUTES):
        p.append("priority_attributes must contain exactly the rubric attributes")
    elif label["priority"] != compute_priority(attrs):
        p.append(f"priority {label['priority']} does not match attributes ({compute_priority(attrs)})")

    actions = label["expected_actions"]
    if not actions:
        p.append("expected_actions must not be empty")
    p += [f"invalid action: {a}" for a in actions if a not in ACTIONS]
    if label["expected_escalate"] != ("escalate_human" in actions):
        p.append("expected_escalate must be true exactly when escalate_human is an expected action")
    if label["expected_escalate"] and not label["escalation_reason"]:
        p.append("escalation_reason is required when expected_escalate is true")

    p += [f"unknown KB id: {k}" for k in label["required_kb_ids"] if k not in KB_ARTICLES]

    has_order = label["referenced_order_id"] is not None
    if label["order_identifiable"] != has_order:
        p.append("order_identifiable must be true exactly when referenced_order_id is set")

    if label["difficulty"] not in DIFFICULTIES:
        p.append(f"invalid difficulty: {label['difficulty']}")
    if label["adversarial_type"] is not None and label["adversarial_type"] not in ADVERSARIAL_TYPES:
        p.append(f"invalid adversarial_type: {label['adversarial_type']}")
    if (label["difficulty"] == "adversarial") != (label["adversarial_type"] is not None):
        p.append("difficulty 'adversarial' and adversarial_type must go together")
    if label["split"] not in SPLITS:
        p.append(f"invalid split: {label['split']}")
    if label["text_source"] not in TEXT_SOURCES:
        p.append(f"invalid text_source: {label['text_source']}")
    if not isinstance(label["expected_facts"], dict):
        p.append("expected_facts must be an object")
    if not isinstance(label["ambiguity_flag"], bool):
        p.append("ambiguity_flag must be boolean")
    return p


def validate_label(label: dict) -> None:
    problems = label_problems(label)
    if problems:
        raise ValueError(f"invalid label {label.get('ticket_id')}: " + "; ".join(problems))


def write_labels(path: Path, labels: list[dict]) -> None:
    """Write labels as JSON Lines, sorted by ticket id.

    Uses UTF-8 and '\\n' line endings on every operating system so the file hash is identical on
    Windows and Linux.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for label in sorted(labels, key=lambda x: x["ticket_id"]):
            f.write(json.dumps(label, ensure_ascii=False) + "\n")


def read_labels(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]