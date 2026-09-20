"""Unit tests for the automatic loading of ``doxtr_pdf_theme_core``.

doxtr-roadmap loads theme-core automatically at ``setup()`` time when the
package is importable, unless the user opts out via
``doxtr_roadmap_autoload_theme_core = False``.  These tests exercise
:func:`doxtr_roadmap._autoload_theme_core` and its registration in
:func:`doxtr_roadmap.setup` in isolation, without a real Sphinx build.
"""

import pytest
from unittest.mock import MagicMock

import doxtr_roadmap
from doxtr_roadmap import _autoload_theme_core, _THEME_CORE_PACKAGE
from doxtr_roadmap.config_defaults import DEFAULT_CONFIG
from doxtr_roadmap.theme_adapter import (
    _theme_core_loaded,
    _THEME_CORE_MARKER_ATTR,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeConfig:
    """Config stub whose attributes resolve like Sphinx's ``Config``.

    Only ``doxtr_roadmap_autoload_theme_core`` is relevant here; it defaults to
    ``True`` (matching the registered default) and can be overridden per test.
    """

    def __init__(self, autoload=True):
        self.doxtr_roadmap_autoload_theme_core = autoload


def _make_app(autoload=True):
    """Return a MagicMock app with a config exposing the autoload flag."""
    app = MagicMock()
    app.config = _FakeConfig(autoload=autoload)
    return app


# ---------------------------------------------------------------------------
# _autoload_theme_core behaviour
# ---------------------------------------------------------------------------

def test_autoload_calls_setup_extension_when_importable(monkeypatch):
    """Package importable + option enabled → app.setup_extension is called."""
    app = _make_app(autoload=True)
    # Pretend the package is installed regardless of the real environment.
    monkeypatch.setattr(
        doxtr_roadmap.importlib.util,
        "find_spec",
        lambda name: object() if name == _THEME_CORE_PACKAGE else None,
    )
    _autoload_theme_core(app)
    app.setup_extension.assert_called_once_with(_THEME_CORE_PACKAGE)


def test_autoload_skipped_when_option_false(monkeypatch):
    """Option disabled → setup_extension is never called, even if installed."""
    app = _make_app(autoload=False)
    # find_spec would report the package as present, but the option gates it.
    monkeypatch.setattr(
        doxtr_roadmap.importlib.util,
        "find_spec",
        lambda name: object(),
    )
    _autoload_theme_core(app)
    app.setup_extension.assert_not_called()


def test_autoload_skipped_when_not_importable(monkeypatch):
    """Package absent → setup_extension not called and no crash."""
    app = _make_app(autoload=True)
    monkeypatch.setattr(
        doxtr_roadmap.importlib.util,
        "find_spec",
        lambda name: None,
    )
    _autoload_theme_core(app)
    app.setup_extension.assert_not_called()


def test_autoload_swallows_setup_extension_error(monkeypatch):
    """A failure inside setup_extension must not propagate (build-safe)."""
    app = _make_app(autoload=True)
    monkeypatch.setattr(
        doxtr_roadmap.importlib.util,
        "find_spec",
        lambda name: object(),
    )
    app.setup_extension.side_effect = RuntimeError("boom")
    # Should not raise.
    _autoload_theme_core(app)
    app.setup_extension.assert_called_once_with(_THEME_CORE_PACKAGE)


def test_autoload_defaults_to_enabled_when_attr_missing(monkeypatch):
    """Missing config attr falls back to enabled (getattr default True)."""
    app = MagicMock()
    # A bare object with no autoload attribute.
    app.config = object()
    monkeypatch.setattr(
        doxtr_roadmap.importlib.util,
        "find_spec",
        lambda name: object(),
    )
    _autoload_theme_core(app)
    app.setup_extension.assert_called_once_with(_THEME_CORE_PACKAGE)


# ---------------------------------------------------------------------------
# setup() registration + wiring
# ---------------------------------------------------------------------------

def test_setup_registers_autoload_config_value_with_default():
    """setup() registers doxtr_roadmap_autoload_theme_core with default True."""
    app = MagicMock()
    # setup() reads app.config.doxtr_roadmap_autoload_theme_core inside the
    # auto-load helper; provide the registered default.
    app.config = _FakeConfig(autoload=True)

    doxtr_roadmap.setup(app)

    calls = {
        c.args[0]: c
        for c in app.add_config_value.call_args_list
        if c.args
    }
    assert "doxtr_roadmap_autoload_theme_core" in calls
    call = calls["doxtr_roadmap_autoload_theme_core"]
    # Positional args: (name, default, rebuild)
    assert call.args[1] is DEFAULT_CONFIG["autoload_theme_core"] is True
    assert call.args[2] == "env"
    assert call.kwargs.get("types") == (bool,)


def test_setup_invokes_autoload(monkeypatch):
    """setup() triggers the auto-load path (setup_extension called)."""
    app = MagicMock()
    app.config = _FakeConfig(autoload=True)
    monkeypatch.setattr(
        doxtr_roadmap.importlib.util,
        "find_spec",
        lambda name: object(),
    )
    doxtr_roadmap.setup(app)
    app.setup_extension.assert_called_once_with(_THEME_CORE_PACKAGE)


def test_default_config_has_autoload_theme_core():
    """DEFAULT_CONFIG carries the autoload_theme_core default."""
    assert DEFAULT_CONFIG["autoload_theme_core"] is True


# ---------------------------------------------------------------------------
# Auto-load → detection interplay
# ---------------------------------------------------------------------------
#
# Auto-load calls ``app.setup_extension(_THEME_CORE_PACKAGE)``, which loads
# theme-core *transitively* — it never appears in ``config.extensions``.  The
# ``use_theme_core="auto"`` path then relies on
# :func:`doxtr_roadmap.theme_adapter._theme_core_loaded` detecting that
# transitive load via theme-core's resolved marker attribute.  These tests pin
# that contract so the two independently-tested units stay compatible.

def test_theme_core_loaded_detects_transitive_marker():
    """A transitively-loaded core (marker attr set, not in extensions) is seen.

    This is the exact end-state produced by :func:`_autoload_theme_core`:
    ``setup_extension`` runs theme-core's ``config-inited`` hook, which sets the
    resolved marker attribute, but the package name is absent from the user's
    ``config.extensions`` list.
    """
    config = MagicMock()
    config.extensions = []  # transitive load → not listed by the user
    setattr(config, _THEME_CORE_MARKER_ATTR, "invert")  # resolved by core hook
    assert _theme_core_loaded(config) is True


def test_theme_core_loaded_false_without_marker_or_extension():
    """No auto-load, no explicit listing, no marker → core reported absent."""
    config = MagicMock()
    config.extensions = []
    # A real Config lacks the marker attr when core never ran; emulate with None
    # (a MagicMock would otherwise return a truthy attr for any name).
    setattr(config, _THEME_CORE_MARKER_ATTR, None)
    assert _theme_core_loaded(config) is False
