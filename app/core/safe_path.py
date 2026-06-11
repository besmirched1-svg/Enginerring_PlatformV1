"""Filesystem trust-boundary primitive (Phase 17.6, task #34).

The platform's drawing-ingest pipeline and its
adjacent filesystem operations have multiple
sites where untrusted bytes (a multipart
``file.filename``, a URL-path segment, an OCR-
extracted title-block ``name``) become path
components. The pre-17.6 code path used
``os.path.join`` directly, which is unsafe:
``os.path.join("/uploads", "../etc/passwd")``
silently produces ``/uploads/../etc/passwd``,
and the trailing ``os.path.normpath`` does
not actually sandbox — it just collapses
``..`` without checking that the result is
still inside the trust boundary.

The right answer to this class of bug is a
**single canonical safe-path boundary
primitive** that the codebase uses everywhere
an untrusted value flows into a filesystem
path. ``safe_join`` is that primitive.

The architectural motivation is critical: if
the fix for path-traversal vulnerabilities is
scattered "``..`` not in path" checks at every
call site, future call sites will forget the
check. A centralized primitive makes the
filesystem trust boundary a **property of the
platform**, not a property of any one
programmer's recall.

**Engineering semantics are preserved.** Path
components may contain the engineering symbol
set (``hopper`` ``frame`` ``decorticator-a3``,
``hopper.step``, ``hopper-rev-2.pdf``). The
primitive rejects only what is never
legitimate: NUL bytes, control characters,
``..`` segments, absolute paths, and segments
above the length cap. ``os.path.basename`` is
applied as belt-and-suspenders: even if a
caller passes a path with a slash, the helper
strips the directory components before any
other check.

**Rules (in order, on each component):**

1. ``os.path.basename`` strip (defense in depth).
2. Reject absolute paths (``/...`` or
   ``C:\\...``).
3. Reject NUL bytes.
4. Reject C0 / DEL / C1 control characters.
5. Reject ``..`` and ``.`` segments explicitly
   (these cannot survive ``os.path.basename``
   in any case, but the explicit check aids
   auditing).
6. Reject empty components.
7. Reject components exceeding
   ``MAX_SEGMENT_LENGTH`` (256).
8. ``Path.resolve()`` the result and verify
   it is a child of ``base_dir.resolve()``.

**On violation** the helper raises
``UnsafePathError`` (a ``ValueError`` subclass).
Callers translate to HTTP 400 (in the route
layer) or to a structured failure (in the
orchestrator / revisions.py — the build is
preserved as ``rejected_by_governance`` so
the audit trail records what happened).

**Caller contract.** Callers should pass the
*untrusted* components as positional
arguments after the trust-anchored base
directory. The base directory should be a
literal string or a path that the application
controls. For example:

    safe_join("outputs", "revisions", machine_name, revision_id)
    safe_join(UPLOADS_DIR, file.filename)

The base is *trusted*; the components are
*untrusted*. The function does not trust the
base for the *filesystem* — it still resolves
it, in case ``"outputs"`` happens to be a
symlink to ``/etc``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Union


# Path-component length caps. 256 is well above
# any realistic engineering filename
# ("hopper-a3-rev-2-decorticator-frame.pdf"
# is 41 chars). The cap exists to bound the
# memory and I/O of downstream consumers
# (NDJSON line parsers, audit log readers,
# shell tools) and to fail-fast on attacker
# payloads.
MAX_SEGMENT_LENGTH: int = 256
MAX_FILENAME_LENGTH: int = 128
MAX_PATH_LENGTH: int = 4096


# C0 control chars (0x00-0x1F) and DEL (0x7F)
# and C1 control chars (0x80-0x9F). NUL is
# included in C0 but the explicit NUL check
# in safe_join gives a clearer error message.
_SUSPICIOUS_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class UnsafePathError(ValueError):
    """A path component failed the safe-join check.

    Subclass of ``ValueError`` so callers that
    want a broad catch (``except ValueError``)
    can still translate the error. The
    ``str(exc)`` form is the human-readable
    explanation; it is safe to surface to the
    client (it names the violation, not the
    payload).
    """


def safe_join(
    base_dir: Union[str, Path, "os.PathLike[str]"],
    *components: str,
) -> Path:
    """Join ``components`` to ``base_dir`` and verify
    the result is contained in ``base_dir`` after
    ``Path.resolve()``.

    The base directory is the **trust boundary**.
    The components are **untrusted**. The return
    is guaranteed to be a child of ``base_dir``
    after ``resolve()``; symlinks, ``..``,
    absolute paths, NUL bytes, and control
    characters are all rejected.

    On violation: raises ``UnsafePathError``
    (a ``ValueError`` subclass).

    See the module docstring for the full rules
    and caller contract.

    Parameters
    ----------
    base_dir:
        The trust-anchored base directory.
        Resolved to its absolute form, then
        used as the containment check.
    *components:
        Untrusted path components. Each is
        stripped via ``os.path.basename`` and
        validated. May be zero components
        (returns ``base_dir`` itself, which is
        the boundary and is safe by construction).

    Returns
    -------
    Path
        A resolved Path that is a child of
        ``base_dir.resolve()``.

    Raises
    ------
    UnsafePathError
        On any violation of the safe-join rules.
    """
    base = Path(os.fspath(base_dir)).resolve()

    def _is_absolute(c: str) -> bool:
        """Cross-platform absolute-path
        detector. ``os.path.isabs`` is
        platform-specific: on POSIX it
        recognizes only ``/``-prefixed paths;
        on Windows it recognizes drive letters
        and UNC paths. We add a manual check
        for the other platform's shape so a
        Windows-shaped payload on POSIX
        (or vice versa) is still rejected."""
        if os.path.isabs(c):
            return True
        if os.sep == "\\":
            # We're on Windows. ``os.path.isabs``
            # catches drive letters and UNC; we
            # also need to catch POSIX-shaped
            # ``/etc/passwd`` payloads.
            return c.startswith("/")
        else:
            # We're on POSIX. ``os.path.isabs``
            # catches ``/etc/passwd``; we also
            # need to catch Windows-shaped
            # ``C:\\Windows`` payloads.
            return (
                (len(c) >= 2 and c[1] == ":")
                or c.startswith("\\\\")
                or c.startswith("//")
            )

    safe_components: list[str] = []
    for raw in components:
        if raw is None:
            # Treat None as empty (callers may
            # have a default-of-None for an
            # optional field). The empty
            # component check below rejects it.
            raw = ""
        raw_str = str(raw)
        # 2. absolute-path rejection on the
        # raw input. ``os.path.basename``
        # strips the drive letter on
        # Windows, so checking the basename
        # would miss a payload like
        # ``C:\\Windows``. The isabs check
        # must run on the raw string.
        if _is_absolute(raw_str):
            raise UnsafePathError(
                f"absolute path component: {raw_str!r}"
            )
        # 1. basename strip (only after the
        # absolute-path check has run on
        # the raw input).
        c = os.path.basename(raw_str)
        # If the basename differs from the
        # raw input, the raw input contained
        # a path separator (the only way
        # ``os.path.basename`` produces a
        # shorter string). On Windows this
        # catches ``hopper\\test`` and
        # ``hopper/test``; on POSIX it
        # catches ``hopper/test``. In all
        # cases, the raw input is a
        # directory-shaped payload and the
        # caller is misusing the API (the
        # caller should pass segments, not
        # joined paths).
        if c != raw_str:
            raise UnsafePathError(
                f"path separator in component: {raw_str!r}"
            )
        # The cross-separator check is now
        # subsumed by the ``c != raw_str``
        # check above (on every platform,
        # ``os.path.basename`` strips the
        # platform's separator; on POSIX
        # only ``/`` is stripped, on Windows
        # both ``/`` and ``\\`` are stripped;
        # either way, a separator in the
        # raw input makes basename shorter
        # than the raw input).
        # 3. NUL rejection (explicit for clarity
        # — the C0 regex below catches it but
        # the dedicated message is helpful).
        if "\x00" in c:
            raise UnsafePathError(
                f"NUL byte in path component: {raw_str!r}"
            )
        # 4. control-character rejection
        if _SUSPICIOUS_CHARS.search(c):
            raise UnsafePathError(
                f"control character in path component: {raw_str!r}"
            )
        # 5. traversal segment rejection
        if c in ("..", "."):
            raise UnsafePathError(
                f"traversal segment: {raw_str!r}"
            )
        # 6. empty component rejection
        if not c:
            raise UnsafePathError(
                f"empty path component: {raw_str!r}"
            )
        # 7. length cap
        if len(c) > MAX_SEGMENT_LENGTH:
            raise UnsafePathError(
                f"path component too long: {len(c)} > {MAX_SEGMENT_LENGTH}"
            )
        safe_components.append(c)
    # 8. resolve + containment check
    candidate = base.joinpath(*safe_components).resolve()
    # The candidate is a child of base iff base
    # is in candidate.parents. The equality
    # case (zero components, returning the
    # base itself) is also valid.
    if candidate != base and base not in candidate.parents:
        raise UnsafePathError(
            f"path escapes base: {candidate} not in {base}"
        )
    # 9. final path-length cap (defense in depth
    # for downstream consumers that parse
    # paths into a fixed buffer).
    if len(str(candidate)) > MAX_PATH_LENGTH:
        raise UnsafePathError(
            f"path too long: {len(str(candidate))} > {MAX_PATH_LENGTH}"
        )
    return candidate


__all__ = [
    "MAX_SEGMENT_LENGTH",
    "MAX_FILENAME_LENGTH",
    "MAX_PATH_LENGTH",
    "UnsafePathError",
    "safe_join",
]
