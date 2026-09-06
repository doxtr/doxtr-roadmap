"""Pure PlantUML Gantt generator for doxtr_roadmap.

No Sphinx or docutils imports — this module is fully testable without a Sphinx
application.  All inputs are explicit parameters; no module-level globals from
config or CSV data.

The main entry point is :func:`generate_puml`.  All helper functions are
prefixed with an underscore and are not part of the public API.
"""

import datetime
import math
from typing import Callable, Optional, Tuple

# ---------------------------------------------------------------------------
# Type alias for the link-resolver callable  [E-3]
# ---------------------------------------------------------------------------

# A link resolver accepts a raw CSV ``link`` cell value and returns either
# ``(url: str, title: str)`` on success (title may be an empty string), or
# ``None`` when the cell is empty, malformed, or unresolvable.
# Implementations must be side-effect-free with respect to the generator
# (they may log warnings internally).
LinkResolverCallable = Optional[Callable[[str], Optional[Tuple[str, str]]]]


# ---------------------------------------------------------------------------
# Public helpers (used in tests)
# ---------------------------------------------------------------------------

def _working_days(start: datetime.date, end: datetime.date) -> int:
    """Count calendar days in ``[start, end)`` excluding Saturdays and Sundays.

    Parameters
    ----------
    start:
        First day of the range (inclusive).
    end:
        Last day of the range (exclusive).

    Returns
    -------
    int
        Number of Monday–Friday days in the half-open interval.
    """
    days = 0
    d = start
    step = datetime.timedelta(days=1)
    while d < end:
        if d.weekday() < 5:  # Mon–Fri
            days += 1
        d += step
    return days


def percent_complete(
    start: datetime.date,
    end: datetime.date,
    count_weekends: bool = True,
) -> int:
    """Calculate completion percentage based on today's date.

    The percentage is rounded (not truncated) so that when PlantUML re-applies
    it to the bar, the "done" boundary lands on today's date rather than up to
    a full day short.

    When *count_weekends* is ``False`` (i.e. the diagram closes weekends), the
    fraction is measured in working days, matching how PlantUML sizes and fills
    bars once Saturdays/Sundays are closed; otherwise the fill boundary would
    drift because calendar days and rendered columns no longer align.

    Parameters
    ----------
    start:
        Display start date (may be clamped from the real start).
    end:
        Display end date (may be clamped from the real end).
    count_weekends:
        When ``True`` use calendar-day arithmetic; when ``False`` use
        working-day arithmetic.

    Returns
    -------
    int
        Completion percentage in ``[0, 100]``.
    """
    today = datetime.date.today()
    if today >= end:
        return 100
    if today <= start:
        return 0
    if count_weekends:
        total = (end - start).days
        elapsed = (today - start).days
    else:
        total = _working_days(start, end)
        elapsed = _working_days(start, today)
    if total <= 0:
        return 0
    return round((elapsed / total) * 100)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _font_style_lines(selector: str, spec: dict, indent: str = "   ") -> list:
    """Render a PlantUML ganttDiagram style block for one font selector.

    Attributes left as ``None`` are omitted so PlantUML keeps its own defaults.

    Parameters
    ----------
    selector:
        The PlantUML style selector name (e.g. ``"task"``, ``"separator"``).
    spec:
        Dict with optional keys ``name``, ``size``, ``style``, ``color``.
    indent:
        Leading whitespace for each line.

    Returns
    -------
    list[str]
        Lines for the style block, or an empty list if *spec* has no attributes.
    """
    body = []
    if spec.get("size") is not None:
        body.append(f"{indent}   FontSize {spec['size']}")
    if spec.get("style"):
        body.append(f"{indent}   FontStyle {spec['style']}")
    if spec.get("name"):
        body.append(f"{indent}   FontName {spec['name']}")
    if spec.get("color"):
        body.append(f"{indent}   FontColor {spec['color']}")
    if not body:
        return []
    return [f"{indent}{selector} {{", *body, f"{indent}}}"]


