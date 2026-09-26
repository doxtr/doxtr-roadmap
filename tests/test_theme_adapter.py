"""Unit tests for doxtr_roadmap/theme_adapter.py."""

import pytest
from unittest.mock import MagicMock
from doxtr_roadmap.theme_adapter import get_effective_style, _theme_core_loaded
from doxtr_roadmap.config_defaults import DEFAULT_CONFIG


def _make_config(**kwargs):
    """Create a fake Sphinx config object."""
    cfg = MagicMock()
    cfg.extensions = kwargs.pop("extensions", [])
    # Set all doxtr_roadmap_* attrs to None by default (meaning "use defaults")
    for attr in [
        "doxtr_roadmap_default_scale", "doxtr_roadmap_scale_factor",
        "doxtr_roadmap_default_start", "doxtr_roadmap_default_title",
        "doxtr_roadmap_clean_style", "doxtr_roadmap_close_weekends_on_single_period",
        "doxtr_roadmap_bar", "doxtr_roadmap_sections", "doxtr_roadmap_today",
        "doxtr_roadmap_fonts", "doxtr_roadmap_closed", "doxtr_roadmap_use_theme_core",
        "doxtr_roadmap_allowed_tags", "doxtr_roadmap_allowed_tag_patterns",
        "doxtr_roadmap_collision_detection", "doxtr_roadmap_collision_char_width_factor",
        "doxtr_roadmap_collision_gap_days",
        "doxtr_roadmap_column_zoom",
        "doxtr_roadmap_link_appendix", "doxtr_roadmap_link_appendix_builders",
        "doxtr_roadmap_link_appendix_title",
        "doxtr_roadmap_figure", "doxtr_roadmap_figure_caption",
        "doxtr_roadmap_renderer", "doxtr_roadmap_color_resolver",
        "doxtr_semantic_palette", "doxtr_globals",
    ]:
        setattr(cfg, attr, None)
    cfg.doxtr_roadmap_use_theme_core = "auto"
    # Apply overrides
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# No theme-core
# ---------------------------------------------------------------------------

def test_no_theme_core_uses_defaults():
    cfg = _make_config()
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]
    assert style["today"]["color"] == DEFAULT_CONFIG["today"]["color"]
    assert style["fonts"]["title"]["size"] == DEFAULT_CONFIG["fonts"]["title"]["size"]


def test_use_theme_core_false_ignores_palette():
    cfg = _make_config(
        doxtr_roadmap_use_theme_core=False,
        doxtr_semantic_palette={"primary": "#AABBCC"},
        extensions=["doxtr_pdf_theme_core"],
    )
    style = get_effective_style(cfg)
    # palette should be ignored
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]


def test_use_theme_core_auto_inactive():
    """auto + core not in extensions → defaults used."""
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"primary": "#AABBCC"},
        extensions=[],
    )
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]


# ---------------------------------------------------------------------------
# With theme-core active
# ---------------------------------------------------------------------------

def test_use_theme_core_auto_active():
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"primary": "#112233"},
        doxtr_globals={"light": {}},
        extensions=["doxtr_pdf_theme_core"],
    )
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == "#112233"


def test_primary_maps_to_done_color():
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"primary": "#FACADE"},
        doxtr_globals={"light": {}},
        extensions=["doxtr_pdf_theme_core"],
    )
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == "#FACADE"


def test_secondary_maps_to_today_color():
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"secondary": "#DECAF0"},
        doxtr_globals={"light": {}},
        extensions=["doxtr_pdf_theme_core"],
    )
    style = get_effective_style(cfg)
    assert style["today"]["color"] == "#DECAF0"


def test_main_font_maps_to_task_font():
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={},
        doxtr_globals={"light": {"main_font": "Roboto"}},
        extensions=["doxtr_pdf_theme_core"],
    )
    style = get_effective_style(cfg)
    assert style["fonts"]["task"]["name"] == "Roboto"


# ---------------------------------------------------------------------------
# User config wins over theme-core
# ---------------------------------------------------------------------------

