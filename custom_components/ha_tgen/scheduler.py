"""Minute-based calendar scheduling with persisted DST duplicate protection."""

from datetime import datetime

from .models import Camera


def due_schedules(
    camera: Camera, local_now: datetime, last_runs: dict[str, str]
) -> list[tuple[str, str, str]]:
    due = []
    for mode, schedule in camera.schedules.items():
        if not schedule.enabled or local_now.strftime("%H:%M") != schedule.time:
            continue
        if mode == "weekly" and local_now.weekday() != 0:
            continue
        if mode == "monthly" and local_now.day != 1:
            continue
        key = f"{camera.id}:{mode}"
        day = local_now.date().isoformat()
        if last_runs.get(key) != day:
            due.append((mode, key, day))
    return due
