"""Generate a small synthetic clip for browser tests (never shipped in the integration)."""

import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

root = Path(".preview")
root.mkdir(exist_ok=True)
binary = shutil.which("ffmpeg")
if not binary:
    import imageio_ffmpeg

    binary = imageio_ffmpeg.get_ffmpeg_exe()
process = subprocess.Popen(
    [
        binary,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pixel_format",
        "rgb24",
        "-video_size",
        "640x360",
        "-framerate",
        "12",
        "-i",
        "pipe:0",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(root / "demo.mp4"),
    ],
    stdin=subprocess.PIPE,
)
try:
    for frame in range(36):
        image = Image.new("RGB", (640, 360), (166 + frame, 193 + frame // 2, 180))
        draw = ImageDraw.Draw(image)
        draw.ellipse((400 - frame * 2, 35, 455 - frame * 2, 90), fill=(247, 224, 158))
        draw.polygon(
            [(0, 260), (120, 170), (280, 230), (430, 190), (640, 250), (640, 360), (0, 360)],
            fill=(96, 135, 105),
        )
        draw.polygon(
            [(0, 310), (170, 240), (340, 285), (540, 220), (640, 260), (640, 360), (0, 360)],
            fill=(51, 93, 69),
        )
        draw.text((22, 320), "TIMELAPSE / DEMO", fill=(232, 239, 227))
        process.stdin.write(image.tobytes())
    process.stdin.close()
    if process.wait():
        raise RuntimeError("Demo video encoding failed")
finally:
    if process.poll() is None:
        process.kill()
        process.wait()
