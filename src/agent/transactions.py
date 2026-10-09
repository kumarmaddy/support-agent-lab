"""Transactional tickets (phase-2-design.md, section 6): the pieces that cancellation and address-change tickets need beyond Phase 1.

The decision itself is made in ``decide.py``. This module holds the one extra model task, copying the new delivery address out of
the ticket, and the check that makes its answer safe to use: the address must appear word for word in the ticket and may contain
only the characters an address needs, so the text can neither be invented nor carry an instruction into a reply or a hand-over.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

from src.agent.model import ModelClient, ModelResponse
from src.agent.prompting import Prompt
from src.agent.reading import render_user

ADDRESS_SCHEMA = {
    "type": "object",
    "properties": {"address": {"type": "string", "maxLength": 100}},
    "required": ["address"],
    "additionalProperties": False,
}
ADDRESS_MAX_TOKENS = 60
MAX_ADDRESS_CHARS = 100
_ALLOWED = re.compile(r"^[A-Za-z0-9 ,.'#/-]+$")


@dataclass(frozen=True)
class Transactions:
    """Switches on the cancellation and address-change path (``--transactions``)."""
    address_prompt: Prompt


@dataclass
class AddressOutcome:
    address: str                                    # "" when nothing usable was found
    reason: str                                     # ok / empty / not_in_ticket / bad_characters / too_short / model_error
    response: Optional[ModelResponse] = None
    attempts: list = field(default_factory=list)


def _squash(text: str) -> str:
    return " ".join(text.split())


def check_address(candidate, subject: str, body: str) -> tuple:
    """(address, reason). The address is returned only when it passes every rule; the reason names the first rule that failed."""
    if not isinstance(candidate, str):
        return "", "empty"
    address = _squash(candidate).strip(" .,;")
    if not address:
        return "", "empty"
    if len(address) > MAX_ADDRESS_CHARS or not _ALLOWED.fullmatch(address):
        return "", "bad_characters"
    if len(address.split()) < 2 or not any(ch.isdigit() for ch in address):
        return "", "too_short"
    if address not in _squash(f"{subject}\n{body}"):
        return "", "not_in_ticket"
    return address, "ok"


def extract_address(model: ModelClient, prompt: Prompt, subject: str, body: str, seed: int = 0) -> AddressOutcome:
    response = model.chat(prompt.text, render_user(subject, body), ADDRESS_SCHEMA, seed=seed, max_tokens=ADDRESS_MAX_TOKENS)
    if not response.ok or not isinstance(response.content, dict):
        return AddressOutcome("", "model_error", response, [response])
    address, reason = check_address(response.content.get("address"), subject, body)
    return AddressOutcome(address, reason, response, [response])