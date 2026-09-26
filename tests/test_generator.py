"""Unit tests for doxtr_roadmap/generator.py."""

import datetime
import copy
import pytest

from doxtr_roadmap import generator
from doxtr_roadmap.config_defaults import DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides):
    """Return a deep copy of DEFAULT_CONFIG with overrides applied."""
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["default_start"] = "2026-01-01"
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


def _items_one_task(name="Task A", start="2026-02-01", end="2026-04-30",
                    link="", tags="", is_subtask=False, row_group=None,
                    section="Sec"):
    """Return a minimal items list with one section/task."""
    pid = name
    return [(section, [(name, start, end, link, tags, is_subtask, row_group, pid)])]


def _items_two_tasks_same_row(section="S",
                              a_name="T1", a_start="2026-01-01", a_end="2026-03-31",
                              b_name="T2", b_start="2026-04-01", b_end="2026-06-30",
                              group="grp"):
    return [(section, [
        (a_name, a_start, a_end, "", "", False, group, a_name),
        (b_name, b_start, b_end, "", "", False, group, b_name),
    ])]


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------

def test_startgantt_endgantt():
    items = _items_one_task()
    out = generator.generate_puml(items, _cfg())
    assert out.strip().startswith("@startgantt")
    assert out.strip().endswith("@endgantt")


def test_scale_line():
    out = generator.generate_puml(_items_one_task(), _cfg(scale_factor=1.5))
    assert "scale 1.5" in out


def test_projectscale_line():
    out = generator.generate_puml(_items_one_task(), _cfg())
    assert "projectscale monthly" in out


def test_project_starts_line():
    out = generator.generate_puml(
        _items_one_task(),
        _cfg(),
        project_start=datetime.date(2026, 1, 1),
    )
    assert "Project starts 2026-01-01" in out


def test_clean_style_hides_columns():
    out = generator.generate_puml(_items_one_task(), _cfg(clean_style=True))
    assert "hide column start" in out
    assert "hide column end" in out
    assert "hide column duration" in out


def test_clean_style_absent():
    out = generator.generate_puml(_items_one_task(), _cfg(clean_style=False))
    assert "hide column start" not in out
    assert "hide column end" not in out
    assert "hide column duration" not in out


def test_default_config_clean_style_is_true():
    """DEFAULT_CONFIG must have clean_style=True (baseline is PlantUML v1.2026.7)."""
    assert DEFAULT_CONFIG["clean_style"] is True


def test_default_has_hide_column():
    """Default config (clean_style True) must emit hide column lines."""
    import copy
    default_cfg = copy.deepcopy(DEFAULT_CONFIG)
    default_cfg["default_start"] = "2026-01-01"
    out = generator.generate_puml(_items_one_task(), default_cfg)
    assert "hide column start" in out
    assert "hide column end" in out
    assert "hide column duration" in out


def test_close_weekends():
    out = generator.generate_puml(
        _items_one_task(), _cfg(), close_weekends=True
    )
    assert "saturday are closed" in out
    assert "sunday are closed" in out


def test_today_line():
    out = generator.generate_puml(
        _items_one_task(), _cfg(today={"color": "#E53935"})
    )
    assert "today is colored in #E53935" in out


def test_today_line_absent():
    out = generator.generate_puml(
        _items_one_task(), _cfg(today={"color": None})
    )
    assert "today is colored in" not in out


# ---------------------------------------------------------------------------
# Section and task declaration
# ---------------------------------------------------------------------------

def test_section_header():
    items = _items_one_task(section="MySection")
    out = generator.generate_puml(items, _cfg())
    assert "-- MySection --" in out


def test_blank_section_emits_no_separator():
    """A blank section name renders its tasks without a ``-- ... --`` header.

    This lets a roadmap omit sections entirely (blank ``section`` column or a
    CSV with no ``section`` column at all) without producing a stray empty
    separator line.
    """
    items = _items_one_task(name="Task A", section="")
    out = generator.generate_puml(items, _cfg())
    # No section separator at all (not even an empty '--  --')
    assert not any(
        line.startswith("--") for line in out.splitlines()
    ), "Blank section must not emit a separator line"
    # The task itself is still rendered
    assert "[Task A]" in out


def test_empty_section_skipped_on_clip():
    """Tasks outside clip window → section header should not appear."""
    items = _items_one_task(start="2025-01-01", end="2025-06-30", section="Old")
    out = generator.generate_puml(
        items, _cfg(),
        project_start=datetime.date(2026, 1, 1),
        project_end=datetime.date(2026, 12, 31),
    )
    assert "-- Old --" not in out


def test_regular_task_line():
    items = _items_one_task(name="My Task", start="2026-02-01", end="2026-04-30")
    out = generator.generate_puml(
        items, _cfg(),
        project_start=datetime.date(2026, 1, 1),
    )
    assert "[My Task] as [My Task]" in out
    assert "starts 2026-02-01 and ends 2026-04-30" in out
    assert "is colored in" in out