def _creole_title(text: str, spec: dict) -> str:
    """Wrap the gantt title text in inline creole font markup.

    The gantt ``title`` style selector is ignored by this PlantUML version, but
    the title text honours inline creole (``<font:...>``, ``<size:...>``,
    ``<color:...>``, ``<b>``/``<i>``).  *spec* is the ``fonts.title`` dict;
    any field left as ``None`` is skipped.

    Parameters
    ----------
    text:
        Raw title string.
    spec:
        Font spec dict (keys: ``name``, ``size``, ``style``, ``color``).

    Returns
    -------
    str
        Title string wrapped in the appropriate creole tags.
    """
    if not spec:
        return text
    open_tags = []
    close_tags = []
    if spec.get("name"):
        open_tags.append(f"<font:{spec['name']}>")
        close_tags.insert(0, "</font>")
    if spec.get("size") is not None:
        open_tags.append(f"<size:{spec['size']}>")
        close_tags.insert(0, "</size>")
    if spec.get("color"):
        open_tags.append(f"<color:{spec['color']}>")
        close_tags.insert(0, "</color>")
    style = (spec.get("style") or "").lower()
    if style == "bold":
        open_tags.append("<b>")
        close_tags.insert(0, "</b>")
    elif style == "italic":
        open_tags.append("<i>")
        close_tags.insert(0, "</i>")
    return "".join(open_tags) + text + "".join(close_tags)


def _build_style_block(config: dict) -> list:
    """Build the PlantUML ``<style>`` block from config fonts/colours.

    Parameters
    ----------
    config:
        Effective config dict (merged global + directive overrides).

    Returns
    -------
    list[str]
        Lines for the ``<style>…</style>`` block.
    """
    fonts = config.get("fonts", {})
    lines = ["<style>", "ganttDiagram {"]
    # Font selectors mapped to PlantUML ganttDiagram style keys.
    for selector, key in (
        ("task", "task"),
        ("separator", "separator"),
        ("timeline.month", "month"),
        ("timeline.year", "year"),
    ):
        spec = fonts.get(key)
        extra = None
        if key == "task":
            frame = config.get("bar", {}).get("frame_color")
            if frame:
                extra = [f"      LineColor {frame}"]
        if spec or extra:
            block = _font_style_lines(selector, spec or {})
            if not block and not extra:
                continue
            if not block:
                block = [f"   {selector} {{", "   }"]
            if extra:
                block = block[:-1] + extra + block[-1:]
            lines.extend(block)
    # Global undone background.
    undone = config.get("bar", {}).get("undone_color")
    if undone:
        lines.extend(["   undone {", f"      BackGroundColor {undone}", "   }"])
    # Closed (non-working) day background.
    closed_bg = config.get("closed", {}).get("background_color")
    if closed_bg:
        lines.extend(["   closed {", f"      BackGroundColor {closed_bg}", "   }"])
    lines.extend(["}", "</style>"])
    return lines


def _section_colors(section: str, config: dict):
    """Resolve bar colours for a section from config.

    Returns a tuple ``(done, frame, frame_overrides)`` where *done* is the
    completed fill colour, *frame* is the bar border colour (``None`` = inherit
    PlantUML's default grey), and *frame_overrides* maps individual task names
    to a different frame colour.

    Parameters
    ----------
    section:
        Section name as it appears in the CSV data.
    config:
        Effective config dict.

    Returns
    -------
    tuple
        ``(done_color, frame_color, frame_overrides_dict)``
    """
    bar_cfg = config.get("bar", {})
    default_done = bar_cfg.get("done_color") or "#FF8C00"
    default_frame = bar_cfg.get("frame_color")
    sec_cfg = config.get("sections", {}).get(section, {})
    return (
        sec_cfg.get("done") or default_done,
        sec_cfg.get("frame", default_frame),
        dict(sec_cfg.get("frame_overrides") or {}),
    )


def _color_clause(done: str, frame) -> str:
    """Build the PlantUML ``is colored in …`` colour clause for a task bar.

    Emits the two-colour ``DONE/FRAME`` form when a frame colour is set, and the
    single-colour ``DONE`` form otherwise (to keep PlantUML's default border).

    Parameters
    ----------
    done:
        Completed-portion fill colour string.
    frame:
        Bar border colour string, or ``None``.

    Returns
    -------
    str
        Colour clause string (without the ``is colored in`` prefix).
    """
    if frame:
        return f"{done}/{frame}"
    return done


# ---------------------------------------------------------------------------
# Collision-detection helpers
# ---------------------------------------------------------------------------

#: Approximate calendar days occupied by one text character at each scale.
#: Values are intentionally slightly over-estimated so that labels that are
#: close to colliding are nudged to a new lane rather than left to just
#: barely fit (and potentially still overlap in the rendered PNG).
_SCALE_DAYS_PER_CHAR: dict = {
    "daily":   1.1,
    "weekly":  4.0,
    "monthly": 9.0,
}

