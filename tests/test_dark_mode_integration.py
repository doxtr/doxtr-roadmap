"""Tests for dark-mode integration with doxtr-pdf-theme-core.

doxtr-roadmap generates its PlantUML source *inline*, so theme-core's ``_dark``
file-swap cannot help it. Instead, the theme adapter reads theme-core's public
dark-mode context and emits dark-appropriate colours directly into the
generated PlantUML. These tests cover:

* ``generator._build_style_block`` emitting a diagram ``BackGroundColor``,
* ``theme_adapter._read_theme_core`` switching to the dark palette + dark knobs
  when the core reports dark mode is active,
* ``theme_adapter.get_effective_style`` threading ``diagram_background_color``,
* the light-mode / passthrough paths remaining unchanged.

The core's dark-mode context is faked so these tests do not require a real
Sphinx build or the core to be installed at a particular version. The one test
that exercises the real helper is skipped when the core is too old.
"""

import copy
import datetime
from unittest.mock import MagicMock

import pytest
import doxtr_pdf_theme_core as _dptc

from doxtr_roadmap import generator
from doxtr_roadmap.config_defaults import DEFAULT_CONFIG
from doxtr_roadmap import theme_adapter


def _cfg(**overrides):
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["default_start"] = "2026-01-01"
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


def _items_one_task():
    return [("Sec", [("Task A", "2026-02-01", "2026-04-30", "", "", False, None, "Task A")])]


# ---------------------------------------------------------------------------
# generator: diagram_background_color
# ---------------------------------------------------------------------------


def test_diagram_background_color_emitted():
    out = generator.generate_puml(
        _items_one_task(), _cfg(diagram_background_color="#242424"),
        project_start=datetime.date(2026, 1, 1),
    )
    # Emitted as the first line inside the ganttDiagram { ... } block.
    assert "BackGroundColor #242424" in out
    idx_open = out.index("ganttDiagram {")
    idx_bg = out.index("BackGroundColor #242424")
    assert idx_bg > idx_open


def test_diagram_background_color_absent_by_default():
    """No diagram_background_color key → no diagram-level BackGroundColor line.

    (undone/closed backgrounds are separate and only appear when their own
    keys are set, which the default config does set for undone.)
    """
    cfg = _cfg()
    cfg["diagram_background_color"] = None
    cfg["bar"] = {"done_color": "#FF8C00", "undone_color": None, "frame_color": None}
    cfg["closed"] = {"background_color": None}
    out = generator.generate_puml(_items_one_task(), cfg)
    assert "BackGroundColor" not in out


def test_default_config_has_diagram_background_color_key():
    assert "diagram_background_color" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["diagram_background_color"] is None


# ---------------------------------------------------------------------------
# theme_adapter: dark-mode context switching
# ---------------------------------------------------------------------------


def _fake_config_with_dark_ctx(active, palette=None, page=None, text=None,
                               globals_light=None):
    """Build a MagicMock config plus a fake get_dark_mode_context result.

    Returns (config, patch_target) where patch_target is the fake context dict
    that a monkeypatched get_dark_mode_context should return.
    """
    config = MagicMock()
    config.doxtr_semantic_palette = {"primary": "#183060", "secondary": "#78D8F0"}
    config.doxtr_globals = {"light": globals_light or {}}
    ctx = {
        "active": active,
        "strategy": "invert" if active else "passthrough",
        "palette": palette,
        "page_color": page,
        "text_color": text,
        "invert_color": lambda c: "#DBDBDB" if c == "#000000" else c,
    }
    return config, ctx


