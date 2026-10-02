from datetime import date

import pytest

from custom_components.ha_tgen.models import Camera, Settings
from custom_components.ha_tgen.paths import archive_path, validate_directory
from custom_components.ha_tgen.periods import resolve_period
from custom_components.ha_tgen.snapshots import scan_snapshots, timestamp_from_name


def test_scan_filters_dates_extensions_and_sorts(tmp_path):
    for filename in [
        "trackmix_20260930_000000.jpg",
        "trackmix_20261001_000000.PNG",
        "trackmix_20260901_020000.jpeg",
        "trackmix_20260901_010000.jpg",
        "trackmix_bad.jpg",
        "unrelated.jpg",
        "trackmix_20260915_010000.txt",
    ]:
        (tmp_path / filename).write_bytes(b"image")
    sub = tmp_path / "subfolder"
    sub.mkdir()
    (sub / "trackmix_20260915_010000.jpg").write_bytes(b"image")
    camera = Camera.parse({"name": "Garden", "source_dir": str(tmp_path), "prefix": "trackmix_"})
    scan = scan_snapshots(camera, [str(tmp_path)], resolve_period("monthly", date(2026, 10, 2)))
    assert [p.name for p in scan.images] == [
        "trackmix_20260901_010000.jpg",
        "trackmix_20260901_020000.jpeg",
        "trackmix_20260930_000000.jpg",
    ]
    assert scan.skipped == 2
    assert len(scan.samples) == 3
    assert timestamp_from_name("TRACKMIX_20261108_053000.JPG", camera).hour == 5


def test_custom_filename_format(tmp_path):
    camera = Camera.parse(
        {"name": "Gate", "source_dir": str(tmp_path), "prefix": "gate-", "timestamp_format": "%Y-%m-%d_%H-%M"}
    )
    assert timestamp_from_name("gate-2026-10-02_13-45.png", camera).minute == 45
    assert timestamp_from_name("gate-2026-02-30_13-45.png", camera) is None


def test_symlink_outside_source_is_skipped(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"private")
    try:
        (source / "cam_20261002_120000.jpg").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires a Windows developer mode or privilege")
    camera = Camera.parse({"name": "Cam", "source_dir": str(source), "prefix": "cam_"})
    scan = scan_snapshots(camera, [str(source)])
    assert not scan.images
    assert scan.skipped == 1


def test_path_boundaries(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    sibling = tmp_path / "allowed-other"
    sibling.mkdir()
    assert validate_directory(str(allowed), [str(allowed)]) == allowed
    with pytest.raises(ValueError):
        validate_directory(str(sibling), [str(allowed)])
    with pytest.raises(ValueError):
        validate_directory("relative/path", [str(allowed)])
    for name in ("../secret.mp4", str(tmp_path / "secret.mp4"), "folder/secret.txt"):
        with pytest.raises(ValueError):
            archive_path(str(allowed), name)


@pytest.mark.parametrize(
    "field,value",
    [
        ("fps", 0),
        ("fps", True),
        ("crf", 52),
        ("timeout", 9),
        ("resolution", "8k"),
        ("timestamp_format", "%H%M"),
        ("prefix", "../"),
    ],
)
def test_camera_validation(tmp_path, field, value):
    with pytest.raises(ValueError):
        Camera.parse({"name": "Cam", "source_dir": str(tmp_path), field: value})


def test_default_schedules_and_retention(tmp_path):
    camera = Camera.parse({"name": "Cam", "source_dir": str(tmp_path)})
    assert not any(s.enabled for s in camera.schedules.values())
    assert Settings().retention_days == 0
