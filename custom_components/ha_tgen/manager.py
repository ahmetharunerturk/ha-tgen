"""Single-worker queue, persistent archive, configuration and calendar triggers."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .const import MAX_JOB_HISTORY, MAX_PENDING_JOBS, MAX_WARNING_SAMPLES
from .encoder import encode
from .models import Camera, Job, Settings, Video, new_id, valid_id
from .paths import archive_path, validate_directory
from .periods import Period, resolve_period
from .scheduler import due_schedules
from .snapshots import scan_snapshots

_LOGGER = logging.getLogger(__name__)


class TimelapseManager:
    """HA-independent business logic; persistence and I/O are supplied by HA."""

    def __init__(
        self,
        *,
        executor: Callable[..., Awaitable[Any]],
        save: Callable[[dict], Awaitable[None]],
        source_roots: list[str],
        output_roots: list[str],
        binary: str,
        timezone_name: str,
        output_root: str,
        data: dict | None = None,
        encoder: Callable = encode,
    ) -> None:
        self.executor, self.save, self.binary, self.encoder = executor, save, binary, encoder
        self.source_roots, self.output_roots = source_roots, output_roots
        self.timezone_name = timezone_name
        data = data or {}
        self.settings = Settings.parse(data.get("settings", {"output_root": output_root}))
        self.cameras = {row["id"]: Camera.parse(row) for row in data.get("cameras", [])}
        self.jobs = {row["id"]: Job(**row) for row in data.get("jobs", [])}
        self.videos = {row["id"]: Video(**row) for row in data.get("videos", [])}
        self.last_runs = dict(data.get("last_runs", {}))
        self.listeners: set[Callable[[], None]] = set()
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.lock = asyncio.Lock()
        self.save_lock = asyncio.Lock()
        self.worker: asyncio.Task | None = None
        self.active: asyncio.Task | None = None
        self.active_id: str | None = None
        self.closing = False
        self.last_cleanup_day: str | None = None

    def local_now(self) -> datetime:
        return datetime.now(ZoneInfo(self.timezone_name))

    def persisted(self) -> dict:
        return {
            "settings": asdict(self.settings),
            "cameras": [c.to_dict() for c in self.cameras.values()],
            "jobs": [j.to_dict() for j in self.jobs.values()],
            "videos": [v.to_dict() for v in self.videos.values()],
            "last_runs": dict(self.last_runs),
        }

    def state(self, admin: bool = True) -> dict:
        videos = sorted(self.videos.values(), key=lambda v: v.created_at, reverse=True)
        latest: set[tuple[str, str]] = set()
        gallery = []
        for video in videos:
            key = (video.camera_id, video.mode)
            gallery.append(
                {**video.to_dict(), "latest": key not in latest, "duration": video.frames / video.fps}
            )
            latest.add(key)
        return {
            "settings": asdict(self.settings) if admin else {},
            "source_roots": self.source_roots if admin else [],
            "output_roots": self.output_roots if admin else [],
            "cameras": [
                c.to_dict() if admin else {"id": c.id, "name": c.name} for c in self.cameras.values()
            ],
            "jobs": [j.to_dict(False) for j in reversed(list(self.jobs.values()))] if admin else [],
            "videos": gallery,
            "timezone": self.timezone_name,
        }

    def notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:
                _LOGGER.exception("Timelapse state listener failed")

    async def persist(self) -> None:
        async with self.save_lock:
            await self.save(deepcopy(self.persisted()))
        self.notify()

    async def start(self) -> None:
        root = await self.executor(
            validate_directory, self.settings.output_root, self.output_roots, create=True
        )
        self.settings.output_root = str(root)
        # Jobs cannot be resumed safely after their original process disappears.
        for job in self.jobs.values():
            if job.status in ("queued", "running"):
                job.status, job.error = "interrupted", "Home Assistant restarted; retry manually"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                filename = self.job_filename(job)
                path = await self.executor(archive_path, self.settings.output_root, filename)
                await self.executor(path.with_suffix(".part.mp4").unlink, True)
        await self.persist()
        self.worker = asyncio.create_task(self._worker(), name="ha_tgen.worker")

    async def close(self) -> None:
        if self.closing:
            return
        self.closing = True
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        for job in self.jobs.values():
            if job.status in ("queued", "running"):
                job.status = "interrupted"
                job.error = "Integration stopped; retry manually"
                job.finished_at = datetime.now(timezone.utc).isoformat()
        self.listeners.clear()
        await self.persist()

    async def preview(self, data: dict) -> dict:
        camera = Camera.parse(data)
        result = await self.executor(scan_snapshots, camera, self.source_roots)
        return result.preview()

    async def put_camera(self, data: dict) -> dict:
        camera_id = data.get("id")
        camera = Camera.parse(data)
        root = await self.executor(validate_directory, camera.source_dir, self.source_roots)
        camera.source_dir = str(root)
        async with self.lock:
            if camera_id and camera.id not in self.cameras:
                raise ValueError("Camera not found")
            previous = self.cameras.get(camera.id)
            self.cameras[camera.id] = camera
            try:
                await self.persist()
            except Exception:
                if previous:
                    self.cameras[camera.id] = previous
                else:
                    self.cameras.pop(camera.id)
                raise
        return camera.to_dict()

    async def delete_camera(self, camera_id: str) -> None:
        camera_id = valid_id(camera_id)
        async with self.lock:
            if any(
                j.camera_id == camera_id and j.status in ("queued", "running") for j in self.jobs.values()
            ):
                raise ValueError("Cancel pending camera jobs before removing the camera")
            if camera_id not in self.cameras:
                raise ValueError("Camera not found")
            camera = self.cameras.pop(camera_id)
            try:
                await self.persist()
            except Exception:
                self.cameras[camera_id] = camera
                raise

    async def put_settings(self, data: dict) -> None:
        settings = Settings.parse(data)
        root = await self.executor(validate_directory, settings.output_root, self.output_roots, create=True)
        settings.output_root = str(root)
        async with self.lock:
            if settings.output_root != self.settings.output_root and (
                self.videos or any(j.status in ("queued", "running") for j in self.jobs.values())
            ):
                raise ValueError("Output directory cannot change while videos or pending jobs exist")
            previous, self.settings = self.settings, settings
            try:
                await self.persist()
            except Exception:
                self.settings = previous
                raise

    async def generate(
        self,
        camera_ids: list[str],
        mode: str,
        start_date: str | None = None,
        end_date: str | None = None,
        now: datetime | None = None,
        run_marker: tuple[str, str] | None = None,
        period_override: Period | None = None,
    ) -> list[str]:
        if self.closing:
            raise ValueError("Integration is stopping")
        if not camera_ids:
            raise ValueError("Select at least one camera")
        ids = list(dict.fromkeys(valid_id(value) for value in camera_ids))
        period = period_override or resolve_period(
            mode, (now or self.local_now()).date(), start_date, end_date
        )
        async with self.lock:
            if any(key not in self.cameras for key in ids):
                raise ValueError("Camera not found")
            pending = sum(j.status in ("queued", "running") for j in self.jobs.values())
            if pending + len(ids) > MAX_PENDING_JOBS:
                raise ValueError("Job queue is full")
            created = datetime.now(timezone.utc).isoformat()
            jobs = [
                Job(
                    new_id(),
                    key,
                    self.cameras[key].name,
                    mode,
                    period.start.isoformat(),
                    period.inclusive_end.isoformat(),
                    created,
                    self.cameras[key].to_dict(),
                )
                for key in ids
            ]
            for job in jobs:
                self.jobs[job.id] = job
            previous_marker = None
            if run_marker:
                previous_marker = self.last_runs.get(run_marker[0])
                self.last_runs[run_marker[0]] = run_marker[1]
            try:
                await self.persist()
            except Exception:
                for job in jobs:
                    self.jobs.pop(job.id)
                if run_marker:
                    if previous_marker:
                        self.last_runs[run_marker[0]] = previous_marker
                    else:
                        self.last_runs.pop(run_marker[0], None)
                raise
            for job in jobs:
                self.queue.put_nowait(job.id)
            return [j.id for j in jobs]

    async def cancel(self, job_id: str) -> None:
        job_id = valid_id(job_id)
        async with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise ValueError("Job not found")
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = datetime.now(timezone.utc).isoformat()
                await self.persist()
            elif job.status == "running" and self.active and self.active_id == job_id:
                self.active.cancel()

    async def retry(self, job_id: str) -> list[str]:
        job = self.jobs.get(valid_id(job_id))
        if job is None or job.status in ("queued", "running"):
            raise ValueError("Only finished jobs can be retried")
        period = resolve_period("custom", self.local_now().date(), job.start_date, job.end_date)
        return await self.generate([job.camera_id], job.mode, period_override=period)

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                job = self.jobs.get(job_id)
                if job is None or job.status != "queued":
                    continue
                self.active_id = job_id
                self.active = asyncio.create_task(self._run(job), name=f"ha_tgen.encode.{job_id}")
                try:
                    await self.active
                except asyncio.CancelledError:
                    if self.closing:
                        raise
                except Exception:
                    _LOGGER.exception("Failed to persist timelapse job %s", job_id)
                finally:
                    self.active = None
                    self.active_id = None
            finally:
                self.queue.task_done()

    @staticmethod
    def job_filename(job: Job) -> str:
        return f"{job.camera_id}/{job.mode}/{job.start_date}_{job.end_date}_{job.id}.mp4"

    async def _run(self, job: Job) -> None:
        job.status = "running"
        last_notice = 0.0

        def progress(processed: int, frames: int, skipped: int, warnings: list[str]) -> None:
            nonlocal last_notice
            job.processed, job.frames = processed, frames
            job.skipped = scan.skipped + skipped
            job.warnings = (scan.warnings + warnings)[:MAX_WARNING_SAMPLES]
            if time.monotonic() - last_notice >= 0.5 or processed == job.total:
                last_notice = time.monotonic()
                self.notify()

        try:
            await self.persist()
            camera = Camera.parse(job.camera)
            period = resolve_period("custom", self.local_now().date(), job.start_date, job.end_date)
            scan = await self.executor(scan_snapshots, camera, self.source_roots, period)
            job.total, job.skipped, job.warnings = len(scan.images), scan.skipped, scan.warnings
            if job.total < 2:
                raise ValueError("At least two matching images are required")
            filename = self.job_filename(job)
            destination = await self.executor(archive_path, self.settings.output_root, filename)
            fps = camera.yearly_fps if job.mode == "yearly" else camera.fps
            result = await self.encoder(
                scan.images, camera, destination, fps, self.binary, self.executor, progress
            )
            video = Video(
                job.id,
                camera.id,
                camera.name,
                job.mode,
                job.start_date,
                job.end_date,
                datetime.now(timezone.utc).isoformat(),
                filename,
                result.frames,
                fps,
                result.size,
            )
            self.videos[video.id] = video
            job.video_id, job.status = video.id, "succeeded"
        except asyncio.CancelledError:
            job.status = "interrupted" if self.closing else "cancelled"
            raise
        except Exception as err:
            job.status, job.error = "failed", str(err)
            _LOGGER.warning("Timelapse job %s failed: %s", job.id, err)
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            completed = [key for key, value in self.jobs.items() if value.status not in ("queued", "running")]
            for key in completed[:-MAX_JOB_HISTORY]:
                self.jobs.pop(key, None)
            await self.persist()

    async def video_path(self, video_id: str):
        video = self.videos.get(valid_id(video_id))
        if video is None:
            raise ValueError("Video not found")
        return await self.executor(archive_path, self.settings.output_root, video.filename)

    async def delete_video(self, video_id: str) -> None:
        video_id = valid_id(video_id)
        async with self.lock:
            video = self.videos.get(video_id)
            if video is None:
                raise ValueError("Video not found")
            path = await self.video_path(video_id)
            await self.executor(path.unlink, True)
            self.videos.pop(video_id)
            await self.persist()

    async def cleanup(self, now: datetime) -> None:
        if not self.settings.retention_days:
            return
        threshold = now - timedelta(days=self.settings.retention_days)
        for video in list(self.videos.values()):
            if datetime.fromisoformat(video.created_at) < threshold:
                await self.delete_video(video.id)

    async def tick(self, now: datetime | None = None) -> None:
        if self.closing:
            return
        now = (now or self.local_now()).astimezone(ZoneInfo(self.timezone_name))
        for camera in list(self.cameras.values()):
            for mode, key, day in due_schedules(camera, now, self.last_runs):
                try:
                    await self.generate([camera.id], mode, now=now, run_marker=(key, day))
                except (ValueError, OSError):
                    _LOGGER.exception("Scheduled timelapse could not be queued")
        day = now.date().isoformat()
        if self.last_cleanup_day != day:
            try:
                await self.cleanup(now)
                self.last_cleanup_day = day
            except (ValueError, OSError):
                _LOGGER.exception("Timelapse retention cleanup failed")
