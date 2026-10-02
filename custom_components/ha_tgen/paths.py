"""File boundaries. Every function here must run outside the event loop."""

from pathlib import Path
from tempfile import TemporaryFile


def within(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def validate_directory(value: str, allowed_roots: list[str], *, create: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Directory must be absolute")
    path = path.resolve()
    roots = [Path(root).resolve() for root in allowed_roots]
    if not within(path, roots):
        raise ValueError("Directory is outside the permitted roots")
    if create:
        path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise ValueError("Directory does not exist or is not a directory")
    if create:
        # Check real write access without leaving a probe file in the user's archive.
        with TemporaryFile(dir=path):
            pass
    return path


def archive_path(output_root: str, filename: str) -> Path:
    root = Path(output_root).resolve()
    relative = Path(filename)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid archive filename")
    path = (root / relative).resolve()
    if not within(path, [root]) or path == root or path.suffix != ".mp4":
        raise ValueError("Invalid archive path")
    return path
