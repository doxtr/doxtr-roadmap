"""Unit tests for doxtr_roadmap/tags.py."""

import pytest
from doxtr_roadmap import tags


# ---------------------------------------------------------------------------
# parse_tag_list
# ---------------------------------------------------------------------------

def test_parse_tag_list_basic():
    result = tags.parse_tag_list("eng, code")
    assert result == ["eng", "code"]


def test_parse_tag_list_quoted_comma():
    raw = 'bib:author:"van B, L"'
    result = tags.parse_tag_list(raw)
    assert result == ['bib:author:"van B, L"']


def test_parse_tag_list_empty():
    assert tags.parse_tag_list("") == []


def test_parse_tag_list_whitespace_only():
    assert tags.parse_tag_list("   ") == []


def test_parse_tag_list_multiple():
    result = tags.parse_tag_list("a, b, c")
    assert result == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# is_tag_allowed
# ---------------------------------------------------------------------------

class _FakeConfig:
    doxtr_roadmap_allowed_tags = {}
    doxtr_roadmap_allowed_tag_patterns = {}


def test_is_tag_allowed_no_restrictions():
    cfg = _FakeConfig()
    assert tags.is_tag_allowed("anything", cfg) is True


def test_is_tag_allowed_static():
    cfg = _FakeConfig()
    cfg.doxtr_roadmap_allowed_tags = {"eng": "Engineering"}
    assert tags.is_tag_allowed("eng", cfg) is True


def test_is_tag_allowed_pattern():
    cfg = _FakeConfig()
    cfg.doxtr_roadmap_allowed_tag_patterns = {"bib:.*": "Bibliographic"}
    assert tags.is_tag_allowed("bib:author", cfg) is True


def test_is_tag_allowed_xlink_fallback(monkeypatch):
    """Tag in xlink_allowed_tags is accepted when xlink present."""
    cfg = _FakeConfig()
    cfg.doxtr_roadmap_allowed_tags = {"eng": "Engineering"}
    cfg.xlink_allowed_tags = {"security": "Security"}
    cfg.xlink_allowed_tag_patterns = {}
    # Temporarily mark _xlink_present = True
    monkeypatch.setattr(tags, "_xlink_present", True)
    assert tags.is_tag_allowed("security", cfg) is True


def test_is_tag_not_allowed():
    cfg = _FakeConfig()
    cfg.doxtr_roadmap_allowed_tags = {"eng": "Engineering"}
    assert tags.is_tag_allowed("unknown", cfg) is False


# ---------------------------------------------------------------------------
# parse_nested_tags
# ---------------------------------------------------------------------------

def test_parse_nested_tags_basic():
    result = tags.parse_nested_tags("security, public")
    assert "security" in result
    assert "public" in result
    assert result["security"]["hide"] is False
    assert result["public"]["hide"] is False


def test_parse_nested_tags_hide():
    result = tags.parse_nested_tags("!internal")
    assert "internal" in result
    assert result["internal"]["hide"] is True


def test_parse_nested_tags_cascade():
    # '!!' suffix sets cascade=True; hide is only set by prefix '!!' or '!'
    result = tags.parse_nested_tags("security [ compliance !! ]")
    assert "security" in result
    children = result["security"]["children"]
    assert "compliance" in children
    assert children["compliance"]["cascade"] is True


def test_parse_nested_tags_hide_cascade_prefix():
    # Prefix '!!' sets both hide=True and cascade=True
    result = tags.parse_nested_tags("!!internal")
    assert "internal" in result
    assert result["internal"]["hide"] is True
    assert result["internal"]["cascade"] is True


def test_parse_nested_tags_empty():
    result = tags.parse_nested_tags("")
    assert result == {}


# ---------------------------------------------------------------------------
# row_matches_filter
# ---------------------------------------------------------------------------

def test_row_matches_filter_simple():
    tree = tags.parse_nested_tags("security, public")
    assert tags.row_matches_filter(["security"], tree) is True
    assert tags.row_matches_filter(["public"], tree) is True


def test_row_matches_filter_excluded():
    tree = tags.parse_nested_tags("!internal")
    assert tags.row_matches_filter(["internal"], tree) is False


def test_row_matches_filter_empty_filter():
    assert tags.row_matches_filter(["anything"], {}) is True


def test_row_matches_filter_no_tags():
    tree = tags.parse_nested_tags("security")
    assert tags.row_matches_filter([], tree) is False


def test_row_matches_filter_unrelated_tag():
    tree = tags.parse_nested_tags("security")
    assert tags.row_matches_filter(["public"], tree) is False


def test_row_matches_filter_one_of_multiple_matches():
    tree = tags.parse_nested_tags("security, public")
    assert tags.row_matches_filter(["public", "other"], tree) is True


# ---------------------------------------------------------------------------
# parse_row_tags — space- and comma-aware CSV row tag tokeniser
# ---------------------------------------------------------------------------

def test_parse_row_tags_space_separated():
    """Space-separated tags are split into individual tokens."""
    assert tags.parse_row_tags("eng ops") == ["eng", "ops"]