#: Minimum label footprint in days — even a single-character label reserves
#: this many days so that very short names still occupy visible horizontal
#: space on the timeline.
_LABEL_MIN_DAYS: float = 4.0


def _estimate_label_days(
    name: str,
    scale: str,
    char_width_factor: float = 1.0,
) -> float:
    """Estimate how many calendar days a task's text label spans horizontally.

    PlantUML renders labels at a roughly fixed pixel width regardless of the
    projectscale, but each scale maps a different number of days to a column.
    A long label that fits on a monthly chart may run over into the adjacent
    bar on a daily chart.

    Parameters
    ----------
    name:
        Task display name (the label that PlantUML draws over the bar).
    scale:
        PlantUML projectscale string — ``"daily"``, ``"weekly"``, or
        ``"monthly"``.
    char_width_factor:
        Multiplicative tuning knob.  1.0 uses the calibrated defaults.
        Values > 1 reserve more space (split sooner); values < 1 pack
        more tightly.

    Returns
    -------
    float
        Estimated horizontal footprint of the label in calendar days.
    """
    base = _SCALE_DAYS_PER_CHAR.get(scale, _SCALE_DAYS_PER_CHAR["monthly"])
    days = len(name) * base * char_width_factor
    return max(days, _LABEL_MIN_DAYS)


def _bar_extent(
    disp_start: datetime.date,
    disp_end: datetime.date,
    name: str,
    is_milestone: bool,
    scale: str,
    char_width_factor: float,
    gap_days: int,
) -> tuple:
    """Return the full horizontal footprint ``(left, right)`` of a task bar.

    The footprint is ``[disp_start, max(disp_end, disp_start + label_days) + gap_days)``.
    For milestones (``disp_start == disp_end``) the bar has zero width but
    the label still occupies ``label_days`` to the right.

    Parameters
    ----------
    disp_start:
        Rendered start date of the bar.
    disp_end:
        Rendered end date of the bar.
    name:
        Task label string.
    is_milestone:
        Whether this task is a milestone (zero-width bar).
    scale:
        PlantUML projectscale string.
    char_width_factor:
        Label-width tuning knob (see :func:`_estimate_label_days`).
    gap_days:
        Mandatory clear gap (in calendar days) added to the right edge so
        that adjacent labels on the same lane don't abut.

    Returns
    -------
    tuple
        ``(left_date, right_date)`` — both as :class:`datetime.date`.
    """
    label_days = _estimate_label_days(name, scale, char_width_factor)
    label_end = disp_start + datetime.timedelta(days=math.ceil(label_days))
    if is_milestone:
        right = label_end + datetime.timedelta(days=gap_days)
    else:
        right = max(disp_end, label_end) + datetime.timedelta(days=gap_days)
    return (disp_start, right)


def _extents_overlap(ext_a: tuple, ext_b: tuple) -> bool:
    """Return True if the two half-open date intervals intersect.

    An interval is ``[left, right)`` where *right* is exclusive.  Two
    intervals overlap iff *neither* one ends before the other begins.

    Parameters
    ----------
    ext_a:
        ``(left_date, right_date)`` — the first interval.
    ext_b:
        ``(left_date, right_date)`` — the second interval.

    Returns
    -------
    bool
    """
    a_left, a_right = ext_a
    b_left, b_right = ext_b
    return a_left < b_right and b_left < a_right


def _pack_lanes(
    members: list,
    scale: str,
    char_width_factor: float,
    gap_days: int,
) -> list:
    """Greedily pack *members* into as few collision-free lanes as possible.

    Each *member* is a dict with keys ``pid``, ``name``, ``disp_start``,
    ``disp_end``, and ``is_milestone``.  Members are placed in the order
    they appear in *members* (CSV order, generally left-to-right on the
    timeline).

    First-fit strategy: for each member, assign it to the first lane on which
    it does not collide with **any** already-placed member.  If no such lane
    exists, open a new lane.  Groups are small so checking all members on
    every lane is cheap and safe.

    Parameters
    ----------
    members:
        Ordered list of member dicts for one ``row_group``.
    scale:
        PlantUML projectscale string.
    char_width_factor:
        Label-width tuning knob.
    gap_days:
        Minimum gap between adjacent bars on the same lane.

    Returns
    -------
    list[list]
        List of lanes; each lane is a list of member dicts in the order they
        were placed.  A group that fits on one lane returns a single-element
        list; a group whose members all collide returns one lane per member.
    """
    # Each entry: (list_of_member_dicts, list_of_extents)
    lanes: list = []

    for member in members:
        extent = _bar_extent(
            member["disp_start"],
            member["disp_end"],
            member["name"],
            member["is_milestone"],
            scale,
            char_width_factor,
            gap_days,
        )
        placed = False
        for lane_members, lane_extents in lanes:
            # Check against ALL members already on this lane (groups are small)
            collides = any(_extents_overlap(extent, ex) for ex in lane_extents)
            if not collides:
                lane_members.append(member)
                lane_extents.append(extent)
                placed = True
                break
        if not placed:
            lanes.append(([member], [extent]))

    return [lm for lm, _ in lanes]


