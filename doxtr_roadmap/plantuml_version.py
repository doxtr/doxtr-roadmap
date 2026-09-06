"""Pure helpers for PlantUML version parsing and comparison.

These functions are intentionally free of Sphinx, subprocess, or any I/O
imports so that they can be unit-tested without any external process.

Constants
---------
MIN_PLANTUML_VERSION
    The required minimum as a ``(major, year, release)`` tuple.
MIN_PLANTUML_VERSION_STR
    Human-readable string form of the minimum version.

Functions
---------
parse_plantuml_version(text)
    Extract the version tuple from ``plantuml -version`` output.
is_version_sufficient(found, minimum)
    Return True when *found* meets or exceeds *minimum*.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_PLANTUML_VERSION: tuple[int, int, int] = (1, 2026, 7)
"""Minimum required PlantUML version as ``(major, year, release)`` tuple."""

MIN_PLANTUML_VERSION_STR: str = "1.2026.7"
"""Minimum required PlantUML version as a human-readable string."""

# Matches the canonical version line emitted by ``plantuml -version``:
#   PlantUML version 1.2023.7 (Fri May 12 19:23:42 CEST 2023)
_VERSION_RE = re.compile(r"PlantUML version (\d+)\.(\d+)\.(\d+)")


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def parse_plantuml_version(text: str) -> tuple[int, int, int] | None:
    """Extract the PlantUML version tuple from ``plantuml -version`` output.

    Parameters
    ----------
    text:
        Combined stdout + stderr text from running ``plantuml -version``.

    Returns
    -------
    tuple[int, int, int] | None
        ``(major, year, release)`` on success, ``None`` if the version line
        was not found in *text*.

    Examples
    --------
    >>> parse_plantuml_version("PlantUML version 1.2023.7 (Fri May 12 ...)")
    (1, 2023, 7)
    >>> parse_plantuml_version("unexpected output") is None
    True
    """
    m = _VERSION_RE.search(text)
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def is_version_sufficient(
    found: tuple[int, ...],
    minimum: tuple[int, ...],
) -> bool:
    """Return True when *found* meets or exceeds *minimum* (lexicographic tuple comparison).

    Parameters
    ----------
    found:
        Version tuple, e.g. ``(1, 2023, 7)`` from :func:`parse_plantuml_version`.
    minimum:
        Required minimum version tuple, e.g. ``(1, 2026, 7)``.

    Returns
    -------
    bool
        ``True`` if ``found >= minimum``, ``False`` otherwise.

    Examples
    --------
    >>> is_version_sufficient((1, 2026, 7), (1, 2026, 7))
    True
    >>> is_version_sufficient((1, 2023, 7), (1, 2026, 7))
    False
    """
    return found >= minimum
