"""CSV parser for doxtr_roadmap.

Loads roadmap items from a CSV file or an inline string, returns a structured
list suitable for :func:`generator.generate_puml`.

CSV columns (canonical names):
    section, name, start, end, row_group, link, tags

Two-pass subtask detection:
    Pass 1 — collect all top-level task names.
    Pass 2 — rows whose ``section`` column matches a known top-level task name
             are attached as subtasks directly after that parent task.

Multi-file combining:
    :func:`load_items_from_files` accepts an ordered iterable of file paths and
    chains all rows from every file into a **single** two-pass run so that
    sections with the same name merge across files and subtasks can reference
    parent tasks defined in a different file.  Per-file CSV parsing (opening
    independent DictReaders) would break cross-file subtask detection and
    produce duplicate section entries for same-named sections.
"""

import csv
import io
import itertools
import datetime
import warnings
from pathlib import Path
from typing import NamedTuple, Optional


# ---------------------------------------------------------------------------
# Column model
# ---------------------------------------------------------------------------

#: Canonical CSV column names understood by the parser.
COLUMNS = ("section", "name", "start", "end", "row_group", "link", "tags")

#: Columns that are strictly required to render a bar and therefore may never
#: be blanked via a per-file ``ignore=`` option.  ``section`` is not required
#: (rows with a blank section simply render without a ``-- ... --`` header).
REQUIRED_COLUMNS = frozenset({"name", "start", "end"})

#: Default set of columns a user may suppress per-file (everything that is not
#: strictly required).  Surfaced as the ``ignorable_columns`` config default.
DEFAULT_IGNORABLE_COLUMNS = tuple(c for c in COLUMNS if c not in REQUIRED_COLUMNS)


# ---------------------------------------------------------------------------
# TaskItem — typed NamedTuple replacing raw positional tuples  [E-1]
# ---------------------------------------------------------------------------

class TaskItem(NamedTuple):
    """A single roadmap task produced by the CSV parser.

    Fields
    ------
    name:
        Display name of the task.
    start:
        Start date string (ISO ``YYYY-MM-DD``).
    end:
        End date string (ISO ``YYYY-MM-DD``).  Equal to *start* for milestones.
    link:
        Raw ``link`` cell value (plain URL or ``:xlink:`id``` expression).
    tags:
        Raw comma-separated tags cell value.
    is_subtask:
        ``True`` when this row is a subtask (its CSV ``section`` column named
        a parent task rather than a section heading).
    row_group:
        Non-empty string when this task shares a Gantt row with others in the
        same group; ``None`` otherwise.
    pid:
        Unique PlantUML identifier string appended by :func:`_assign_task_ids`.
        First occurrence of a display name keeps the name as its pid; later
        duplicates get a ``<name>__<n>`` suffix (starting at 2).
    """

    name: str
    start: str
    end: str
    link: str
    tags: str
    is_subtask: bool
    row_group: Optional[str]
    pid: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_items_from_files(paths, options=None) -> list:
    """Load roadmap items from **multiple** CSV files, combining them as one.

    All files are treated as a single roadmap: sections with the same name
    merge, and subtask/row-group relationships work across file boundaries.
    This is achieved by chaining every file's rows into a single iterable and
    passing it to :func:`_parse_rows` in one call — **not** by parsing each
    file independently and concatenating the results (which would break
    cross-file subtask detection and duplicate same-named sections).

    Files are read in the order given in *paths*.  Within each file rows
    appear in their source order.  Each file must have its own header row
    (parsed by :class:`csv.DictReader`); the recognised columns are the same
    for every file (``section``, ``name``, ``start``, ``end``, ``row_group``,
    ``link``, ``tags``).  Optional columns may be omitted per-file
    independently — :func:`_parse_rows` uses ``row.get(col, "")`` throughout.
    Empty or header-only files contribute zero rows without raising.

    Per-file processing options
    ---------------------------
    *options*, when given, is a parallel iterable aligned with *paths*.  Each
    element is either ``None`` (no options) or a
    :class:`~doxtr_roadmap.file_options.FileOptions` describing per-file
    processing to apply **at parse time**, before rows are chained together:

    - ``ignore_columns`` — every named column is blanked for that file's rows,
      so downstream filtering, the link appendix, and rendering all see the
      suppressed (empty) value.  Blanking ``row_group`` also drops the row
      from same-row grouping; blanking ``tags`` makes ``:tags:`` / ``:query:``
      see an empty tag set for those rows; blanking ``section`` flattens the
      rows (they render without a section header and no longer parent
      subtasks, since section-based subtask detection keys on that column).
    - ``norender`` — the file's rows are parsed (so they remain available for
      period-name resolution) but are **not** emitted into the diagram.

    Parameters
    ----------
    paths:
        Ordered iterable of :class:`pathlib.Path` or path strings.
    options:
        Optional parallel iterable of
        :class:`~doxtr_roadmap.file_options.FileOptions` (or ``None`` entries),
        one per path.  When shorter than *paths* the remaining files get no
        options; when ``None`` no per-file processing is applied.

    Returns
    -------
    list
        Parsed sections list (see :func:`_parse_rows` for structure).
    """
    paths = list(paths)
    opts_list = list(options) if options is not None else []

    all_rows: list = []
    for idx, path in enumerate(paths):
        opts = opts_list[idx] if idx < len(opts_list) else None
        ignore_cols = getattr(opts, "ignore_columns", None) or frozenset()
        # A norender file is parsed for period-lookup / documentation but must
        # not contribute any rendered rows.  We simply skip chaining its rows.
        if getattr(opts, "norender", False):
            with open(path, newline="", encoding="utf-8") as fh:
                # Still read it so a malformed file surfaces its error here,
                # matching the behaviour of a rendered file.
                list(csv.DictReader(fh))
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            # Materialise rows while the file is still open.
            # csv.DictReader is lazy; yielding from it after close() would
            # produce empty / corrupt data.
            for row in reader:
                if ignore_cols:
                    row = _blank_columns(row, ignore_cols)
                all_rows.append(row)
    return _parse_rows(iter(all_rows))


