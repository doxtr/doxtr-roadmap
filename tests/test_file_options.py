"""Unit tests for doxtr_roadmap/file_options.py and per-file column
suppression / norender behaviour in csv_parser."""

import pytest

from doxtr_roadmap import csv_parser
from doxtr_roadmap.file_options import (
    FileOptionError,
    FileOptions,
    split_spec_and_options,
    parse_file_options,
)

IGNORABLE = list(csv_parser.DEFAULT_IGNORABLE_COLUMNS)


# ---------------------------------------------------------------------------
# split_spec_and_options
# ---------------------------------------------------------------------------

def test_split_no_bracket():
    fn, opts = split_spec_and_options("sprints/sprint-01.csv")
    assert fn == "sprints/sprint-01.csv"
    assert opts is None


def test_split_with_bracket():
    fn, opts = split_spec_and_options("sprints/sprint-01.csv[ignore=section,link]")
    assert fn == "sprints/sprint-01.csv"
    assert opts == "ignore=section,link"


def test_split_glob_charclass_not_treated_as_options():
    # A glob character class that does NOT close at end-of-token is left intact.
    fn, opts = split_spec_and_options("file[0-9].csv")
    assert fn == "file[0-9].csv"
    assert opts is None


def test_split_glob_charclass_with_trailing_options():
    fn, opts = split_spec_and_options("file[0-9].csv[norender]")
    assert fn == "file[0-9].csv"
    assert opts == "norender"


# ---------------------------------------------------------------------------
# parse_file_options
# ---------------------------------------------------------------------------

def test_parse_none_is_empty():
    o = parse_file_options(None, IGNORABLE)
    assert o == FileOptions(frozenset(), False)


def test_parse_ignore_single():
    o = parse_file_options("ignore=section", IGNORABLE)
    assert o.ignore_columns == frozenset({"section"})
    assert o.norender is False


def test_parse_ignore_multiple_and_norender():
    o = parse_file_options("ignore=section,link;norender", IGNORABLE)
    assert o.ignore_columns == frozenset({"section", "link"})
    assert o.norender is True


def test_parse_case_insensitive_flag_and_key():
    o = parse_file_options("IGNORE=tags;NoRender", IGNORABLE)
    assert o.ignore_columns == frozenset({"tags"})
    assert o.norender is True


def test_parse_whitespace_tolerant():
    o = parse_file_options(" ignore = section , link ; norender ", IGNORABLE)
    assert o.ignore_columns == frozenset({"section", "link"})
    assert o.norender is True


def test_parse_trailing_semicolon_ok():
    o = parse_file_options("norender;", IGNORABLE)
    assert o.norender is True


def test_parse_required_column_rejected():
    for col in ("name", "start", "end"):
        with pytest.raises(FileOptionError):
            parse_file_options(f"ignore={col}", IGNORABLE)


def test_parse_unknown_column_rejected():
    with pytest.raises(FileOptionError):
        parse_file_options("ignore=nope", IGNORABLE)


def test_parse_unknown_flag_rejected():
    with pytest.raises(FileOptionError):
        parse_file_options("noRenderer", IGNORABLE)


def test_parse_unknown_key_rejected():
    with pytest.raises(FileOptionError):
        parse_file_options("drop=section", IGNORABLE)


def test_parse_empty_ignore_rejected():
    with pytest.raises(FileOptionError):
        parse_file_options("ignore=", IGNORABLE)


def test_parse_configurable_ignorable_set():
    # If the caller narrows the ignorable set, other columns are rejected.
    with pytest.raises(FileOptionError):
        parse_file_options("ignore=link", ["section"])
    o = parse_file_options("ignore=section", ["section"])
    assert o.ignore_columns == frozenset({"section"})


# ---------------------------------------------------------------------------
# Parse-time column blanking via load_items_from_files
# ---------------------------------------------------------------------------

CSV = """\
section,name,start,end,row_group,link,tags
Alpha,Task A,2026-01-01,2026-03-31,grp,https://example.com,eng
Alpha,Task B,2026-04-01,2026-06-30,grp,https://example.com,ops
"""


def _write(tmp_path, text, name="data.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_ignore_tags_blanked(tmp_path):
    p = _write(tmp_path, CSV)
    opts = FileOptions(ignore_columns=frozenset({"tags"}))
    items = csv_parser.load_items_from_files([p], [opts])
    tasks = [t for _s, ts in items for t in ts]
    assert all(t.tags == "" for t in tasks)


def test_ignore_link_blanked(tmp_path):
    p = _write(tmp_path, CSV)
    opts = FileOptions(ignore_columns=frozenset({"link"}))
    items = csv_parser.load_items_from_files([p], [opts])
    tasks = [t for _s, ts in items for t in ts]
    assert all(t.link == "" for t in tasks)


def test_ignore_row_group_blanked(tmp_path):
    p = _write(tmp_path, CSV)
    opts = FileOptions(ignore_columns=frozenset({"row_group"}))
    items = csv_parser.load_items_from_files([p], [opts])
    tasks = [t for _s, ts in items for t in ts]
    assert all(t.row_group is None for t in tasks)


def test_ignore_section_flattens(tmp_path):
    p = _write(tmp_path, CSV)
    opts = FileOptions(ignore_columns=frozenset({"section"}))
    items = csv_parser.load_items_from_files([p], [opts])
    # A blank section renders under a single unnamed section.
    assert [s for s, _ in items] == [""]


def test_norender_skips_rows_but_reads_file(tmp_path):
    p = _write(tmp_path, CSV)
    opts = FileOptions(ignore_columns=frozenset(), norender=True)
    items = csv_parser.load_items_from_files([p], [opts])
    assert items == []


def test_norender_still_raises_on_missing_file(tmp_path):
    opts = FileOptions(ignore_columns=frozenset(), norender=True)
    with pytest.raises(OSError):
        csv_parser.load_items_from_files([tmp_path / "nope.csv"], [opts])


def test_per_file_options_are_independent(tmp_path):
    # Two files: ignore tags only in the first, render both.
    p1 = _write(tmp_path, CSV, "a.csv")
    p2 = _write(tmp_path, CSV, "b.csv")
    o1 = FileOptions(ignore_columns=frozenset({"tags"}))
    items = csv_parser.load_items_from_files([p1, p2], [o1, None])
    # Both files share section "Alpha" so they merge into one section with
    # 4 tasks; the first file's tags are blanked, the second file's kept.
    tasks = [t for _s, ts in items for t in ts]
    tag_values = sorted(t.tags for t in tasks)
    # two blanked ("") from file 1, two kept ("eng","ops") from file 2
    assert tag_values == ["", "", "eng", "ops"]


def test_options_shorter_than_paths(tmp_path):
    p1 = _write(tmp_path, CSV, "a.csv")
    p2 = _write(tmp_path, CSV, "b.csv")
    # Only one options entry; the second file gets no options.
    items = csv_parser.load_items_from_files([p1, p2], [None])
    tasks = [t for _s, ts in items for t in ts]
    assert len(tasks) == 4


def test_no_options_backward_compatible(tmp_path):
    p = _write(tmp_path, CSV)
    items = csv_parser.load_items_from_files([p])
    tasks = [t for _s, ts in items for t in ts]
    assert all(t.tags for t in tasks)