def test_user_bar_override_wins():
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"primary": "#112233"},
        doxtr_globals={"light": {}},
        extensions=["doxtr_pdf_theme_core"],
        doxtr_roadmap_bar={"done_color": "#AABBCC", "undone_color": "#FFF", "frame_color": None},
    )
    style = get_effective_style(cfg)
    # User bar wins over theme-core primary
    assert style["bar"]["done_color"] == "#AABBCC"


def test_missing_palette_key_graceful():
    """Missing 'primary' in palette → done_color stays at default."""
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"secondary": "#AABBCC"},
        doxtr_globals={"light": {}},
        extensions=["doxtr_pdf_theme_core"],
    )
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]


def test_warning_use_true_core_absent(caplog):
    """use_theme_core=True but core absent → warning emitted."""
    import logging
    cfg = _make_config(
        doxtr_roadmap_use_theme_core=True,
        extensions=[],  # core NOT in extensions
    )
    with caplog.at_level(logging.WARNING):
        get_effective_style(cfg)
    assert any("use_theme_core" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Collision detection defaults and overrides
# ---------------------------------------------------------------------------

def test_effective_style_has_collision_defaults():
    """get_effective_style carries collision_detection=True and char_width_factor=1.0 by default."""
    cfg = _make_config()
    style = get_effective_style(cfg)
    assert style["collision_detection"] is True
    assert style["collision_char_width_factor"] == 1.0
    assert style["collision_gap_days"] == 2


def test_effective_style_collision_detection_user_override_false():
    """User setting doxtr_roadmap_collision_detection=False is respected."""
    cfg = _make_config(doxtr_roadmap_collision_detection=False)
    style = get_effective_style(cfg)
    assert style["collision_detection"] is False


def test_effective_style_collision_char_width_factor_override():
    """User setting doxtr_roadmap_collision_char_width_factor=2.5 is respected."""
    cfg = _make_config(doxtr_roadmap_collision_char_width_factor=2.5)
    style = get_effective_style(cfg)
    assert style["collision_char_width_factor"] == 2.5


def test_effective_style_collision_gap_days_override():
    """User setting doxtr_roadmap_collision_gap_days=7 is respected."""
    cfg = _make_config(doxtr_roadmap_collision_gap_days=7)
    style = get_effective_style(cfg)
    assert style["collision_gap_days"] == 7


# ---------------------------------------------------------------------------
# column_zoom defaults and overrides
# ---------------------------------------------------------------------------

def test_effective_style_has_column_zoom_default():
    """get_effective_style carries column_zoom=1 by default."""
    cfg = _make_config()
    style = get_effective_style(cfg)
    assert style["column_zoom"] == 1


def test_effective_style_column_zoom_user_override():
    """User setting doxtr_roadmap_column_zoom=3 propagates through effective style."""
    cfg = _make_config(doxtr_roadmap_column_zoom=3)
    style = get_effective_style(cfg)
    assert style["column_zoom"] == 3


def test_effective_style_column_zoom_float_override():
    """User setting doxtr_roadmap_column_zoom=2.5 propagates through effective style."""
    cfg = _make_config(doxtr_roadmap_column_zoom=2.5)
    style = get_effective_style(cfg)
    assert style["column_zoom"] == 2.5


# ---------------------------------------------------------------------------
# link_appendix defaults and overrides
# ---------------------------------------------------------------------------

def test_effective_style_has_link_appendix_defaults():
    """get_effective_style carries link_appendix='list', builders=['latex'], title='Links' by default."""
    cfg = _make_config()
    style = get_effective_style(cfg)
    assert style["link_appendix"] == "list"
    assert style["link_appendix_builders"] == ["latex"]
    assert style["link_appendix_title"] == "Links"


def test_effective_style_link_appendix_user_override_list():
    """User setting doxtr_roadmap_link_appendix='list' propagates through effective style."""
    cfg = _make_config(doxtr_roadmap_link_appendix="list")
    style = get_effective_style(cfg)
    assert style["link_appendix"] == "list"


def test_effective_style_link_appendix_user_override_footnote():
    """User setting doxtr_roadmap_link_appendix='footnote' propagates through effective style."""
    cfg = _make_config(doxtr_roadmap_link_appendix="footnote")
    style = get_effective_style(cfg)
    assert style["link_appendix"] == "footnote"


def test_effective_style_link_appendix_builders_override():
    """User setting doxtr_roadmap_link_appendix_builders=['html'] propagates correctly."""
    cfg = _make_config(doxtr_roadmap_link_appendix_builders=["html"])
    style = get_effective_style(cfg)
    assert style["link_appendix_builders"] == ["html"]


def test_effective_style_link_appendix_builders_all():
    """User setting doxtr_roadmap_link_appendix_builders='all' propagates correctly."""
    cfg = _make_config(doxtr_roadmap_link_appendix_builders="all")
    style = get_effective_style(cfg)
    assert style["link_appendix_builders"] == "all"


def test_effective_style_link_appendix_title_override():
    """User setting doxtr_roadmap_link_appendix_title='External Links' propagates correctly."""
    cfg = _make_config(doxtr_roadmap_link_appendix_title="External Links")
    style = get_effective_style(cfg)
    assert style["link_appendix_title"] == "External Links"


# ---------------------------------------------------------------------------
# figure / figure_caption defaults and overrides
# ---------------------------------------------------------------------------

def test_effective_style_has_figure_defaults():
    """get_effective_style carries figure=False and figure_caption=None by default."""
    cfg = _make_config()
    style = get_effective_style(cfg)
    assert style["figure"] is False
    assert style["figure_caption"] is None


def test_effective_style_figure_user_override_true():
    """User setting doxtr_roadmap_figure=True propagates through effective style."""
    cfg = _make_config(doxtr_roadmap_figure=True)
    style = get_effective_style(cfg)
    assert style["figure"] is True


def test_effective_style_figure_caption_user_override():
    """User setting doxtr_roadmap_figure_caption='My Chart' propagates correctly."""
    cfg = _make_config(doxtr_roadmap_figure_caption="My Chart")
    style = get_effective_style(cfg)
    assert style["figure_caption"] == "My Chart"


def test_effective_style_figure_caption_none_when_not_set():
    """figure_caption stays None when not configured."""
    cfg = _make_config()
    style = get_effective_style(cfg)
    assert style["figure_caption"] is None


# ---------------------------------------------------------------------------
# Transitive theme-core detection
# ---------------------------------------------------------------------------
# When another extension pulls in doxtr_pdf_theme_core via
# app.setup_extension(...), theme-core is fully initialised (its config-inited
# hook sets doxtr_dark_mode_strategy_resolved) but it is NOT listed in
# config.extensions. The adapter must still detect it under "auto" so users no
# longer need to add theme-core to extensions (or force use_theme_core=True) by
# hand in conf.py to get correct (dark-mode) renders.


class _PlainConfig:
    """Minimal stand-in for a Sphinx config object.

    Unlike MagicMock, missing attributes raise AttributeError, so getattr with
    a default behaves exactly like a real Sphinx config for the marker check.
    """

    def __init__(self, **attrs):
        self.extensions = attrs.pop("extensions", [])
        for k, v in attrs.items():
            setattr(self, k, v)


def test_theme_core_loaded_explicit_extension():
    cfg = _PlainConfig(extensions=["doxtr_pdf_theme_core"])
    assert _theme_core_loaded(cfg) is True


def test_theme_core_loaded_transitive_marker():
    """Not in extensions, but theme-core's resolved marker is set."""
    cfg = _PlainConfig(
        extensions=["some_other_ext"],
        doxtr_dark_mode_strategy_resolved="invert",
    )
    assert _theme_core_loaded(cfg) is True


def test_theme_core_not_loaded_when_absent():
    cfg = _PlainConfig(extensions=["some_other_ext"])
    assert _theme_core_loaded(cfg) is False


def test_theme_core_marker_ignored_when_not_string():
    """A non-string marker value (e.g. an unset MagicMock attr) is ignored."""
    cfg = _PlainConfig(
        extensions=[],
        doxtr_dark_mode_strategy_resolved=object(),
    )
    assert _theme_core_loaded(cfg) is False


def test_theme_core_marker_ignored_when_empty_string():
    cfg = _PlainConfig(
        extensions=[],
        doxtr_dark_mode_strategy_resolved="",
    )
    assert _theme_core_loaded(cfg) is False


def test_auto_active_via_transitive_marker(monkeypatch):
    """auto + core loaded transitively (marker set, not in extensions) →
    theme-core palette is applied without any conf.py workaround."""
    # Light mode: force get_dark_mode_context inactive so the light
    # doxtr_semantic_palette path is exercised deterministically.
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"primary": "#0055AA"},
        doxtr_globals={"light": {}},
        extensions=[],  # theme-core NOT declared by the user
    )
    # Simulate theme-core's config-inited hook having run.
    cfg.doxtr_dark_mode_strategy_resolved = "invert"
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == "#0055AA"


