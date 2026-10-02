"""Scan flat snapshot directories without following external symbolic links."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .const import MAX_WARNING_SAMPLES
from .models import Camera
from .paths import validate_directory, within
from .periods import Period


@dataclass
class ScanResult:
    images: list[Path] = field(default_factory=list)
    skipped: int = 0
    samples: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def preview(self) -> dict:
        return {
            "count": len(self.images),
            "skipped": self.skipped,
            "samples": self.samples,
            "warnings": self.warnings,
        }


def timestamp_from_name(name: str, camera: Camera) -> datetime | None:
    stem = Path(name).stem
    if not stem.lower().startswith(camera.prefix.lower()):
        return None
    try:
        return datetime.strptime(stem[len(camera.prefix) :], camera.timestamp_format)
    except ValueError:
        return None


def scan_snapshots(camera: Camera, allowed_roots: list[str], period: Period | None = None) -> ScanResult:
    root = validate_directory(camera.source_dir, allowed_roots)
    result = ScanResult()
    selected: list[tuple[datetime, str, Path]] = []
    for entry in root.iterdir():
        if entry.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        try:
            resolved = entry.resolve()
            if not within(resolved, [root]) or not resolved.is_file():
                raise ValueError("File is outside the source directory")
            stamp = timestamp_from_name(entry.name, camera)
            if stamp is None:
                raise ValueError("Filename timestamp does not match")
        except (OSError, ValueError) as err:
            result.skipped += 1
            if len(result.warnings) < MAX_WARNING_SAMPLES:
                result.warnings.append(f"{entry.name}: {err}")
            continue
        if period is None or period.start <= stamp.date() < period.end:
            selected.append((stamp, entry.name, entry))
    selected.sort(key=lambda row: (row[0], row[1]))
    result.images = [row[2] for row in selected]
    result.samples = [{"filename": row[1], "timestamp": row[0].isoformat()} for row in selected[:5]]
    return result
