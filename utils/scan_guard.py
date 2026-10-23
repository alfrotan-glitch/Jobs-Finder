"""Single-writer cross-process scan guard for dashboard, CLI and scheduled runs.

The Windows Task Scheduler runs an independent Python process. An asyncio
lock inside the web server alone cannot stop simultaneous scans in two
processes. This small OS file lock keeps discovery+matching atomic as a unit.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from utils import tracker


class ScanAlreadyRunning(RuntimeError):
    """A different Jobs-Finder process is already scanning."""


@contextmanager
def exclusive_scan() -> Iterator[None]:
    path = Path(str(tracker.canonical_db_path()) + ".scan.lock")
    with path.open("a+b") as file:
        file.seek(0)
        if file.read(1) != b"1":
            file.seek(0)
            file.write(b"1")
            file.flush()
        file.seek(0)
        locked = False
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as exc:
                raise ScanAlreadyRunning("Another job scan is currently running.") from exc
        else:
            import fcntl

            try:
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except BlockingIOError as exc:
                raise ScanAlreadyRunning("Another job scan is currently running.") from exc
        try:
            yield
        finally:
            if locked:
                file.seek(0)
                if os.name == "nt":
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
