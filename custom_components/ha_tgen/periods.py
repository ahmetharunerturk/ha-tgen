"""Calendar periods. Internally all end dates are exclusive."""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str

    @property
    def inclusive_end(self) -> date:
        return self.end - timedelta(days=1)


def resolve_period(
    mode: str, today: date, start_text: str | None = None, end_text: str | None = None
) -> Period:
    if mode == "weekly":
        end = today - timedelta(days=today.weekday())
        start = end - timedelta(days=7)
        iso = start.isocalendar()
        return Period(start, end, f"{iso.year}-W{iso.week:02d}")
    if mode == "monthly":
        end = today.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
        return Period(start, end, start.strftime("%Y-%m"))
    if mode == "yearly":
        return Period(today.replace(month=1, day=1), today + timedelta(days=1), str(today.year))
    if mode != "custom":
        raise ValueError("Unknown mode")
    try:
        start = date.fromisoformat(start_text or "")
        inclusive_end = date.fromisoformat(end_text or "")
        if start.isoformat() != start_text or inclusive_end.isoformat() != end_text:
            raise ValueError
        if inclusive_end < start:
            raise ValueError
        end = inclusive_end + timedelta(days=1)
    except (ValueError, OverflowError) as err:
        raise ValueError("Use YYYY-MM-DD dates with end date on or after start date") from err
    return Period(start, end, f"{start.isoformat()}_{inclusive_end.isoformat()}")