def test_completion_line_always_present():
    """Future task → 0% completed line always emitted."""
    items = [(
        "S", [("FutureTask", "2099-01-01", "2099-12-31", "", "", False, None, "FutureTask")]
    )]
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2099, 1, 1)
    )
    assert "[FutureTask] is 0% completed" in out


def test_completion_100_past_task():
    items = [(
        "S", [("PastTask", "2020-01-01", "2020-06-30", "", "", False, None, "PastTask")]
    )]
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2020, 1, 1)
    )
    assert "[PastTask] is 100% completed" in out


def test_milestone_task():
    items = _items_one_task(name="M1", start="2026-03-15", end="2026-03-15")
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1)
    )
    assert "happens 2026-03-15" in out
    assert "is colored in" in out


def test_milestone_not_clamped():
    """Milestone outside clip window is omitted entirely."""
    items = _items_one_task(name="M1", start="2025-01-01", end="2025-01-01")
    out = generator.generate_puml(
        items, _cfg(),
        project_start=datetime.date(2026, 1, 1),
        project_end=datetime.date(2026, 12, 31),
    )
    assert "M1" not in out


def test_row_group_directive():
    """With collision_detection=False, all group members are forced onto one row."""
    items = _items_two_tasks_same_row()
    out = generator.generate_puml(
        items, _cfg(collision_detection=False), project_start=datetime.date(2026, 1, 1)
    )
    assert "[T2] displays on same row as [T1]" in out


def test_row_group_collision_splits_overlapping():
    """Two fully-overlapping tasks with collision_detection=True → separate rows."""
    items = _items_two_tasks_same_row(
        a_start="2026-01-01", a_end="2026-06-30",
        b_start="2026-01-01", b_end="2026-06-30",
    )
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1)
    )
    # Collision detected → T2 must NOT display on same row as T1
    assert "[T2] displays on same row as [T1]" not in out


def test_row_group_no_collision_same_row():
    """Two well-separated, short-named tasks → same row (one lane)."""
    # A and B are single-char names (short label); B starts well after A ends.
    # At monthly scale: label for 'A' = max(1*9, 4) = 9 days; + gap 2 = 11 days.
    # A ends 2026-03-31; right extent = Apr 11.  B starts May 1 > Apr 11 → no collision.
    items = [("S", [
        ("A", "2026-01-01", "2026-03-31", "", "", False, "g", "A"),
        ("B", "2026-05-01", "2026-07-31", "", "", False, "g", "B"),
    ])]
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1)
    )
    assert "[B] displays on same row as [A]" in out


# ---------------------------------------------------------------------------
# Link emission
# ---------------------------------------------------------------------------

def test_link_plain_url():
    def resolver(cell):
        return ("https://example.com", "")
    items = _items_one_task(link="https://example.com")
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1),
        link_resolver=resolver
    )
    assert "links to [[https://example.com]]" in out


def test_link_with_title():
    def resolver(cell):
        return ("https://example.com", "My Title")
    items = _items_one_task(link=":xlink:`some-id`")
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1),
        link_resolver=resolver
    )
    assert "links to [[https://example.com My Title]]" in out


def test_link_none():
    """No link_resolver → no links to line."""
    items = _items_one_task(link="https://example.com")
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1),
        link_resolver=None
    )
    assert "links to" not in out


# ---------------------------------------------------------------------------
# Subtask
# ---------------------------------------------------------------------------

def test_subtask_indented():
    """Subtask with is_subtask=True is present in output."""
    items = [("S", [
        ("Parent", "2026-01-01", "2026-12-31", "", "", False, None, "Parent"),
        ("Child",  "2026-01-01", "2026-06-30", "", "", True,  None, "Child"),
    ])]
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1)
    )
    assert "[Parent]" in out
    assert "[Child]" in out


# ---------------------------------------------------------------------------
# column_zoom tests
# ---------------------------------------------------------------------------

def test_column_zoom_3_integer():
    """column_zoom=3 → `projectscale monthly zoom 3` (integer, no .0)."""
    out = generator.generate_puml(_items_one_task(), _cfg(column_zoom=3))
    assert "projectscale monthly zoom 3" in out
    # Must not have a bare `projectscale monthly` line (i.e. not without zoom)
    lines = [l for l in out.splitlines() if l.startswith("projectscale")]
    assert len(lines) == 1
    assert lines[0] == "projectscale monthly zoom 3"


def test_column_zoom_1_default_no_suffix():
    """column_zoom=1 (default) → bare `projectscale monthly` with no ` zoom ` suffix."""
    out = generator.generate_puml(_items_one_task(), _cfg(column_zoom=1))
    assert "projectscale monthly" in out
    assert " zoom " not in out


def test_column_zoom_absent_default_no_suffix():
    """No column_zoom key → bare `projectscale monthly` (regression guard)."""
    cfg = _cfg()
    cfg.pop("column_zoom", None)  # ensure key absent
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "projectscale monthly" in out
    assert " zoom " not in out


def test_column_zoom_2_5_float():
    """column_zoom=2.5 → `projectscale monthly zoom 2.5`."""
    out = generator.generate_puml(_items_one_task(), _cfg(column_zoom=2.5))
    assert "projectscale monthly zoom 2.5" in out


