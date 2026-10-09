"""Pipeline step 6: validate a reply before it is used (phase-1-design.md, section 6).

A reply passes only if it uses no fact that was not supplied. The checks are mechanical on purpose, so the same rules apply to
a model-written reply and to a template, and a failure always names the rule that failed.

Rules (each returns a short code):
  length           empty, or longer than MAX_CHARS
  unknown_date     a calendar date that is not one of the supplied dates
  relative_time    weekday names, today/tomorrow, "within N days": promises or guesses about timing
  unknown_order    an order number that was not supplied
  unknown_token    a long number or reference (for example a tracking number) that was not supplied
  amount           any money amount (none are ever supplied in this slice)
  promise          refund, compensation, discount, credit, expedite, upgrade, guarantee, replacement, "will arrive"
  internal_text    a knowledge-base id, an internal-guidance marker, or six consecutive words copied from internal guidance
  prompt_leak      mentions of prompts, tools, instructions or the ticket delimiters
  unsupported_claim  directs the customer to a channel nobody supplied (website, app, portal, phone, link)
  misplaced_reference  a supplied reference (tracking number) that is not introduced as a number or reference
  missing_fact     a fact the reply must contain (for example the tracking number) is absent
"""
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Optional

MAX_CHARS = 700
SHINGLE_WORDS = 6

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
_MONTH_ALT = "|".join(_MONTHS + tuple(m[:3] for m in _MONTHS) + ("sept",))
_DATE_MD = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
_DATE_DM = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_ALT})\b\.?(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_RELATIVE = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|tomorrow|yesterday)\b"
                       r"|\bwithin\s+\w+(?:\s+\w+)?\s+(?:hours?|days?|weeks?)\b|\bby\s+(?:the\s+)?end\s+of\b|\bnext\s+(?:week|day)\b", re.IGNORECASE)
_ORDER_ID = re.compile(r"\bO-\d{6}\b", re.IGNORECASE)
_ORDER_LIKE = re.compile(r"\bORDER[-\s#]?\d{3,}\b|#\s?\d{4,}", re.IGNORECASE)     # an order number in some other shape is invented too
_TOKEN = re.compile(r"\b(?:[A-Z]{1,4}\d{6,}|\d{6,})\b")
_AMOUNT = re.compile(r"[$€£]\s?\d|\b\d+(?:[.,]\d+)?\s?(?:usd|dollars?|euros?|pounds?)\b", re.IGNORECASE)
_PROMISE = re.compile(r"\b(refund\w*|compensat\w*|voucher\w*|discount\w*|credit\w*|reimburs\w*|expedit\w*|upgrad\w*|guarantee\w*|"
                      r"replacement\w*|free of charge)\b|\bwill\s+(?:arrive|be\s+delivered|be\s+dispatched|ship|reach)\b", re.IGNORECASE)
_INTERNAL = re.compile(r"\bKB-[A-Z]{3}-\d{2}\b|support guidance|\binternal\b", re.IGNORECASE)
_CHANNEL = re.compile(r"\b(web\s?site|web\s?page|portal|app|online|click|links?|url|https?\S*|call (?:us|our)|phone|hotline|live chat|contact us|email us)\b", re.IGNORECASE)
_REFERENCE_LABEL = re.compile(r"(?:number|no\.?|reference|ref\.?|id|code)\W*(?:is\W*)?$", re.IGNORECASE)
_DISPATCH_WORD = re.compile(r"\b(ship|ships|shipped|shipping|dispatch|dispatches|dispatched|dispatching|send|sent)\b", re.IGNORECASE)
_LEAK = re.compile(r"system prompt|\bprompt\b|\btools?\b|\binstructions?\b|</?ticket>|\bas an ai\b|\blanguage model\b", re.IGNORECASE)


@dataclass(frozen=True)
class ReplyFacts:
    """What a reply may state, and what it must state."""
    allowed_dates: frozenset = frozenset()          # datetime.date values
    allowed_ids: frozenset = frozenset()            # order numbers, upper-case
    allowed_tokens: frozenset = frozenset()         # tracking numbers and other references
    must_include: tuple = ()                        # rendered strings that must appear in the reply
    delivery_dates_only: bool = False               # the only dates supplied are delivery promises (no dispatch date is known)


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9']+", text.lower())


def _shingles(words: list, size: int) -> set:
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def internal_shingles(guidance_texts: Iterable[str]) -> frozenset:
    found = set()
    for text in guidance_texts:
        found |= _shingles(_words(text), SHINGLE_WORDS)
    return frozenset(found)


def _month_number(name: str) -> int:
    key = name.lower().rstrip(".")
    if key == "sept":
        return 9
    for number, full in enumerate(_MONTHS, 1):
        if full == key or full[:3] == key:
            return number
    raise ValueError(name)


def dates_in(text: str) -> list:
    """Every (month, day, year-or-None) written in the text."""
    found = [(_month_number(m[1]), int(m[2]), int(m[3]) if m[3] else None) for m in _DATE_MD.finditer(text)]
    found += [(_month_number(m[2]), int(m[1]), int(m[3]) if m[3] else None) for m in _DATE_DM.finditer(text)]
    found += [(int(m[2]), int(m[3]), int(m[1])) for m in _DATE_ISO.finditer(text)]
    return found


