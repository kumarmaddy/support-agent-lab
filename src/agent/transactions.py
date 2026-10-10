"""Transactional tickets (phase-2-design.md, section 6): the pieces that cancellation, address-change, return and refund tickets need beyond Phase 1.

The decision itself is made in ``decide.py``. This module holds the one extra model task, copying the new delivery address out of
the ticket, and the check that makes its answer safe to use: the address must appear word for word in the ticket and may contain
only the characters an address needs, so the text can neither be invented nor carry an instruction into a reply or a hand-over.
"""
import difflib
import re
from dataclasses import dataclass, field
from typing import Optional

from src.agent import decide as d
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
    """Switches on the cancellation and address-change path (``--transactions``); with a request prompt, returns and exchanges too."""
    address_prompt: Prompt
    request_prompt: Optional[Prompt] = None
    refund_prompt: Optional[Prompt] = None

    @property
    def scope(self) -> frozenset:
        if self.request_prompt is None:
            return d.TRANSACTION_SCOPE
        return d.REFUNDS_SCOPE if self.refund_prompt is not None else d.RETURNS_SCOPE


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


# ------------------------------------------------------------------ returns, exchanges and replacements (stage 2.5b)
REQUEST_KINDS = ("return", "exchange", "replacement", "refund", "unclear")
REQUEST_SCHEMA = {
    "type": "object",
    "properties": {"request": {"type": "string", "enum": list(REQUEST_KINDS)},
                   "item": {"type": "string", "maxLength": 60},
                   "requested_size": {"type": "string", "maxLength": 8}},
    "required": ["request", "item", "requested_size"],
    "additionalProperties": False,
}
REQUEST_MAX_TOKENS = 80
SIZES = frozenset({"XS", "S", "M", "L", "XL", "XXL", "7", "8", "9", "10", "11", "12", "13"})      # KB-RET-04: apparel XS-XXL, footwear 7-13
_ITEM_ALLOWED = re.compile(r"^[A-Za-z0-9 '&-]+$")
MATCH_MIN, MATCH_MARGIN = 0.8, 0.05


@dataclass
class RequestOutcome:
    kind: str                                       # return / exchange / replacement / refund / unclear
    item_phrase: str                                # the customer's words for the product, verified to be in the ticket ("" if none)
    requested_size: str                             # a size from SIZES that appears in the ticket ("" if none)
    reason: str                                     # ok / model_error / invalid
    attempts: list = field(default_factory=list)


def _words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def check_request(content, subject: str, body: str) -> tuple:
    """(kind, item_phrase, requested_size) from the model's answer, keeping only what the ticket itself supports."""
    if not isinstance(content, dict) or content.get("request") not in REQUEST_KINDS:
        return "unclear", "", ""
    ticket = _squash(f"{subject}\n{body}")
    item = _squash(str(content.get("item") or ""))
    if not item or len(item) > 60 or not _ITEM_ALLOWED.fullmatch(item) or item.lower() not in ticket.lower():
        item = ""
    size = _squash(str(content.get("requested_size") or "")).upper()
    if size not in SIZES or not re.search(rf"(?<![\w-]){re.escape(size)}(?![\w-])", ticket.upper()):
        size = ""
    return content["request"], item, size


def read_request(model: ModelClient, prompt: Prompt, subject: str, body: str, seed: int = 0) -> RequestOutcome:
    response = model.chat(prompt.text, render_user(subject, body), REQUEST_SCHEMA, seed=seed, max_tokens=REQUEST_MAX_TOKENS)
    if not response.ok or not isinstance(response.content, dict):
        return RequestOutcome("unclear", "", "", "model_error", [response])
    kind, item, size = check_request(response.content, subject, body)
    return RequestOutcome(kind, item, size, "ok" if response.content.get("request") in REQUEST_KINDS else "invalid", [response])


def match_item(phrase: str, items: tuple):
    """The order line the customer means, or None. A phrase is matched to the order's own product names, so a spelling slip in the
    ticket still finds the right line; two close candidates, or none, give None. With no phrase, a one-line order is that line."""
    if not phrase:
        return items[0] if len(items) == 1 else None
    wanted, scored = _words(phrase), []
    for line in items:
        name = _words(line.product)
        scored.append((1.0 if name and name in wanted else difflib.SequenceMatcher(None, wanted, name).ratio(), line))
    scored.sort(key=lambda pair: -pair[0])
    best = scored[0]
    if best[0] < MATCH_MIN or (len(scored) > 1 and best[0] - scored[1][0] < MATCH_MARGIN):
        return None
    return best[1]


# ------------------------------------------------------------------ refunds (stage 2.5c)
REFUND_TOPICS = ("status", "duplicate_charge", "item_refund", "item_unspecified", "other")
REFUND_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string", "enum": list(REFUND_TOPICS)}},
    "required": ["topic"],
    "additionalProperties": False,
}
REFUND_MAX_TOKENS = 30
_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?!\d)")


@dataclass
class RefundOutcome:
    topic: str                                      # one of REFUND_TOPICS; "other" when the answer is unusable
    reason: str                                     # ok / invalid / model_error
    attempts: list = field(default_factory=list)


def stated_amounts(subject: str, body: str) -> tuple:
    """Every dollar amount written in the ticket, in cents, found by code. The agent never repeats these: it uses them only to check that
    the customer and the payment record agree before a refund is proposed."""
    found = set()
    for whole, cents in _MONEY.findall(f"{subject}\n{body}"):
        found.add(int(whole.replace(",", "")) * 100 + int((cents or "0").ljust(2, "0")))
    return tuple(sorted(found))


def read_refund(model: ModelClient, prompt: Prompt, subject: str, body: str, seed: int = 0) -> RefundOutcome:
    response = model.chat(prompt.text, render_user(subject, body), REFUND_SCHEMA, seed=seed, max_tokens=REFUND_MAX_TOKENS)
    if not response.ok or not isinstance(response.content, dict):
        return RefundOutcome("other", "model_error", [response])
    topic = response.content.get("topic")
    return RefundOutcome(topic, "ok", [response]) if topic in REFUND_TOPICS else RefundOutcome("other", "invalid", [response])