def find_period_window(period_names: list, items: list):
    """Resolve one or more period names to a ``(min_start, max_end)`` date window.

    Period names are matched case-insensitively against *every* task name in
    *every* section of *items*.  The returned window spans from the earliest
    start to the latest end of all matched periods, so passing two period names
    limits the zoom to exactly those two.

    Parameters
    ----------
    period_names:
        List of period name strings (e.g. ``["Set27-01", "Set27-04"]``).
    items:
        Parsed roadmap data as returned by :func:`csv_parser.load_items_from_file`.
        Tasks may be :class:`~csv_parser.TaskItem` instances or raw tuples with
        the same positional layout.

    Returns
    -------
    tuple
        ``(datetime.date, datetime.date)`` — the min start and max end.

    Raises
    ------
    ValueError
        If any of the requested period names are not found in *items*.
    """
    wanted = {p.strip().lower() for p in period_names if p.strip()}
    starts = []
    ends = []
    matched = set()
    for _section, tasks in items:
        for task in tasks:
            # Support both TaskItem (attribute access) and legacy tuples
            name = task[0] if not hasattr(task, "name") else task.name
            start_str = task[1] if not hasattr(task, "start") else task.start
            end_str = task[2] if not hasattr(task, "end") else task.end
            if name.strip().lower() in wanted:
                starts.append(datetime.date.fromisoformat(start_str))
                ends.append(datetime.date.fromisoformat(end_str))
                matched.add(name.strip().lower())
    missing = sorted(wanted - matched)
    if missing:
        raise ValueError(
            "unknown period name(s): " + ", ".join(missing)
            + ". Use names exactly as they appear in the CSV."
        )
    return min(starts), max(ends)


