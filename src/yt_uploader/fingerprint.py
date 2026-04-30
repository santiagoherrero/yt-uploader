import hashlib
from pathlib import Path

HEAD_BYTES = 10 * 1024 * 1024


def compute(path: Path) -> str:
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as f:
        remaining = min(HEAD_BYTES, size)
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return f"{h.hexdigest()}:{size}"
