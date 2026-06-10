# tests/test_supported_file_types.py
#
# Pin the Phase 17 frozen input set.
#
# Every extension in app/vision/constants.py
# SUPPORTED_FILE_TYPES must be listed here, and the
# test asserts the registry contains exactly these
# extensions and no others. A future developer cannot
# silently add WEBP, HEIC, DXF, DWG, ZIP, or any other
# format without breaking this test.
#
# The spec amendment procedure (PHASE17_SPEC.md §10)
# requires:
#   1. A spec amendment PR.
#   2. A maintainer approval.
#   3. A changelog entry in PHASE17_SPEC.md.
#
# This test enforces the third step's intent: any change
# to the input set must also update this test.
from __future__ import annotations

import pytest

from app.vision.constants import SUPPORTED_FILE_TYPES


# The frozen Phase 17 v1 input set. If you change this
# list, you are amending the spec. Update PHASE17_SPEC.md
# §2.1 and the spec's changelog at the top of that file.
FROZEN_EXTENSIONS = [
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".svg",
    ".bmp",
]


@pytest.mark.parametrize("ext", FROZEN_EXTENSIONS)
def test_supported_extensions(ext: str) -> None:
    """Every frozen extension must be in the registry."""
    assert ext in SUPPORTED_FILE_TYPES, (
        f"Extension '{ext}' is in the frozen Phase 17 input set "
        f"but is missing from app.vision.constants.SUPPORTED_FILE_TYPES. "
        f"If this extension is being added, update PHASE17_SPEC.md §2.1 "
        f"and the spec's changelog."
    )


def test_registry_matches_frozen_set() -> None:
    """The registry must contain exactly the frozen set, no more, no less."""
    assert SUPPORTED_FILE_TYPES == frozenset(FROZEN_EXTENSIONS), (
        f"SUPPORTED_FILE_TYPES = {sorted(SUPPORTED_FILE_TYPES)} "
        f"does not match the frozen set {sorted(FROZEN_EXTENSIONS)}. "
        f"Adding or removing extensions requires a spec amendment "
        f"(PHASE17_SPEC.md §10)."
    )


def test_registry_is_frozenset() -> None:
    """The registry must be immutable so route/OCR references cannot mutate it."""
    assert isinstance(SUPPORTED_FILE_TYPES, frozenset), (
        f"SUPPORTED_FILE_TYPES must be a frozenset to prevent in-place "
        f"mutation by route handlers. Got {type(SUPPORTED_FILE_TYPES).__name__}."
    )


def test_extensions_are_lowercase() -> None:
    """All extensions must be lowercase. The route lowercases incoming
    filenames before lookup, so the registry must match."""
    for ext in SUPPORTED_FILE_TYPES:
        assert ext == ext.lower(), (
            f"Extension '{ext}' is not lowercase. The route lowercases "
            f"the suffix before lookup; the registry must match."
        )
        assert ext.startswith("."), (
            f"Extension '{ext}' does not start with '.'. All entries "
            f"must be in dot-prefixed form (e.g. '.pdf', not 'pdf')."
        )


def test_no_duplicate_extensions() -> None:
    """The frozen set must not contain duplicates. (frozenset
    construction would silently dedupe, masking bugs.)"""
    assert len(FROZEN_EXTENSIONS) == len(set(FROZEN_EXTENSIONS)), (
        f"FROZEN_EXTENSIONS contains duplicates: {FROZEN_EXTENSIONS}"
    )
