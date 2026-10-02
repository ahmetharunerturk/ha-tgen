from datetime import date

import pytest

from custom_components.ha_tgen.periods import resolve_period


@pytest.mark.parametrize(
    "today,start,end,label",
    [
        ("2026-01-01", "2025-12-22", "2025-12-29", "2025-W52"),
        ("2026-01-05", "2025-12-29", "2026-01-05", "2026-W01"),
        ("2026-10-04", "2026-09-21", "2026-09-28", "2026-W39"),
    ],
)
def test_previous_completed_iso_week(today, start, end, label):
    period = resolve_period("weekly", date.fromisoformat(today))
    assert (period.start.isoformat(), period.end.isoformat(), period.label) == (start, end, label)


def test_month_and_leap_year_boundaries():
    january = resolve_period("monthly", date(2026, 1, 31))
    assert january.start == date(2025, 12, 1)
    assert january.end == date(2026, 1, 1)
    leap = resolve_period("monthly", date(2024, 3, 1))
    assert (leap.end - leap.start).days == 29


def test_year_to_date_includes_today():
    period = resolve_period("yearly", date(2024, 12, 31))
    assert period.start == date(2024, 1, 1)
    assert period.end == date(2025, 1, 1)


def test_custom_single_day_inclusive():
    period = resolve_period("custom", date.today(), "2024-02-29", "2024-02-29")
    assert period.end == date(2024, 3, 1)
    assert period.inclusive_end == period.start


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-02-30", "2026-03-01"),
        ("2026-10-03", "2026-10-02"),
        ("20261002", "2026-10-02"),
        (None, None),
        ("9999-12-31", "9999-12-31"),
    ],
)
def test_custom_invalid_dates(start, end):
    with pytest.raises(ValueError):
        resolve_period("custom", date.today(), start, end)