def test_column_zoom_2_0_whole_float_formatted_as_int():
    """column_zoom=2.0 → `zoom 2` not `zoom 2.0` (whole-number formatting)."""
    out = generator.generate_puml(_items_one_task(), _cfg(column_zoom=2.0))
    assert "projectscale monthly zoom 2" in out
    assert "zoom 2.0" not in out


def test_column_zoom_0_treated_as_no_zoom():
    """column_zoom=0 → treated as no zoom (bare projectscale line)."""
    out = generator.generate_puml(_items_one_task(), _cfg(column_zoom=0))
    assert " zoom " not in out
    assert "projectscale monthly" in out


def test_column_zoom_negative_treated_as_no_zoom():
    """column_zoom=-2 → treated as no zoom (guard against invalid values)."""
    out = generator.generate_puml(_items_one_task(), _cfg(column_zoom=-2))
    assert " zoom " not in out
    assert "projectscale monthly" in out


def test_column_zoom_weekly_scale():
    """column_zoom=2 with weekly scale → `projectscale weekly zoom 2`."""
    cfg = _cfg(column_zoom=2, default_scale="weekly")
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "projectscale weekly zoom 2" in out



# ---------------------------------------------------------------------------
# Part B: empty / zero-task gantt placeholder
# ---------------------------------------------------------------------------

def test_empty_items_list_produces_placeholder():
    """generate_puml with an empty items list emits the 'No matching tasks'
    placeholder task rather than an empty gantt body."""
    out = generator.generate_puml(
        items=[],
        config=_cfg(),
        project_start=datetime.date(2026, 1, 1),
    )
    assert "@startgantt" in out
    assert "@endgantt" in out
    assert "No matching tasks" in out
    assert "__doxtr_empty__" in out
    # Must be a regular bar task (not a milestone 'happens') — PlantUML NPEs
    # on milestone-only gantts in v1.2026.7.
    assert "starts 2026-01-01 and ends 2026-01-02" in out
    assert "is 0% completed" in out


def test_all_tasks_clipped_produces_placeholder():
    """generate_puml where all tasks fall outside the clip window emits
    the placeholder (not an empty gantt)."""
    items = _items_one_task(start="2024-01-01", end="2024-12-31")
    out = generator.generate_puml(
        items=items,
        config=_cfg(),
        project_start=datetime.date(2026, 1, 1),
        project_end=datetime.date(2026, 12, 31),
    )
    assert "@startgantt" in out
    assert "@endgantt" in out
    assert "No matching tasks" in out
    assert "__doxtr_empty__" in out


def test_non_empty_items_no_placeholder():
    """generate_puml with real tasks does NOT emit the placeholder."""
    items = _items_one_task()
    out = generator.generate_puml(
        items=items,
        config=_cfg(),
        project_start=datetime.date(2026, 1, 1),
    )
    assert "No matching tasks" not in out
    assert "__doxtr_empty__" not in out


def test_placeholder_uses_project_start_date():
    """The placeholder bar task starts at project_start."""
    out = generator.generate_puml(
        items=[],
        config=_cfg(),
        project_start=datetime.date(2027, 6, 15),
    )
    assert "starts 2027-06-15 and ends 2027-06-16" in out


def test_placeholder_has_section_separator():
    """The placeholder gantt includes a '-- (no matching tasks) --' separator."""
    out = generator.generate_puml(
        items=[],
        config=_cfg(),
        project_start=datetime.date(2026, 1, 1),
    )
    assert "-- (no matching tasks) --" in out


def test_pid_collision_distinct_pids():
    """Two rows sharing a display name keep distinct pids in the decl."""
    items = [("S", [
        ("PI27-01", "2026-11-01", "2027-01-31", "", "", False, None, "PI27-01"),
        ("PI27-01", "2027-02-01", "2027-04-30", "", "", False, None, "PI27-01__2"),
    ])]
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 11, 1)
    )
    assert "[PI27-01] as [PI27-01]" in out
    assert "[PI27-01] as [PI27-01__2]" in out


# ---------------------------------------------------------------------------
# Clip window / clamping
# ---------------------------------------------------------------------------

def test_clip_window_omits_tasks():
    items = _items_one_task(start="2024-01-01", end="2024-12-31")
    out = generator.generate_puml(
        items, _cfg(),
        project_start=datetime.date(2026, 1, 1),
        project_end=datetime.date(2026, 12, 31),
    )
    assert "Task A" not in out


def test_clip_window_clamps_tasks():
    """Task starting before clip start → clamped to clip_start."""
    items = _items_one_task(start="2025-10-01", end="2026-06-30")
    out = generator.generate_puml(
        items, _cfg(),
        project_start=datetime.date(2026, 1, 1),
        project_end=datetime.date(2026, 12, 31),
    )
    assert "starts 2026-01-01" in out


# ---------------------------------------------------------------------------
# Colour clause
# ---------------------------------------------------------------------------

def test_color_clause_with_frame():
    cfg = _cfg(bar={"done_color": "#AABBCC", "undone_color": "#FFF", "frame_color": "#112233"})
    items = _items_one_task()
    out = generator.generate_puml(
        items, cfg, project_start=datetime.date(2026, 1, 1)
    )
    assert "#AABBCC/#112233" in out


