"""Project-local trash moves for files that must not be directly deleted."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path


def move_to_trash(path: Path, *, trash_root: Path | None = None) -> Path | None:
    """Move an existing path into a timestamped trash directory.

    The function never permanently deletes the source. Callers may later inspect
    or restore the moved item. Missing paths are treated as an idempotent no-op.
    """
    source = path.expanduser().resolve()
    if not source.exists() and not source.is_symlink():
        return None
    root = trash_root.expanduser().resolve() if trash_root is not None else source.parent / ".trash"
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    destination = root / f"{stamp}-{uuid.uuid4().hex[:8]}-{source.name}"
    shutil.move(str(source), str(destination))
    return destination
