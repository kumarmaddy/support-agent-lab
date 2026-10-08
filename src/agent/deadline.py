"""Turn the date words a customer used into a calendar date (pipeline step 4 input).

The model only quotes the wording ("Thursday", "October 9", "before 8 October"); this module resolves it in code, relative to
the day the ticket arrived. Doing the arithmetic in code keeps it exact and testable, and the model never decides a date.

Supported wording: ISO dates, "Month D" and "D Month" (optionally with an ordinal, a year, or a weekday in front), a weekday
name (the next such day after the ticket date), "today", "tonight", "tomorrow", and a bare ordinal such as "the 15th".
Wording that does not name a date ("soon", "as soon as possible") resolves to None: a hard deadline needs a date.
Known limitation: numeric day/month forms such as 9/10 are ambiguous and are not interpreted.
"""
import re
from datetime import date, timedelta
from typing import Optional

WITHIN_DAYS = 3        # a stated date this close to the ticket date cannot be guaranteed (data design, section 7)

_MONTHS = {}
for _i, _name in enumerate(("january", "february", "march", "april", "may", "june", "july", "august", "september",
                            "october", "november", "december"), 1):
    _MONTHS[_name] = _i
    _MONTHS[_name[:3]] = _i
_MONTHS["sept"] = 9
_WEEKDAYS = {name: i for i, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"))}

_MONTH = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MONTH_DAY = re.compile(rf"\b{_MONTH}\s+{_ORD}\b(?:,?\s+(\d{{4}}))?", re.IGNORECASE)
_DAY_MONTH = re.compile(rf"\b{_ORD}\s+(?:of\s+)?{_MONTH}(?:,?\s+(\d{{4}}))?\b", re.IGNORECASE)
_BARE_ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)
_WEEKDAY = re.compile(r"\b(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)


def _build(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_day(month: int, day: int, year: Optional[int], today: date) -> Optional[date]:
    if year is not None:
        return _build(year, month, day)
    found = _build(today.year, month, day)
    if found is not None and found < today:
        found = _build(today.year + 1, month, day)
    return found


def resolve_deadline(phrase: str, today: date) -> Optional[date]:
    """The date a deadline phrase refers to, or None if it names no date."""
    text = (phrase or "").strip()
    if not text:
        return None
    if m := _ISO.search(text):
        return _build(int(m[1]), int(m[2]), int(m[3]))
    if m := _MONTH_DAY.search(text):
        return _month_day(_MONTHS[m[1].lower()], int(m[2]), int(m[3]) if m[3] else None, today)
    if m := _DAY_MONTH.search(text):
        return _month_day(_MONTHS[m[2].lower()], int(m[1]), int(m[3]) if m[3] else None, today)
    lowered = text.lower()
    if re.search(r"\b(today|tonight)\b", lowered):
        return today
    if re.search(r"\btomorrow\b", lowered):
        return today + timedelta(days=1)
    if m := _WEEKDAY.search(text):
        ahead = (_WEEKDAYS[m[1].lower()] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    if m := _BARE_ORDINAL.search(text):
        day = int(m[1])
        for offset in (0, 1):
            month = (today.month - 1 + offset) % 12 + 1
            year = today.year + (today.month - 1 + offset) // 12
            found = _build(year, month, day)
            if found is not None and found >= today:
                return found
    return None


def is_within_window(deadline: Optional[date], today: date, days: int = WITHIN_DAYS) -> bool:
    """True when a dated deadline is at most ``days`` days after ``today`` (or already past)."""
    return deadline is not None and (deadline - today).days <= days