def test_read_theme_core_dark_uses_dark_palette(monkeypatch):
    dark_palette = {
        "primary": "#E8E8E8",
        "secondary": "#B388FF",
        "page": "#242424",
    }
    config, ctx = _fake_config_with_dark_ctx(
        active=True, palette=dark_palette, page="#242424", text="#DBDBDB",
    )
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)

    # Bar done colour comes from the DARK primary, not the light palette.
    assert partial["bar"]["done_color"] == "#E8E8E8"
    # Today colour from dark secondary.
    assert partial["today"]["color"] == "#B388FF"
    # Dark diagram background = dark page colour.
    assert partial["diagram_background_color"] == "#242424"
    # Readable label colour applied to task / separator / timeline fonts.
    assert partial["fonts"]["task"]["color"] == "#DBDBDB"
    assert partial["fonts"]["separator"]["color"] == "#DBDBDB"
    assert partial["fonts"]["month"]["color"] == "#DBDBDB"
    assert partial["fonts"]["year"]["color"] == "#DBDBDB"


def test_read_theme_core_light_unchanged(monkeypatch):
    """When the context reports inactive, the light palette is used and no
    dark-only knobs are emitted (backward-compatible behaviour)."""
    config, ctx = _fake_config_with_dark_ctx(active=False)
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)

    assert partial["bar"]["done_color"] == "#183060"   # light primary
    assert partial["today"]["color"] == "#78D8F0"      # light secondary
    assert "diagram_background_color" not in partial
    assert "color" not in partial["fonts"]["task"]
    assert "month" not in partial["fonts"]
    assert "year" not in partial["fonts"]


def test_read_theme_core_helper_missing_falls_back(monkeypatch):
    """If the core does not expose get_dark_mode_context (older version), the
    adapter falls back to the light palette without raising."""
    import doxtr_pdf_theme_core as core
    # Simulate an older core lacking the helper.
    monkeypatch.delattr(core, "get_dark_mode_context", raising=False)
    config = MagicMock()
    config.doxtr_semantic_palette = {"primary": "#183060", "secondary": "#78D8F0"}
    config.doxtr_globals = {"light": {}}
    partial = theme_adapter._read_theme_core(config)
    assert partial["bar"]["done_color"] == "#183060"
    assert "diagram_background_color" not in partial


def test_read_theme_core_dark_font_size_still_parsed(monkeypatch):
    """The main_font_size parsing path still works in dark mode."""
    config, ctx = _fake_config_with_dark_ctx(
        active=True,
        palette={"primary": "#E8E8E8", "page": "#242424"},
        page="#242424", text="#DBDBDB",
        globals_light={"main_font_size": "14pt", "main_font": "Spectral"},
    )
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)
    assert partial["fonts"]["task"]["size"] == 14
    assert partial["fonts"]["task"]["name"] == "Spectral"


# ---------------------------------------------------------------------------
# get_effective_style: diagram_background_color threading
# ---------------------------------------------------------------------------


def test_effective_style_default_diagram_bg_none():
    config = MagicMock()
    config.extensions = []
    config.doxtr_roadmap_use_theme_core = False
    # Force all roadmap_* config to None so defaults apply.
    for attr in (
        "doxtr_roadmap_default_scale", "doxtr_roadmap_scale_factor",
        "doxtr_roadmap_default_start", "doxtr_roadmap_default_title",
        "doxtr_roadmap_clean_style", "doxtr_roadmap_close_weekends_on_single_period",
        "doxtr_roadmap_bar", "doxtr_roadmap_sections", "doxtr_roadmap_today",
        "doxtr_roadmap_fonts", "doxtr_roadmap_closed",
        "doxtr_roadmap_allowed_tags", "doxtr_roadmap_allowed_tag_patterns",
        "doxtr_roadmap_collision_detection",
        "doxtr_roadmap_collision_char_width_factor",
        "doxtr_roadmap_collision_gap_days", "doxtr_roadmap_column_zoom",
        "doxtr_roadmap_diagram_background_color",
    ):
        setattr(config, attr, None)
    style = theme_adapter.get_effective_style(config)
    assert style["diagram_background_color"] is None


