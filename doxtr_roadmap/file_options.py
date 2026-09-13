"""Parser for per-file ``:file:`` option brackets and calendar option strings.

This module implements the small option grammar that lets a user attach
processing directives to an individual ``:file:`` spec (or a
``doxtr_roadmap_period_calendars_options`` entry) so that non-essential
columns can be dropped, or a file can be loaded purely as a reference without
rendering any bars.

Grammar
-------
An option string is the text inside ``[...]`` appended directly to a filename::

    sprints/sprint-01.csv[ignore=section,link;norender]

- Options are separated by ``;``.
- Each option is either:
    * a **bare flag** — a single identifier (e.g. ``norender``); or
    * a **key=value** pair whose value is a comma-separated list
      (e.g. ``ignore=section,link``).
- Whitespace around separators, keys, and values is ignored.
- Keys and flags are matched case-insensitively.

Supported options
------------------
``ignore=<col>[,<col>...]``
    Blank the named column(s) for every row loaded from this spec, at parse
    time.  Downstream filtering (``:tags:`` / ``:query:``), the link appendix,
    and rendering all see the suppressed (empty) value.  Only columns present
    in the configured *ignorable* set are accepted; attempting to ignore a
    strictly-required column (``name`` / ``start`` / ``end``) raises
    :class:`FileOptionError`.

``norender`` (flag)
    Load and parse the file normally (so its rows remain available for
    period-name resolution and are documented in the source CSV), but emit no
    bars from this file into the generated diagram.

The parser is deliberately dependency-free so it can be unit-tested in
isolation and reused by both the directive and the period-calendar loader.
"""

import re
from typing import NamedTuple, Optional, Tuple

__all__ = [
    "FileOptionError",
    "FileOptions",
    "split_spec_and_options",
    "parse_file_options",
]


class FileOptionError(ValueError):
    """Raised when a ``:file:`` option bracket is malformed or references an
    unknown option / non-ignorable column."""


class FileOptions(NamedTuple):
    """Parsed per-file processing options.

    Fields
    ------
    ignore_columns:
        Frozen set of column names to blank at parse time (already validated
        against the ignorable set).  May be empty.
    norender:
        ``True`` when the file's rows must be loaded but not rendered as bars.
    """

    ignore_columns: frozenset
    norender: bool = False


# An empty options object — the common "no bracket present" case.
_EMPTY = FileOptions(ignore_columns=frozenset(), norender=False)

# Recognised bare flags (case-insensitive).
_KNOWN_FLAGS = frozenset({"norender"})

# Recognised key=value option keys (case-insensitive).
_KNOWN_KEYS = frozenset({"ignore"})

# A filename spec optionally followed by a single trailing ``[...]`` bracket.
# The bracket, when present, must be the last thing in the token so that glob
# metacharacters ``[`` used *inside* a path (character classes) are not
# mistaken for an option bracket unless they close at the very end.
_SPEC_BRACKET_RE = re.compile(r"^(?P<file>.*?)\[(?P<opts>[^\[\]]*)\]\s*$", re.DOTALL)


def split_spec_and_options(spec: str) -> Tuple[str, Optional[str]]:
    """Split a raw ``:file:`` spec into ``(filename, options_or_None)``.

    A trailing ``[...]`` bracket is interpreted as an option block and stripped
    from the returned filename.  When no trailing bracket is present the whole
    spec is returned as the filename and *options* is ``None``.

    Only a bracket that closes at the very end of the token is treated as an
    option block; this keeps glob character-classes such as ``file[0-9].csv``
    working (they do not close at end-of-token) while still allowing
    ``file[0-9].csv[ignore=tags]``.

    Parameters
    ----------
    spec:
        A single filename spec token (already split off from the space/comma
        separated ``:file:`` value).

    Returns
    -------
    tuple
        ``(filename, options_str_or_None)``.  *filename* is stripped of
        surrounding whitespace.
    """
    m = _SPEC_BRACKET_RE.match(spec)
    if not m:
        return spec.strip(), None
    return m.group("file").strip(), m.group("opts")


def parse_file_options(options_str, ignorable_columns) -> FileOptions:
    """Parse an option string (the text between ``[`` and ``]``).

    Parameters
    ----------
    options_str:
        The raw text inside the brackets, or ``None`` when no bracket was
        present (returns the empty options object).
    ignorable_columns:
        Iterable of column names that may appear in an ``ignore=`` list.
        Columns outside this set raise :class:`FileOptionError`.

    Returns
    -------
    FileOptions

    Raises
    ------
    FileOptionError
        On an unknown option key/flag, a malformed segment, or an ``ignore=``
        value naming a non-ignorable column.
    """
    if options_str is None:
        return _EMPTY

    allowed_cols = {c.strip() for c in ignorable_columns if c and c.strip()}

    ignore_cols: set = set()
    norender = False

    for raw_seg in options_str.split(";"):
        seg = raw_seg.strip()
        if not seg:
            continue  # tolerate empty segments (e.g. trailing ';')

        if "=" in seg:
            key, _, value = seg.partition("=")
            key = key.strip().lower()
            if key not in _KNOWN_KEYS:
                raise FileOptionError(
                    f"unknown file option key {key!r} "
                    f"(supported: {', '.join(sorted(_KNOWN_KEYS))})"
                )
            if key == "ignore":
                cols = [c.strip() for c in value.split(",") if c.strip()]
                if not cols:
                    raise FileOptionError(
                        "ignore= requires at least one column name"
                    )
                for col in cols:
                    if col not in allowed_cols:
                        raise FileOptionError(
                            f"column {col!r} cannot be ignored "
                            f"(ignorable columns: "
                            f"{', '.join(sorted(allowed_cols)) or '(none)'})"
                        )
                    ignore_cols.add(col)
        else:
            flag = seg.lower()
            if flag not in _KNOWN_FLAGS:
                raise FileOptionError(
                    f"unknown file option flag {flag!r} "
                    f"(supported flags: {', '.join(sorted(_KNOWN_FLAGS))}; "
                    f"key=value options: {', '.join(sorted(_KNOWN_KEYS))})"
                )
            if flag == "norender":
                norender = True

    return FileOptions(ignore_columns=frozenset(ignore_cols), norender=norender)
