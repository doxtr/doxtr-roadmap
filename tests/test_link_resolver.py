"""Unit tests for doxtr_roadmap/link_resolver.py."""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from doxtr_roadmap.link_resolver import LinkResolver, parse_xlink_role, _local_xlink_scan


def _make_app(extensions=None):
    """Create a minimal fake Sphinx app."""
    app = MagicMock()
    app.config.extensions = extensions or []
    app.env.srcdir = "/tmp/fake_srcdir"
    app.env.config = app.config
    # Simulate missing _doxtr_roadmap_warned so LinkResolver creates it
    if not hasattr(app.env, "_doxtr_roadmap_warned"):
        del app.env._doxtr_roadmap_warned
    return app


def _make_resolver(extensions=None, warned=None):
    """Create a LinkResolver with an injected warned set for clean test isolation."""
    app = _make_app(extensions=extensions)
    warned_set = warned if warned is not None else set()
    return LinkResolver(app, _warned=warned_set), app, warned_set


# ---------------------------------------------------------------------------
# parse_xlink_role
# ---------------------------------------------------------------------------

def test_parse_xlink_role_bare_id():
    key, label = parse_xlink_role("some-id")
    assert key == "some-id"
    assert label is None


def test_parse_xlink_role_with_label():
    key, label = parse_xlink_role("Title <id>")
    assert key == "id"
    assert label == "Title"


def test_parse_xlink_role_full_syntax():
    key, label = parse_xlink_role(":xlink:`Title <id>`")
    assert key == "id"
    assert label == "Title"


def test_parse_xlink_role_bare_syntax():
    key, label = parse_xlink_role(":xlink:`some-id`")
    assert key == "some-id"
    assert label is None


def test_parse_xlink_role_empty():
    key, label = parse_xlink_role("")
    assert key is None
    assert label is None


# ---------------------------------------------------------------------------
# resolve() — basic
# ---------------------------------------------------------------------------

def test_resolve_empty_cell():
    resolver, _, _ = _make_resolver()
    assert resolver.resolve("") is None
    assert resolver.resolve("   ") is None
    assert resolver.resolve(None) is None


def test_resolve_plain_url():
    resolver, _, _ = _make_resolver()
    result = resolver.resolve("https://example.com")
    assert result == ("https://example.com", "")


def test_resolve_plain_url_http():
    resolver, _, _ = _make_resolver()
    result = resolver.resolve("http://example.com/path")
    assert result == ("http://example.com/path", "")


def test_resolve_plain_url_no_http():
    resolver, _, _ = _make_resolver()
    result = resolver.resolve("not-a-url")
    assert result is None


# ---------------------------------------------------------------------------
# S-5: xlink-detection via _ROLE_RE only — no fragile heuristics
# ---------------------------------------------------------------------------

def test_resolve_feature_pending_not_xlink():
    """'Feature <pending>' must NOT be treated as xlink — no xlink: role prefix."""
    resolver, _, _ = _make_resolver()
    result = resolver.resolve("Feature <pending>")
    assert result is None, (
        "Cell 'Feature <pending>' has no xlink: role prefix and must be "
        "treated as plain/none, not xlink."
    )


def test_resolve_angle_brackets_with_http_not_xlink():
    """A URL-like cell is returned as plain URL."""
    resolver, _, _ = _make_resolver()
    result = resolver.resolve("https://example.com/page")
    assert result == ("https://example.com/page", "")


# ---------------------------------------------------------------------------
# resolve() — xlink absent
# ---------------------------------------------------------------------------

def test_resolve_xlink_role_xlink_absent():
    """xlink not in extensions → None + warning."""
    warned = set()
    resolver, _, _ = _make_resolver(extensions=[], warned=warned)
    result = resolver.resolve(":xlink:`some-id`")
    assert result is None


def test_warning_deduplicated():
    """Same unknown id → only one entry in warned set."""
    warned = set()
    resolver, _, _ = _make_resolver(extensions=[], warned=warned)
    resolver.resolve(":xlink:`dup-id`")
    resolver.resolve(":xlink:`dup-id`")
    assert sum(1 for k in warned if "dup-id" in k) == 1


