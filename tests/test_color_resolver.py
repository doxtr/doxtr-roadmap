"""Unit tests for doxtr_roadmap/color_resolver.py."""

import pytest

from doxtr_roadmap import color_resolver
from doxtr_roadmap.color_resolver import (
    ColorResolver,
    derive_frame_color,
    _relative_luminance,
    _rgb_distance,
)

# theme-core is an optional dependency; most resolution tests need it.
core = color_resolver._theme_core()
requires_core = pytest.mark.skipif(core is None, reason="doxtr_pdf_theme_core not installed")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_relative_luminance_extremes():
    assert _relative_luminance("#000000") == pytest.approx(0.0, abs=1e-6)
    assert _relative_luminance("#FFFFFF") == pytest.approx(1.0, abs=1e-6)


def test_relative_luminance_ignores_alpha_and_shortforms():
    assert _relative_luminance("#FFFFFFFF") == pytest.approx(1.0, abs=1e-6)
    assert _relative_luminance("#FFF") == pytest.approx(1.0, abs=1e-6)


def test_relative_luminance_invalid_is_zero():
    assert _relative_luminance("not-a-color") == 0.0
    assert _relative_luminance("") == 0.0


def test_rgb_distance():
    assert _rgb_distance("#000000", "#FFFFFF") == 765
    assert _rgb_distance("#123456", "#123456") == 0
    assert _rgb_distance("#010000", "#000000") == 1


# ---------------------------------------------------------------------------
# derive_frame_color
# ---------------------------------------------------------------------------

@requires_core
def test_frame_light_fill_is_darkened():
    """A light fill yields a darker (lower-luminance) frame."""
    frame = derive_frame_color("#F0F0F0", 30)
    assert frame is not None
    assert _relative_luminance(frame) < _relative_luminance("#F0F0F0")


@requires_core
def test_frame_dark_fill_is_lightened():
    frame = derive_frame_color("#123456", 30)
    assert frame is not None
    assert _relative_luminance(frame) > _relative_luminance("#123456")


@requires_core
def test_frame_pure_black_lightened_not_stuck():
    """Pure black cannot be darkened, so it must be lightened to a visible grey."""
    frame = derive_frame_color("#000000", 30)
    assert frame is not None
    assert _rgb_distance(frame, "#000000") >= color_resolver._MIN_FRAME_DISTANCE


@requires_core
def test_frame_pure_white_darkened_not_stuck():
    frame = derive_frame_color("#FFFFFF", 30)
    assert frame is not None
    assert _rgb_distance(frame, "#FFFFFF") >= color_resolver._MIN_FRAME_DISTANCE


@requires_core
def test_frame_preserves_alpha():
    frame = derive_frame_color("#4567896F", 30)
    assert frame is not None
    assert frame.upper().endswith("6F")


@requires_core
def test_frame_configurable_delta():
    """A larger delta produces a frame further from the fill."""
    small = derive_frame_color("#808080", 10)
    large = derive_frame_color("#808080", 50)
    assert _rgb_distance(large, "#808080") > _rgb_distance(small, "#808080")


def test_frame_zero_delta_disabled():
    assert derive_frame_color("#FF8C00", 0) is None


def test_frame_invalid_delta_disabled():
    assert derive_frame_color("#FF8C00", "nope") is None


def test_frame_none_input_disabled():
    assert derive_frame_color("", 30) is None
    assert derive_frame_color(None, 30) is None


# ---------------------------------------------------------------------------
# ColorResolver.resolve
# ---------------------------------------------------------------------------

def _light_resolver(delta=30):
    return ColorResolver(
        palette={"primary": "#3366CC", "secondary": "#CC3366", "page": "#FFFFFF"},
        page_bg="#FFFFFF",
        dark_active=False,
        invert=lambda c: c,
        frame_delta=delta,
        core=core,
    )


def test_resolve_none_returns_defaults():
    r = _light_resolver()
    done, frame = r.resolve(None, "#FF8C00", "#AABBCC")
    assert done == "#FF8C00"
    assert frame == "#AABBCC"


