"""Redaction of personal identifiers before anything reaches the audit log (NFR-3).

Order ids, ticket ids, customer ids, payment ids and tracking numbers are the keys of the system and are kept. Email addresses, street
addresses, phone numbers, card numbers and customer names are replaced by a marker. Two layers work together:

  * by key: a field known to hold an address, a name or an email is replaced whole, whatever it contains, and a field known to hold an
    identifier is left alone (so a long tracking number is not mistaken for a card number);
  * by pattern: every other string is scanned for the same kinds of identifier.

``leftovers`` is a deliberately broader check used after redaction; anything it still finds means the redaction failed.
"""
import re

EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
CARD_LAST4 = re.compile(r"\b(?:ending(?: in)?|last (?:4|four)(?: digits)?(?: (?:of|on) (?:my|the|your) card)?(?: (?:is|are))?)\s*:?\s*\d{4}\b", re.IGNORECASE)
CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
PHONE = re.compile(r"(?<![\w-])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\w-])|(?<![\w-])\+\d{1,3}(?:[ .-]?\d{2,4}){2,4}(?![\w-])")
STREET_TYPES = "Lane|Street|Avenue|Road|Court|Drive|Way|Boulevard|Blvd|Place|Terrace|Trail|Circle|St|Ave|Rd|Ln|Dr|Ct|Pl"
STREET = re.compile(rf"\b\d{{1,6}}\s+(?:[A-Za-z][\w.'-]*\s+){{0,3}}?(?:{STREET_TYPES})\b\.?(?:,\s*[A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*)?)?(?:\s+\d{{5}}(?:-\d{{4}})?)?")
GREETING = re.compile(r"^(Hello|Hi|Dear)[ \t]+[A-Z][\w'-]+(?:[ \t]+[A-Z][\w'-]+)?,", re.MULTILINE)

ADDRESS_KEYS = frozenset({"requested_address", "address", "new_address", "delivery_address", "shipping_address"})
NAME_KEYS = frozenset({"name", "customer_name", "first_name", "full_name"})
EMAIL_KEYS = frozenset({"email", "customer_email", "sender_email"})
IDENTIFIER_KEYS = frozenset({"ticket_id", "order_id", "customer_id", "payment_id", "refund_id", "return_id", "duplicate_payment_id", "tracking_no",
                             "run_id", "rule_id", "policy_sha256", "sha256", "reply_sha256", "hash", "prev", "kb_id", "article"})

ADDRESS_MARK, NAME_MARK, EMAIL_MARK, PHONE_MARK, CARD_MARK, LAST4_MARK = "[ADDRESS]", "[NAME]", "[EMAIL]", "[PHONE]", "[CARD]", "[CARD-LAST4]"


def redact_text(text: str) -> str:
    """Pattern layer for one string."""
    text = EMAIL.sub(EMAIL_MARK, text)
    text = CARD_LAST4.sub(LAST4_MARK, text)
    text = CARD.sub(CARD_MARK, text)
    text = PHONE.sub(PHONE_MARK, text)
    text = STREET.sub(ADDRESS_MARK, text)
    return GREETING.sub(lambda m: f"{m.group(1)} {NAME_MARK},", text)


def redact(value, key: str = ""):
    """Redact a JSON-like value: dicts and lists are walked, strings are cleaned, other scalars pass through."""
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, key) for v in value]
    if not isinstance(value, str):
        return value
    if key in IDENTIFIER_KEYS:
        return value
    if key in ADDRESS_KEYS:
        return ADDRESS_MARK if value else value
    if key in NAME_KEYS:
        return NAME_MARK if value else value
    if key in EMAIL_KEYS:
        return EMAIL_MARK if value else value
    return redact_text(value)


# ------------------------------------------------------------------ the check after redaction
_LONG_DIGITS = re.compile(r"(?<![\w-])\d{13,}(?![\w-])")


def leftovers(text: str) -> list:
    """Kinds of identifier still visible in already-redacted text (broader than the patterns that redact: an '@', a long digit run, a
    phone-shaped number, a street address, a greeting with a name). An empty list means nothing found."""
    found = []
    if "@" in text:
        found.append("email")
    if _LONG_DIGITS.search(text) or CARD.search(text):
        found.append("card")
    if PHONE.search(text):
        found.append("phone")
    if STREET.search(text):
        found.append("address")
    if GREETING.search(text):
        found.append("name")
    return found