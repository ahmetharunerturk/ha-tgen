"""Validated, JSON-serializable configuration and job records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .const import DEFAULT_OUTPUT_ROOT, DEFAULT_TIMESTAMP_FORMAT


def new_id() -> str:
    return uuid4().hex


def valid_id(value: str) -> str:
    try:
        return UUID(value).hex
    except (ValueError, AttributeError) as err:
        raise ValueError("Invalid identifier") from err


def integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass
class Schedule:
    enabled: bool = False
    time: str = "00:15"

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Schedule:
        if not isinstance(data, dict) or not isinstance(data.get("enabled", False), bool):
            raise ValueError("Invalid schedule")
        value = data.get("time", "00:15")
        if not isinstance(value, str) or len(value) != 5:
            raise ValueError("Schedule time must use HH:MM")
        try:
            if datetime.strptime(value, "%H:%M").strftime("%H:%M") != value:
                raise ValueError
        except ValueError as err:
            raise ValueError("Schedule time must use HH:MM") from err
        return cls(data.get("enabled", False), value)


@dataclass
class Camera:
    id: str
    name: str
    source_dir: str
    prefix: str = ""
    timestamp_format: str = DEFAULT_TIMESTAMP_FORMAT
    fps: int = 12
    yearly_fps: int = 24
    crf: int = 23
    resolution: str = "source"
    timeout: int = 3600
    schedules: dict[str, Schedule] = field(
        default_factory=lambda: {
            "weekly": Schedule(False, "00:15"),
            "monthly": Schedule(False, "00:30"),
            "yearly": Schedule(False, "01:00"),
        }
    )

    @classmethod
    def parse(cls, data: dict[str, Any], camera_id: str | None = None) -> Camera:
        if not isinstance(data, dict):
            raise ValueError("Invalid camera configuration")
        name = data.get("name", "")
        source = data.get("source_dir", "")
        prefix = data.get("prefix", "")
        fmt = data.get("timestamp_format", DEFAULT_TIMESTAMP_FORMAT)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError("Camera name is required (up to 100 characters)")
        if not isinstance(source, str) or not source or len(source) > 4096:
            raise ValueError("An absolute source directory is required")
        if not isinstance(prefix, str) or len(prefix) > 100 or any(c in prefix for c in "/\\\r\n"):
            raise ValueError("Invalid filename prefix")
        if not isinstance(fmt, str) or len(fmt) > 100 or not all(t in fmt for t in ("%Y", "%m", "%d")):
            raise ValueError("Timestamp format must contain %Y, %m and %d")
        sample = datetime(2026, 9, 15, 12, 34, 56)
        try:
            datetime.strptime(sample.strftime(fmt), fmt)
        except ValueError as err:
            raise ValueError("Invalid timestamp format") from err
        resolution = data.get("resolution", "source")
        if resolution not in ("source", "720p", "1080p", "2160p"):
            raise ValueError("Invalid resolution")
        schedules = data.get("schedules", {})
        if not isinstance(schedules, dict):
            raise ValueError("Invalid schedules")
        defaults = cls(new_id(), name, source).schedules
        return cls(
            id=valid_id(camera_id or data.get("id") or new_id()),
            name=name.strip(),
            source_dir=source,
            prefix=prefix,
            timestamp_format=fmt,
            fps=integer(data.get("fps", 12), "FPS", 1, 60),
            yearly_fps=integer(data.get("yearly_fps", 24), "Yearly FPS", 1, 60),
            crf=integer(data.get("crf", 23), "CRF", 0, 51),
            resolution=resolution,
            timeout=integer(data.get("timeout", 3600), "Timeout", 10, 86400),
            schedules={
                mode: Schedule.parse(schedules.get(mode, asdict(default)))
                for mode, default in defaults.items()
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Settings:
    output_root: str = DEFAULT_OUTPUT_ROOT
    retention_days: int = 0

    @classmethod
    def parse(cls, data: dict[str, Any]) -> Settings:
        root = data.get("output_root", DEFAULT_OUTPUT_ROOT)
        if not isinstance(root, str) or not root:
            raise ValueError("An output directory is required")
        return cls(root, integer(data.get("retention_days", 0), "Retention days", 0, 36500))


@dataclass
class Job:
    id: str
    camera_id: str
    camera_name: str
    mode: str
    start_date: str
    end_date: str
    created_at: str
    camera: dict[str, Any]
    status: str = "queued"
    processed: int = 0
    total: int = 0
    frames: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    finished_at: str | None = None
    video_id: str | None = None

    def to_dict(self, include_config: bool = True) -> dict[str, Any]:
        result = asdict(self)
        if not include_config:
            result.pop("camera")
        return result


@dataclass
class Video:
    id: str
    camera_id: str
    camera_name: str
    mode: str
    start_date: str
    end_date: str
    created_at: str
    filename: str
    frames: int
    fps: int
    size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
