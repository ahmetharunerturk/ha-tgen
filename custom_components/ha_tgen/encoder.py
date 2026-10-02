"""Bounded-memory RGB streaming to an asynchronous FFmpeg child process."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from .const import MAX_WARNING_SAMPLES
from .models import Camera
from .paths import within

Executor = Callable[..., Awaitable[Any]]
Progress = Callable[[int, int, int, list[str]], None]


@dataclass
class EncodeResult:
    frames: int = 0
    skipped: int = 0
    size: int = 0
    warnings: list[str] = field(default_factory=list)


class EncodingError(Exception):
    """A recoverable encoding failure."""


def prepare_frame(
    path: Path, source_root: str, size: tuple[int, int] | None, resolution: str
) -> tuple[bytes, tuple[int, int]]:
    # Recheck each file when opening it: the scan is not a permanent permission grant.
    if not within(path.resolve(), [Path(source_root)]):
        raise ValueError("Image is outside the source directory")
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        if size is None:
            sizes = {"720p": (1280, 720), "1080p": (1920, 1080), "2160p": (3840, 2160)}
            size = sizes.get(resolution, (max(2, image.width // 2 * 2), max(2, image.height // 2 * 2)))
        image = ImageOps.pad(image, size, method=Image.Resampling.LANCZOS, color="black")
        return image.tobytes(), size


async def check_ffmpeg(binary: str) -> None:
    """Check the actual binary and required encoder, including on official images."""
    process = await asyncio.create_subprocess_exec(
        binary,
        "-hide_banner",
        "-encoders",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(10):
            stdout, stderr = await process.communicate()
        if process.returncode or b"libx264" not in stdout:
            raise EncodingError(f"FFmpeg with libx264 is required: {stderr.decode(errors='replace')[:200]}")
    finally:
        await stop_process(process)


async def stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), 3)
    except TimeoutError:
        process.kill()
        await process.wait()


async def encode(
    images: list[Path],
    camera: Camera,
    destination: Path,
    fps: int,
    binary: str,
    executor: Executor,
    progress: Progress,
) -> EncodeResult:
    """Write an atomic archive output. Preserve every accepted frame exactly once."""
    process = None
    log_task = None
    temp = destination.with_suffix(".part.mp4")
    result = EncodeResult()
    stderr_tail = bytearray()
    size = None

    async def consume_stderr() -> None:
        assert process is not None and process.stderr is not None
        while chunk := await process.stderr.read(4096):
            stderr_tail.extend(chunk)
            del stderr_tail[:-16384]

    try:
        async with asyncio.timeout(camera.timeout):
            await executor(destination.parent.mkdir, 0o755, True, True)
            # Parent components may have changed since the job was queued.
            if await executor(destination.resolve) != destination:
                raise EncodingError("Output path contains a symbolic link")
            for index, image in enumerate(images):
                try:
                    frame, size = await executor(
                        prepare_frame, image, camera.source_dir, size, camera.resolution
                    )
                except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as err:
                    result.skipped += 1
                    if len(result.warnings) < MAX_WARNING_SAMPLES:
                        result.warnings.append(f"{image.name}: {err}")
                    progress(index + 1, result.frames, result.skipped, result.warnings)
                    continue
                if process is None:
                    process = await asyncio.create_subprocess_exec(
                        binary,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-y",
                        "-f",
                        "rawvideo",
                        "-pixel_format",
                        "rgb24",
                        "-video_size",
                        f"{size[0]}x{size[1]}",
                        "-framerate",
                        str(fps),
                        "-i",
                        "pipe:0",
                        "-an",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-crf",
                        str(camera.crf),
                        "-threads",
                        "2",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(temp),
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    log_task = asyncio.create_task(consume_stderr())
                assert process.stdin is not None
                process.stdin.write(frame)
                await process.stdin.drain()
                result.frames += 1
                progress(index + 1, result.frames, result.skipped, result.warnings)
            if process is None or result.frames < 2:
                raise EncodingError("At least two valid images are required")
            assert process.stdin is not None
            process.stdin.close()
            await process.wait()
            if log_task:
                await log_task
            if process.returncode:
                raise EncodingError(f"FFmpeg failed: {stderr_tail.decode(errors='replace')[-2000:]}")
            result.size = await executor(lambda: temp.stat().st_size)
            if result.size == 0:
                raise EncodingError("FFmpeg produced an empty video")
            await executor(temp.replace, destination)
            return result
    except TimeoutError as err:
        raise EncodingError(f"Encoding exceeded {camera.timeout} seconds") from err
    except (BrokenPipeError, ConnectionResetError) as err:
        if process:
            await stop_process(process)
        if log_task:
            await log_task
        raise EncodingError(
            f"FFmpeg closed its input: {stderr_tail.decode(errors='replace')[-2000:]}"
        ) from err
    finally:
        if process:
            await stop_process(process)
        if log_task:
            await log_task
        await executor(temp.unlink, True)
