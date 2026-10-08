from datetime import date

import pytest

from src.agent.deadline import WITHIN_DAYS, is_within_window, resolve_deadline

TUE = date(2026, 10, 6)          # a Tuesday


@pytest.mark.parametrize("phrase,expected", [
    ("Thursday", date(2026, 10, 8)),
    ("Tuesday", date(2026, 10, 13)),                    # same weekday means next week
    ("Monday", date(2026, 10, 12)),
    ("Friday October 9", date(2026, 10, 9)),
    ("before 8 October", date(2026, 10, 8)),
    ("October 15", date(2026, 10, 15)),
    ("15 October", date(2026, 10, 15)),
    ("Oct 15th", date(2026, 10, 15)),
    ("the 15th of October 2026", date(2026, 10, 15)),
    ("2026-10-09", date(2026, 10, 9)),
    ("tomorrow", date(2026, 10, 7)),
    ("today", TUE),
    ("tonight", TUE),
    ("the 15th", date(2026, 10, 15)),
    ("the 3rd", date(2026, 11, 3)),                    # already past this month: next month
    ("September 3", date(2027, 9, 3)),                 # already past this year: next year
    ("January 2 2027", date(2027, 1, 2)),
])
def test_phrases_resolve_to_the_expected_date(phrase, expected):
    assert resolve_deadline(phrase, TUE) == expected


@pytest.mark.parametrize("phrase", ["", "   ", "soon", "as soon as possible", "urgently", "before my trip", "February 30", "9/10", None])
def test_wording_without_a_date_resolves_to_none(phrase):
    assert resolve_deadline(phrase, TUE) is None


def test_december_ordinal_rolls_into_next_year():
    assert resolve_deadline("the 2nd", date(2026, 12, 20)) == date(2027, 1, 2)


def test_window_boundary_is_three_days():
    assert WITHIN_DAYS == 3
    assert is_within_window(date(2026, 10, 9), TUE)            # 3 days: within
    assert not is_within_window(date(2026, 10, 10), TUE)       # 4 days: outside
    assert is_within_window(date(2026, 10, 1), TUE)            # already past: cannot be met
    assert not is_within_window(None, TUE)


def test_resolver_reproduces_every_labelled_deadline(dev_dataset):
    """Every dev ticket with a labelled deadline date: build the wording the generator used and resolve it."""
    import calendar
    from src.agent.tools import Toolbox
    db, _, labels = dev_dataset
    box = Toolbox.from_path(db)
    checked = 0
    for lab in labels:
        wanted = lab["expected_facts"].get("deadline_date")
        if not wanted:
            continue
        ticket = box.get_ticket(lab["ticket_id"]).data
        target = date.fromisoformat(wanted)
        month, day, weekday = calendar.month_name[target.month], target.day, calendar.day_name[target.weekday()]
        text = f"{ticket.subject}\n{ticket.body}".lower()
        phrase = next(p for p in (f"{weekday} {month} {day}", f"{month} {day}", f"{day} {month}", weekday) if p.lower() in text)
        assert resolve_deadline(phrase, date.fromisoformat(ticket.received_at[:10])) == target, lab["ticket_id"]
        checked += 1
    box.conn.close()
    assert checked == 5                                          # 4 within the window (S22) and 1 too far away (S03)