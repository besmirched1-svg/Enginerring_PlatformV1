# app/core/revisions.py
#
# Versioned build archive. Every successful build snapshots its artifacts
# into `outputs/revisions/<machine>_<rev>/` so older designs can be diffed,
# promoted, or rolled back. Designed to support the goal's evolution system
# (compare iterations, promote best-performing outputs).
#
# Layout per revision:
#
#     outputs/revisions/htds_p2_alpha_rev0007/
#         revision.json     - manifest (config, scores, timestamps)
#         scad/             - assembly + per-component .scad sources
#         stl/              - rendered STL(s)
#         images/           - rendered PNG(s)
#         bom/              - assembly_bom.csv copy
#
# A `latest` symlink (or, on Windows, a `latest.txt` pointer file) lives in
# `outputs/revisions/` for each machine so external tools can find the most
# recent build without scanning timestamps.

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.core.revisions")

REVISIONS_ROOT = Path("outputs/revisions")

# Filenames are sanitized so machine names with shell-unfriendly chars
# (slashes, spaces, etc.) don't break the path.
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize(name: str) -> str:
    cleaned = _SAFE_NAME.sub("_", name.strip())
    return cleaned or "machine"


def _next_rev_number(machine_name: str) -> int:
    """Find the highest existing rev number for this machine and add one."""
    safe = _sanitize(machine_name)
    if not REVISIONS_ROOT.exists():
        return 0
    pattern = re.compile(rf"^{re.escape(safe)}_rev(\d+)$")
    highest = -1
    for entry in REVISIONS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        m = pattern.match(entry.name)
        if m:
            highest = max(highest, int(m.group(1)))
    return highest + 1


def _write_latest_pointer(machine_name: str, rev_dir: Path) -> None:
    """
    Cross-platform 'latest' marker. On POSIX try a symlink; on Windows (or
    if symlinking is denied) fall back to a plain text pointer.
    """
    safe = _sanitize(machine_name)
    pointer = REVISIONS_ROOT / f"{safe}_latest"
    txt_pointer = REVISIONS_ROOT / f"{safe}_latest.txt"

    if sys.platform.startswith("win"):
        # Windows: stick to a text pointer to avoid privilege requirements.
        try:
            txt_pointer.write_text(rev_dir.name, encoding="utf-8")
        except Exception:
            logger.exception("Failed to write latest.txt pointer for %s", machine_name)
        return

    # POSIX: try symlink first, fall back to txt.
    try:
        if pointer.is_symlink() or pointer.exists():
            pointer.unlink()
        pointer.symlink_to(rev_dir.name, target_is_directory=True)
    except OSError:
        try:
            txt_pointer.write_text(rev_dir.name, encoding="utf-8")
        except Exception:
            logger.exception("Failed to write latest pointer for %s", machine_name)


def _copy_if_exists(src: Path | str, dest_dir: Path) -> str | None:
    """Copy a file into dest_dir, returning the new relative path or None."""
    if not src:
        return None
    src_path = Path(src)
    if not src_path.exists():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src_path.name
    try:
        shutil.copy2(src_path, target)
        return str(target.relative_to(REVISIONS_ROOT.parent))
    except Exception:
        logger.exception("Failed to copy %s -> %s", src_path, target)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def archive_revision(
    machine_name: str,
    config: dict[str, Any],
    components: dict[str, str],
    assembly_scad: str | None,
    assembly_stl: str | None,
    assembly_png: str | None,
    bom_csv: str | None,
    scores: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Snapshot a completed build into outputs/revisions/<machine>_rev<n>/.

    Returns a manifest dict describing the revision (also written to
    revision.json inside the rev dir).

    All paths in the inputs are strings or Path objects — missing artifacts
    are tolerated (e.g. PNG render failed but STL succeeded).
    """
    REVISIONS_ROOT.mkdir(parents=True, exist_ok=True)
    safe = _sanitize(machine_name)
    rev_n = _next_rev_number(machine_name)
    rev_dir = REVISIONS_ROOT / f"{safe}_rev{rev_n:04d}"
    rev_dir.mkdir(parents=True, exist_ok=True)

    scad_dir = rev_dir / "scad"
    stl_dir = rev_dir / "stl"
    img_dir = rev_dir / "images"
    bom_dir = rev_dir / "bom"

    archived_components: dict[str, str | None] = {}
    for name, path in (components or {}).items():
        archived_components[name] = _copy_if_exists(path, scad_dir)

    archived = {
        "machine": machine_name,
        "revision": rev_n,
        "directory": str(rev_dir),
        "created_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "config": config,
        "scores": scores or {},
        "artifacts": {
            "assembly_scad": _copy_if_exists(assembly_scad, scad_dir),
            "assembly_stl":  _copy_if_exists(assembly_stl, stl_dir),
            "assembly_png":  _copy_if_exists(assembly_png, img_dir),
            "bom_csv":       _copy_if_exists(bom_csv, bom_dir),
            "components":    archived_components,
        },
    }

    manifest_path = rev_dir / "revision.json"
    try:
        manifest_path.write_text(
            json.dumps(archived, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed to write revision manifest %s", manifest_path)

    _write_latest_pointer(machine_name, rev_dir)

    logger.info(
        "Archived revision %s (machine=%s, components=%d)",
        rev_dir.name, machine_name, len(archived_components),
    )
    return archived


def list_revisions(machine_name: str) -> list[dict[str, Any]]:
    """Return all revisions for a machine, oldest first. Used by Phase 3 to
    select the best-performing revision for promotion."""
    safe = _sanitize(machine_name)
    pattern = re.compile(rf"^{re.escape(safe)}_rev(\d+)$")
    if not REVISIONS_ROOT.exists():
        return []
    revisions: list[tuple[int, Path]] = []
    for entry in REVISIONS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        m = pattern.match(entry.name)
        if m:
            revisions.append((int(m.group(1)), entry))
    revisions.sort(key=lambda pair: pair[0])

    out: list[dict[str, Any]] = []
    for _, entry in revisions:
        manifest = entry / "revision.json"
        if manifest.exists():
            try:
                out.append(json.loads(manifest.read_text(encoding="utf-8")))
            except Exception:
                logger.exception("Bad manifest %s", manifest)
    return out