def test_effective_style_user_diagram_bg_override():
    config = MagicMock()
    config.extensions = []
    config.doxtr_roadmap_use_theme_core = False
    for attr in (
        "doxtr_roadmap_default_scale", "doxtr_roadmap_scale_factor",
        "doxtr_roadmap_default_start", "doxtr_roadmap_default_title",
        "doxtr_roadmap_clean_style", "doxtr_roadmap_close_weekends_on_single_period",
        "doxtr_roadmap_bar", "doxtr_roadmap_sections", "doxtr_roadmap_today",
        "doxtr_roadmap_fonts", "doxtr_roadmap_closed",
        "doxtr_roadmap_allowed_tags", "doxtr_roadmap_allowed_tag_patterns",
        "doxtr_roadmap_collision_detection",
        "doxtr_roadmap_collision_char_width_factor",
        "doxtr_roadmap_collision_gap_days", "doxtr_roadmap_column_zoom",
    ):
        setattr(config, attr, None)
    config.doxtr_roadmap_diagram_background_color = "#101010"
    style = theme_adapter.get_effective_style(config)
    assert style["diagram_background_color"] == "#101010"


def test_effective_style_user_foreground_color_override():
    """A user-set doxtr_roadmap_foreground_color overrides the default (None)
    and takes the highest priority (above theme-core dark values)."""
    config = MagicMock()
    config.extensions = []
    config.doxtr_roadmap_use_theme_core = False
    for attr in (
        "doxtr_roadmap_default_scale", "doxtr_roadmap_scale_factor",
        "doxtr_roadmap_default_start", "doxtr_roadmap_default_title",
        "doxtr_roadmap_clean_style", "doxtr_roadmap_close_weekends_on_single_period",
        "doxtr_roadmap_bar", "doxtr_roadmap_sections", "doxtr_roadmap_today",
        "doxtr_roadmap_fonts", "doxtr_roadmap_closed",
        "doxtr_roadmap_allowed_tags", "doxtr_roadmap_allowed_tag_patterns",
        "doxtr_roadmap_collision_detection",
        "doxtr_roadmap_collision_char_width_factor",
        "doxtr_roadmap_collision_gap_days", "doxtr_roadmap_column_zoom",
        "doxtr_roadmap_diagram_background_color",
    ):
        setattr(config, attr, None)
    config.doxtr_roadmap_foreground_color = "#FF0000"
    style = theme_adapter.get_effective_style(config)
    assert style["foreground_color"] == "#FF0000"


# ---------------------------------------------------------------------------
# End-to-end: dark palette → generated PlantUML has dark background
# ---------------------------------------------------------------------------


def test_end_to_end_dark_puml_has_dark_background(monkeypatch):
    dark_palette = {"primary": "#E8E8E8", "secondary": "#B388FF", "page": "#242424"}
    config, ctx = _fake_config_with_dark_ctx(
        active=True, palette=dark_palette, page="#242424", text="#DBDBDB",
    )
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)

    # Merge the dark partial into an effective style the way get_effective_style
    # does, then generate.
    from doxtr_roadmap.config_defaults import _deep_merge
    effective = {
        "default_scale": "monthly", "scale_factor": 1.25,
        "default_start": "2026-01-01", "default_title": "Roadmap",
        "clean_style": True, "bar": dict(DEFAULT_CONFIG["bar"]),
        "sections": {}, "today": {}, "fonts": {k: dict(v) for k, v in DEFAULT_CONFIG["fonts"].items()},
        "closed": {}, "diagram_background_color": None,
    }
    effective = _deep_merge(effective, partial)
    out = generator.generate_puml(
        _items_one_task(), effective, project_start=datetime.date(2026, 1, 1)
    )
    assert "BackGroundColor #242424" in out       # dark diagram background
    assert "#E8E8E8" in out                        # dark done-bar colour
    assert "today is colored in #B388FF" in out    # dark today marker


# ---------------------------------------------------------------------------
# Regression: registered config defaults must not clobber theme-core dark values
# ---------------------------------------------------------------------------