def _blank_columns(row: dict, ignore_cols) -> dict:
    """Return a shallow copy of *row* with each column in *ignore_cols* blanked.

    Blanking (rather than deleting) keeps the key present so the downstream
    ``row.get(col, "")`` calls in :func:`_parse_rows` behave identically to a
    genuinely empty cell.

    Parameters
    ----------
    row:
        A single CSV row dict from :class:`csv.DictReader`.
    ignore_cols:
        Iterable of column names to blank.

    Returns
    -------
    dict
        A new dict; the original *row* is not mutated.
    """
    out = dict(row)
    for col in ignore_cols:
        out[col] = ""
    return out


def load_items_from_file(path) -> list:
    """Load roadmap items from a CSV file on disk.

    Parameters
    ----------
    path:
        :class:`pathlib.Path` or path string pointing to the CSV file.

    Returns
    -------
    list
        Parsed sections list (see :func:`_parse_rows` for structure).
    """
    return load_items_from_files([path])


def load_items_from_string(text: str) -> list:
    """Load roadmap items from an inline CSV string.

    The first non-blank line in *text* must be the header row.

    Parameters
    ----------
    text:
        CSV text with header as first line.

    Returns
    -------
    list
        Parsed sections list (see :func:`_parse_rows` for structure).

    Raises
    ------
    ValueError
        If *text* is empty or contains no header.
    """
    text = text.strip()
    if not text:
        raise ValueError("Inline CSV content is empty; provide a header row.")
    reader = csv.DictReader(io.StringIO(text))
    return _parse_rows(reader)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_rows(rows_iter) -> list:
    """Core two-pass CSV parsing logic.

    Returns a list of ``(section_name, tasks)`` tuples.  Each task is a
    :class:`TaskItem` with fields::

        TaskItem(name, start, end, link, tags, is_subtask, row_group, pid)

    The *pid* field is filled in by :func:`_assign_task_ids` after the two
    passes; the ``row_group`` and ``pid`` fields are set in pass 2 (``pid``
    is initially an empty placeholder and replaced by ``_assign_task_ids``).

    Parameters
    ----------
    rows_iter:
        An iterable of row dicts, each mapping column-name strings to cell
        values.  A :class:`csv.DictReader` is a suitable source, as is any
        iterable of ``dict`` objects (e.g. a pre-materialised list of rows
        from multiple files, as produced by :func:`load_items_from_files`).

    Returns
    -------
    list
        ``[(section, tasks)]`` where each element of *tasks* is a
        :class:`TaskItem`.
    """
    rows = []

    for row in rows_iter:
        group = (row.get("row_group") or "").strip() or None
        tags_cell = (row.get("tags") or "").strip()
        link_cell = (row.get("link") or "").strip()

        rows.append({
            "first":  row.get("section", "").strip(),
            "name":   row.get("name", "").strip(),
            "group":  group,
            "start":  row.get("start", "").strip(),
            "end":    row.get("end", "").strip(),
            "link":   link_cell,
            "tags":   tags_cell,
        })

    if not rows:
        return []

    # Pass 1: collect names of all rows — a row is a top-level task when its
    # ``first`` column does NOT match any row's ``name`` (i.e. names a section,
    # not a parent task).
    task_names = {r["name"] for r in rows}
    top_level_names = {r["name"] for r in rows if r["first"] not in task_names}

    # Pass 2: build sections in row order, inserting subtasks after parents.
    sections = []
    section_index = {}
    task_pos = {}  # parent task name → (section_idx, task_list_index)

    def _ensure_section(name):
        if name not in section_index:
            section_index[name] = len(sections)
            sections.append((name, []))
        return section_index[name]

    for r in rows:
        first, name = r["first"], r["name"]
        # Build a TaskItem with a placeholder pid (""); _assign_task_ids fills it.
        entry = TaskItem(
            name=name,
            start=r["start"],
            end=r["end"],
            link=r["link"],
            tags=r["tags"],
            is_subtask=False,  # may be overridden below
            row_group=r["group"],
            pid="",  # placeholder; filled by _assign_task_ids
        )
        if (
            first in top_level_names
            and first not in section_index
            and first in task_names
            and first != name
        ):
            # 'first' names a parent task → attach as subtask right after it.
            if first not in task_pos:
                warnings.warn(
                    f"doxtr-roadmap: subtask '{name}' references parent '{first}' "
                    f"which has not been seen yet; treating '{first}' as a section.",
                    UserWarning,
                    stacklevel=2,
                )
                idx = _ensure_section(first)
                sections[idx][1].append(entry._replace(is_subtask=False))
                task_pos[name] = (idx, len(sections[idx][1]) - 1)
                continue
            sec_idx, parent_pos = task_pos[first]
            tasks = sections[sec_idx][1]
            # Insert after the parent and any subtasks already attached to it.
            insert_at = parent_pos + 1
            while insert_at < len(tasks) and tasks[insert_at].is_subtask:
                insert_at += 1
            tasks.insert(insert_at, entry._replace(is_subtask=True))
        else:
            idx = _ensure_section(first)
            sections[idx][1].append(entry)
            task_pos[name] = (idx, len(sections[idx][1]) - 1)

    _assign_task_ids(sections)
    return sections


def _assign_task_ids(sections: list) -> None:
    """Assign a unique PlantUML identifier to every task, in place.

    The first task with a given display name keeps that name as its pid.
    Each later duplicate gets a ``<name>__<n>`` suffix (starting at 2).

    Each :class:`TaskItem` is replaced with a new :class:`TaskItem` that has
    the *pid* field filled in::

        TaskItem(name, start, end, link, tags, is_subtask, row_group, pid)

    .. note::
        Rendering two bars with the same display name requires PlantUML
        V1.2024.6 or newer; older versions silently merge same-named tasks.

    Parameters
    ----------
    sections:
        The sections list as assembled by :func:`_parse_rows` (mutated in
        place, each :class:`TaskItem` replaced with a pid-filled copy).
    """
    seen: dict = {}
    for _section, tasks in sections:
        for i, task in enumerate(tasks):
            name = task.name
            count = seen.get(name, 0)
            pid = name if count == 0 else f"{name}__{count + 1}"
            seen[name] = count + 1
            tasks[i] = task._replace(pid=pid)
