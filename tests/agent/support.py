"""Helpers shared by the agent tests: a scripted model and readings derived from the development labels."""
import calendar
from datetime import date

from src.agent.model import ModelResponse

IN_SLICE = ("S01", "S02", "S03", "S04", "S22")


def in_slice(label) -> bool:
    return label["scenario_id"] in IN_SLICE or (label["scenario_id"] == "S24" and label["category"] == "order_status")


class ScriptedModel:
    """A model stand-in. ``read`` and ``reply`` are callables (system, user, seed) -> dict or an error string."""
    model = "scripted:1b"

    def __init__(self, read=None, reply=None):
        self.read, self.reply, self.calls = read, reply, []

    def chat(self, system, user, schema, seed=0, max_tokens=200):
        self.calls.append({"system": system, "user": user, "schema": schema, "seed": seed})
        handler = self.reply if "body" in schema["properties"] else self.read
        out = handler(system, user, seed) if handler else "no_handler"
        return ModelResponse(error=out, seed=seed) if isinstance(out, str) else ModelResponse(content=out, seed=seed, model=self.model)


def deadline_wording(label, ticket) -> str:
    """The words a careful reader would quote for the labelled deadline (empty if the ticket has none)."""
    wanted = label["expected_facts"].get("deadline_date")
    if not wanted:
        return ""
    target, text = date.fromisoformat(wanted), f"{ticket.subject}\n{ticket.body}".lower()
    month, weekday = calendar.month_name[target.month], calendar.day_name[target.weekday()]
    options = (f"{weekday} {month} {target.day}", f"{month} {target.day}", f"{target.day} {month}", weekday)
    return next(o for o in options if o.lower() in text)


def oracle_read(labels_by_id, box, ticket_id):
    """Read-step answer a perfect reader would give for a development ticket."""
    label, ticket = labels_by_id[ticket_id], box.get_ticket(ticket_id).data
    return {"category": label["category"], "deadline_phrase": deadline_wording(label, ticket),
            "mentions_chargeback_or_legal": bool(label["priority_attributes"]["chargeback_or_legal_threat"])}