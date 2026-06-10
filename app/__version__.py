"""Platform version.

Single source of truth for the user-facing version string. The
``/api/health`` endpoint (added with startup checks) reads this
value; the README and RELEASE_NOTES reference it; the Docker
image build arg also derives its tag from it.

The version follows semver:

    MAJOR.MINOR.PATCH[-prerelease]

Prerelease tags used in this project:

    - ``rc1`` — release candidate, behavior frozen, bug-fix only
    - ``rc2`` — second release candidate if rc1 reveals a blocker

Stable release tag scheme: ``v1.0.0``, ``v1.1.0``, etc.
"""

from __future__ import annotations

__version__ = "1.0.0-rc1"

# Mirror as a module-level constant so callers that want to import
# the literal (not the string) can do so without re-typing it.
VERSION = __version__

# Codename frozen at RC1 to mark the "Industrial Foundation" release.
CODENAME = "Industrial Foundation"

# Phase marker. Bumped when the platform enters a new major phase.
PHASE = 16