def resolve_window(
    period_names=None,
    start=None,
    end=None,
    items=None,
    config=None,
):
    """Compute the ``(project_start, project_end)`` clip window.

    Precedence and combination rules:

    - If period names are given, they set the base window (earliest start /
      latest end of those periods).
    - Explicit *start* / *end* override the corresponding edge of that window
      (or of the defaults when no periods are given).
    - With no arguments, returns ``(default_start, None)`` — the full,
      unclipped timeline.

    When a period is selected the project start must never be later than the
    period's start: a project start past the first period task makes that task
    begin before the diagram start.  So if the resolved start falls after the
    period start, it is clamped back to the period start.

    Parameters
    ----------
    period_names:
        Optional list of period name strings.
    start:
        Optional explicit ``datetime.date`` start override.
    end:
        Optional explicit ``datetime.date`` end override.
    items:
        Parsed roadmap data (required when *period_names* is given).
    config:
        Config dict (used to read ``default_start``).

    Returns
    -------
    tuple
        ``(datetime.date, datetime.date | None)``
    """
    cfg = config or {}
    # R-3: fall back to today when default_start is None
    raw_default = cfg.get("default_start")
    if raw_default:
        default_start = datetime.date.fromisoformat(raw_default)
    else:
        default_start = datetime.date.today()

    period_start = period_end = None
    if period_names:
        period_start, period_end = find_period_window(period_names, items or [])

    win_start = start or period_start
    win_end = end or period_end

    if win_start is None:
        win_start = default_start
    # Never let the project start drift past the selected period's start.
    if period_start is not None and win_start > period_start:
        win_start = period_start
    if win_start is not None and win_end is not None and win_end < win_start:
        raise ValueError(
            f"end date {win_end} is before start date {win_start}"
        )
    return win_start, win_end


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_puml(
    items: list,
    config: dict,
    project_start=None,
    project_end=None,
    scale: str = None,
    close_weekends: bool = False,
    title: str = None,
    link_resolver: LinkResolverCallable = None,
) -> str:
    """Generate a PlantUML ``@startgantt … @endgantt`` string from roadmap data.

    This function is pure: it has no side-effects, no Sphinx imports, and no
    module-level globals.  All configuration is passed explicitly.

    Parameters
    ----------
    items:
        Parsed roadmap sections as returned by
        :func:`csv_parser.load_items_from_file` or
        :func:`csv_parser.load_items_from_string`.  Each element is a
        ``(section_name, tasks)`` tuple where each task is a
        :class:`~csv_parser.TaskItem` (or a compatible tuple with the same
        positional layout for backward compatibility).
    config:
        Effective config dict (global Sphinx config merged with any directive
        option overrides).
    project_start:
        Diagram start date (``datetime.date``).  Falls back to
        ``config["default_start"]`` or today if not set.
    project_end:
        Diagram end date (``datetime.date``), or ``None`` for an open-ended
        timeline.
    scale:
        PlantUML projectscale string (``"daily"``, ``"weekly"``,
        ``"monthly"``).  Falls back to ``config["default_scale"]``.
    close_weekends:
        When ``True`` emits ``saturday are closed`` / ``sunday are closed``
        lines.
    title:
        Override the diagram title.  Falls back to ``config["default_title"]``.
    link_resolver:
        Optional :data:`LinkResolverCallable` — a callable
        ``(cell: str) -> (url: str, title: str) | None``.
        Contract: accepts a raw CSV ``link`` cell value; returns a
        ``(url, title)`` tuple on success (title may be empty string), or
        ``None`` when the cell is empty, malformed, or the id cannot be
        resolved.  When ``None``, links are silently skipped (useful in unit
        tests).

    Returns
    -------
    str
        Complete PlantUML source string.
    """
    # Resolve defaults
    raw_default_start = config.get("default_start")
    if project_start is None:
        if raw_default_start:
            project_start = datetime.date.fromisoformat(raw_default_start)
        else:
            project_start = datetime.date.today()
    scale = scale or config.get("default_scale", "monthly")

    # Collision-detection config
    collision_detection = config.get("collision_detection", True)
    collision_char_width_factor = config.get("collision_char_width_factor", 1.0)
    collision_gap_days = int(config.get("collision_gap_days", 2))
    title = title or config.get("default_title", "Roadmap")

    # Column-zoom: append `zoom <factor>` to projectscale when > 1 and valid.
    _raw_zoom = config.get("column_zoom", 1)
    try:
        _zoom = float(_raw_zoom)
    except (TypeError, ValueError):
        _zoom = 1.0
    if _zoom <= 0:
        _zoom = 1.0

    def _fmt_zoom(z: float) -> str:
        """Return zoom as int string when whole, float string otherwise."""
        return str(int(z)) if z == int(z) else str(z)

    if _zoom != 1.0:
        projectscale_line = f"projectscale {scale} zoom {_fmt_zoom(_zoom)}"
    else:
        projectscale_line = f"projectscale {scale}"

    lines = [
        "@startgantt",
        f"scale {config.get('scale_factor', 1.25)}",
        *_build_style_block(config),
        "",
        f"title {_creole_title(title, config.get('fonts', {}).get('title'))}",
        projectscale_line,
        f"Project starts {project_start.isoformat()}",
    ]

    if config.get("clean_style", False):
        lines.append("hide column start")
        lines.append("hide column end")
        lines.append("hide column duration")

    if close_weekends:
        lines.append("saturday are closed")
        lines.append("sunday are closed")

    today_color = config.get("today", {}).get("color")
    if today_color:
        lines.append(f"today is colored in {today_color}")

    # Clip window helpers
    clip_start = project_start
    clip_end = project_end

    def _overlaps(t_start, t_end):
        if t_end < clip_start:
            return False
        if clip_end is not None and t_start > clip_end:
            return False
        return True

    def _clamp(d):
        d = max(d, clip_start)
        if clip_end is not None:
            d = min(d, clip_end)
        return d

    # Track whether any task line was emitted across all sections.
    _any_task_rendered = False

    for section, tasks in items:
        color_done, section_frame, frame_overrides = _section_colors(
            section, config
        )
        rendered = []
        for task in tasks:
            # Support both TaskItem (attribute access) and legacy tuples
            if hasattr(task, "name"):
                name       = task.name
                start_str  = task.start
                end_str    = task.end
                link_cell  = task.link
                is_subtask = task.is_subtask
                row_group  = task.row_group
                pid        = task.pid
            else:
                name       = task[0]
                start_str  = task[1]
                end_str    = task[2]
                link_cell  = task[3]
                is_subtask = task[5]
                row_group  = task[6]
                pid        = task[7]

            start = datetime.date.fromisoformat(start_str)
            end   = datetime.date.fromisoformat(end_str)

            if not _overlaps(start, end):
                continue

            is_milestone = (start == end)
            if is_milestone:
                disp_start, disp_end = start, end
            else:
                disp_start = _clamp(start)
                disp_end   = _clamp(end)
                if disp_start == disp_end:
                    # Bar clamped to one day → nudge end out by one day.
                    disp_end = disp_start + datetime.timedelta(days=1)

            rendered.append(
                (name, start, end, disp_start, disp_end, is_milestone,
                 link_cell, is_subtask, row_group, pid)
            )

        if not rendered:
            continue  # skip empty sections after zoom

        _any_task_rendered = True
        lines.append("")
        # Only emit a section separator when the section has a non-empty name.
        # Rows with a blank ``section`` column (or a CSV with no ``section``
        # column at all) render their tasks without a ``-- ... --`` header,
        # so a section-less roadmap has no stray empty separator line.
        if section and section.strip():
            lines.append(f"-- {section} --")

        row_groups: dict = {}
        for (name, start, end, disp_start, disp_end, is_milestone,
             link_cell, _is_subtask, row_group, pid) in rendered:

            if row_group is not None:
                row_groups.setdefault(row_group, []).append({
                    "pid": pid,
                    "name": name,
                    "disp_start": disp_start,
                    "disp_end": disp_end,
                    "is_milestone": is_milestone,
                })

            frame = frame_overrides.get(name, section_frame)
            color_clause = _color_clause(color_done, frame)

            decl = f"[{name}] as [{pid}]"

            if is_milestone:
                lines.append(f"{decl} happens {disp_start.isoformat()}")
                lines.append(f"[{pid}] is colored in {color_clause}")
            else:
                pct = percent_complete(
                    disp_start, disp_end,
                    count_weekends=not close_weekends,
                )
                lines.append(
                    f"{decl} starts {disp_start.isoformat()} and ends "
                    f"{disp_end.isoformat()} and is colored in {color_clause}"
                )
                lines.append(f"[{pid}] is {pct}% completed")

            # Resolve hyperlink
            if link_cell and link_cell.strip() and link_resolver is not None:
                result = link_resolver(link_cell)
                if result is not None:
                    url, link_title = result
                    if link_title:
                        lines.append(f"[{pid}] links to [[{url} {link_title}]]")
                    else:
                        lines.append(f"[{pid}] links to [[{url}]]")

        # Pack same-row groups — with optional collision detection
        for members in row_groups.values():
            if collision_detection:
                lanes = _pack_lanes(
                    members, scale,
                    collision_char_width_factor,
                    collision_gap_days,
                )
            else:
                # Old behaviour: force all members onto one lane regardless
                # of bar/label overlap (users who deliberately want overlap).
                lanes = [members]

            for lane in lanes:
                if len(lane) < 2:
                    continue  # single member — no directive needed
                anchor_pid = lane[0]["pid"]
                for member in lane[1:]:
                    lines.append(
                        f"[{member['pid']}] displays on same row as [{anchor_pid}]"
                    )

    # If no tasks were emitted (e.g. all filtered/clipped out), emit a
    # placeholder task so PlantUML never receives an empty gantt body.
    # An empty @startgantt…@endgantt (or one with only a milestone via
    # 'happens') triggers a NullPointerException in PlantUML's TimeHeader
    # and produces an error image.  A one-day bar task is the minimal valid
    # gantt entry that PlantUML renders cleanly.
    if not _any_task_rendered:
        _placeholder_end = project_start + datetime.timedelta(days=1)
        lines.append("")
        lines.append("-- (no matching tasks) --")
        lines.append(
            f"[No matching tasks] as [__doxtr_empty__] "
            f"starts {project_start.isoformat()} "
            f"and ends {_placeholder_end.isoformat()} "
            f"and is colored in #CCCCCC"
        )
        lines.append("[__doxtr_empty__] is 0% completed")

    lines.append("")
    lines.append("@endgantt")
    lines.append("")
    return "\n".join(lines)
