"""Pipeline steps 1 and 2: read the ticket, then check the reading (phase-1-design.md, section 2).

Step 1 asks the model for three things: the category and two yes/no flags. Order numbers are NOT taken from the model:
they follow a fixed format and are found by a pattern in code, which is exact and cannot be talked into a different
number (design change recorded in phase-1-design.md v1.1).

Step 2 checks the model's answer in code. Anything outside the allowed values means the reading failed. One retry is
made with a different seed; if that fails too the outcome is "failed" and the pipeline routes the ticket to a person.

The ticket text goes to the model as data, inside delimiters, with any delimiter lookalike removed and the length capped.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from src.agent.model import ModelClient, ModelResponse
from src.agent.prompting import Prompt
from src.agent.taxonomy import BOUNDARY_RULES, CATEGORIES, DEFINITIONS

MAX_TICKET_CHARS = 4000
MAX_TOKENS = 80
FLAGS = ("states_hard_deadline", "mentions_chargeback_or_legal")
FIELDS = ("category",) + FLAGS
ORDER_ID_PATTERN = re.compile(r"\bO-\d{6}\b", re.IGNORECASE)
_DELIMITER = re.compile(r"<\s*/?\s*ticket\s*>", re.IGNORECASE)

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "states_hard_deadline": {"type": "boolean"},
        "mentions_chargeback_or_legal": {"type": "boolean"},
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Reading:
    category: str
    states_hard_deadline: bool
    mentions_chargeback_or_legal: bool
    order_ids: tuple


@dataclass
class ReadOutcome:
    ok: bool
    reading: Optional[Reading] = None
    reason: Optional[str] = None            # set when not ok: model_error / invalid_reading
    attempts: list = field(default_factory=list)      # ModelResponse for each try, kept for the trace
    prompt: str = ""                        # prompt label, e.g. read_ticket.v1
    prompt_sha256: str = ""


# ------------------------------------------------------------------ helpers
def extract_order_ids(subject: str, body: str) -> tuple:
    """Order numbers written in the ticket: upper-cased, de-duplicated, in order of first appearance."""
    found = []
    for match in ORDER_ID_PATTERN.finditer(f"{subject}\n{body}"):
        order_id = match.group(0).upper()
        if order_id not in found:
            found.append(order_id)
    return tuple(found)


def render_system(prompt: Prompt) -> str:
    categories = "\n".join(f"   - {name}: {DEFINITIONS[name]}" for name in CATEGORIES)
    rules = "\n".join(f"   {i}. {rule}" for i, rule in enumerate(BOUNDARY_RULES, 1))
    return prompt.text.replace("{categories}", categories).replace("{rules}", rules)


def render_user(subject: str, body: str) -> str:
    text = _DELIMITER.sub("", f"Subject: {subject}\n\n{body}")[:MAX_TICKET_CHARS]
    return f"<ticket>\n{text}\n</ticket>"


def check_reading(content: object, order_ids: tuple) -> Optional[Reading]:
    """Step 2. Returns the validated reading, or None if the model's answer is not acceptable."""
    if not isinstance(content, dict) or set(content) != set(FIELDS):
        return None
    if content["category"] not in CATEGORIES:
        return None
    if not all(type(content[name]) is bool for name in FLAGS):
        return None
    return Reading(content["category"], content["states_hard_deadline"], content["mentions_chargeback_or_legal"], order_ids)


# ------------------------------------------------------------------ steps 1 and 2
def read_ticket(model: ModelClient, prompt: Prompt, subject: str, body: str, seed: int = 0) -> ReadOutcome:
    outcome = ReadOutcome(ok=False, prompt=prompt.label, prompt_sha256=prompt.sha256)
    system, user = render_system(prompt), render_user(subject, body)
    order_ids = extract_order_ids(subject, body)
    for attempt in range(2):
        response: ModelResponse = model.chat(system, user, READ_SCHEMA, seed=seed + attempt, max_tokens=MAX_TOKENS)
        outcome.attempts.append(response)
        if not response.ok:
            outcome.reason = "model_error"
            continue
        reading = check_reading(response.content, order_ids)
        if reading is not None:
            outcome.ok, outcome.reading, outcome.reason = True, reading, None
            return outcome
        outcome.reason = "invalid_reading"
    return outcome