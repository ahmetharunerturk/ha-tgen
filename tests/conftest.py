import asyncio
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def ffmpeg():
    if binary := shutil.which("ffmpeg"):
        return binary
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pytest.skip("FFmpeg is required; install ffmpeg or imageio-ffmpeg")


@pytest.fixture
def executor():
    return asyncio.to_thread