def test_color_clause_without_frame():
    cfg = _cfg(bar={"done_color": "#AABBCC", "undone_color": "#FFF", "frame_color": None})
    items = _items_one_task()
    out = generator.generate_puml(
        items, cfg, project_start=datetime.date(2026, 1, 1)
    )
    assert "#AABBCC/#" not in out
    assert "#AABBCC" in out


# ---------------------------------------------------------------------------
# Style block
# ---------------------------------------------------------------------------

def test_style_block_emitted():
    out = generator.generate_puml(_items_one_task(), _cfg())
    assert "<style>" in out
    assert "ganttDiagram {" in out
    assert "</style>" in out


def test_undone_background():
    cfg = _cfg(bar={"done_color": "#FF8C00", "undone_color": "#FFF3E0", "frame_color": None})
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "BackGroundColor #FFF3E0" in out


def test_font_style_title_selector():
    """Title font spec emitted via creole (not style block for title)."""
    cfg = _cfg()
    out = generator.generate_puml(
        _items_one_task(), cfg,
        title="Test Title",
    )
    # Creole bold wrapping from the title spec
    assert "<b>Test Title</b>" in out


def test_creole_title_bold():
    result = generator._creole_title("Hello", {"style": "bold"})
    assert result == "<b>Hello</b>"


# ---------------------------------------------------------------------------
# Working days & percent_complete
# ---------------------------------------------------------------------------

def test_working_days_count():
    """Mon 2024-01-01 to Mon 2024-01-08 = 5 working days."""
    d1 = datetime.date(2024, 1, 1)
    d2 = datetime.date(2024, 1, 8)
    assert generator._working_days(d1, d2) == 5


def test_percent_complete_calendar():
    start = datetime.date(2020, 1, 1)
    end   = datetime.date(2020, 1, 11)  # 10-day span
    # today clamped to middle for determinism would require monkeypatching;
    # test boundary cases instead.
    assert generator.percent_complete(start, end, count_weekends=True) in range(0, 101)


def test_percent_complete_working_days():
    start = datetime.date(2020, 1, 1)
    end   = datetime.date(2020, 1, 11)
    # Should return 0–100
    pct = generator.percent_complete(start, end, count_weekends=False)
    assert 0 <= pct <= 100


def test_percent_complete_future():
    start = datetime.date(2099, 1, 1)
    end   = datetime.date(2099, 12, 31)
    assert generator.percent_complete(start, end) == 0


def test_percent_complete_past():
    start = datetime.date(2000, 1, 1)
    end   = datetime.date(2000, 6, 30)
    assert generator.percent_complete(start, end) == 100


# ---------------------------------------------------------------------------
# find_period_window / resolve_window
# ---------------------------------------------------------------------------

def test_find_period_window():
    items = [("P", [
        ("Set27-01", "2026-11-09", "2027-01-29", "", "", False, None, "Set27-01"),
        ("Set27-04", "2027-02-01", "2027-04-09", "", "", False, None, "Set27-04"),
    ])]
    start, end = generator.find_period_window(["Set27-01"], items)
    assert start == datetime.date(2026, 11, 9)
    assert end   == datetime.date(2027, 1, 29)


def test_find_period_window_span_two():
    items = [("P", [
        ("Set27-01", "2026-11-09", "2027-01-29", "", "", False, None, "Set27-01"),
        ("Set27-04", "2027-02-01", "2027-04-09", "", "", False, None, "Set27-04"),
    ])]
    start, end = generator.find_period_window(["Set27-01", "Set27-04"], items)
    assert start == datetime.date(2026, 11, 9)
    assert end   == datetime.date(2027, 4, 9)


def test_find_period_window_unknown_raises():
    items = [("P", [("Set27-01", "2026-11-09", "2027-01-29", "", "", False, None, "Set27-01")])]
    with pytest.raises(ValueError, match="unknown period"):
        generator.find_period_window(["NoSuchPeriod"], items)


def test_resolve_window_defaults():
    cfg = {"default_start": "2026-01-01"}
    start, end = generator.resolve_window(config=cfg)
    assert start == datetime.date(2026, 1, 1)
    assert end is None


def test_resolve_window_explicit_dates():
    cfg = {"default_start": "2026-01-01"}
    start, end = generator.resolve_window(
        start=datetime.date(2026, 3, 1),
        end=datetime.date(2026, 9, 30),
        config=cfg,
    )
    assert start == datetime.date(2026, 3, 1)
    assert end   == datetime.date(2026, 9, 30)


# ---------------------------------------------------------------------------
# T-5: percent_complete with fixed today (monkeypatched)
# ---------------------------------------------------------------------------

class _FixedDate(datetime.date):
    """datetime.date subclass that returns a fixed value for today()."""
    _fixed: datetime.date = datetime.date(2026, 1, 6)

    @classmethod
    def today(cls):
        return cls._fixed