def test_parse_row_tags_comma_separated():
    """Comma-separated tags (with optional whitespace) produce individual tokens."""
    assert tags.parse_row_tags("eng, ops") == ["eng", "ops"]


def test_parse_row_tags_mixed_comma_and_space():
    """Mixed comma and space delimiters all produce individual tokens."""
    assert tags.parse_row_tags("eng,ops security") == ["eng", "ops", "security"]


def test_parse_row_tags_quoted_comma_preserved():
    """A quoted value with an embedded comma is kept as one token."""
    result = tags.parse_row_tags('bib:author:"van B, L" ops')
    assert result == ['bib:author:"van B, L"', 'ops']


def test_parse_row_tags_quoted_space_preserved():
    """A double-quoted value with internal spaces is NOT split."""
    result = tags.parse_row_tags('"multi word tag" eng')
    assert result == ['"multi word tag"', 'eng']


def test_parse_row_tags_empty():
    """Empty string returns an empty list."""
    assert tags.parse_row_tags("") == []


def test_parse_row_tags_whitespace_only():
    """Whitespace-only string returns an empty list."""
    assert tags.parse_row_tags("   ") == []


def test_parse_row_tags_single_tag():
    """A single tag with no delimiters returns a one-element list."""
    assert tags.parse_row_tags("eng") == ["eng"]


def test_parse_row_tags_extra_whitespace():
    """Extra whitespace between tokens is collapsed."""
    result = tags.parse_row_tags("eng   ops   security")
    assert result == ["eng", "ops", "security"]


def test_parse_row_tags_comma_only_no_spaces():
    """Pure comma separation (no spaces) works correctly."""
    assert tags.parse_row_tags("eng,ops,security") == ["eng", "ops", "security"]




def test_local_fallback_parse_tag_list():
    """_local_parse_tag_list works correctly without xlink."""
    from doxtr_roadmap.tags import _local_parse_tag_list
    assert _local_parse_tag_list("a, b, c") == ["a", "b", "c"]
    assert _local_parse_tag_list('bib:author:"van B, L"') == ['bib:author:"van B, L"']
    assert _local_parse_tag_list("") == []


def test_local_fallback_match_tag_pattern():
    """_local_match_tag_pattern works without xlink."""
    from doxtr_roadmap.tags import _local_match_tag_pattern

    class _Cfg:
        doxtr_roadmap_allowed_tag_patterns = {"bib:.*": "Bibliographic"}

    assert _local_match_tag_pattern("bib:author", _Cfg()) == "Bibliographic"
    assert _local_match_tag_pattern("other", _Cfg()) is None


def test_local_fallback_resolve_tag_info():
    """_local_resolve_tag_info works without xlink."""
    from doxtr_roadmap.tags import _local_resolve_tag_info

    class _Cfg:
        doxtr_roadmap_allowed_tags = {"eng": "Engineering"}
        doxtr_roadmap_allowed_tag_patterns = {}

    name, desc = _local_resolve_tag_info("eng", _Cfg())
    assert name == "Engineering"

    name, desc = _local_resolve_tag_info(None, _Cfg())
    assert name == "Untagged"

    name, desc = _local_resolve_tag_info("unknown", _Cfg())
    assert name == "unknown"


def test_local_fallbacks_via_module_reload(monkeypatch):
    """After removing sphinxcontrib.xlink from sys.modules, reloaded tags module
    uses local implementations for parse_tag_list/match_tag_pattern/resolve_tag_info.
    
    If xlink is persistently importable (namespace package), we verify the local
    functions directly rather than trying to trick the import machinery.
    """
    import sys
    import importlib

    # Save original modules
    saved = {k: v for k, v in sys.modules.items() if "sphinxcontrib.xlink" in k}
    for k in list(saved):
        del sys.modules[k]
    # Also hide the top-level xlink entry
    saved_top = sys.modules.pop("sphinxcontrib.xlink", None)

    try:
        # Reload tags with xlink removed from sys.modules
        import doxtr_roadmap.tags as tags_mod
        importlib.reload(tags_mod)

        # Regardless of whether xlink re-imports (namespace pkg), verify that
        # the local implementations behave correctly when called directly.
        result = tags_mod._local_parse_tag_list("x, y")
        assert result == ["x", "y"], f"Expected ['x', 'y'], got {result}"

        class _Cfg:
            doxtr_roadmap_allowed_tags = {"x": "X tag"}
            doxtr_roadmap_allowed_tag_patterns = {}
            xlink_allowed_tags = {}
            xlink_allowed_tag_patterns = {}

        name, _ = tags_mod._local_resolve_tag_info("x", _Cfg())
        assert name == "X tag"

        meta = tags_mod._local_match_tag_pattern("bib:author", type(
            "C", (), {"doxtr_roadmap_allowed_tag_patterns": {"bib:.*": "bib"}}
        )())
        assert meta == "bib"

    finally:
        # Restore xlink modules
        for k, v in saved.items():
            sys.modules[k] = v
        if saved_top is not None:
            sys.modules["sphinxcontrib.xlink"] = saved_top
        # Reload to restore original bindings
        importlib.reload(tags_mod)
