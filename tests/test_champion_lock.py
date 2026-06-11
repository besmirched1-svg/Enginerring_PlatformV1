"""Tests for the cross-platform file lock (Phase 17.6).

The load-bearing property: two threads contending for the
same lock serialize — the second acquire blocks until the
first releases, and a read-modify-write cycle inside the
lock is not torn. This is the same shape as the
``TestConcurrentCommit`` tests in
``test_ingestion_storage.py``, applied to the file-system
boundary.

Tests run in the platform's process via threading (the
platform has no multiprocessing-based test harness). The
serialization behavior on a single process is the same as
across processes on POSIX (``flock`` is per-process on
the file, not per-fd) and on Windows (``msvcrt.locking``
is per-fd on the byte range, but the kernel still
serializes across processes on the same byte range).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app.core.champion_lock import (
    _HAS_FCNTL,
    _HAS_MSVCRT,
    _lock_path,
    file_lock,
)


@pytest.fixture
def champion_file(tmp_path: Path) -> Path:
    """A fresh champion-pointer file in a temp dir."""
    path = tmp_path / "champion_pointer.json"
    path.write_text("{}", encoding="utf-8")
    return path


class TestFileLockBasic:
    """The single-thread acquire/release cycle."""

    def test_lock_creates_sidecar_file(self, champion_file: Path) -> None:
        """The lock file is the protected file's sibling with
        a ``.lock`` suffix. Created on first acquire."""
        lock_path = Path(_lock_path(str(champion_file)))
        assert not lock_path.exists()
        with file_lock(str(champion_file)):
            assert lock_path.exists()
        # The lock file is left on disk after release.
        # The kernel has released its lock; the file
        # itself is just a stub.
        assert lock_path.exists()

    def test_lock_releases_on_normal_exit(
        self, champion_file: Path,
    ) -> None:
        """A successful acquire-release cycle leaves the
        lock available for the next acquirer."""
        with file_lock(str(champion_file)):
            pass
        # The second acquire should not block. We cannot
        # easily assert "no blocking" in pytest, but if
        # the prior lock were held, this would deadlock
        # the test process. Successful return is the
        # assertion.
        with file_lock(str(champion_file)):
            pass

    def test_lock_releases_on_exception(
        self, champion_file: Path,
    ) -> None:
        """An exception inside the ``with`` block still
        releases the lock. This is the load-bearing
        invariant: an orchestrator that raises mid-block
        does not deadlock the next promotion."""
        with pytest.raises(RuntimeError, match="boom"):
            with file_lock(str(champion_file)):
                raise RuntimeError("boom")
        # The lock must be released. If it were not, the
        # second acquire would deadlock the test.
        with file_lock(str(champion_file)):
            pass


class TestConcurrentSerialization:
    """Two threads contending for the same lock."""

    def test_lock_serializes_concurrent_writes(
        self, champion_file: Path,
    ) -> None:
        """Two threads race to write the champion pointer.
        The lock serializes them: the file's final content
        is exactly one of the two attempted writes, not a
        torn read-modify-write.

        This is the canonical TOCTOU regression detector
        for the platform's promotion path. Without the
        lock, the second thread's read can return the
        first thread's partial write, and the second
        thread's subsequent write overwrites the first
        with stale data. With the lock, the second thread
        sees the first thread's complete state and
        produces a consistent overlay.
        """
        path_str = str(champion_file)
        lock_str = _lock_path(path_str)

        # Distinct values per thread, so a torn write
        # is detectable: the file's final content either
        # is thread A's value, thread B's value, or a
        # mix (e.g., "A" appearing under "B" key) which
        # is the bug we are guarding against.
        payloads = {
            "thread_a": {"thread_a": "alpha"},
            "thread_b": {"thread_b": "beta"},
        }
        observed_order: list[str] = []
        order_lock = threading.Lock()

        barrier = threading.Barrier(2)

        def writer(name: str) -> None:
            barrier.wait()
            with file_lock(path_str):
                # Read, modify, write. A read-modify-write
                # under the lock is the canonical pattern
                # ``set_new_champion`` uses.
                with open(path_str, "r", encoding="utf-8") as f:
                    content = f.read()
                registry = json.loads(content) if content else {}
                # Slow the write down so the second
                # thread is highly likely to attempt
                # acquisition while we still hold the
                # lock. 50ms is more than enough to
                # exercise the contention on a slow CI
                # runner.
                time.sleep(0.05)
                registry.update(payloads[name])
                with order_lock:
                    observed_order.append(name)
                with open(path_str, "w", encoding="utf-8") as f:
                    json.dump(registry, f)

        ta = threading.Thread(target=writer, args=("thread_a",))
        tb = threading.Thread(target=writer, args=("thread_b",))
        ta.start()
        tb.start()
        ta.join()
        tb.join()

        # Final state: the file is consistent. The
        # observed_order list tells us which thread went
        # first; the on-disk state must reflect exactly
        # the result of (first writer, second writer)
        # applied in that order. Both keys must be
        # present (neither writer's work was lost) and
        # the file must be valid JSON.
        with open(path_str, "r", encoding="utf-8") as f:
            final = json.load(f)
        # The final registry is the union of the two
        # payloads (each thread wrote its own key, the
        # lock prevented the second thread from
        # clobbering the first's write).
        expected = {**payloads[observed_order[0]], **payloads[observed_order[1]]}
        assert final == expected, (
            f"Expected union of both writers, got {final}. "
            f"observed_order={observed_order}. A torn write "
            f"would have one writer's key missing or replaced."
        )
        # Both keys are present in the final registry.
        # A torn write would have one of them missing or
        # duplicated under a wrong key.
        assert "alpha" in str(final)
        assert "beta" in str(final)

        # The lock file exists.
        assert Path(lock_str).exists()


class TestFallback:
    """The no-op fallback path. The pre-17.6 code
    silently fell back when ``fcntl`` was unavailable;
    17.6 retains the fallback but routes it through
    ``file_lock`` so the rest of the platform has one
    entry point.

    These tests monkeypatch the module's
    ``_HAS_FCNTL``/``_HAS_MSVCRT`` flags to simulate
    a platform that has neither primitive. The fallback
    is exercised, and writes succeed (they are not
    serialized, but they do not error).
    """

    def test_no_op_fallback_writes_succeed(
        self, champion_file: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With both primitives unavailable, the lock is
        a no-op. Two sequential acquires both succeed."""
        monkeypatch.setattr("app.core.champion_lock._HAS_FCNTL", False)
        monkeypatch.setattr("app.core.champion_lock._HAS_MSVCRT", False)
        # Reset the one-shot warning flag so the test
        # can observe the warning if it cares to.
        monkeypatch.setattr(
            "app.core.champion_lock._FALLBACK_WARNED", False,
        )
        with file_lock(str(champion_file)):
            champion_file.write_text('{"a": 1}', encoding="utf-8")
        with file_lock(str(champion_file)):
            champion_file.write_text('{"a": 2}', encoding="utf-8")
        # Both writes happened. The final state is the
        # second one's.
        assert json.loads(champion_file.read_text(encoding="utf-8")) == {"a": 2}


class TestPlatformDetection:
    """Sanity checks on the platform-detection flags.

    These are not strict assertions (the test is
    environment-dependent) but they document what the
    platform expects to find on a developer machine and
    on CI."""

    def test_at_least_one_lock_primitive_available(self) -> None:
        # On any real Python interpreter (POSIX or
        # Windows), at least one of fcntl or msvcrt
        # should be importable. The fallback is for
        # exotic embedded interpreters only.
        assert _HAS_FCNTL or _HAS_MSVCRT, (
            "Neither fcntl nor msvcrt is available. "
            "Champion-pointer writes will not serialize. "
            "This is the pre-17.6 fallback; check the "
            "environment."
        )