def _dark_config_via_get_effective_style():
    """Build a MagicMock config whose dict-valued roadmap_* options carry the
    DEFAULT_CONFIG values (as Sphinx registers them) while theme-core reports
    dark mode. Reproduces the real build: getattr(config, 'doxtr_roadmap_bar')
    returns the *default* light bar dict even though the user set nothing.
    """
    config = MagicMock()
    config.extensions = ["doxtr_pdf_theme_core"]
    config.doxtr_roadmap_use_theme_core = "auto"
    config.doxtr_semantic_palette = {"primary": "#183060", "secondary": "#78D8F0"}
    config.doxtr_globals = {"light": {}}
    # Dict-valued options: registered with DEFAULT_CONFIG values (non-None!).
    config.doxtr_roadmap_bar = copy.deepcopy(DEFAULT_CONFIG["bar"])
    config.doxtr_roadmap_fonts = copy.deepcopy(DEFAULT_CONFIG["fonts"])
    config.doxtr_roadmap_today = copy.deepcopy(DEFAULT_CONFIG["today"])
    config.doxtr_roadmap_closed = copy.deepcopy(DEFAULT_CONFIG["closed"])
    config.doxtr_roadmap_sections = copy.deepcopy(DEFAULT_CONFIG["sections"])
    # Scalar options: registered defaults; None where DEFAULT_CONFIG is None.
    config.doxtr_roadmap_default_scale = DEFAULT_CONFIG["default_scale"]
    config.doxtr_roadmap_scale_factor = DEFAULT_CONFIG["scale_factor"]
    config.doxtr_roadmap_default_start = None
    config.doxtr_roadmap_default_title = DEFAULT_CONFIG["default_title"]
    config.doxtr_roadmap_clean_style = DEFAULT_CONFIG["clean_style"]
    config.doxtr_roadmap_close_weekends_on_single_period = \
        DEFAULT_CONFIG["close_weekends_on_single_period"]
    config.doxtr_roadmap_collision_detection = DEFAULT_CONFIG["collision_detection"]
    config.doxtr_roadmap_collision_char_width_factor = \
        DEFAULT_CONFIG["collision_char_width_factor"]
    config.doxtr_roadmap_collision_gap_days = DEFAULT_CONFIG["collision_gap_days"]
    config.doxtr_roadmap_column_zoom = DEFAULT_CONFIG["column_zoom"]
    config.doxtr_roadmap_diagram_background_color = \
        DEFAULT_CONFIG["diagram_background_color"]
    config.doxtr_roadmap_foreground_color = DEFAULT_CONFIG["foreground_color"]
    config.doxtr_roadmap_link_appendix = DEFAULT_CONFIG["link_appendix"]
    config.doxtr_roadmap_link_appendix_builders = \
        list(DEFAULT_CONFIG["link_appendix_builders"])
    config.doxtr_roadmap_link_appendix_title = DEFAULT_CONFIG["link_appendix_title"]
    config.doxtr_roadmap_figure = DEFAULT_CONFIG["figure"]
    config.doxtr_roadmap_figure_caption = DEFAULT_CONFIG["figure_caption"]
    config.doxtr_roadmap_html_format = DEFAULT_CONFIG["html_format"]
    config.doxtr_roadmap_latex_format = DEFAULT_CONFIG["latex_format"]
    config.doxtr_roadmap_period_calendars = dict(DEFAULT_CONFIG["period_calendars"])
    config.doxtr_roadmap_period_resolver_hooks = list(DEFAULT_CONFIG["period_resolver_hooks"])
    config.doxtr_roadmap_business_days = DEFAULT_CONFIG["business_days"]
    return config


