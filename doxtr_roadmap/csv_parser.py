"""CSV parser for doxtr_roadmap.

Loads roadmap items from a CSV file or an inline string, returns a structured
list suitable for :func:`generator.generate_puml`.

CSV columns (canonical names):
    section, name, start, end, row_group, link, tags, color

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
COLUMNS = (
    "section", "name", "start", "end", "row_group", "link", "tags", "color",
)

#: Sentinel value in the ``color`` column that resets the effective colour back
#: to the roadmap default (i.e. stops inheritance and falls back to
#: ``bar.done_color``).  Compared case-insensitively.
COLOR_DEFAULT_SENTINEL = "default"

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
    color:
        The *effective* colour expression for this task after inheritance has
        been resolved by :func:`_resolve_colors`.  This is a raw, unresolved
        expression (a semantic ``dd:`` expression or a ``#hex`` string) — the
        mapping from expression to a static hex value happens later, in the
        directive, where the theme-core palette / dark-mode context is
        available.  ``None`` means "use the roadmap default colour" (either the
        section had no colour at all, or a ``default`` sentinel reset it).
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
    color: Optional[str] = None


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

        TaskItem(name, start, end, link, tags, is_subtask, row_group, pid, color)

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
        color_cell = (row.get("color") or "").strip()

        rows.append({
            "first":  row.get("section", "").strip(),
            "name":   row.get("name", "").strip(),
            "group":  group,
            "start":  row.get("start", "").strip(),
            "end":    row.get("end", "").strip(),
            "link":   link_cell,
            "tags":   tags_cell,
            "color":  color_cell,
        })

    if not rows:
        return []

    # Pass 1: collect names of all rows.  A row's ``first`` (section) column
    # names a *parent task* when it matches some row's ``name``; otherwise it
    # names a section heading.  Subtasks may themselves parent deeper subtasks
    # (sub-sub-…tasks), so parent detection keys on the full set of task
    # names, not only the top-level ones.
    task_names = {r["name"] for r in rows}

    # Pass 2: build sections in row order, inserting subtasks after parents.
    sections = []
    section_index = {}
    task_pos = {}   # task name → (section_idx, task_list_index)
    # task name → parent task name (None for top-level tasks).  Used by
    # _resolve_colors to walk the inheritance chain for recursive nesting.
    task_parent = {}
    # (section_idx, task_list_index) → depth (0 = top-level, 1 = subtask, …).
    # Stored keyed by identity of the task's position so _resolve_colors can
    # reconstruct nesting for arbitrary depth.
    task_depth = {}

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
            color=r["color"] or None,  # raw cell; resolved by _resolve_colors
        )
        # ``first`` names a parent task (rather than a section) when it matches
        # some row's name, is not itself already a section header, and is not
        # this same row.  This holds for arbitrarily deep nesting: a subtask
        # can name another subtask as its parent.
        is_child = (
            first in task_names
            and first not in section_index
            and first != name
            and first in task_pos
        )
        parent_unresolved = (
            first in task_names
            and first not in section_index
            and first != name
            and first not in task_pos
        )
        if is_child:
            sec_idx, parent_pos = task_pos[first]
            tasks = sections[sec_idx][1]
            parent_depth = task_depth[(sec_idx, parent_pos)]
            # Insert after the parent and its entire existing descendant
            # subtree (any following tasks whose depth is greater than the
            # parent's), so sibling subtasks stay grouped under their parent.
            insert_at = parent_pos + 1
            while insert_at < len(tasks) and (
                task_depth.get((sec_idx, insert_at), 0) > parent_depth
            ):
                insert_at += 1
            # Shift the recorded positions of every task at/after the insertion
            # point in this section by one, keeping task_pos / task_depth
            # consistent after the list grows.
            _shift_positions(task_pos, task_depth, sec_idx, insert_at)
            tasks.insert(insert_at, entry._replace(is_subtask=True))
            task_pos[name] = (sec_idx, insert_at)
            task_depth[(sec_idx, insert_at)] = parent_depth + 1
            task_parent[name] = first
        else:
            if parent_unresolved:
                warnings.warn(
                    f"doxtr-roadmap: subtask '{name}' references parent '{first}' "
                    f"which has not been seen yet; treating '{first}' as a section.",
                    UserWarning,
                    stacklevel=2,
                )
            idx = _ensure_section(first)
            tasks = sections[idx][1]
            tasks.append(entry)
            pos = len(tasks) - 1
            task_pos[name] = (idx, pos)
            task_depth[(idx, pos)] = 0
            task_parent[name] = None

    _assign_task_ids(sections)
    _resolve_colors(sections, task_parent)
    return sections


def _shift_positions(task_pos: dict, task_depth: dict, sec_idx: int, insert_at: int) -> None:
    """Shift recorded task positions to account for an insertion.

    When a subtask is inserted at ``insert_at`` in section ``sec_idx``, every
    previously-recorded task whose index in that section is ``>= insert_at``
    moves one slot to the right.  This helper rewrites both ``task_pos`` (name
    → position) and ``task_depth`` (position → depth) so they stay consistent
    with the mutated list.  Iterating over snapshots avoids mutating the dicts
    while reading them.

    Parameters
    ----------
    task_pos:
        Mapping of task name → ``(section_idx, list_index)``.
    task_depth:
        Mapping of ``(section_idx, list_index)`` → nesting depth.
    sec_idx:
        Section whose list is being inserted into.
    insert_at:
        Index at which a new task is about to be inserted.
    """
    for tname, (s_idx, pos) in list(task_pos.items()):
        if s_idx == sec_idx and pos >= insert_at:
            task_pos[tname] = (s_idx, pos + 1)
    shifted = {}
    for (s_idx, pos), depth in list(task_depth.items()):
        if s_idx == sec_idx and pos >= insert_at:
            shifted[(s_idx, pos + 1)] = depth
        else:
            shifted[(s_idx, pos)] = depth
    task_depth.clear()
    task_depth.update(shifted)


def _assign_task_ids(sections: list) -> None:
    """Assign a unique PlantUML identifier to every task, in place.

    The first task with a given display name keeps that name as its pid.
    Each later duplicate gets a ``<name>__<n>`` suffix (starting at 2).

    Each :class:`TaskItem` is replaced with a new :class:`TaskItem` that has
    the *pid* field filled in::

        TaskItem(name, start, end, link, tags, is_subtask, row_group, pid, color)

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