def test_auto_inactive_without_marker_or_extension():
    """auto + no extension entry + no resolved marker → defaults (unchanged)."""
    cfg = _make_config(
        doxtr_roadmap_use_theme_core="auto",
        doxtr_semantic_palette={"primary": "#0055AA"},
        doxtr_globals={"light": {}},
        extensions=[],
    )
    # No doxtr_dark_mode_strategy_resolved marker → MagicMock returns a Mock,
    # which _theme_core_loaded must reject (not a str).
    style = get_effective_style(cfg)
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]


def test_use_true_no_warning_with_transitive_marker(caplog, monkeypatch):
    """use_theme_core=True + transitive load (marker set) → no 'core absent'
    warning, palette applied."""
    import logging
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(
        doxtr_roadmap_use_theme_core=True,
        doxtr_semantic_palette={"primary": "#0055AA"},
        doxtr_globals={"light": {}},
        extensions=[],  # not declared, but loaded transitively
    )
    cfg.doxtr_dark_mode_strategy_resolved = "invert"
    with caplog.at_level(logging.WARNING):
        style = get_effective_style(cfg)
    assert not any("use_theme_core" in r.message for r in caplog.records)
    assert style["bar"]["done_color"] == "#0055AA"


# ---------------------------------------------------------------------------
# Undone colour derivation (always lighter than done in light, darker in dark)
# ---------------------------------------------------------------------------

