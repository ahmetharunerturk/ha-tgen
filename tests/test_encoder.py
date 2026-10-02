import asyncio

import pytest
from PIL import Image

from custom_components.ha_tgen.encoder import EncodingError, check_ffmpeg, encode, prepare_frame
from custom_components.ha_tgen.models import Camera


def images(tmp_path):
    files = []
    for index, (color, size, extension) in enumerate(
        [("red", (65, 49), "jpg"), ("green", (32, 64), "png"), ("blue", (80, 20), "jpeg")]
    ):
        path = tmp_path / f"cam_20261002_12000{index}.{extension}"
        Image.new("RGB", size, color).save(path)
        files.append(path)
    return files


@pytest.mark.parametrize("fps", [1, 12, 24, 60])
async def test_real_ffmpeg_frame_order_count_and_duration(tmp_path, ffmpeg, executor, fps):
    files = images(tmp_path)
    camera = Camera.parse({"name": "Camera", "source_dir": str(tmp_path), "prefix": "cam_"})
    destination = tmp_path / "output" / "test.mp4"
    await check_ffmpeg(ffmpeg)
    result = await encode(files, camera, destination, fps, ffmpeg, executor, lambda *_: None)
    assert result.frames == 3
    assert result.size == destination.stat().st_size
    assert not destination.with_suffix(".part.mp4").exists()
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-i",
        str(destination),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-vsync",
        "0",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode(errors="replace")
    frame_size = 64 * 48 * 3
    assert len(stdout) == 3 * frame_size
    center = (24 * 64 + 32) * 3
    for index, channel in enumerate((0, 1, 2)):
        rgb = stdout[index * frame_size + center : index * frame_size + center + 3]
        assert rgb[channel] > max(rgb[c] for c in (0, 1, 2) if c != channel) + 60
    # Probe the container's time base rather than rounded human-readable Duration.
    import json
    import shutil

    if probe := shutil.which("ffprobe"):
        proc = await asyncio.create_subprocess_exec(
            probe,
            "-v",
            "error",
            "-show_streams",
            "-of",
            "json",
            str(destination),
            stdout=asyncio.subprocess.PIPE,
        )
        data, _ = await proc.communicate()
        stream = json.loads(data)["streams"][0]
        assert int(stream["nb_frames"]) == 3
        assert float(stream["duration"]) == pytest.approx(3 / fps, abs=0.001)


async def test_corrupt_frames_are_skipped_and_minimum_enforced(tmp_path, ffmpeg, executor):
    files = images(tmp_path)
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"invalid image")
    camera = Camera.parse({"name": "Camera", "source_dir": str(tmp_path)})
    output = tmp_path / "out.mp4"
    result = await encode([files[0], bad, files[1]], camera, output, 12, ffmpeg, executor, lambda *_: None)
    assert result.frames == 2 and result.skipped == 1
    before = output.read_bytes()
    with pytest.raises(EncodingError):
        await encode([bad, files[0]], camera, output, 12, ffmpeg, executor, lambda *_: None)
    assert output.read_bytes() == before
    assert not output.with_suffix(".part.mp4").exists()


async def test_cancellation_and_timeout_remove_partial_output(tmp_path, ffmpeg, executor):
    files = images(tmp_path)
    camera = Camera.parse({"name": "Camera", "source_dir": str(tmp_path)})
    output = tmp_path / "out.mp4"
    started = asyncio.Event()
    blocked = asyncio.Event()

    async def slow_executor(func, *args):
        if func is prepare_frame and started.is_set():
            await blocked.wait()
        value = await executor(func, *args)
        if func is prepare_frame:
            started.set()
        return value

    task = asyncio.create_task(encode(files, camera, output, 12, ffmpeg, slow_executor, lambda *_: None))
    await started.wait()
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not output.exists()
    assert not output.with_suffix(".part.mp4").exists()
    camera.timeout = 0.1
    with pytest.raises(EncodingError, match="exceeded"):
        await encode(files, camera, output, 12, ffmpeg, slow_executor, lambda *_: None)
    assert not output.with_suffix(".part.mp4").exists()


async def test_disk_write_failure_preserves_existing_video(tmp_path, ffmpeg, executor):
    files = images(tmp_path)
    camera = Camera.parse({"name": "Camera", "source_dir": str(tmp_path)})
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous successful video")

    async def full_disk(func, *args):
        if getattr(func, "__name__", "") == "mkdir":
            raise OSError("No space left on device")
        return await executor(func, *args)

    with pytest.raises(OSError):
        await encode(files, camera, output, 12, ffmpeg, full_disk, lambda *_: None)
    assert output.read_bytes() == b"previous successful video"