def test_percent_complete_calendar_exact(monkeypatch):
    """Monkeypatch today to a known midpoint — assert exact percentage."""
    start = datetime.date(2026, 1, 1)
    end   = datetime.date(2026, 1, 11)   # 10 calendar days
    # Fix today at day 5 = 2026-01-06
    _FixedDate._fixed = datetime.date(2026, 1, 6)
    monkeypatch.setattr(generator.datetime, "date", _FixedDate)
    # elapsed=5, total=10 → 50%
    result = generator.percent_complete(start, end, count_weekends=True)
    assert result == 50


def test_percent_complete_working_days_exact(monkeypatch):
    """Monkeypatch today to midpoint within a Mon–Fri week."""
    # Mon 2026-01-05 to Mon 2026-01-12 = 5 working days
    start = datetime.date(2026, 1, 5)
    end   = datetime.date(2026, 1, 12)
    # Fix today at Wed 2026-01-07 (3rd working day, elapsed=2 Mon+Tue)
    _FixedDate._fixed = datetime.date(2026, 1, 7)
    monkeypatch.setattr(generator.datetime, "date", _FixedDate)
    # elapsed working days = 2 (Mon, Tue), total = 5 → 40%
    result = generator.percent_complete(start, end, count_weekends=False)
    assert result == 40


# ---------------------------------------------------------------------------
# T-6: resolve_window — period given, no explicit start; end-before-start error
# ---------------------------------------------------------------------------

def test_resolve_window_period_no_explicit_start():
    """Period given, no explicit start → win_start == period start."""
    items = [("P", [
        ("Sprint1", "2026-03-01", "2026-03-31", "", "", False, None, "Sprint1"),
    ])]
    cfg = {"default_start": "2026-01-01"}
    start, end = generator.resolve_window(
        period_names=["Sprint1"],
        items=items,
        config=cfg,
    )
    assert start == datetime.date(2026, 3, 1)
    assert end   == datetime.date(2026, 3, 31)


def test_resolve_window_end_before_start_raises():
    """end < start raises ValueError."""
    cfg = {"default_start": "2026-01-01"}
    with pytest.raises(ValueError, match="end date"):
        generator.resolve_window(
            start=datetime.date(2026, 6, 1),
            end=datetime.date(2026, 1, 1),
            config=cfg,
        )


# ---------------------------------------------------------------------------
# T-8: closed.background_color emitted in style block
# ---------------------------------------------------------------------------

def test_closed_background_color_in_style():
    cfg = _cfg(closed={"background_color": "#EEEEEE"})
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "closed {" in out
    assert "BackGroundColor #EEEEEE" in out


# ---------------------------------------------------------------------------
# T-9: creole italic title
# ---------------------------------------------------------------------------

def test_creole_title_italic():
    result = generator._creole_title("Hello", {"style": "italic"})
    assert result == "<i>Hello</i>"


def test_creole_title_italic_in_puml(monkeypatch):
    """Italic title font spec → <i>…</i> in generated puml."""
    import copy
    cfg = copy.deepcopy(_cfg())
    cfg["fonts"]["title"] = {"name": None, "size": None, "style": "italic", "color": None}
    out = generator.generate_puml(
        _items_one_task(), cfg,
        project_start=datetime.date(2026, 1, 1),
        title="My Title",
    )
    assert "<i>My Title</i>" in out


# ---------------------------------------------------------------------------
# T-10: FontName / FontColor emitted when fonts.task.name / color set
# ---------------------------------------------------------------------------

def test_font_name_emitted():
    import copy
    cfg = copy.deepcopy(_cfg())
    cfg["fonts"]["task"] = {"name": "Roboto", "size": None, "style": None, "color": None}
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "FontName Roboto" in out


def test_font_color_emitted():
    import copy
    cfg = copy.deepcopy(_cfg())
    cfg["fonts"]["task"] = {"name": None, "size": None, "style": None, "color": "#123456"}
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "FontColor #123456" in out


# ---------------------------------------------------------------------------
# S-8 / T-7: one-day nudge when a bar clamps to zero duration
# ---------------------------------------------------------------------------

def test_bar_clamped_zero_duration_nudged():
    """A task where clamp produces disp_start == disp_end gets a one-day nudge."""
    # Task runs 2025-12-01 – 2026-01-31; clip window starts 2026-01-31.
    # After clamping: disp_start = disp_end = 2026-01-31 → nudge to 2026-02-01.
    items = _items_one_task(start="2025-12-01", end="2026-01-31")
    out = generator.generate_puml(
        items, _cfg(),
        project_start=datetime.date(2026, 1, 31),
        project_end=datetime.date(2026, 12, 31),
    )
    assert "starts 2026-01-31 and ends 2026-02-01" in out


# ---------------------------------------------------------------------------
# M-8: generate_puml with project_start=None and default_start None → today
# ---------------------------------------------------------------------------

def test_generate_puml_no_start_falls_back_to_today(monkeypatch):
    """project_start=None, default_start=None → falls back to today."""
    _FixedDate._fixed = datetime.date(2026, 6, 15)
    monkeypatch.setattr(generator.datetime, "date", _FixedDate)
    import copy
    cfg = copy.deepcopy(_cfg())
    cfg["default_start"] = None
    items = _items_one_task(start="2026-06-01", end="2026-08-31")
    out = generator.generate_puml(items, cfg, project_start=None)
    assert "Project starts 2026-06-15" in out