def test_resolve_hex_light_passthrough():
    r = _light_resolver()
    done, frame = r.resolve("#123456", "#FF8C00", None)
    assert done == "#123456"
    if core is not None:
        assert frame is not None  # frame derived from the fill


@requires_core
def test_resolve_dd_primary():
    r = _light_resolver()
    done, _frame = r.resolve("dd:primary", "#FF8C00", None)
    assert done == "#3366CC"


@requires_core
def test_resolve_dd_inline_operation():
    r = _light_resolver()
    done, _frame = r.resolve("dd:#FFCC00:lighten:50", "#FF8C00", None)
    assert done.startswith("#")
    assert done != "#FF8C00"


@requires_core
def test_resolve_unknown_dd_key_falls_back(caplog):
    r = _light_resolver()
    done, frame = r.resolve("dd:nonexistent", "#FF8C00", "#DEFA17")
    assert done == "#FF8C00"
    assert frame == "#DEFA17"


@requires_core
def test_resolve_explicit_red_dd_not_treated_as_error():
    r = _light_resolver()
    done, _frame = r.resolve("dd:#ff0000", "#FF8C00", None)
    assert done.lower() == "#ff0000"


def test_resolve_dd_without_core_warns_and_falls_back(caplog):
    r = ColorResolver(
        palette={}, page_bg=None, dark_active=False,
        invert=lambda c: c, frame_delta=30, core=None,
    )
    done, frame = r.resolve("dd:primary", "#FF8C00", "#DEFA17")
    assert done == "#FF8C00"
    assert frame == "#DEFA17"


def test_resolve_dd_without_core_warns_once(caplog):
    import logging
    r = ColorResolver(
        palette={}, page_bg=None, dark_active=False,
        invert=lambda c: c, frame_delta=30, core=None,
    )
    with caplog.at_level(logging.WARNING):
        r.resolve("dd:primary", "#FF8C00", None)
        r.resolve("dd:secondary", "#FF8C00", None)
    warnings = [rec for rec in caplog.records if "requires" in rec.getMessage()]
    assert len(warnings) == 1  # warned only once per resolver


@requires_core
def test_resolve_hex_dark_mode_inverts():
    inv = core.hex_dark_invert
    r = ColorResolver(
        palette={"primary": "#99BBFF"}, page_bg="#1A1A1A",
        dark_active=True, invert=inv, frame_delta=30, core=core,
    )
    done, _frame = r.resolve("#FF8C00", "#FF8C00", None)
    assert done != "#FF8C00"          # inverted for the dark page
    assert done == inv("#FF8C00")


@requires_core
def test_resolve_dd_dark_mode_uses_dark_palette():
    inv = core.hex_dark_invert
    r = ColorResolver(
        palette={"primary": "#99BBFF"}, page_bg="#1A1A1A",
        dark_active=True, invert=inv, frame_delta=30, core=core,
    )
    done, _frame = r.resolve("dd:primary", "#FF8C00", None)
    assert done == "#99BBFF"          # the dark palette value, not the default


# ---------------------------------------------------------------------------
# _merged_light_palette / from_config
# ---------------------------------------------------------------------------

class _FakeConfig:
    """Minimal stand-in for a Sphinx config object."""
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


@requires_core
def test_merged_light_palette_includes_core_defaults():
    """Core palette keys (e.g. 'primary') resolve even without user overrides."""
    from doxtr_pdf_theme_core.core_config import DOXTR_SEMANTIC_PALETTE
    cfg = _FakeConfig(doxtr_semantic_palette={})  # user set nothing
    palette = color_resolver._merged_light_palette(cfg, core)
    assert palette.get("primary") == DOXTR_SEMANTIC_PALETTE["primary"]


@requires_core
def test_merged_light_palette_user_overrides_core():
    cfg = _FakeConfig(doxtr_semantic_palette={"primary": "#AA00BB"})
    palette = color_resolver._merged_light_palette(cfg, core)
    assert palette["primary"] == "#AA00BB"


