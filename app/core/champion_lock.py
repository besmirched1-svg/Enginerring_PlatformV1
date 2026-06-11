"""Cross-platform advisory file lock (Phase 17.6).

The platform's promotion block performs four writes that
must be atomic as a group: the champion pointer, the
revision manifest's ``promotion_status``, the lineage log,
and the global audit log. Two concurrent promotions to the
same machine must serialize. The pre-17.6 implementation
used ``fcntl.flock`` on the champion pointer only, and only
on POSIX — on Windows the import is gated behind
``try/except ImportError`` and the lock is silently
skipped. This module replaces that with a cross-platform
advisory lock that works on both POSIX and Windows without
a new dependency.

**Mechanism:**

- On POSIX, the lock uses ``fcntl.flock(LOCK_EX)`` on a
  sidecar ``<path>.lock`` file. The lock is exclusive
  and blocking: a second acquirer waits for the first to
  release. ``LOCK_UN`` is called on context exit (normal
  or exceptional).
- On Windows, ``fcntl`` is unavailable, so the lock uses
  ``msvcrt.locking`` on the first byte of a sidecar lock
  file. ``msvcrt.locking`` takes a file descriptor
  obtained from ``os.open(...)`` — Python's built-in
  ``open()`` returns a buffered handle, not the C-runtime
  file descriptor that ``msvcrt.locking`` expects.

  ``msvcrt.locking`` locks a byte range; a single byte at
  offset 0 is sufficient. The lock is released by
  re-locking the same byte with ``LK_UNLCK`` on context
  exit. The lock file is opened in ``O_BINARY`` on Windows
  to avoid newline translation; on POSIX the binary flag
  is permitted but a no-op.

**Advisory, not mandatory.** The lock is honored only by
code that goes through this module. A process that opens
``champion_pointer.json`` directly without acquiring the
lock can still race; that's the standard caveat with
advisory locks, and the platform's contract is "all writes
go through ``set_new_champion``."

**Lock file lifecycle.** The lock file is created lazily
on first acquire and never deleted. On POSIX that's
slightly noisy (``*.lock`` files alongside every
promoted file) but harmless. On Windows the file is also
unlinked never; the kernel releases its lock when the
process exits, and the file is left as a stub.

**Thread safety.** The lock is reentrant in the sense
that a single process can acquire it from multiple
threads and they will serialize (POSIX ``flock`` and
Windows ``msvcrt.locking`` both block on contention).
The lock is NOT reentrant in the sense that a thread
that already holds the lock and tries to acquire it
again will deadlock; the platform's usage pattern
(serial acquire-release) does not exhibit this case.

**Graceful fallback.** If neither ``fcntl`` nor
``msvcrt`` is importable (no real platform today, but
some embedded interpreters lack both), the lock degrades
to a no-op context manager. A one-time warning is logged
so the fallback is visible. This is the same fallback
the pre-17.6 code had, hoisted into a single place.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from typing import Iterator, Optional

logger = logging.getLogger("engine.champion_lock")

# Detect the available locking primitive at import time.
# Exactly one of these will be non-None on any real
# platform: fcntl on POSIX, msvcrt on Windows.
try:
    import fcntl  # type: ignore[import-not-found]
    _HAS_FCNTL = True
except ImportError:
    fcntl = None  # type: ignore[assignment]
    _HAS_FCNTL = False

try:
    import msvcrt  # type: ignore[import-not-found]
    _HAS_MSVCRT = True
except ImportError:
    msvcrt = None  # type: ignore[assignment]
    _HAS_MSVCRT = False

# One-time warning when neither primitive is available.
# A second call to the warning is suppressed so a hot
# loop that acquires the lock many times in a single
# run does not spam the log.
_FALLBACK_WARNED = False

# Windows msvcrt locking modes. The ``LK_NBLCK`` constant
# is named "NB" (non-blocking) in the msvcrt header, but
# in CPython's binding it is the BLOCKING lock call —
# the function blocks until the lock is granted. The
# ``LK_UNLCK`` constant is the unlock mode.
_LK_UNLCK = 0
_LK_NBLCK = 2


def _lock_path(path: str) -> str:
    """The lock file's path: a sidecar ``<path>.lock``.

    Sibling to the protected file, not nested inside it.
    The lock file and the protected file live in the
    same directory so a relative path is preserved.
    """
    return path + ".lock"


@contextlib.contextmanager
def file_lock(path: str) -> Iterator[None]:
    """Acquire an exclusive advisory lock on ``path``.

    Blocking: if another process or thread holds the
    lock, this call waits. The lock is released on
    context exit (normal or exceptional).

    Args:
        path: The protected file's path. The lock file
            is ``<path>.lock`` in the same directory.

    Yields:
        None. The lock is held for the duration of the
        ``with`` block.

    Example:
        with file_lock("outputs/revisions/champion_pointer.json"):
            # read-modify-write the champion pointer safely
            ...
    """
    lock_path = _lock_path(path)
    # Ensure the parent directory exists so the open
    # call below does not fail on a fresh checkout.
    parent = os.path.dirname(lock_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    if _HAS_FCNTL:
        yield from _acquire_posix(lock_path)
    elif _HAS_MSVCRT:
        yield from _acquire_windows(lock_path)
    else:
        # No-op fallback. The pre-17.6 code did the
        # same, hoisted into one place.
        global _FALLBACK_WARNED
        if not _FALLBACK_WARNED:
            logger.warning(
                "file_lock: no fcntl or msvcrt available on %s; "
                "falling back to a no-op lock. Champion-pointer "
                "writes are NOT serialized on this platform.",
                sys.platform,
            )
            _FALLBACK_WARNED = True
        yield


def _acquire_posix(lock_path: str) -> Iterator[None]:
    """POSIX ``fcntl.flock``-backed lock.

    Plain generator (no ``@contextmanager`` decorator):
    the dispatcher ``file_lock`` calls ``yield from`` on
    us, which means we must yield directly. The lock
    file is opened with ``os.open`` (not Python's
    built-in ``open``) so we have the raw file
    descriptor that ``fcntl.flock`` expects. The fd is
    closed on context exit; the file itself is left on
    disk.

    ``fcntl.flock`` is intrinsically thread-safe on POSIX
    when used on a shared file: a second ``flock`` call
    from the same process on the same file descriptor
    returns immediately, but two threads using *separate*
    fds to the same file will block. We always open a
    fresh fd per acquire, which is the standard pattern
    for cross-thread serialization.
    """
    # O_CREAT ensures the lock file exists; O_RDWR so
    # flock can take an exclusive lock. The mode is
    # ignored when the file already exists.
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        # Blocking exclusive lock. ``fcntl.flock`` raises
        # ``OSError`` on failure (e.g., the file was
        # unlinked between open and lock). The caller
        # sees that as a normal lock failure.
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            logger.exception(
                "file_lock: failed to release POSIX flock on %s",
                lock_path,
            )
        os.close(fd)


def _acquire_windows(lock_path: str) -> Iterator[None]:
    """Windows ``msvcrt.locking``-backed lock.

    Plain generator (no ``@contextmanager`` decorator):
    the dispatcher ``file_lock`` calls ``yield from`` on
    us.

    Opens the lock file with ``os.open`` in binary mode
    (``O_BINARY`` is 0o0 on POSIX, 0x8000 on Windows; the
    bit is harmless on POSIX and required on Windows to
    disable newline translation). The fd is the
    C-runtime file descriptor that ``msvcrt.locking``
    expects.

    Locks a single byte at offset 0. ``msvcrt.locking``
    is **not** blocking on Windows: a second acquire
    on a contested byte raises ``PermissionError`` (errno
    13) immediately rather than waiting for the holder
    to release. This is different from POSIX ``flock``,
    which blocks. To match POSIX's blocking semantics
    on Windows, the acquire is wrapped in a retry loop
    with a small sleep between attempts. The loop polls
    until the lock is granted or the process is killed.

    On context exit, the same byte is unlocked with
    ``LK_UNLCK``.

    Note: ``msvcrt.locking`` is mandatory, not advisory.
    Unlike POSIX ``flock``, an ``open()`` on the file
    does not bypass the lock — the kernel will block the
    second opener if it tries to lock the same range. A
    process that reads the file without locking does not
    see corruption (Windows file locking is mandatory for
    writers only), so the platform's contract still
    applies: "all writes go through ``set_new_champion``."
    """
    # ``O_BINARY`` disables newline translation on Windows.
    # On POSIX the flag is a no-op. The flag value differs
    # by platform, so we read it from ``os`` directly.
    o_binary = getattr(os, "O_BINARY", 0)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | o_binary, 0o644)
    try:
        # Seek to the start so the locked range is well-
        # defined. ``msvcrt.locking`` locks from the
        # current file position for ``nbytes`` bytes; we
        # want byte 0.
        os.lseek(fd, 0, os.SEEK_SET)
        # Poll the lock. ``msvcrt.locking`` raises
        # ``PermissionError`` on contention rather than
        # blocking; we sleep and retry. 10 ms is short
        # enough to feel blocking for callers and long
        # enough to avoid pegging the CPU. ``time.sleep``
        # is used (not ``threading.Event.wait``) because
        # we want a process-level wait, not a thread-
        # level signal.
        import time
        while True:
            try:
                msvcrt.locking(fd, _LK_NBLCK, 1)
                break
            except PermissionError:
                time.sleep(0.01)
        yield
    finally:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, _LK_UNLCK, 1)
        except Exception:
            logger.exception(
                "file_lock: failed to release msvcrt lock on %s",
                lock_path,
            )
        os.close(fd)


__all__ = ["file_lock"]
