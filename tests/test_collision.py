"""Unit tests for the collision-detection helpers and integration.

All tests are pure / hermetic — no PlantUML subprocess calls, no Sphinx
application.  They exercise:

- _estimate_label_days      (scale / length / char_width_factor)
- _bar_extent               (right edge computation, milestone handling)
- _pack_lanes               (greedy first-fit lane assignment)
- generate_puml integration (collision_detection True vs False, regression)
"""

import copy
import datetime
import pytest

from doxtr_roadmap import generator
from doxtr_roadmap import csv_parser
from doxtr_roadmap.config_defaults import DEFAULT_CONFIG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _d(iso: str) -> datetime.date:
    return datetime.date.fromisoformat(iso)


def _cfg(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["default_start"] = "2026-01-01"
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


def _member(pid, name, disp_start, disp_end, is_milestone=False):
    return {
        "pid": pid,
        "name": name,
        "disp_start": _d(disp_start),
        "disp_end": _d(disp_end),
        "is_milestone": is_milestone,
    }


# ---------------------------------------------------------------------------
# _estimate_label_days
# ---------------------------------------------------------------------------

class TestEstimateLabelDays:
    def test_scales_with_name_length(self):
        short = generator._estimate_label_days("A", "monthly", 1.0)
        long_ = generator._estimate_label_days("A" * 20, "monthly", 1.0)
        assert long_ > short

    def test_monthly_greater_than_weekly_for_same_name(self):
        m = generator._estimate_label_days("Task Name", "monthly", 1.0)
        w = generator._estimate_label_days("Task Name", "weekly", 1.0)
        d = generator._estimate_label_days("Task Name", "daily", 1.0)
        assert m > w > d

    def test_char_width_factor_scales_linearly(self):
        base = generator._estimate_label_days("Hello", "monthly", 1.0)
        double = generator._estimate_label_days("Hello", "monthly", 2.0)
        assert abs(double - 2 * base) < 0.001

    def test_minimum_enforced_for_short_name(self):
        # A single char at daily scale = 1.1 days, but minimum is 4.0
        result = generator._estimate_label_days("A", "daily", 1.0)
        assert result == generator._LABEL_MIN_DAYS

    def test_unknown_scale_treated_as_monthly(self):
        m = generator._estimate_label_days("X", "monthly", 1.0)
        u = generator._estimate_label_days("X", "unknown_scale", 1.0)
        assert m == u

    def test_empty_name_returns_minimum(self):
        result = generator._estimate_label_days("", "monthly", 1.0)
        assert result == generator._LABEL_MIN_DAYS

    def test_daily_base_is_approx_1_1(self):
        # Long enough name that minimum doesn't dominate
        name = "A" * 10
        result = generator._estimate_label_days(name, "daily", 1.0)
        expected = 10 * 1.1
        assert abs(result - expected) < 0.01

    def test_weekly_base_is_4(self):
        name = "A" * 10
        result = generator._estimate_label_days(name, "weekly", 1.0)
        assert abs(result - 40.0) < 0.01

    def test_monthly_base_is_9(self):
        name = "A" * 10
        result = generator._estimate_label_days(name, "monthly", 1.0)
        assert abs(result - 90.0) < 0.01

    # --- zoom ---------------------------------------------------------------
    def test_zoom_divides_footprint(self):
        # zoom=2 halves the day-footprint relative to zoom=1 (name long
        # enough that the _LABEL_MIN_DAYS floor does not dominate either).
        name = "A" * 10
        base = generator._estimate_label_days(name, "monthly", 1.0, 1.0)
        zoomed = generator._estimate_label_days(name, "monthly", 1.0, 2.0)
        assert abs(zoomed - base / 2) < 0.001

    def test_zoom_default_matches_explicit_one(self):
        # Omitting zoom must equal passing zoom=1.0 exactly (no behaviour
        # change for existing callers).
        name = "Some Task"
        assert (
            generator._estimate_label_days(name, "monthly", 1.0)
            == generator._estimate_label_days(name, "monthly", 1.0, 1.0)
        )

    def test_zoom_respects_minimum_floor(self):
        # Even with a large zoom shrinking the footprint, the minimum floor
        # still applies.
        result = generator._estimate_label_days("A" * 10, "monthly", 1.0, 1000.0)
        assert result == generator._LABEL_MIN_DAYS

    def test_non_positive_zoom_treated_as_one(self):
        base = generator._estimate_label_days("A" * 10, "monthly", 1.0, 1.0)
        assert generator._estimate_label_days("A" * 10, "monthly", 1.0, 0.0) == base
        assert generator._estimate_label_days("A" * 10, "monthly", 1.0, -3.0) == base

    def test_nan_zoom_treated_as_one(self):
        # NaN slips past a plain `zoom <= 0` guard (nan <= 0 is False); the
        # `math.isfinite` guard must catch it and fall back to zoom=1.
        base = generator._estimate_label_days("A" * 10, "monthly", 1.0, 1.0)
        assert (
            generator._estimate_label_days("A" * 10, "monthly", 1.0, float("nan"))
            == base
        )

    def test_inf_zoom_treated_as_one(self):
        # inf also slips past `zoom <= 0` (inf <= 0 is False) and would
        # collapse the footprint to 0; the guard must fall back to zoom=1.
        base = generator._estimate_label_days("A" * 10, "monthly", 1.0, 1.0)
        assert (
            generator._estimate_label_days("A" * 10, "monthly", 1.0, float("inf"))
            == base
        )


# ---------------------------------------------------------------------------
# _bar_extent
# ---------------------------------------------------------------------------

class TestBarExtent:
    def test_right_edge_is_max_of_end_or_label_end_plus_gap(self):
        # Bar much longer than its label → right edge driven by disp_end
        start = _d("2026-01-01")
        end = _d("2026-06-30")  # ~180 days >> label
        left, right = generator._bar_extent(start, end, "A", False, "monthly", 1.0, 2)
        assert left == start
        # right = max(Jun30, Jan1+9days) + 2 = Jun30 + 2
        assert right == end + datetime.timedelta(days=2)

    def test_right_edge_driven_by_label_when_bar_is_short(self):
        # 1-day bar for a long name → label overruns past bar end
        start = _d("2026-01-01")
        end = _d("2026-01-02")
        name = "Very Long Task Name Here"
        label_days = generator._estimate_label_days(name, "monthly", 1.0)
        left, right = generator._bar_extent(start, end, name, False, "monthly", 1.0, 2)
        import math
        expected_right = start + datetime.timedelta(days=math.ceil(label_days) + 2)
        assert right == expected_right

    def test_gap_is_added(self):
        start = _d("2026-01-01")
        end = _d("2026-03-31")
        _, right0 = generator._bar_extent(start, end, "A", False, "monthly", 1.0, 0)
        _, right2 = generator._bar_extent(start, end, "A", False, "monthly", 1.0, 2)
        assert (right2 - right0).days == 2

    def test_milestone_extent_starts_at_date_and_spans_label(self):
        start = _d("2026-03-15")
        end = _d("2026-03-15")  # milestone
        left, right = generator._bar_extent(start, end, "M1", True, "monthly", 1.0, 2)
        assert left == start
        # label for "M1" = max(2 * 9, 4) = 18 days; right = start + 18 + 2
        import math
        label_days = generator._estimate_label_days("M1", "monthly", 1.0)
        expected = start + datetime.timedelta(days=math.ceil(label_days) + 2)
        assert right == expected

    def test_milestone_right_not_driven_by_bar_end(self):
        # For a milestone disp_end == disp_start; _bar_extent must NOT use disp_end
        # to extend the right edge (since it equals disp_start — no bar width).
        start = end = _d("2026-06-01")
        left_m, right_m = generator._bar_extent(start, end, "M", True, "monthly", 1.0, 0)
        left_r, right_r = generator._bar_extent(start, end, "M", False, "monthly", 1.0, 0)
        # Both paths should produce the same result for a zero-width bar
        assert left_m == left_r
        assert right_m == right_r

    def test_char_width_factor_widens_extent(self):
        start = _d("2026-01-01")
        end = _d("2026-01-02")
        _, right1 = generator._bar_extent(start, end, "Hello", False, "monthly", 1.0, 0)
        _, right2 = generator._bar_extent(start, end, "Hello", False, "monthly", 2.0, 0)
        assert right2 > right1

    def test_zoom_shrinks_right_edge(self):
        # A short bar whose right edge is label-driven: a higher zoom shrinks
        # the label's day-footprint, so the right edge moves left.
        start = _d("2026-01-01")
        end = _d("2026-01-02")
        name = "Very Long Task Name Here"
        _, right1 = generator._bar_extent(start, end, name, False, "monthly", 1.0, 0, 1.0)
        _, right2 = generator._bar_extent(start, end, name, False, "monthly", 1.0, 0, 2.0)
        assert right2 < right1


# ---------------------------------------------------------------------------
# _pack_lanes
# ---------------------------------------------------------------------------

class TestPackLanes:
    def test_two_fully_overlapping_tasks_give_two_lanes(self):
        members = [
            _member("A", "Task", "2026-01-01", "2026-06-30"),
            _member("B", "Task", "2026-01-01", "2026-06-30"),
        ]
        lanes = generator._pack_lanes(members, "monthly", 1.0, 2)
        assert len(lanes) == 2
        assert lanes[0][0]["pid"] == "A"
        assert lanes[1][0]["pid"] == "B"

    def test_two_well_separated_tasks_give_one_lane(self):
        # At monthly scale: "A" label = max(1*9, 4) = 9 days + 2 gap = 11 days right buffer.
        # A ends 2026-03-31; right extent = 2026-04-11.
        # B starts 2026-05-01 > 2026-04-11 → no collision.
        members = [
            _member("A", "A", "2026-01-01", "2026-03-31"),
            _member("B", "B", "2026-05-01", "2026-07-31"),
        ]
        lanes = generator._pack_lanes(members, "monthly", 1.0, 2)
        assert len(lanes) == 1
        assert len(lanes[0]) == 2
        assert lanes[0][0]["pid"] == "A"
        assert lanes[0][1]["pid"] == "B"

    def test_three_tasks_where_first_and_second_collide_but_third_fits_after_first(self):
        # T1: A, Jan-Jun. T2: B, Mar-May (collides with T1). T3: C, Aug-Oct (fits after T1).
        # Expected: lanes[0]=[T1, T3], lanes[1]=[T2]
        members = [
            _member("T1", "A", "2026-01-01", "2026-06-30"),
            _member("T2", "B", "2026-03-01", "2026-05-31"),
            _member("T3", "C", "2026-08-01", "2026-10-31"),
        ]
        lanes = generator._pack_lanes(members, "monthly", 1.0, 2)
        assert len(lanes) == 2
        # Lane 0: T1 and T3
        assert lanes[0][0]["pid"] == "T1"
        assert lanes[0][1]["pid"] == "T3"
        # Lane 1: T2
        assert lanes[1][0]["pid"] == "T2"

    def test_single_member_gives_one_lane_with_one_member(self):
        members = [_member("X", "Task X", "2026-01-01", "2026-03-31")]
        lanes = generator._pack_lanes(members, "monthly", 1.0, 2)
        assert len(lanes) == 1
        assert len(lanes[0]) == 1
        assert lanes[0][0]["pid"] == "X"

    def test_milestone_collision(self):
        # Two milestones on the same date → second gets new lane
        members = [
            _member("M1", "Milestone A", "2026-06-01", "2026-06-01", is_milestone=True),
            _member("M2", "Milestone B", "2026-06-01", "2026-06-01", is_milestone=True),
        ]
        lanes = generator._pack_lanes(members, "monthly", 1.0, 2)
        assert len(lanes) == 2

    def test_high_char_width_factor_forces_split_on_adjacent_tasks(self):
        # Adjacent tasks that wouldn't collide at factor=1.0 collide at factor=10.0
        members = [
            _member("A", "A", "2026-01-01", "2026-03-31"),
            _member("B", "B", "2026-04-01", "2026-06-30"),
        ]
        lanes_normal = generator._pack_lanes(members, "monthly", 1.0, 2)
        lanes_wide = generator._pack_lanes(members, "monthly", 10.0, 2)
        # At factor=10: "A" label = max(1*9*10, 4) = 90 days; right = Mar31 + 90 + 2 = Jul1
        # B starts Apr1 < Jul1 → collision → 2 lanes
        assert len(lanes_wide) == 2
        # Normal factor should still collide for adjacent months (see calculation below),
        # but the point is wide factor definitely splits; normal may or may not.
        # The test is that wide > normal in number of lanes or equal.
        assert len(lanes_wide) >= len(lanes_normal)

    def test_empty_members_returns_empty(self):
        lanes = generator._pack_lanes([], "monthly", 1.0, 2)
        assert lanes == []

    def test_zoom_packs_group_that_splits_at_zoom_one(self):
        # A group whose long labels collide (and split into extra lanes) at
        # zoom=1 packs onto fewer lanes at a higher zoom, because zoom shrinks
        # each label's day-footprint.
        members = [
            _member("A", "A" * 10, "2026-01-01", "2026-01-10"),
            _member("B", "B" * 10, "2026-04-01", "2026-04-10"),
        ]
        lanes_zoom1 = generator._pack_lanes(members, "monthly", 1.0, 2, 1.0)
        lanes_zoom8 = generator._pack_lanes(members, "monthly", 1.0, 2, 8.0)
        assert len(lanes_zoom1) == 2
        assert len(lanes_zoom8) < len(lanes_zoom1)
        assert len(lanes_zoom8) == 1

    def test_zoom_default_matches_explicit_one(self):
        # Default zoom must reproduce the zoom=1.0 lane assignment exactly.
        members = [
            _member("A", "A" * 10, "2026-01-01", "2026-01-10"),
            _member("B", "B" * 10, "2026-04-01", "2026-04-10"),
        ]
        default = generator._pack_lanes(members, "monthly", 1.0, 2)
        explicit = generator._pack_lanes(members, "monthly", 1.0, 2, 1.0)
        assert [
            [m["pid"] for m in lane] for lane in default
        ] == [
            [m["pid"] for m in lane] for lane in explicit
        ]

    def test_milestone_group_packs_under_zoom(self):
        # Milestones have zero bar width, so their extent is purely
        # label-driven — zoom has a proportionally large effect. Two
        # long-labelled milestones that collide (2 lanes) at zoom=1 pack
        # onto a single lane at high zoom.
        members = [
            _member("M1", "M" * 12, "2026-01-15", "2026-01-15", is_milestone=True),
            _member("M2", "N" * 12, "2026-04-15", "2026-04-15", is_milestone=True),
        ]
        lanes_zoom1 = generator._pack_lanes(members, "monthly", 1.0, 2, 1.0)
        lanes_zoom8 = generator._pack_lanes(members, "monthly", 1.0, 2, 8.0)
        assert len(lanes_zoom1) == 2
        assert len(lanes_zoom8) == 1


# ---------------------------------------------------------------------------
# Generator integration: generate_puml with collision_detection
# ---------------------------------------------------------------------------

def _items_overlapping_group():
    """Two tasks in the same group with fully overlapping dates."""
    return [("Sec", [
        ("Task A", "2026-01-01", "2026-06-30", "", "", False, "grp", "Task A"),
        ("Task B", "2026-01-01", "2026-06-30", "", "", False, "grp", "Task B"),
    ])]


def _items_noncolliding_group():
    """Two single-char-named tasks, far enough apart to share a lane."""
    return [("Sec", [
        ("A", "2026-01-01", "2026-03-31", "", "", False, "grp", "A"),
        ("B", "2026-05-01", "2026-07-31", "", "", False, "grp", "B"),
    ])]


class TestGeneratePumlIntegration:
    def test_overlapping_with_detection_on_does_not_emit_same_row(self):
        out = generator.generate_puml(
            _items_overlapping_group(),
            _cfg(collision_detection=True),
            project_start=_d("2026-01-01"),
        )
        # The two tasks are on separate lanes → NO displays on same row as
        assert "[Task B] displays on same row as [Task A]" not in out

    def test_overlapping_with_detection_off_emits_same_row(self):
        out = generator.generate_puml(
            _items_overlapping_group(),
            _cfg(collision_detection=False),
            project_start=_d("2026-01-01"),
        )
        # Old behaviour: forced onto same row
        assert "[Task B] displays on same row as [Task A]" in out

    def test_noncolliding_group_shares_row_regardless_of_detection(self):
        """Non-colliding tasks share a row with detection ON (no regression)."""
        out = generator.generate_puml(
            _items_noncolliding_group(),
            _cfg(collision_detection=True),
            project_start=_d("2026-01-01"),
        )
        assert "[B] displays on same row as [A]" in out

    def test_noncolliding_group_same_output_detection_on_vs_off(self):
        """Non-colliding group produces identical same-row output in both modes."""
        on = generator.generate_puml(
            _items_noncolliding_group(),
            _cfg(collision_detection=True),
            project_start=_d("2026-01-01"),
        )
        off = generator.generate_puml(
            _items_noncolliding_group(),
            _cfg(collision_detection=False),
            project_start=_d("2026-01-01"),
        )
        assert ("[B] displays on same row as [A]" in on)
        assert ("[B] displays on same row as [A]" in off)

    def test_single_member_group_emits_no_directive(self):
        items = [("Sec", [
            ("Solo", "2026-01-01", "2026-06-30", "", "", False, "grp", "Solo"),
        ])]
        out = generator.generate_puml(
            items, _cfg(), project_start=_d("2026-01-01")
        )
        assert "displays on same row as" not in out

    def test_detection_default_is_true(self):
        """DEFAULT_CONFIG must have collision_detection=True."""
        assert DEFAULT_CONFIG["collision_detection"] is True
        assert DEFAULT_CONFIG["collision_char_width_factor"] == 1.0
        assert DEFAULT_CONFIG["collision_gap_days"] == 2

    def test_char_width_factor_affects_splitting(self):
        """Higher char_width_factor makes adjacent tasks split sooner."""
        # Use a SHORT bar so the label overruns it and factor makes a difference.
        # A: Jan1–Jan10 (short bar, label dominates).
        # factor=1: label=max(1*9,4)=9d, right=max(Jan10,Jan1+9=Jan10)+2=Jan12
        #   B starts Jan13 > Jan12 → no collision → same row.
        # factor=5: label=max(1*9*5,4)=45d, right=max(Jan10,Jan1+45=Feb15)+2=Feb17
        #   B starts Jan13 < Feb17 → collision → split.
        items = [("Sec", [
            ("A", "2026-01-01", "2026-01-10", "", "", False, "grp", "A"),
            ("B", "2026-01-13", "2026-04-30", "", "", False, "grp", "B"),
        ])]
        out_normal = generator.generate_puml(
            items, _cfg(collision_char_width_factor=1.0),
            project_start=_d("2026-01-01"),
        )
        out_wide = generator.generate_puml(
            items, _cfg(collision_char_width_factor=5.0),
            project_start=_d("2026-01-01"),
        )
        assert "[B] displays on same row as [A]" in out_normal
        assert "[B] displays on same row as [A]" not in out_wide

    def test_docs_factor_0_7_example_shares_row(self):
        """Regression guard for the docs 'less aggressive splitting' example.

        The chapter's Collision-detection section claims that the Import/Export
        pair splits at the default factor 1.0 but shares one row at 0.7.  This
        locks that claim so the example prose can't silently drift from the
        implementation again.
        """
        csv_text = (
            "section,name,start,end,row_group,link,tags\n"
            "Lane,Import,2027-01-01,2027-01-20,lane,,eng\n"
            "Lane,Export,2027-02-15,2027-03-06,lane,,eng\n"
        )
        items = csv_parser.load_items_from_string(csv_text)
        out_default = generator.generate_puml(
            items, _cfg(collision_char_width_factor=1.0),
            project_start=_d("2027-01-01"), scale="monthly",
        )
        out_relaxed = generator.generate_puml(
            items, _cfg(collision_char_width_factor=0.7),
            project_start=_d("2027-01-01"), scale="monthly",
        )
        # default 1.0 → split (no same-row directive)
        assert "displays on same row as" not in out_default
        # relaxed 0.7 → shared row
        assert "displays on same row as" in out_relaxed

    def test_column_zoom_relaxes_collision(self):
        """A group that splits at zoom 1 shares a row at higher column-zoom.

        Column zoom widens every column without changing the days each
        column represents, so a label covers proportionally fewer days on
        screen.  A collision detected at zoom 1 therefore disappears at a
        sufficiently high zoom.
        """
        items = [("Sec", [
            ("Long Task Name A", "2026-01-01", "2026-01-10", "", "", False, "grp", "Long Task Name A"),
            ("Long Task Name B", "2026-02-15", "2026-04-30", "", "", False, "grp", "Long Task Name B"),
        ])]
        out_zoom1 = generator.generate_puml(
            items, _cfg(column_zoom=1),
            project_start=_d("2026-01-01"), scale="monthly",
        )
        out_zoom8 = generator.generate_puml(
            items, _cfg(column_zoom=8),
            project_start=_d("2026-01-01"), scale="monthly",
        )
        # zoom 1 → collision → split (no same-row directive)
        assert "displays on same row as" not in out_zoom1
        # high zoom → labels shrink → fits on one row
        assert "displays on same row as" in out_zoom8

    def test_column_zoom_one_unchanged(self):
        """column_zoom=1 (the default) leaves collision output unchanged."""
        items = [("Sec", [
            ("Long Task Name A", "2026-01-01", "2026-01-10", "", "", False, "grp", "Long Task Name A"),
            ("Long Task Name B", "2026-02-15", "2026-04-30", "", "", False, "grp", "Long Task Name B"),
        ])]
        out_default = generator.generate_puml(
            items, _cfg(),
            project_start=_d("2026-01-01"), scale="monthly",
        )
        out_zoom1 = generator.generate_puml(
            items, _cfg(column_zoom=1),
            project_start=_d("2026-01-01"), scale="monthly",
        )
        # Both split identically; zoom 1 is a no-op for collision detection.
        assert "displays on same row as" not in out_default
        assert "displays on same row as" not in out_zoom1