def _resolve_colors(sections: list, task_parent: dict) -> None:
    """Resolve the effective colour of every task, in place, via inheritance.

    Inheritance rules (see the module docstring / the ``color`` column):

    * **Section colour** — a section's colour is the colour of the *first* row
      belonging to that section that carries a non-blank ``color`` cell, in
      row order.  (The section header itself has no dedicated row; its colour
      is established by whichever of its rows first names one.)
    * **Top-level tasks** — a top-level task with a blank ``color`` cell
      inherits its section's colour.  A non-blank cell overrides it.
    * **Subtasks (recursive)** — a subtask with a blank ``color`` cell inherits
      the *effective* colour of its parent task (which may itself have
      inherited from a grand-parent or the section).  This trickles down the
      whole parent chain to sub-sub-…tasks.  A non-blank cell on any task
      overrides inheritance from that task downwards.
    * **Default sentinel** — a ``color`` cell equal to :data:`COLOR_DEFAULT_SENTINEL`
      (case-insensitive, e.g. ``default``) explicitly resets the effective
      colour to ``None`` (the roadmap default fill), stopping inheritance at
      that task; its descendants then inherit ``None`` unless they set their
      own colour.

    A resolved effective colour of ``None`` means "use the roadmap default"
    (``bar.done_color``).  Non-``None`` values are the raw, still-unresolved
    colour expressions (``dd:...`` or ``#hex``) — the expression→hex mapping is
    performed later in the directive, where the palette / dark-mode context is
    available.

    Parameters
    ----------
    sections:
        The sections list as assembled by :func:`_parse_rows` (mutated in
        place; each :class:`TaskItem` is replaced with a colour-resolved copy).
    task_parent:
        Mapping of task name → parent task name (``None`` for top-level tasks),
        built during pass 2.  Used to walk the inheritance chain so a subtask
        inherits its *parent's already-resolved* effective colour regardless of
        nesting depth.
    """
    for _section, tasks in sections:
        # Section colour = first non-blank, non-sentinel colour cell in order.
        section_color = None
        for task in tasks:
            raw = (task.color or "").strip()
            if not raw:
                continue
            if raw.lower() == COLOR_DEFAULT_SENTINEL:
                # An explicit default reset does not itself "colour" the
                # section — it only resets that task; keep looking for a real
                # colour to establish the section colour.
                continue
            section_color = raw
            break

        # Resolve each task's effective colour.  Subtasks are always inserted
        # after their parent (and the parent's descendants), so a single
        # forward pass guarantees a parent is resolved before its children.
        # ``resolved`` maps a task name to its final effective colour so a
        # child can look its parent up regardless of nesting depth.
        resolved: dict = {}
        for i, task in enumerate(tasks):
            raw = (task.color or "").strip()
            parent = task_parent.get(task.name)
            if parent is not None and parent in resolved:
                inherited = resolved[parent]
            else:
                inherited = section_color

            if not raw:
                effective = inherited
            elif raw.lower() == COLOR_DEFAULT_SENTINEL:
                effective = None
            else:
                effective = raw

            tasks[i] = task._replace(color=effective)
            resolved[task.name] = effective