def missing_facts(text: str, facts: ReplyFacts) -> list:
    lowered = text.lower()
    return [item for item in facts.must_include if item.lower() not in lowered]


def _misplaced_reference(text: str, facts: ReplyFacts) -> bool:
    """True when a supplied reference appears without a label such as 'tracking number' just before it, which is how a
    tracking number ends up in a sentence about the status."""
    for token in facts.allowed_tokens:
        for match in re.finditer(re.escape(token), text, re.IGNORECASE):
            if not _REFERENCE_LABEL.search(text[max(0, match.start() - 30):match.start()]):
                return True
    return False


def _dispatch_date(text: str) -> bool:
    """True when one sentence has both a date and a shipping word: the date supplied is the delivery promise, not a dispatch date."""
    return any(_DISPATCH_WORD.search(sentence) and dates_in(sentence) for sentence in re.split(r"(?<=[.!?])\s+", text))


def validate_reply(text: str, facts: ReplyFacts, internal: frozenset = frozenset()) -> list:
    """Return the codes of the rules the reply breaks; an empty list means it passes."""
    failures = []
    if not text.strip() or len(text) > MAX_CHARS:
        failures.append("length")
    allowed = {(d.month, d.day, d.year) for d in facts.allowed_dates}
    for month, day, year in dates_in(text):
        if not any((month, day) == (a[0], a[1]) and year in (None, a[2]) for a in allowed):
            failures.append("unknown_date")
            break
    if _RELATIVE.search(text):
        failures.append("relative_time")
    if any(m.group(0).upper() not in facts.allowed_ids for m in _ORDER_ID.finditer(text)) or _ORDER_LIKE.search(text):
        failures.append("unknown_order")
    without_orders = _ORDER_ID.sub(" ", text)
    if any(m.group(0).upper() not in facts.allowed_tokens for m in _TOKEN.finditer(without_orders)):
        failures.append("unknown_token")
    if _AMOUNT.search(text):
        failures.append("amount")
    if _PROMISE.search(text):
        failures.append("promise")
    if _CHANNEL.search(text):
        failures.append("unsupported_claim")
    if facts.delivery_dates_only and _dispatch_date(text):
        failures.append("wrong_date_role")
    if _misplaced_reference(text, facts):
        failures.append("misplaced_reference")
    if _INTERNAL.search(text) or (internal and _shingles(_words(text), SHINGLE_WORDS) & internal):
        failures.append("internal_text")
    if _LEAK.search(text):
        failures.append("prompt_leak")
    if missing_facts(text, facts):
        failures.append("missing_fact")
    return failures


# ------------------------------------------------------------------ knowledge answers (phase-2-design.md, section 4, gate 3)
_NUMBER = re.compile(r"\b\d+\b")
MIN_SHARED_WORDS = 2


def _content_words(text: str) -> set:
    from src.kb.retrieve import tokens        # the same stemming and stop words as retrieval
    return set(tokens(text))


def validate_knowledge_reply(text: str, key_facts: list, internal: frozenset = frozenset()) -> list:
    """Rules for a reply that restates a knowledge-base article. The article's key facts are the only source of content.

    Policy words such as refund, within 30 days or contact us are fine when the key facts themselves use them, and not otherwise.
      length               empty or too long
      unsupported_term     a promise, channel or relative-time word that no key fact uses
      unknown_number       a number that no key fact contains
      unknown_order        an order number that no key fact contains (no date or amount is ever supplied)
      amount, unknown_date money or a calendar date (articles contain neither)
      internal_text        a knowledge-base id, an internal-guidance marker or six words copied from internal guidance
      prompt_leak          mentions of prompts, tools or instructions
      unsupported_sentence a sentence that shares fewer than two content words with the key facts (and is not a short courtesy line)
    The last rule is a weak support test: it catches invented content, not a claim that reverses a fact. A person reviews that."""
    facts_text = " ".join(key_facts)
    lowered = facts_text.lower()
    failures = []
    if not text.strip() or len(text) > MAX_CHARS:
        failures.append("length")
    for pattern in (_PROMISE, _CHANNEL, _RELATIVE):
        if any(m.group(0).lower() not in lowered for m in pattern.finditer(text)):
            failures.append("unsupported_term")
            break
    fact_numbers = set(_NUMBER.findall(facts_text))
    if any(n not in fact_numbers for n in _NUMBER.findall(_ORDER_ID.sub(" ", text))):
        failures.append("unknown_number")
    allowed_orders = {m.group(0).upper() for m in _ORDER_ID.finditer(facts_text)}
    if any(m.group(0).upper() not in allowed_orders for m in _ORDER_ID.finditer(text)):
        failures.append("unknown_order")
    if _AMOUNT.search(text):
        failures.append("amount")
    if dates_in(text):
        failures.append("unknown_date")
    own = _shingles(_words(facts_text), SHINGLE_WORDS)
    if _INTERNAL.search(text) or (internal and _shingles(_words(text), SHINGLE_WORDS) & (internal - own)):
        failures.append("internal_text")
    if _LEAK.search(text):
        failures.append("prompt_leak")
    fact_words = _content_words(facts_text)
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        words = _content_words(sentence)
        if len(words) > 2 and len(words & fact_words) < MIN_SHARED_WORDS:
            failures.append("unsupported_sentence")
            break
    return failures