def test_undone_derived_light_mode_default(monkeypatch):
    """With no dark mode, undone is derived lighter than the default done."""
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(extensions=[])
    style = get_effective_style(cfg)
    from doxtr_pdf_theme_core.utils import _get_luminance
    done = style["bar"]["done_color"]
    undone = style["bar"]["undone_color"]
    assert _get_luminance(undone) > _get_luminance(done)


def test_undone_derived_from_custom_done(monkeypatch):
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(
        doxtr_roadmap_bar={"done_color": "#1976D2"},
        extensions=[],
    )
    style = get_effective_style(cfg)
    from doxtr_roadmap.color_resolver import derive_undone_color
    assert style["bar"]["undone_color"] == derive_undone_color(
        "#1976D2", 88.7, dark_mode=False
    )


def test_undone_user_override_wins(monkeypatch):
    """An explicit undone_color override is never replaced by derivation."""
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(
        doxtr_roadmap_bar={"done_color": "#FF8C00", "undone_color": "#EEEEEE"},
        extensions=[],
    )
    style = get_effective_style(cfg)
    assert style["bar"]["undone_color"] == "#EEEEEE"


def test_undone_delta_zero_disables_derivation(monkeypatch):
    """Setting undone_brightness_delta=0 keeps the literal undone_color."""
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(
        doxtr_roadmap_bar={
            "done_color": "#FF8C00",
            "undone_color": "#FFF3E0",
            "undone_brightness_delta": 0,
        },
        extensions=[],
    )
    style = get_effective_style(cfg)
    assert style["bar"]["undone_color"] == "#FFF3E0"


def test_undone_derivation_skipped_for_custom_renderer(monkeypatch):
    """A custom renderer receives the raw undone_color (built-in derivation off)."""
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False, "palette": None, "page_color": None,
                   "text_color": None, "invert_color": lambda x: x},
        raising=False,
    )
    cfg = _make_config(
        doxtr_roadmap_bar={"done_color": "#1976D2"},
        doxtr_roadmap_renderer="my_theme.roadmap:render",
        extensions=[],
    )
    style = get_effective_style(cfg)
    # Derivation skipped → the DEFAULT_CONFIG literal undone_color is kept.
    assert style["bar"]["undone_color"] == DEFAULT_CONFIG["bar"]["undone_color"]