# ---------------------------------------------------------------------------
# M-9: theme_adapter main_font_size "14pt" parsed, "bad" hits exception path
# ---------------------------------------------------------------------------

def test_theme_adapter_main_font_size_pt_string():
    """main_font_size '14pt' → task font size 14 (int)."""
    from doxtr_roadmap.theme_adapter import _read_theme_core
    from unittest.mock import MagicMock
    config = MagicMock()
    config.doxtr_semantic_palette = {}
    config.doxtr_globals = {"light": {"main_font_size": "14pt"}}
    partial = _read_theme_core(config)
    assert partial["fonts"]["task"]["size"] == 14


def test_theme_adapter_main_font_size_bad_string():
    """main_font_size 'bad' → no size key emitted (exception silently swallowed)."""
    from doxtr_roadmap.theme_adapter import _read_theme_core
    from unittest.mock import MagicMock
    config = MagicMock()
    config.doxtr_semantic_palette = {}
    config.doxtr_globals = {"light": {"main_font_size": "bad"}}
    partial = _read_theme_core(config)
    # size should not be set when value cannot be parsed
    assert partial["fonts"]["task"].get("size") is None


def test_theme_adapter_attr_fallback():
    """_attr fallback path: config value is None → default used."""
    from doxtr_roadmap.theme_adapter import get_effective_style
    from unittest.mock import MagicMock
    config = MagicMock()
    config.extensions = []
    config.doxtr_roadmap_use_theme_core = False
    # All roadmap config values return None → defaults kick in
    for attr in [
        "doxtr_roadmap_default_scale", "doxtr_roadmap_scale_factor",
        "doxtr_roadmap_default_start", "doxtr_roadmap_default_title",
        "doxtr_roadmap_clean_style", "doxtr_roadmap_close_weekends_on_single_period",
        "doxtr_roadmap_bar", "doxtr_roadmap_sections", "doxtr_roadmap_today",
        "doxtr_roadmap_fonts", "doxtr_roadmap_closed",
        "doxtr_roadmap_allowed_tags", "doxtr_roadmap_allowed_tag_patterns",
        "doxtr_roadmap_collision_detection", "doxtr_roadmap_collision_char_width_factor",
        "doxtr_roadmap_collision_gap_days",
    ]:
        setattr(config, attr, None)
    style = get_effective_style(config)
    from doxtr_roadmap.config_defaults import DEFAULT_CONFIG
    assert style["default_scale"] == DEFAULT_CONFIG["default_scale"]
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]


# ---------------------------------------------------------------------------
# PlantUML label escaping / pid sanitization
# ---------------------------------------------------------------------------

def test_sanitize_plantuml_pid_replaces_brackets_in_name():
    """Square brackets in a task name become parentheses."""
    assert generator._sanitize_plantuml_pid("Task [WIP]") == "Task (WIP)"
    assert generator._sanitize_plantuml_pid("[a][b]") == "(a)(b)"


def test_sanitize_plantuml_pid_replaces_brackets_in_pid():
    """The same sanitizer is used for pids (identifier collision safety)."""
    assert generator._sanitize_plantuml_pid("pid[1]") == "pid(1)"


def test_sanitize_plantuml_pid_leaves_other_chars_untouched():
    """Non-bracket characters (& ' spaces parentheses) are preserved."""
    raw = "A & B's (note) ~ x"
    assert generator._sanitize_plantuml_pid(raw) == raw


