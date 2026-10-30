"""
Dates as the lab writes them: day-month-year (30-10-2026), times on the 24-hour clock (30-10-2026 16:40).

Stored dates stay ISO (2026-10-30), which sort and compare as they are; these are only how they are shown,
and how day and month pages are named.
"""

import calendar
from datetime import date, datetime

DATE = '%d-%m-%Y'
STAMP = '%d-%m-%Y %H:%M'


def day_title(when: date) -> str:
    """A day page's title: 30-10-2026 Thursday."""
    return f'{when.strftime(DATE)} {calendar.day_name[when.weekday()]}'


def month_title(when: date) -> str:
    """A month page's title: October 2026."""
    return f'{calendar.month_name[when.month]} {when.year}'


def stamp(moment: datetime) -> str:
    return moment.strftime(STAMP)