def test_registered_defaults_do_not_clobber_dark_theme(monkeypatch):
    """The core bug: doxtr_roadmap_bar / _today are registered with non-None
    DEFAULT_CONFIG dicts, so a naive 'if getattr(...) is not None' merge
    re-applies the LIGHT defaults on top of the dark theme partial, turning
    dark bars back to #FF8C00. get_effective_style must diff against the
    default and keep the dark theme colours.
    """
    dark_palette = {
        "primary": "#AABBDE", "secondary": "#165B6C", "page": "#242424",
    }
    ctx = {
        "active": True, "strategy": "invert", "palette": dark_palette,
        "page_color": "#242424", "text_color": "#DBDBDB",
        "invert_color": lambda c: c,
    }
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    config = _dark_config_via_get_effective_style()
    eff = theme_adapter.get_effective_style(config)

    # Dark theme values must survive the (default-valued) user merge.
    assert eff["bar"]["done_color"] == "#AABBDE"      # NOT the light #FF8C00
    assert eff["today"]["color"] == "#165B6C"         # NOT the light #E53935
    assert eff["diagram_background_color"] == "#242424"
    assert eff["foreground_color"] == "#DBDBDB"       # root FontColor/LineColor
    assert eff["fonts"]["task"]["color"] == "#DBDBDB"
    assert eff["fonts"]["title"]["color"] == "#DBDBDB"
    # This mock uses an identity invert_color, so undone stays the cream
    # default here; the real hex_dark_invert path is covered separately in
    # test_dark_undone_and_foreground_with_real_invert.
    assert eff["bar"]["undone_color"] == "#FFF3E0"


def test_genuine_user_bar_override_still_wins(monkeypatch):
    """A real user override (value differs from DEFAULT_CONFIG) must still take
    precedence over theme-core, even in dark mode."""
    ctx = {
        "active": True, "strategy": "invert",
        "palette": {"primary": "#AABBDE", "page": "#242424"},
        "page_color": "#242424", "text_color": "#DBDBDB",
        "invert_color": lambda c: c,
    }
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    config = _dark_config_via_get_effective_style()
    # User genuinely overrides the done colour in conf.py.
    user_bar = copy.deepcopy(DEFAULT_CONFIG["bar"])
    user_bar["done_color"] = "#123456"
    config.doxtr_roadmap_bar = user_bar
    eff = theme_adapter.get_effective_style(config)
    assert eff["bar"]["done_color"] == "#123456"  # user wins over theme dark


def test_dict_diff_helper():
    assert theme_adapter._dict_diff({"a": 1, "b": 2}, {"a": 1, "b": 9}) == {"b": 9}
    assert theme_adapter._dict_diff({"x": {"y": 1}}, {"x": {"y": 1, "z": 2}}) == {"x": {"z": 2}}
    assert theme_adapter._dict_diff({"a": 1}, {"a": 1}) == {}
    assert theme_adapter._dict_diff({}, {"new": 5}) == {"new": 5}
    # None-override: a None value in actual is a genuine override, not "absent"
    assert theme_adapter._dict_diff({"a": "#FF8C00"}, {"a": None}) == {"a": None}
    # Type-mismatch: if actual replaces a dict with a scalar, the scalar wins
    assert theme_adapter._dict_diff({"a": {"x": 1}}, {"a": "replaced"}) == {"a": "replaced"}


# ---------------------------------------------------------------------------
# generator: foreground_color root FontColor/LineColor
# ---------------------------------------------------------------------------


def test_foreground_color_emitted_as_root_fontcolor():
    out = generator.generate_puml(
        _items_one_task(), _cfg(foreground_color="#DBDBDB"),
        project_start=datetime.date(2026, 1, 1),
    )
    style = out[out.index("<style>"):out.index("</style>")]
    # Root-level (not inside a task {} sub-block) FontColor + LineColor.
    assert "   FontColor #DBDBDB" in style
    assert "   LineColor #DBDBDB" in style


def test_foreground_color_absent_by_default():
    cfg = _cfg()
    cfg["foreground_color"] = None
    out = generator.generate_puml(_items_one_task(), cfg)
    style = out[out.index("<style>"):out.index("</style>")]
    # No root-level FontColor line (task sub-block may still have one only if
    # fonts.task.color is set, which the default config leaves as None).
    assert "   FontColor" not in style