@pytest.mark.parametrize(
    "raw, entity",
    [
        ("&", "&#38;"),
        ("<", "&#60;"),
        (">", "&#62;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("'", "&#39;"),
        ("~", "&#126;"),
        ('"', "&#34;"),
    ],
)
def test_escape_plantuml_link_label_structural_chars(raw, entity):
    """Each structural character is escaped to its HTML entity."""
    assert generator._escape_plantuml_link_label(raw) == entity


def test_escape_plantuml_link_label_ampersand_first_no_double_encoding():
    """`&` is escaped first so entity `&#NN;` sequences are not re-escaped."""
    # A bare '<' would become '&#60;'. If '&' were escaped after '<', the
    # leading '&' of '&#60;' would be re-encoded to '&#38;#60;'. Escaping
    # '&' first prevents that.
    assert generator._escape_plantuml_link_label("<") == "&#60;"
    # Combined input: the only '&' entity introducers present after the fact
    # come from our own replacements and must not be double-encoded.
    result = generator._escape_plantuml_link_label("a<b>c")
    assert result == "a&#60;b&#62;c"
    assert "&#38;#" not in result


def test_escape_plantuml_link_label_creole_digraph_only_when_paired():
    """Creole digraphs are escaped only when a pair is present."""
    # Lone digraph → NOT escaped (renders literally in PlantUML).
    assert generator._escape_plantuml_link_label("a // b") == "a // b"
    assert generator._escape_plantuml_link_label("a--b") == "a--b"
    # Paired digraph → escaped.
    assert generator._escape_plantuml_link_label("//x//") == "&#47;&#47;x&#47;&#47;"
    assert generator._escape_plantuml_link_label("**x**") == "&#42;&#42;x&#42;&#42;"
    assert generator._escape_plantuml_link_label("__x__") == "&#95;&#95;x&#95;&#95;"
    assert generator._escape_plantuml_link_label("--x--") == "&#45;&#45;x&#45;&#45;"


def test_escape_plantuml_link_label_plain_text_unchanged():
    """A label with no special characters is returned verbatim."""
    assert generator._escape_plantuml_link_label("Simple Title") == "Simple Title"


# ---------------------------------------------------------------------------
# Escaping / sanitization — end-to-end through generate_puml
# ---------------------------------------------------------------------------

def test_generate_puml_sanitizes_bracketed_task_name():
    """A task name with brackets is sanitized in both the decl and the pid.

    Drives the ``safe_name``/``safe_pid`` wiring through generate_puml so the
    render loop is covered, not just the unit helper.
    """
    items = _items_one_task(name="Task [WIP]", start="2026-02-01",
                            end="2026-04-30")
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1)
    )
    # Both the display name and the pid are sanitized: '[' -> '(', ']' -> ')'.
    assert "[Task (WIP)] as [Task (WIP)]" in out
    # The percent-complete line references the sanitized pid.
    assert "[Task (WIP)] is " in out
    # The raw bracketed form never leaks into the output.
    assert "[Task [WIP]]" not in out


def test_generate_puml_escapes_link_title_special_chars():
    """A resolved link title with special chars is entity-escaped in output."""
    def resolver(cell):
        return ("https://example.com", "A & B <x>")

    items = _items_one_task(link=":xlink:`some-id`")
    out = generator.generate_puml(
        items, _cfg(), project_start=datetime.date(2026, 1, 1),
        link_resolver=resolver
    )
    assert "links to [[https://example.com A &#38; B &#60;x&#62;]]" in out


def test_escape_plantuml_link_label_odd_run_left_literal():
    """An odd digraph run counts as one occurrence and is left literal.

    Pins the non-overlapping ``str.count(...) >= 2`` decision so a lone
    (unpaired) digraph is rendered verbatim.
    """
    assert generator._escape_plantuml_link_label("a---b") == "a---b"


def test_escape_plantuml_link_label_empty_string():
    """Empty input escapes to empty output."""
    assert generator._escape_plantuml_link_label("") == ""


# ---------------------------------------------------------------------------
# Renderer seam — doxtr_roadmap_renderer replaces the built-in generator
# ---------------------------------------------------------------------------

def _custom_renderer(**kwargs):  # pragma: no cover - resolved via dotted path
    """A stand-in renderer used to prove the seam calls a custom callable."""
    return "@startgantt\nCUSTOM RENDERER\n@endgantt"


def test_resolve_renderer_default_is_generate_puml():
    """A falsy renderer config resolves to the built-in generate_puml."""
    from doxtr_roadmap import directive
    assert directive._resolve_renderer(None) is generator.generate_puml
    assert directive._resolve_renderer("") is generator.generate_puml


def test_resolve_renderer_dotted_path_loads_named_callable():
    """A dotted path resolves to the built-in generator by its own path.

    Uses the extension's own ``generator.generate_puml`` as the target so the
    resolved object is compared against a single, stable module instance
    (avoiding pytest's dual-import of the test module under ``tests.*``).
    """
    from doxtr_roadmap import directive
    resolved = directive._resolve_renderer(
        "doxtr_roadmap.generator.generate_puml"
    )
    assert resolved is generator.generate_puml
    # Colon form resolves identically.
    assert directive._resolve_renderer(
        "doxtr_roadmap.generator:generate_puml"
    ) is generator.generate_puml


def test_resolve_renderer_dotted_path_loads_custom_callable():
    """A dotted path to a custom renderer resolves and is callable.

    Compared by ``__name__`` + behaviour rather than object identity because
    pytest may import this test module under a different fully-qualified name
    than the one used in the dotted path.
    """
    from doxtr_roadmap import directive
    resolved = directive._resolve_renderer(
        "tests.test_generator._custom_renderer"
    )
    assert callable(resolved)
    assert resolved.__name__ == "_custom_renderer"
    # The resolved renderer accepts the generate_puml keyword signature.
    out = resolved(
        items=_items_one_task(), config=_cfg(),
        project_start=datetime.date(2026, 1, 1),
    )
    assert "CUSTOM RENDERER" in out


# ---------------------------------------------------------------------------
# Per-task colour resolution (color_resolver seam)
# ---------------------------------------------------------------------------

from doxtr_roadmap.csv_parser import TaskItem


def _color_items(color, section="Sec", name="Task A"):
    """One TaskItem carrying a colour expression."""
    return [(section, [TaskItem(
        name=name, start="2026-02-01", end="2026-04-30",
        link="", tags="", is_subtask=False, row_group=None, pid=name,
        color=color,
    )])]