@requires_core
def test_merged_light_palette_strips_dark_subkey():
    cfg = _FakeConfig(doxtr_semantic_palette={"dark": {"primary": "#000"}})
    palette = color_resolver._merged_light_palette(cfg, core)
    assert "dark" not in palette


@requires_core
def test_from_config_light_resolves_core_primary():
    """A resolver built from a bare config resolves dd:primary via core defaults."""
    from doxtr_pdf_theme_core.core_config import DOXTR_SEMANTIC_PALETTE
    cfg = _FakeConfig(doxtr_semantic_palette={})
    r = ColorResolver.from_config(cfg, frame_delta=30)
    done, _frame = r.resolve("dd:primary", "#FF8C00", None)
    assert done == DOXTR_SEMANTIC_PALETTE["primary"]


# ---------------------------------------------------------------------------
# derive_undone_color
# ---------------------------------------------------------------------------

from doxtr_roadmap.color_resolver import derive_undone_color, _adjust_brightness


def test_undone_light_mode_is_lighter():
    undone = derive_undone_color("#FF8C00", 88.7, dark_mode=False)
    assert undone is not None
    assert _relative_luminance(undone) > _relative_luminance("#FF8C00")


def test_undone_dark_mode_is_darker():
    undone = derive_undone_color("#FF8C00", 88.7, dark_mode=True)
    assert undone is not None
    assert _relative_luminance(undone) < _relative_luminance("#FF8C00")


def test_undone_default_delta_reproduces_historical_pair():
    """Lightening #FF8C00 by the default 88.7% approximates the old #FFF3E0."""
    undone = derive_undone_color("#FF8C00", 88.7, dark_mode=False)
    assert _rgb_distance(undone, "#FFF3E0") < 12  # within a couple of levels/channel


def test_undone_zero_delta_disabled():
    assert derive_undone_color("#FF8C00", 0, dark_mode=False) is None


def test_undone_invalid_delta_disabled():
    assert derive_undone_color("#FF8C00", "x", dark_mode=False) is None


def test_undone_configurable_delta():
    small = derive_undone_color("#1976D2", 20, dark_mode=False)
    large = derive_undone_color("#1976D2", 80, dark_mode=False)
    assert _rgb_distance(large, "#1976D2") > _rgb_distance(small, "#1976D2")


def test_adjust_brightness_pure_python_matches_formula():
    # Lighten grey by 50%: 128 + (255-128)*0.5 = 191.5 -> 192 (0xC0)
    assert _adjust_brightness("#808080", 50) == "#C0C0C0"
    # Darken grey by 50%: 128 * 0.5 = 64 (0x40)
    assert _adjust_brightness("#808080", -50) == "#404040"


def test_adjust_brightness_preserves_alpha():
    out = _adjust_brightness("#8080806F", 50)
    assert out.upper().endswith("6F")


# ---------------------------------------------------------------------------
# _parse_rgb (single canonical hex parser)
# ---------------------------------------------------------------------------

from doxtr_roadmap.color_resolver import _parse_rgb


def test_parse_rgb_forms():
    assert _parse_rgb("#FF8C00") == ((255, 140, 0), "")
    assert _parse_rgb("FF8C00") == ((255, 140, 0), "")       # no leading #
    assert _parse_rgb("#F80") == ((255, 136, 0), "")          # 3-digit expands
    assert _parse_rgb("#FF8C006F") == ((255, 140, 0), "6F")   # 8-digit alpha
    assert _parse_rgb("#F806") == ((255, 136, 0), "66")       # 4-digit + alpha


def test_parse_rgb_invalid():
    assert _parse_rgb("") is None
    assert _parse_rgb(None) is None
    assert _parse_rgb("#12345") is None       # wrong length
    assert _parse_rgb("#GGGGGG") is None      # non-hex


# ---------------------------------------------------------------------------
# _merged_light_palette — theme-tier merge and no-core fallback
# ---------------------------------------------------------------------------

