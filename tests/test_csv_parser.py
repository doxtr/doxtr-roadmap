"""Unit tests for doxtr_roadmap/csv_parser.py."""

import csv
import io
import warnings
from pathlib import Path
import pytest

from doxtr_roadmap import csv_parser


# ---------------------------------------------------------------------------
# load_items_from_string
# ---------------------------------------------------------------------------

BASIC_CSV = """\
section,name,start,end,row_group,link,tags
Alpha,Task A,2026-01-01,2026-03-31,,https://example.com,eng
Alpha,Task B,2026-04-01,2026-06-30,,,
Beta,Task C,2026-07-01,2026-09-30,,,
"""

def test_load_from_string_basic():
    items = csv_parser.load_items_from_string(BASIC_CSV)
    assert len(items) == 2
    sections = [s for s, _ in items]
    assert "Alpha" in sections
    assert "Beta" in sections
    alpha_tasks = [t for s, tasks in items if s == "Alpha" for t in tasks]
    assert len(alpha_tasks) == 2
    assert alpha_tasks[0].name == "Task A"


def test_load_from_file(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text(BASIC_CSV, encoding="utf-8")
    items = csv_parser.load_items_from_file(p)
    assert len(items) == 2


# ---------------------------------------------------------------------------
# Subtask detection
# ---------------------------------------------------------------------------

SUBTASK_CSV = """\
section,name,start,end,row_group,link,tags
Work,Parent Task,2026-01-01,2026-12-31,,,
Parent Task,Subtask 1,2026-01-01,2026-06-30,,,
Parent Task,Subtask 2,2026-07-01,2026-12-31,,,
Work,Another Task,2026-01-01,2026-12-31,,,
"""

def test_subtask_detection():
    items = csv_parser.load_items_from_string(SUBTASK_CSV)
    # Should be one section: Work
    assert len(items) == 1
    section, tasks = items[0]
    assert section == "Work"
    names = [t.name for t in tasks]
    assert "Parent Task" in names
    assert "Subtask 1" in names
    assert "Subtask 2" in names
    # Subtasks flagged correctly
    sub1 = next(t for t in tasks if t.name == "Subtask 1")
    assert sub1.is_subtask is True


def test_subtask_before_parent_warning():
    """Subtask referencing not-yet-seen parent gets warning and treated as section."""
    csv_text = """\
section,name,start,end,row_group,link,tags
Parent Task,Orphan Sub,2026-01-01,2026-06-30,,,
Work,Parent Task,2026-01-01,2026-12-31,,,
"""
    import warnings
    # Should not raise; just log a warning
    items = csv_parser.load_items_from_string(csv_text)
    assert len(items) >= 1


# ---------------------------------------------------------------------------
# Row group
# ---------------------------------------------------------------------------

ROW_GROUP_CSV = """\
section,name,start,end,row_group,link,tags
S,Task 1,2026-01-01,2026-03-31,grp,,
S,Task 2,2026-04-01,2026-06-30,grp,,
S,Task 3,2026-07-01,2026-09-30,,,
"""

def test_row_group_preserved():
    items = csv_parser.load_items_from_string(ROW_GROUP_CSV)
    _, tasks = items[0]
    t1 = next(t for t in tasks if t.name == "Task 1")
    t3 = next(t for t in tasks if t.name == "Task 3")
    assert t1.row_group == "grp"
    assert t3.row_group is None


def test_empty_row_group():
    csv_text = "section,name,start,end,row_group,link,tags\nS,T,2026-01-01,2026-03-31,,,\n"
    items = csv_parser.load_items_from_string(csv_text)
    task = items[0][1][0]
    assert task.row_group is None


# ---------------------------------------------------------------------------
# Milestone
# ---------------------------------------------------------------------------

def test_milestone_start_eq_end():
    csv_text = "section,name,start,end,row_group,link,tags\nS,M,2026-03-15,2026-03-15,,,\n"
    items = csv_parser.load_items_from_string(csv_text)
    task = items[0][1][0]
    assert task.start == "2026-03-15"
    assert task.end == "2026-03-15"


# ---------------------------------------------------------------------------
# _assign_task_ids
# ---------------------------------------------------------------------------

def test_assign_task_ids_unique():
    csv_text = """\
section,name,start,end,row_group,link,tags
S,PI27-01,2026-11-01,2027-01-31,,,
S,PI27-01,2027-02-01,2027-04-30,,,
S,Unique,2027-05-01,2027-07-31,,,
"""
    items = csv_parser.load_items_from_string(csv_text)
    pids = [t.pid for t in items[0][1]]
    assert pids[0] == "PI27-01"
    assert pids[1] == "PI27-01__2"
    assert pids[2] == "Unique"


# ---------------------------------------------------------------------------
# Section order
# ---------------------------------------------------------------------------

def test_section_order_preserved():
    csv_text = """\
section,name,start,end,row_group,link,tags
Gamma,T1,2026-01-01,2026-03-31,,,
Alpha,T2,2026-04-01,2026-06-30,,,
Beta,T3,2026-07-01,2026-09-30,,,
"""
    items = csv_parser.load_items_from_string(csv_text)
    sections = [s for s, _ in items]
    assert sections == ["Gamma", "Alpha", "Beta"]


# ---------------------------------------------------------------------------
# Link column
# ---------------------------------------------------------------------------

def test_link_column_name():
    csv_text = "section,name,start,end,row_group,link,tags\nS,T,2026-01-01,2026-03-31,,https://example.com,\n"
    items = csv_parser.load_items_from_string(csv_text)
    task = items[0][1][0]
    assert task.link == "https://example.com"


def test_xlink_column_no_longer_recognized():
    """The legacy 'xlink' column is no longer a synonym for 'link'.

    A CSV using only an 'xlink' column produces tasks with no link and emits
    no deprecation warning (the backward-compatibility shim was removed).
    """
    csv_text = (
        "section,name,start,end,row_group,xlink\n"
        "S,T,2026-01-01,2026-03-31,,:xlink:`some-id`\n"
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        items = csv_parser.load_items_from_string(csv_text)
        assert not any(
            "deprecated" in str(warning.message).lower() for warning in w
        ), "No deprecation warning should be emitted for an 'xlink' column"
    task = items[0][1][0]
    assert task.link == "", "An 'xlink' column must not populate the link field"


# ---------------------------------------------------------------------------
# Tags column
# ---------------------------------------------------------------------------

def test_tags_column_parsed():
    csv_text = "section,name,start,end,row_group,link,tags\nS,T,2026-01-01,2026-03-31,,,eng code\n"
    items = csv_parser.load_items_from_string(csv_text)
    task = items[0][1][0]
    assert task.tags == "eng code"  # raw string preserved


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_header_line_required_inline():
    with pytest.raises(ValueError, match="empty"):
        csv_parser.load_items_from_string("")


def test_empty_csv_no_data():
    """CSV with only a header returns empty sections."""
    csv_text = "section,name,start,end,row_group,link,tags\n"
    items = csv_parser.load_items_from_string(csv_text)
    assert items == []


# ---------------------------------------------------------------------------
# load_items_from_files — multi-file combining
# ---------------------------------------------------------------------------

def test_load_items_from_files_two_files_combined(tmp_path):
    """Two files are combined into a single sections list."""
    fa = tmp_path / "a.csv"
    fb = tmp_path / "b.csv"
    fa.write_text(
        "section,name,start,end\n"
        "Alpha,Task A,2026-01-01,2026-03-31\n",
        encoding="utf-8",
    )
    fb.write_text(
        "section,name,start,end\n"
        "Beta,Task B,2026-04-01,2026-06-30\n",
        encoding="utf-8",
    )
    items = csv_parser.load_items_from_files([fa, fb])
    sections = [s for s, _ in items]
    assert "Alpha" in sections
    assert "Beta" in sections
    assert len(items) == 2


def test_load_items_from_files_sections_merge_across_files(tmp_path):
    """Same section name in two files merges into one section."""
    fa = tmp_path / "a.csv"
    fb = tmp_path / "b.csv"
    fa.write_text(
        "section,name,start,end\n"
        "Work,Task A,2026-01-01,2026-03-31\n",
        encoding="utf-8",
    )
    fb.write_text(
        "section,name,start,end\n"
        "Work,Task B,2026-04-01,2026-06-30\n",
        encoding="utf-8",
    )
    items = csv_parser.load_items_from_files([fa, fb])
    # Sections with the same name must merge — only ONE "Work" section.
    sections = [s for s, _ in items]
    assert sections.count("Work") == 1
    _, tasks = items[0]
    names = [t.name for t in tasks]
    assert "Task A" in names
    assert "Task B" in names


def test_load_items_from_files_cross_file_subtask(tmp_path):
    """A subtask in file B can reference a parent task defined in file A."""
    fa = tmp_path / "a.csv"
    fb = tmp_path / "b.csv"
    fa.write_text(
        "section,name,start,end\n"
        "Work,Parent Task,2027-01-01,2027-03-31\n",
        encoding="utf-8",
    )
    fb.write_text(
        "section,name,start,end\n"
        "Parent Task,Cross-file Sub,2027-01-15,2027-02-28\n",
        encoding="utf-8",
    )
    items = csv_parser.load_items_from_files([fa, fb])
    # Should be one section: Work
    assert len(items) == 1
    section, tasks = items[0]
    assert section == "Work"
    names = [t.name for t in tasks]
    assert "Parent Task" in names
    assert "Cross-file Sub" in names
    subtask = next(t for t in tasks if t.name == "Cross-file Sub")
    assert subtask.is_subtask is True


def test_load_items_from_files_order_preserved(tmp_path):
    """Files are read in the given order; task order within and across files is stable."""
    fa = tmp_path / "first.csv"
    fb = tmp_path / "second.csv"
    fa.write_text(
        "section,name,start,end\n"
        "S,First File Task,2027-01-01,2027-01-31\n",
        encoding="utf-8",
    )
    fb.write_text(
        "section,name,start,end\n"
        "S,Second File Task,2027-02-01,2027-02-28\n",
        encoding="utf-8",
    )
    # Order: [fa, fb] => First File Task before Second File Task
    items_ab = csv_parser.load_items_from_files([fa, fb])
    _, tasks_ab = items_ab[0]
    names_ab = [t.name for t in tasks_ab]
    assert names_ab.index("First File Task") < names_ab.index("Second File Task")

    # Reverse order => Second File Task comes first
    items_ba = csv_parser.load_items_from_files([fb, fa])
    _, tasks_ba = items_ba[0]
    names_ba = [t.name for t in tasks_ba]
    assert names_ba.index("Second File Task") < names_ba.index("First File Task")


def test_load_items_from_files_empty_file_contributes_nothing(tmp_path):
    """An empty (header-only) file contributes no rows; no crash."""
    fa = tmp_path / "data.csv"
    fb = tmp_path / "empty.csv"
    fa.write_text(
        "section,name,start,end\n"
        "S,Real Task,2027-01-01,2027-01-31\n",
        encoding="utf-8",
    )
    fb.write_text(
        "section,name,start,end\n",  # header only, no data
        encoding="utf-8",
    )
    items = csv_parser.load_items_from_files([fa, fb])
    assert len(items) == 1
    _, tasks = items[0]
    assert tasks[0].name == "Real Task"


def test_load_items_from_files_matches_single_file_load(tmp_path):
    """load_items_from_files([path]) is identical to load_items_from_file(path)."""
    p = tmp_path / "data.csv"
    p.write_text(BASIC_CSV, encoding="utf-8")
    items_single = csv_parser.load_items_from_file(p)
    items_multi  = csv_parser.load_items_from_files([p])
    # Compare section names and task names (same structure expected)
    assert [(s, [t.name for t in tasks]) for s, tasks in items_single] == \
           [(s, [t.name for t in tasks]) for s, tasks in items_multi]


def test_load_items_from_files_optional_columns_differ_per_file(tmp_path):
    """Files may omit optional columns independently; row.get() handles missing keys."""
    fa = tmp_path / "with_tags.csv"
    fb = tmp_path / "no_tags.csv"
    # File A has tags column; file B omits it entirely
    fa.write_text(
        "section,name,start,end,tags\n"
        "S,Tagged Task,2027-01-01,2027-01-31,eng\n",
        encoding="utf-8",
    )
    fb.write_text(
        "section,name,start,end\n"
        "S,Untagged Task,2027-02-01,2027-02-28\n",
        encoding="utf-8",
    )
    items = csv_parser.load_items_from_files([fa, fb])
    assert len(items) == 1
    _, tasks = items[0]
    tagged   = next(t for t in tasks if t.name == "Tagged Task")
    untagged = next(t for t in tasks if t.name == "Untagged Task")
    assert tagged.tags == "eng"
    assert untagged.tags == ""  # missing column => empty string, no crash


# ---------------------------------------------------------------------------
# Colour column + inheritance
# ---------------------------------------------------------------------------

def _by_name(items):
    """Flatten all tasks across sections into a {name: TaskItem} map."""
    return {t.name: t for _s, tasks in items for t in tasks}


def test_color_column_parsed():
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,Task A,2027-01-15,2027-04-30,,,eng,dd:primary\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    task = _by_name(items)["Task A"]
    assert task.color == "dd:primary"


def test_color_missing_column_defaults_none():
    """A CSV without a color column leaves every task colour at None."""
    csv_text = (
        "section,name,start,end\n"
        "Platform,Task A,2027-01-15,2027-04-30\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    assert _by_name(items)["Task A"].color is None


def test_section_color_from_first_colored_row():
    """The section colour is the first non-blank colour cell in the section.

    Later blank rows in the same section inherit it (matches the spec:
    'Backend Overhaul 2' inherits dd:primary from 'Backend Overhaul').
    """
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,Backend Overhaul,2027-01-15,2027-04-30,,,eng,dd:primary\n"
        "Platform,Backend Overhaul 2,2027-05-01,2027-06-30,,,eng,\n"
        "DefaultColor,Backend Overhaul 3,2027-01-15,2027-04-30,,,eng,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    assert m["Backend Overhaul"].color == "dd:primary"
    assert m["Backend Overhaul 2"].color == "dd:primary"
    assert m["Backend Overhaul 3"].color is None


def test_section_color_uses_first_even_if_not_first_row():
    """A blank first row still lets a later coloured row set the section colour."""
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "S,First,2027-01-01,2027-01-31,,,,\n"
        "S,Second,2027-02-01,2027-02-28,,,,#123456\n"
        "S,Third,2027-03-01,2027-03-31,,,,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    # 'First' precedes the coloured row, so it inherits the section colour too.
    assert m["First"].color == "#123456"
    assert m["Second"].color == "#123456"
    assert m["Third"].color == "#123456"


def test_color_inheritance_recursive_subtasks():
    """Colour trickles down the parent chain for arbitrarily deep subtasks."""
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,Parent,2027-01-15,2027-04-30,,,,#123456\n"
        "Parent,Child,2027-01-15,2027-02-28,,,,\n"
        "Child,GrandChild,2027-01-15,2027-01-31,,,,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    assert m["Parent"].color == "#123456"
    assert m["Child"].color == "#123456"
    assert m["GrandChild"].color == "#123456"
    # And the whole tree is one section with three tasks (recursive nesting).
    assert len(items) == 1
    assert len(items[0][1]) == 3


def test_color_override_mid_chain_inherits_downward():
    """A new colour mid-chain overrides and is inherited by deeper tasks."""
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,Parent,2027-01-15,2027-04-30,,,,#111111\n"
        "Parent,Child,2027-01-15,2027-02-28,,,,#222222\n"
        "Child,GrandChild,2027-01-15,2027-01-31,,,,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    assert m["Parent"].color == "#111111"
    assert m["Child"].color == "#222222"
    assert m["GrandChild"].color == "#222222"  # inherits the new mid-chain colour


def test_color_default_sentinel_resets():
    """A 'default' colour cell resets the effective colour to None."""
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,Parent,2027-01-15,2027-04-30,,,,dd:primary\n"
        "Platform,Reset,2027-05-01,2027-05-31,,,,default\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    assert m["Parent"].color == "dd:primary"
    assert m["Reset"].color is None


def test_color_default_sentinel_resets_subtask_and_descendants():
    """A subtask reset to default stops inheritance; its children inherit None."""
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,Parent,2027-01-15,2027-04-30,,,,#123456\n"
        "Parent,Child,2027-01-15,2027-02-28,,,,default\n"
        "Child,GrandChild,2027-01-15,2027-01-31,,,,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    assert m["Parent"].color == "#123456"
    assert m["Child"].color is None
    assert m["GrandChild"].color is None


def test_color_default_sentinel_case_insensitive():
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Platform,A,2027-01-15,2027-04-30,,,,dd:primary\n"
        "Platform,B,2027-05-01,2027-05-31,,,,DEFAULT\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    assert _by_name(items)["B"].color is None


def test_color_default_sentinel_not_section_color():
    """A leading 'default' cell must not become the section colour."""
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "S,A,2027-01-01,2027-01-31,,,,default\n"
        "S,B,2027-02-01,2027-02-28,,,,#ABCDEF\n"
        "S,C,2027-03-01,2027-03-31,,,,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    m = _by_name(items)
    assert m["A"].color is None          # explicit reset
    assert m["B"].color == "#ABCDEF"
    assert m["C"].color == "#ABCDEF"     # inherits the real section colour


def test_color_inheritance_siblings_and_deep_nesting():
    """Sibling subtasks + a grandchild resolve independently (shift-positions).

    Parent(#111) → ChildA(#222) → GrandA (inherits #222)
                 → ChildB (inherits #111 from parent, not ChildA)
    Exercises _shift_positions: inserting GrandA after ChildA must not
    mis-associate ChildB's parent, and ChildB must inherit the parent colour
    rather than its sibling's.
    """
    csv_text = (
        "section,name,start,end,row_group,link,tags,color\n"
        "Work,Parent,2027-01-01,2027-06-30,,,,#111111\n"
        "Parent,ChildA,2027-01-01,2027-03-31,,,,#222222\n"
        "ChildA,GrandA,2027-01-01,2027-02-15,,,,\n"
        "Parent,ChildB,2027-04-01,2027-06-30,,,,\n"
    )
    items = csv_parser.load_items_from_string(csv_text)
    assert len(items) == 1
    section, tasks = items[0]
    m = {t.name: t for t in tasks}
    assert m["Parent"].color == "#111111"
    assert m["ChildA"].color == "#222222"
    assert m["GrandA"].color == "#222222"   # inherits ChildA (its parent)
    assert m["ChildB"].color == "#111111"   # inherits Parent, NOT sibling ChildA
    # Order: Parent, ChildA, GrandA, ChildB (grandchild nested under ChildA).
    assert [t.name for t in tasks] == ["Parent", "ChildA", "GrandA", "ChildB"]
    # Depth flags: all three descendants are subtasks; Parent is not.
    assert m["Parent"].is_subtask is False
    assert all(m[n].is_subtask for n in ("ChildA", "GrandA", "ChildB"))


def test_color_field_index_pinned():
    """Guard the generator's positional tuple fallback: color must stay last.

    generator.generate_puml reads task[8] for the colour of a legacy tuple, so
    TaskItem.color must remain field index 8.  If a future field is inserted
    before it, this test fails loudly rather than the generator silently
    misreading positions.
    """
    assert csv_parser.TaskItem._fields.index("color") == 8
    assert csv_parser.TaskItem._fields == (
        "name", "start", "end", "link", "tags",
        "is_subtask", "row_group", "pid", "color",
    )