def _fake_resolver(expr, default_done, default_frame):
    """Deterministic stand-in for ColorResolver.resolve (no theme-core)."""
    mapping = {
        "dd:primary": ("#3366CC", "#7094DB"),
        "#123456": ("#123456", "#597189"),
    }
    if expr in mapping:
        return mapping[expr]
    return default_done, default_frame


def test_task_color_overrides_section_done():
    out = generator.generate_puml(
        _color_items("dd:primary"), _cfg(),
        color_resolver=_fake_resolver,
    )
    # done/frame clause from the resolver, not the section default #FF8C00.
    assert "is colored in #3366CC/#7094DB" in out
    assert "#FF8C00" not in out


def test_task_color_hex_with_frame():
    out = generator.generate_puml(
        _color_items("#123456"), _cfg(),
        color_resolver=_fake_resolver,
    )
    assert "is colored in #123456/#597189" in out


def test_task_color_none_uses_section_default():
    out = generator.generate_puml(
        _color_items(None), _cfg(),
        color_resolver=_fake_resolver,
    )
    assert "is colored in #FF8C00" in out


def test_task_color_ignored_without_resolver():
    """Without a resolver, per-task colour is ignored (section default used)."""
    out = generator.generate_puml(_color_items("dd:primary"), _cfg())
    assert "is colored in #FF8C00" in out


def test_task_color_applies_to_milestone():
    items = [("Sec", [TaskItem(
        name="MS", start="2026-02-01", end="2026-02-01",
        link="", tags="", is_subtask=False, row_group=None, pid="MS",
        color="dd:primary",
    )])]
    out = generator.generate_puml(items, _cfg(), color_resolver=_fake_resolver)
    assert "[MS] is colored in #3366CC/#7094DB" in out


def test_legacy_tuple_without_color_still_works():
    """8-element legacy tuples (no colour field) render with section colour."""
    items = _items_one_task()  # 8-tuple form
    out = generator.generate_puml(items, _cfg(), color_resolver=_fake_resolver)
    assert "is colored in #FF8C00" in out


# ---------------------------------------------------------------------------
# _renderer_accepts + colour-engine seam (directive helpers)
# ---------------------------------------------------------------------------

def test_renderer_accepts_explicit_param():
    from doxtr_roadmap import directive
    def r(items, config, color_resolver=None):  # noqa: ANN001
        return ""
    assert directive._renderer_accepts(r, "color_resolver") is True


def test_renderer_accepts_var_keyword():
    from doxtr_roadmap import directive
    def r(**kwargs):
        return ""
    assert directive._renderer_accepts(r, "color_resolver") is True


def test_renderer_accepts_missing_param():
    from doxtr_roadmap import directive
    def r(items, config):  # no color_resolver, no **kwargs
        return ""
    assert directive._renderer_accepts(r, "color_resolver") is False


def test_renderer_accepts_uninspectable_is_false():
    from doxtr_roadmap import directive
    # A builtin whose signature cannot be introspected → conservative False.
    assert directive._renderer_accepts(len, "color_resolver") is False


def test_build_color_resolver_default_uses_builtin():
    """No dotted path → built-in ColorResolver.from_config().resolve callable."""
    from doxtr_roadmap import directive
    from unittest.mock import MagicMock
    cfg = MagicMock()
    cfg.extensions = []
    cfg.doxtr_semantic_palette = {}
    resolver = directive._build_color_resolver(None, cfg, 30)
    assert callable(resolver)
    # Behaves like ColorResolver.resolve: None expr → defaults unchanged.
    assert resolver(None, "#FF8C00", "#AABBCC") == ("#FF8C00", "#AABBCC")


def _seam_factory(config, frame_delta):
    """A custom colour-engine factory for the seam test."""
    def _resolve(expr, default_done, default_frame):
        if expr == "brand":
            return "#0A0B0C", "#111213"
        return default_done, default_frame
    return _resolve


def test_build_color_resolver_custom_factory():
    """A dotted path resolves to a custom factory and returns its callable."""
    from doxtr_roadmap import directive
    from unittest.mock import MagicMock
    resolver = directive._build_color_resolver(
        "tests.test_generator._seam_factory", MagicMock(), 30
    )
    assert resolver("brand", "#FF8C00", None) == ("#0A0B0C", "#111213")
    assert resolver("other", "#FF8C00", "#DEF") == ("#FF8C00", "#DEF")


def test_task_color_inside_row_group_resolves():
    """A coloured task inside a row_group still gets its resolved colour."""
    items = [("Sec", [
        TaskItem(name="T1", start="2026-01-01", end="2026-03-31",
                 link="", tags="", is_subtask=False, row_group="grp",
                 pid="T1", color="dd:primary"),
        TaskItem(name="T2", start="2026-04-01", end="2026-06-30",
                 link="", tags="", is_subtask=False, row_group="grp",
                 pid="T2", color="#123456"),
    ])]
    out = generator.generate_puml(items, _cfg(), color_resolver=_fake_resolver)
    assert "[T1] as [T1] starts" in out
    assert "is colored in #3366CC/#7094DB" in out   # T1 dd:primary
    assert "is colored in #123456/#597189" in out   # T2 hex
