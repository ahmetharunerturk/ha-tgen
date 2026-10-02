import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from custom_components.ha_tgen.encoder import EncodeResult
from custom_components.ha_tgen.manager import TimelapseManager
from custom_components.ha_tgen.models import Job, Video, new_id


@pytest.fixture
async def manager(tmp_path, executor, ffmpeg):
    saved = []

    async def save(data):
        saved.append(deepcopy(data))

    output = tmp_path / "output"
    output.mkdir()
    source = tmp_path / "source"
    source.mkdir()
    for index in range(3):
        Image.new("RGB", (32, 24), (index * 80, 100, 20)).save(source / f"cam_20261002_12000{index}.jpg")
    instance = TimelapseManager(
        executor=executor,
        save=save,
        source_roots=[str(source)],
        output_roots=[str(output)],
        output_root=str(output),
        binary=ffmpeg,
        timezone_name="Europe/Berlin",
    )
    await instance.start()
    await instance.put_camera({"name": "Camera", "source_dir": str(source), "prefix": "cam_"})
    instance.test_saved = saved
    yield instance
    await asyncio.wait_for(instance.close(), 5)


async def test_queue_is_serial_and_results_persist(manager):
    active = 0
    maximum = 0

    async def instrumented(images, camera, destination, fps, binary, executor, progress):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        await asyncio.sleep(0.05)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"generated video")
        active -= 1
        return EncodeResult(frames=3, size=15)

    manager.encoder = instrumented
    camera = next(iter(manager.cameras.values()))
    ids = []
    for _ in range(3):
        ids += await manager.generate([camera.id], "custom", "2026-10-02", "2026-10-02")
    await asyncio.wait_for(manager.queue.join(), 5)
    assert maximum == 1
    assert all(manager.jobs[key].status == "succeeded" for key in ids)
    assert len(manager.videos) == 3
    assert sum(video["latest"] for video in manager.state()["videos"]) == 1
    assert len(manager.test_saved[-1]["videos"]) == 3
    assert "source_dir" not in str(manager.state(admin=False))
    assert not manager.state(admin=False)["jobs"]


async def test_cancel_running_and_queued_does_not_stop_worker(manager):
    started = asyncio.Event()
    blocked = asyncio.Event()

    async def waiting(*args):
        started.set()
        await blocked.wait()
        return EncodeResult(frames=3, size=15)

    manager.encoder = waiting
    camera = next(iter(manager.cameras.values()))
    first = (await manager.generate([camera.id], "custom", "2026-10-02", "2026-10-02"))[0]
    await started.wait()
    second = (await manager.generate([camera.id], "custom", "2026-10-02", "2026-10-02"))[0]
    await manager.cancel(second)
    await manager.cancel(first)
    await asyncio.wait_for(manager.queue.join(), 5)
    assert manager.jobs[first].status == "cancelled"
    assert manager.jobs[second].status == "cancelled"
    assert not manager.worker.done()


async def test_running_job_is_interrupted_on_unload(manager):
    started = asyncio.Event()

    async def waiting(*args):
        started.set()
        await asyncio.Event().wait()

    manager.encoder = waiting
    camera = next(iter(manager.cameras.values()))
    key = (await manager.generate([camera.id], "custom", "2026-10-02", "2026-10-02"))[0]
    await started.wait()
    await asyncio.wait_for(manager.close(), 5)
    assert manager.jobs[key].status == "interrupted"


async def test_restart_marks_pending_jobs_and_removes_partial(tmp_path, executor, ffmpeg):
    camera_id = new_id()
    job = Job(
        new_id(),
        camera_id,
        "Old camera",
        "weekly",
        "2026-09-21",
        "2026-09-27",
        datetime.now(timezone.utc).isoformat(),
        {},
    )
    job.status = "running"
    output = tmp_path / "output"
    filename = TimelapseManager.job_filename(job)
    partial = output / filename
    partial.parent.mkdir(parents=True)
    partial = partial.with_suffix(".part.mp4")
    partial.write_bytes(b"unfinished")

    async def save(_):
        pass

    instance = TimelapseManager(
        executor=executor,
        save=save,
        source_roots=[],
        output_roots=[str(output)],
        output_root=str(output),
        binary=ffmpeg,
        timezone_name="Europe/Berlin",
        data={"jobs": [job.to_dict()]},
    )
    await instance.start()
    assert instance.jobs[job.id].status == "interrupted"
    assert not partial.exists()
    assert instance.queue.empty()
    await instance.close()


async def test_schedule_marker_is_persisted_and_dst_fold_not_repeated(manager):
    from zoneinfo import ZoneInfo

    camera = next(iter(manager.cameras.values()))
    camera.schedules["yearly"].enabled = True
    camera.schedules["yearly"].time = "02:30"
    first = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Berlin"), fold=0)
    await manager.tick(first)
    await manager.tick(first.replace(fold=1))
    await manager.queue.join()
    assert len(manager.jobs) == 1
    assert manager.test_saved[-1]["last_runs"][f"{camera.id}:yearly"] == "2026-10-25"


async def test_retention_only_deletes_indexed_generated_files(manager, tmp_path):
    root = tmp_path / "output"
    old = Video(
        new_id(),
        new_id(),
        "Deleted camera",
        "monthly",
        "2026-08-01",
        "2026-08-31",
        (datetime.now(timezone.utc) - timedelta(days=50)).isoformat(),
        "old.mp4",
        3,
        12,
        5,
    )
    manager.videos[old.id] = old
    (root / "old.mp4").write_bytes(b"old")
    (root / "not-owned.mp4").write_bytes(b"leave this alone")
    manager.settings.retention_days = 30
    await manager.cleanup(datetime.now(timezone.utc))
    assert old.id not in manager.videos
    assert not (root / "old.mp4").exists()
    assert (root / "not-owned.mp4").exists()
    assert len(list((tmp_path / "source").iterdir())) == 3


async def test_save_failure_rolls_back_camera_and_queued_jobs(manager):
    async def unavailable(_):
        raise OSError("Storage unavailable")

    camera = next(iter(manager.cameras.values()))
    previous_save = manager.save
    manager.save = unavailable
    with pytest.raises(OSError):
        await manager.put_camera({**camera.to_dict(), "name": "Changed"})
    assert manager.cameras[camera.id].name == "Camera"
    with pytest.raises(OSError):
        await manager.generate([camera.id], "custom", "2026-10-02", "2026-10-02")
    assert not manager.jobs and manager.queue.empty()
    manager.save = previous_save


async def test_output_root_locked_when_archive_exists(manager):
    camera = next(iter(manager.cameras.values()))
    await manager.generate([camera.id], "custom", "2026-10-02", "2026-10-02")
    await manager.queue.join()
    assert len(manager.videos) == 1
    with pytest.raises(ValueError, match="cannot change"):
        await manager.put_settings(
            {"output_root": manager.settings.output_root + "/new", "retention_days": 0}
        )


async def test_unknown_camera_does_not_enqueue_partial_batch(manager):
    camera = next(iter(manager.cameras.values()))
    with pytest.raises(ValueError):
        await manager.generate([camera.id, new_id()], "weekly")
    assert not manager.jobs
