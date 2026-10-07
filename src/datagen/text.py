"""Ticket text helpers: dates, tone wrappers and typo injection.

All randomness comes from the rng passed in, so output is reproducible for a given seed.
"""
import random
import re
from datetime import date

TONES = ("polite", "neutral", "frustrated", "terse")
TONE_WEIGHTS = (0.30, 0.40, 0.20, 0.10)

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_PROTECTED = {w.lower() for w in _MONTHS + _WEEKDAYS}   # never altered by typo injection
_WORD = re.compile(r"\b[A-Za-z]{6,}\b")

_GREETINGS = {
    "polite": ["Hello,", "Hi there,", "Good morning,", "Hello team,"],
    "neutral": ["Hi,", "Hello,", ""],
    "frustrated": ["", "Hello,"],
    "terse": [""],
}
_EXTRAS = {
    "polite": ["I hope you can help.", "Thanks for your help with this."],
    "frustrated": ["This is really frustrating.", "I'm quite disappointed with the service so far.",
                   "I expected better from you."],
}
_CLOSINGS = {
    "polite": ["Thank you so much,", "Many thanks,", "Kind regards,"],
    "neutral": ["Thanks,", "Regards,", "Best,"],
    "frustrated": ["Regards,", "Thanks,"],
    "terse": ["Thanks,"],
}


def fmt_date(d: date, rng: random.Random) -> str:
    """Unambiguous date text such as 'September 11' or '11 September'."""
    month = _MONTHS[d.month - 1]
    return f"{month} {d.day}" if rng.random() < 0.6 else f"{d.day} {month}"


def weekday_name(d: date) -> str:
    return _WEEKDAYS[d.weekday()]


def add_typos(rng: random.Random, text: str, max_typos: int = 2) -> str:
    """Swap two adjacent letters inside up to max_typos words of 6+ letters.

    Month and weekday names are protected. Order ids and numbers are never touched because only
    purely alphabetic words are candidates.
    """
    words = [m for m in _WORD.finditer(text) if m.group().lower() not in _PROTECTED]
    if not words:
        return text
    k = min(len(words), rng.randint(1, max_typos))
    chosen = sorted(rng.sample(words, k), key=lambda m: m.start(), reverse=True)
    for m in chosen:
        w = m.group()
        i = rng.randint(1, len(w) - 3)
        if w[i] == w[i + 1]:
            continue
        text = text[:m.start()] + w[:i] + w[i + 1] + w[i] + w[i + 2:] + text[m.end():]
    return text


def compose(rng: random.Random, core: str, first_name: str, tone: str, typo: bool) -> str:
    """Wrap the core request with a greeting, an optional tone sentence, a closing and a name."""
    if typo:
        core = add_typos(rng, core)
    parts = []
    greeting = rng.choice(_GREETINGS[tone])
    if greeting:
        parts.append(greeting)
    body = core
    if tone in _EXTRAS and rng.random() < 0.7:
        body = f"{core} {rng.choice(_EXTRAS[tone])}"
    parts.append(body)
    parts.append(f"{rng.choice(_CLOSINGS[tone])}\n{first_name}")
    return "\n\n".join(parts)