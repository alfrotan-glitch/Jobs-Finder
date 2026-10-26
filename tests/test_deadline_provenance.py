"""Never reinterpret a yearless/stale job deadline as a future vacancy."""

from datetime import date

import pytest

from utils.medical_requirements import parse_closing_date


@pytest.mark.parametrize("source", [
    "Closing date: 30 September",
    "Deadline: September 30",
    "Send your CV by 30 September.",
])
def test_date_without_published_year_must_not_roll_forward(source):
    assert parse_closing_date(source, today=date(2026, 10, 26)) is None


def test_explicit_past_date_remains_past():
    assert parse_closing_date("Closing date: 30 September 2026", today=date(2026, 10, 26)) == "2026-09-30"


def test_explicit_future_deadline_keeps_advertised_year():
    assert parse_closing_date("Deadline: 12 November 2026", today=date(2026, 10, 26)) == "2026-11-12"


def test_impossible_calendar_date_is_not_valid():
    assert parse_closing_date("Deadline: 31 February 2026", today=date(2026, 10, 26)) is None
