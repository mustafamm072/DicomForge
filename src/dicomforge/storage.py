"""Atomic local writes, shared by file I/O and resumable releases."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Union


def atomic_write(
    path: Union[str, Path], writer: Callable[[Path], None], *, overwrite: bool = True,
) -> None:
    """Stage beside the destination, fsync, then publish without partial outputs."""
    destination = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=".dicomforge-", dir=destination.parent)
    staging = Path(name)
    os.close(descriptor)
    try:
        writer(staging)
        with staging.open("rb") as stream:
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(staging, destination)
        else:
            # link is an atomic no-clobber publication on the same filesystem.
            os.link(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def write_bytes(path: Union[str, Path], data: bytes, *, overwrite: bool = True) -> None:
    def save(staging: Path) -> None:
        staging.write_bytes(data)
    atomic_write(path, save, overwrite=overwrite)