# ---------------------------------------------------------------------------
# resolve() — xlink present
# ---------------------------------------------------------------------------

def test_resolve_xlink_role_found():
    """xlink present, _get_xlink_data returns data."""
    warned = set()
    app = _make_app(extensions=["sphinxcontrib.xlink"])
    mock_get = MagicMock(return_value=("My Title", "https://example.com/resolved"))
    resolver = LinkResolver.__new__(LinkResolver)
    resolver.app = app
    resolver._xlink_available = True
    resolver._get_xlink_data = mock_get
    resolver._warned = warned

    result = resolver.resolve(":xlink:`my-id`")
    assert result is not None
    url, title = result
    assert url == "https://example.com/resolved"
    assert title == "My Title"


def test_resolve_xlink_with_custom_label():
    """Custom label in cell wins over resolved title."""
    warned = set()
    app = _make_app(extensions=["sphinxcontrib.xlink"])
    mock_get = MagicMock(return_value=("Resolved Title", "https://example.com"))
    resolver = LinkResolver.__new__(LinkResolver)
    resolver.app = app
    resolver._xlink_available = True
    resolver._get_xlink_data = mock_get
    resolver._warned = warned

    result = resolver.resolve(":xlink:`My Label <my-id>`")
    assert result is not None
    url, title = result
    assert title == "My Label"


def test_resolve_xlink_not_found():
    """_get_xlink_data returns (None, None) → None + warning."""
    warned = set()
    app = _make_app(extensions=["sphinxcontrib.xlink"])
    mock_get = MagicMock(return_value=(None, None))
    resolver = LinkResolver.__new__(LinkResolver)
    resolver.app = app
    resolver._xlink_available = True
    resolver._get_xlink_data = mock_get
    resolver._warned = warned

    result = resolver.resolve(":xlink:`missing-id`")
    assert result is None
    assert any("missing-id" in k for k in warned)


# ---------------------------------------------------------------------------
# T-2: _local_xlink_scan with a real temp .xlink dir + file
# ---------------------------------------------------------------------------

def test_local_xlink_scan_finds_entry(tmp_path):
    """_local_xlink_scan resolves an id from a real .xlink file."""
    xlink_dir = tmp_path / "xlinks"
    xlink_dir.mkdir()
    xlink_file = xlink_dir / "entries.xlink"
    xlink_file.write_text(
        "# comment line\n"
        "my-feature :: My Feature Title :: https://example.com/feature :: eng\n"
        "other-id :: Other :: https://other.com ::\n",
        encoding="utf-8",
    )

    app = MagicMock()
    app.env.srcdir = str(tmp_path)
    app.env.config = MagicMock()
    app.env.config.xlink_directory = "xlinks"

    title, url = _local_xlink_scan(app, "my-feature")
    assert title == "My Feature Title"
    assert url == "https://example.com/feature"


def test_local_xlink_scan_missing_id(tmp_path):
    """_local_xlink_scan returns (None, None) when id not found."""
    xlink_dir = tmp_path / "xlinks"
    xlink_dir.mkdir()
    (xlink_dir / "data.xlink").write_text(
        "existing-id :: Title :: https://example.com ::\n",
        encoding="utf-8",
    )

    app = MagicMock()
    app.env.srcdir = str(tmp_path)
    app.env.config = MagicMock()
    app.env.config.xlink_directory = "xlinks"

    title, url = _local_xlink_scan(app, "nonexistent-id")
    assert title is None
    assert url is None


def test_local_xlink_scan_no_directory(tmp_path):
    """_local_xlink_scan returns (None, None) when the xlinks dir is absent."""
    app = MagicMock()
    app.env.srcdir = str(tmp_path)
    app.env.config = MagicMock()
    app.env.config.xlink_directory = "xlinks"  # directory does not exist

    title, url = _local_xlink_scan(app, "any-id")
    assert title is None
    assert url is None