def test_default_config_has_foreground_color_key():
    assert "foreground_color" in DEFAULT_CONFIG
    assert DEFAULT_CONFIG["foreground_color"] is None


def test_title_color_via_creole():
    """fonts.title.color renders as an inline <color:...> creole tag."""
    cfg = _cfg()
    cfg["fonts"]["title"] = {"name": None, "size": 24, "style": "bold", "color": "#DBDBDB"}
    out = generator.generate_puml(
        _items_one_task(), cfg, project_start=datetime.date(2026, 1, 1),
        title="My Title",
    )
    assert "<color:#DBDBDB>" in out
    assert "My Title" in out


# ---------------------------------------------------------------------------
# adapter: real hex_dark_invert path for undone + foreground + title
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(_dptc, "hex_dark_invert")
    or not hasattr(_dptc, "get_dark_mode_context"),
    reason="requires doxtr-pdf-theme-core with hex_dark_invert and "
    "get_dark_mode_context (>=1.1.9)",
)
def test_dark_undone_and_foreground_with_real_invert(monkeypatch):
    """Using theme-core's real get_dark_mode_context (real hex_dark_invert),
    the dark path must set foreground_color, a dark undone bar, and a title
    colour so timeline headers, milestone labels, in-bar labels and the title
    are all legible on the dark page."""
    import doxtr_pdf_theme_core as core

    config = MagicMock()
    config.doxtr_dark_mode = True
    config.doxtr_dark_mode_strategy_resolved = "invert"
    config.doxtr_dark_semantic_palette = {
        "primary": "#AABBDE", "secondary": "#165B6C", "page": "#242424",
    }
    config.doxtr_dark_text_color = "#DBDBDB"
    config.doxtr_semantic_palette = {"primary": "#183060", "secondary": "#78D8F0"}
    config.doxtr_globals = {"light": {}}

    partial = theme_adapter._read_theme_core(config)

    assert partial["foreground_color"] == "#DBDBDB"
    assert partial["fonts"]["title"]["color"] == "#DBDBDB"
    # Undone cream #FFF3E0 must be soft-inverted to a dark shade (not left light).
    undone = partial["bar"]["undone_color"]
    assert undone != "#FFF3E0"
    assert undone.lower() == core.hex_dark_invert("#FFF3E0").lower()
    # The dark undone must actually be dark (low luminance).
    from doxtr_pdf_theme_core.utils import _get_luminance
    assert _get_luminance(undone) < 0.3


# ---------------------------------------------------------------------------
# D3. invert(seed) fallback when text_color is None
# ---------------------------------------------------------------------------


def test_read_theme_core_dark_invert_fallback_for_text_color(monkeypatch):
    """dark active, text_color=None → label_color = invert(_DARK_LABEL_INVERT_SEED)."""
    invert_fn = lambda c: "#DBDBDB" if c == "#000000" else c  # noqa: E731
    config, ctx = _fake_config_with_dark_ctx(
        active=True,
        palette={"primary": "#E8E8E8"},
        page="#242424",
        text=None,  # text_color absent
    )
    ctx["invert_color"] = invert_fn
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)
    # label_color = None or invert("#000000") = "#DBDBDB"
    assert partial["fonts"]["task"]["color"] == "#DBDBDB"
    assert partial["fonts"]["separator"]["color"] == "#DBDBDB"


# ---------------------------------------------------------------------------
# D4. bar.frame_color setdefault semantics
# ---------------------------------------------------------------------------


def test_read_theme_core_dark_frame_color_set_to_text_color(monkeypatch):
    """(a) frame_color not pre-existing → set to text_color."""
    config, ctx = _fake_config_with_dark_ctx(
        active=True,
        palette={"primary": "#E8E8E8"},
        page="#242424",
        text="#DBDBDB",
    )
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)
    assert partial["bar"]["frame_color"] == "#DBDBDB"  # text_color wins


