"""Cross-platform exclusive lock on an open file (POSIX flock / Windows msvcrt)."""
import os
from typing import IO

if os.name == "nt":
    import msvcrt

    def try_lock(handle: IO) -> None:
        handle.seek(0)
        # Lock one byte; raises OSError when another process holds it.
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def unlock(handle: IO) -> None:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def try_lock(handle: IO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(handle: IO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
