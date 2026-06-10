"""Shared upload validation + staging for drawing-ingest routes.

Phase 17.2a refactor. The validation logic that used to live inline
in ``app/api/routes.py:ingest_drawing`` (extension check, size cap,
streaming counter) is extracted here so the 17.2 ``ingest-and-build``
route can share it without duplicating the bytes-of-validity.

The behavior is byte-for-byte equivalent to the inline version:
- Same file-type check against ``SUPPORTED_FILE_TYPES`` (HTTP 415 on miss).
- Same Content-Length pre-check (HTTP 413 on declared-oversize).
- Same streaming backstop with a 64 KB chunk size and a running byte
  counter that aborts with HTTP 413 if the body exceeds the cap.
- Same ``tempfile.NamedTemporaryFile(suffix=suffix, delete=False)``
  staging — the caller is responsible for ``os.remove`` cleanup in
  a ``finally`` block.
- Same ``await file.close()`` in a ``finally`` so the connection is
  released even on the oversize-abort path.

The helper returns a small :class:`StagedUpload` record rather than
just the tempfile path, so the route can recover the original
``suffix`` without re-deriving it from the path (which would be
fragile if a future refactor ever changes the tempfile naming).
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, UploadFile

from app.vision.constants import (
    MAX_FILE_SIZE_BYTES,
    SUPPORTED_FILE_TYPES,
)


# Streaming chunk size for the backstop counter. Matches the
# pre-17.2a inline value; pinned here as a module constant so
# future tunings are one line away from the rest of the helper.
_STREAM_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class StagedUpload:
    """Result of a successful :func:`validate_and_stage_upload` call.

    Attributes
    ----------
    tmp_path:
        Filesystem path of the tempfile holding the validated body.
        The caller owns cleanup (``os.remove(tmp_path)`` in a
        ``finally`` block).
    suffix:
        The lowercase extension that was validated against
        :data:`app.vision.constants.SUPPORTED_FILE_TYPES` (e.g.
        ``".pdf"``). Returned alongside ``tmp_path`` so the route
        does not have to re-derive it from the path.
    bytes_written:
        Total bytes streamed into the tempfile. Equal to the
        request body size, capped at :data:`MAX_FILE_SIZE_BYTES`
        by definition (the helper rejects anything larger).
    """
    tmp_path: str
    suffix: str
    bytes_written: int


async def validate_and_stage_upload(
    request: Request,
    file: UploadFile,
) -> StagedUpload:
    """Validate an upload and stream it to a tempfile.

    Performs three checks in the same order the pre-17.2a inline
    code did:

    1. **Extension check** against :data:`SUPPORTED_FILE_TYPES`.
       Rejects with ``HTTP 415`` if the suffix is not in the
       frozen Phase 17.1 set.
    2. **Content-Length pre-check.** Cheap reject of declared-
       oversize uploads before any I/O. Rejects with ``HTTP 413``
       if the header is present and exceeds :data:`MAX_FILE_SIZE_BYTES`.
       Missing or unparseable ``Content-Length`` falls through to
       the streaming backstop.
    3. **Streaming backstop.** Reads the body in 64 KB chunks,
       counting bytes as it goes. Aborts with ``HTTP 413`` if the
       running total exceeds :data:`MAX_FILE_SIZE_BYTES`. Closes
       and removes the partial tempfile on the abort path before
       raising.

    On success, returns a :class:`StagedUpload`. The caller is
    responsible for ``os.remove(staged.tmp_path)`` in a ``finally``
    block, and for ``await file.close()`` is **not** required
    here — the helper closes the file in its own ``finally`` so
    the connection is released even on the oversize-abort path.

    Parameters
    ----------
    request:
        The FastAPI request. Used only for the ``Content-Length``
        header.
    file:
        The uploaded file. The body is consumed by this call;
        callers must not re-read it.

    Returns
    -------
    StagedUpload
        ``(tmp_path, suffix, bytes_written)`` for the validated
        upload.

    Raises
    ------
    HTTPException
        415 on unsupported extension, 413 on declared or
        streamed oversize.
    """
    # 1. Extension check. Lowercase the suffix so callers can
    # supply ``Hopper.PDF`` and have it accepted.
    suffix = "." + (file.filename or "upload").rsplit(".", 1)[-1].lower()
    if suffix not in SUPPORTED_FILE_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{suffix}'. "
                f"Allowed: {sorted(SUPPORTED_FILE_TYPES)}"
            ),
        )

    # 2. Content-Length pre-check. Cheap reject before any I/O.
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = None
        if declared_size is not None and declared_size > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB "
                    f"limit ({declared_size} bytes declared)."
                ),
            )

    # 3. Streaming backstop. Reads the body in chunks; aborts
    # with HTTP 413 if the running total exceeds the cap.
    bytes_written = 0
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        try:
            while True:
                chunk = await file.read(_STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > MAX_FILE_SIZE_BYTES:
                    tmp.close()
                    try:
                        os.remove(tmp.name)
                    except OSError:
                        pass
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File exceeds "
                            f"{MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB "
                            f"limit (>{bytes_written} bytes streamed)."
                        ),
                    )
                tmp.write(chunk)
        finally:
            await file.close()
        tmp_path = tmp.name

    return StagedUpload(tmp_path=tmp_path, suffix=suffix,
                        bytes_written=bytes_written)