def test_read_theme_core_dark_frame_color_falls_back_to_primary(monkeypatch):
    """(a) frame_color not pre-existing, text_color=None → set to primary."""
    config, ctx = _fake_config_with_dark_ctx(
        active=True,
        palette={"primary": "#E8E8E8"},
        page="#242424",
        text=None,
    )
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)
    assert partial["bar"]["frame_color"] == "#E8E8E8"  # falls back to primary


# ---------------------------------------------------------------------------
# D5. separator sans_font mapping
# ---------------------------------------------------------------------------


def test_read_theme_core_separator_sans_font(monkeypatch):
    """globals_light sans_font → partial['fonts']['separator']['name']."""
    config, ctx = _fake_config_with_dark_ctx(
        active=False,
        globals_light={"sans_font": "SomeSans"},
    )
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context", lambda c: ctx, raising=False
    )
    partial = theme_adapter._read_theme_core(config)
    assert partial["fonts"]["separator"]["name"] == "SomeSans"


# ---------------------------------------------------------------------------
# D6. Smoke-test the real get_dark_mode_context (skipped on core < 1.1.9)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not hasattr(_dptc, "get_dark_mode_context"),
    reason="requires doxtr-pdf-theme-core >= 1.1.9",
)
def test_real_get_dark_mode_context_returns_dict_with_active():
    """Real get_dark_mode_context returns a dict-like with an 'active' key."""
    config = MagicMock()
    ctx = _dptc.get_dark_mode_context(config)
    assert isinstance(ctx, dict)
    assert "active" in ctx


# ---------------------------------------------------------------------------
# D7. get_effective_style string values for use_theme_core
# ---------------------------------------------------------------------------


_COMMON_NONE_ATTRS = (
    "doxtr_roadmap_default_scale", "doxtr_roadmap_scale_factor",
    "doxtr_roadmap_default_start", "doxtr_roadmap_default_title",
    "doxtr_roadmap_clean_style", "doxtr_roadmap_close_weekends_on_single_period",
    "doxtr_roadmap_bar", "doxtr_roadmap_sections", "doxtr_roadmap_today",
    "doxtr_roadmap_fonts", "doxtr_roadmap_closed",
    "doxtr_roadmap_allowed_tags", "doxtr_roadmap_allowed_tag_patterns",
    "doxtr_roadmap_collision_detection",
    "doxtr_roadmap_collision_char_width_factor",
    "doxtr_roadmap_collision_gap_days", "doxtr_roadmap_column_zoom",
    "doxtr_roadmap_diagram_background_color",
)


def test_effective_style_use_theme_core_string_true(monkeypatch):
    """use_theme_core='true' (string) enables theme-core integration."""
    monkeypatch.setattr(
        "doxtr_pdf_theme_core.get_dark_mode_context",
        lambda c: {"active": False},
        raising=False,
    )
    config = MagicMock()
    config.extensions = ["doxtr_pdf_theme_core"]
    config.doxtr_roadmap_use_theme_core = "true"
    config.doxtr_semantic_palette = {"primary": "#AABBCC", "secondary": "#112233"}
    config.doxtr_globals = {"light": {}}
    for attr in _COMMON_NONE_ATTRS:
        setattr(config, attr, None)
    style = theme_adapter.get_effective_style(config)
    # Theme-core enabled: done_color sourced from light primary (dark inactive)
    assert style["bar"]["done_color"] == "#AABBCC"


def test_effective_style_use_theme_core_string_false():
    """use_theme_core='false' (string) disables theme-core integration."""
    config = MagicMock()
    config.extensions = ["doxtr_pdf_theme_core"]
    config.doxtr_roadmap_use_theme_core = "false"
    config.doxtr_semantic_palette = {"primary": "#AABBCC"}
    config.doxtr_globals = {"light": {}}
    for attr in _COMMON_NONE_ATTRS:
        setattr(config, attr, None)
    style = theme_adapter.get_effective_style(config)
    # Theme-core disabled: done_color stays at the DEFAULT_CONFIG value
    assert style["bar"]["done_color"] == DEFAULT_CONFIG["bar"]["done_color"]