class _CfgObj:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def test_merged_light_palette_theme_tier_merge():
    """core <- theme <- user precedence; theme tier is honoured."""
    cfg = _CfgObj(
        doxtr_semantic_palette={"primary": "#USR001"[:7]},  # user wins for primary
        doxtr_theme_defaults={"semantic_palette": {
            "primary": "#THM001"[:7], "accent": "#THM0A0"[:7],
        }},
    )
    # Use a fake core with a DOXTR_SEMANTIC_PALETTE attribute so the merge runs
    # even if the real theme-core is absent (fallback branch), and to isolate
    # the merge order from the installed palette.
    class _FakeCore:
        pass
    # Force the ImportError fallback path (getattr(core, "DOXTR_SEMANTIC_PALETTE")).
    fake = _FakeCore()
    fake.DOXTR_SEMANTIC_PALETTE = {"primary": "#COR001"[:7], "base": "#COR0B0"[:7]}
    # Patch the hard import inside _merged_light_palette to fail so the
    # getattr(core, ...) fallback is exercised deterministically.
    import builtins
    real_import = builtins.__import__

    def _blocked_import(name, *a, **k):
        if name == "doxtr_pdf_theme_core.core_config":
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    builtins.__import__ = _blocked_import
    try:
        palette = color_resolver._merged_light_palette(cfg, fake)
    finally:
        builtins.__import__ = real_import

    assert palette["base"] == "#COR0B0"[:7]       # core-only key
    assert palette["accent"] == "#THM0A0"[:7]     # theme-only key
    assert palette["primary"] == "#USR001"[:7]    # user overrides core+theme


def test_merged_light_palette_no_core_defaults():
    """When neither import nor attr yields core defaults, merge still works."""
    cfg = _CfgObj(doxtr_semantic_palette={"primary": "#ABCDEF"})

    class _BareCore:
        pass  # no DOXTR_SEMANTIC_PALETTE attribute

    import builtins
    real_import = builtins.__import__

    def _blocked_import(name, *a, **k):
        if name == "doxtr_pdf_theme_core.core_config":
            raise ImportError("blocked")
        return real_import(name, *a, **k)

    builtins.__import__ = _blocked_import
    try:
        palette = color_resolver._merged_light_palette(cfg, _BareCore())
    finally:
        builtins.__import__ = real_import
    assert palette == {"primary": "#ABCDEF"}


# ---------------------------------------------------------------------------
# Pure-Python brightness fallback (theme-core dispatch disabled)
# ---------------------------------------------------------------------------

def test_adjust_brightness_pure_python_when_core_absent(monkeypatch):
    """With _theme_core() returning None, the pure-Python path is used."""
    monkeypatch.setattr(color_resolver, "_theme_core", lambda: None)
    # Lighten grey by 50%: 128 + (255-128)*0.5 = 191.5 -> 192 (0xC0)
    assert color_resolver._adjust_brightness("#808080", 50) == "#C0C0C0"
    assert color_resolver._adjust_brightness("#808080", -50) == "#404040"
    assert color_resolver._adjust_brightness("#8080806F", 50).upper().endswith("6F")
    assert color_resolver._adjust_brightness("", 30) is None


def test_relative_luminance_pure_python_when_core_absent(monkeypatch):
    monkeypatch.setattr(color_resolver, "_theme_core", lambda: None)
    assert _relative_luminance("#000000") == pytest.approx(0.0, abs=1e-6)
    assert _relative_luminance("#FFFFFF") == pytest.approx(1.0, abs=1e-6)
    assert _relative_luminance("nothex") == 0.0


def test_frame_derivation_without_core(monkeypatch):
    """Frame derivation works even when theme-core is unavailable."""
    monkeypatch.setattr(color_resolver, "_theme_core", lambda: None)
    frame = derive_frame_color("#123456", 30)
    assert frame is not None and frame.startswith("#")


def test_undone_derivation_without_core(monkeypatch):
    from doxtr_roadmap.color_resolver import derive_undone_color
    monkeypatch.setattr(color_resolver, "_theme_core", lambda: None)
    light = derive_undone_color("#FF8C00", 88.7, dark_mode=False)
    assert _relative_luminance(light) > _relative_luminance("#FF8C00")
