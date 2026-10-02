from datetime import datetime
from zoneinfo import ZoneInfo

from custom_components.ha_tgen.models import Camera, Schedule
from custom_components.ha_tgen.scheduler import due_schedules


def test_week_and_month_schedule_only_on_calendar_boundary(tmp_path):
    camera = Camera.parse({"name": "Camera", "source_dir": str(tmp_path)})
    camera.schedules = {"weekly": Schedule(True, "02:30"), "monthly": Schedule(True, "02:30")}
    berlin = ZoneInfo("Europe/Berlin")
    assert [r[0] for r in due_schedules(camera, datetime(2026, 6, 1, 2, 30, tzinfo=berlin), {})] == [
        "weekly",
        "monthly",
    ]
    assert not due_schedules(camera, datetime(2026, 6, 2, 2, 30, tzinfo=berlin), {})
    assert not due_schedules(camera, datetime(2026, 6, 1, 2, 31, tzinfo=berlin), {})


def test_dst_fold_runs_once_and_missed_run_does_not_catch_up(tmp_path):
    camera = Camera.parse({"name": "Camera", "source_dir": str(tmp_path)})
    camera.schedules = {"yearly": Schedule(True, "02:30")}
    berlin = ZoneInfo("Europe/Berlin")
    first = datetime(2026, 10, 25, 2, 30, tzinfo=berlin, fold=0)
    second = first.replace(fold=1)
    due = due_schedules(camera, first, {})
    assert len(due) == 1
    assert not due_schedules(camera, second, {due[0][1]: due[0][2]})
    assert not due_schedules(camera, first.replace(hour=3), {})
