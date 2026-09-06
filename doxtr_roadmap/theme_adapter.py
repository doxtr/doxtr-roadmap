"""Theme-core adapter for doxtr_roadmap.

Isolates all interaction with ``doxtr_pdf_theme_core``.  The extension operates
correctly without theme-core installed; when theme-core is active its semantic
palette and typography are mapped to roadmap style knobs.

No ``import doxtr_pdf_theme_core`` is performed at runtime; instead the adapter
reads config attributes set by theme-core's own ``setup()`` via
``getattr(config, 'doxtr_semantic_palette', None)``.  This avoids a hard
dependency on the theme-core package.
"""

from sphinx.util import logging
from .config_defaults import DEFAULT_CONFIG, _deep_merge

logger = logging.getLogger(__name__)


def _read_theme_core(config) -> dict:
    """Extract style knobs from a loaded doxtr_pdf_theme_core config.

    Reads ``config.doxtr_semantic_palette`` and
    ``config.doxtr_globals['light']`` and maps them to roadmap style keys.
    Returns only the keys that could be read; missing keys are not included,
    so callers can merge with a lower-priority base dict.

    Parameters
    ----------
    config:
        Sphinx config object (already confirmed to have theme-core attributes).

    Returns
    -------
    dict
        Partial style dict with any of: ``bar.done_color``,
        ``today.color``, ``fonts.task.name``, ``fonts.task.size``,
        ``fonts.separator.name``.
    """
    palette = getattr(config, "doxtr_semantic_palette", None) or {}
    doxtr_globals = getattr(config, "doxtr_globals", None) or {}
    globals_light = doxtr_globals.get("light", {}) or {}

    partial: dict = {"bar": {}, "today": {}, "fonts": {"task": {}, "separator": {}}}

    primary = palette.get("primary")
    if primary:
        partial["bar"]["done_color"] = primary

    secondary = palette.get("secondary")
    danger = palette.get("danger")
    today_color = secondary or danger
    if today_color:
        partial["today"]["color"] = today_color

    main_font = globals_light.get("main_font")
    if main_font:
        partial["fonts"]["task"]["name"] = main_font

    main_font_size = globals_light.get("main_font_size")
    if main_font_size is not None:
        try:
            partial["fonts"]["task"]["size"] = int(str(main_font_size).replace("pt", ""))
        except (ValueError, AttributeError):
            pass

    sans_font = globals_light.get("sans_font")
    if sans_font:
        partial["fonts"]["separator"]["name"] = sans_font

    return partial


def get_effective_style(config) -> dict:
    """Return the effective style knobs for the gantt generator.

    Merges (lowest to highest priority):

    1. ``DEFAULT_CONFIG`` values from :mod:`config_defaults`.
    2. Theme-core adapter output (if ``use_theme_core`` is active).
    3. ``doxtr_roadmap_*`` config values set by the user in ``conf.py``.

    Parameters
    ----------
    config:
        Sphinx config object.

    Returns
    -------
    dict
        Flat-ish style dict suitable for passing to
        :func:`generator.generate_puml` (keys: ``bar``, ``fonts``, ``today``,
        ``closed``, ``clean_style``, ``close_weekends_on_single_period``,
        ``default_scale``, ``default_start``, ``default_title``,
        ``scale_factor``, ``sections``).
    """
    # Start from defaults
    effective = {
        "default_scale": DEFAULT_CONFIG["default_scale"],
        "scale_factor": DEFAULT_CONFIG["scale_factor"],
        "default_start": DEFAULT_CONFIG["default_start"],
        "default_title": DEFAULT_CONFIG["default_title"],
        "clean_style": DEFAULT_CONFIG["clean_style"],
        "close_weekends_on_single_period": DEFAULT_CONFIG["close_weekends_on_single_period"],
        "bar":     dict(DEFAULT_CONFIG["bar"]),
        "sections": dict(DEFAULT_CONFIG["sections"]),
        "today":   dict(DEFAULT_CONFIG["today"]),
        "fonts":   {k: dict(v) for k, v in DEFAULT_CONFIG["fonts"].items()},
        "closed":  dict(DEFAULT_CONFIG["closed"]),
        "collision_detection": DEFAULT_CONFIG["collision_detection"],
        "collision_char_width_factor": DEFAULT_CONFIG["collision_char_width_factor"],
        "collision_gap_days": DEFAULT_CONFIG["collision_gap_days"],
        "column_zoom": DEFAULT_CONFIG["column_zoom"],
        "link_appendix": DEFAULT_CONFIG["link_appendix"],
        "link_appendix_builders": list(DEFAULT_CONFIG["link_appendix_builders"]),
        "link_appendix_title": DEFAULT_CONFIG["link_appendix_title"],
        "figure": DEFAULT_CONFIG["figure"],
        "figure_caption": DEFAULT_CONFIG["figure_caption"],
    }

    # Resolve use_theme_core: "auto" → True iff core is in extensions
    raw_use_theme_core = getattr(config, "doxtr_roadmap_use_theme_core", "auto")
    if isinstance(raw_use_theme_core, str):
        if raw_use_theme_core.lower() in ("true", "1"):
            use_theme_core = True
        elif raw_use_theme_core.lower() in ("false", "0"):
            use_theme_core = False
        else:  # "auto"
            use_theme_core = "doxtr_pdf_theme_core" in (
                getattr(config, "extensions", None) or []
            )
    else:
        use_theme_core = bool(raw_use_theme_core)

    if use_theme_core:
        # Check core is actually loaded
        core_present = "doxtr_pdf_theme_core" in (
            getattr(config, "extensions", None) or []
        )
        if not core_present:
            logger.warning(
                "doxtr-roadmap: doxtr_roadmap_use_theme_core=True but "
                "'doxtr_pdf_theme_core' is not in extensions; "
                "falling back to default style."
            )
        else:
            theme_partial = _read_theme_core(config)
            effective = _deep_merge(effective, theme_partial)

    # Apply user-configured doxtr_roadmap_* values on top (highest priority)
    def _attr(name, fallback):
        val = getattr(config, name, None)
        return val if val is not None else fallback

    user_bar = _attr("doxtr_roadmap_bar", None)
    if user_bar:
        effective["bar"] = _deep_merge(effective["bar"], user_bar)

    user_fonts = _attr("doxtr_roadmap_fonts", None)
    if user_fonts:
        effective["fonts"] = _deep_merge(effective["fonts"], user_fonts)

    user_today = _attr("doxtr_roadmap_today", None)
    if user_today:
        effective["today"] = _deep_merge(effective["today"], user_today)

    user_closed = _attr("doxtr_roadmap_closed", None)
    if user_closed:
        effective["closed"] = _deep_merge(effective["closed"], user_closed)

    user_sections = _attr("doxtr_roadmap_sections", None)
    if user_sections:
        effective["sections"] = _deep_merge(effective["sections"], user_sections)

    for simple_key, cfg_key in (
        ("default_scale", "doxtr_roadmap_default_scale"),
        ("scale_factor", "doxtr_roadmap_scale_factor"),
        ("default_start", "doxtr_roadmap_default_start"),
        ("default_title", "doxtr_roadmap_default_title"),
        ("clean_style", "doxtr_roadmap_clean_style"),
        ("close_weekends_on_single_period",
         "doxtr_roadmap_close_weekends_on_single_period"),
        ("collision_detection", "doxtr_roadmap_collision_detection"),
        ("collision_char_width_factor",
         "doxtr_roadmap_collision_char_width_factor"),
        ("collision_gap_days", "doxtr_roadmap_collision_gap_days"),
        ("column_zoom", "doxtr_roadmap_column_zoom"),
        ("link_appendix", "doxtr_roadmap_link_appendix"),
        ("link_appendix_builders", "doxtr_roadmap_link_appendix_builders"),
        ("link_appendix_title", "doxtr_roadmap_link_appendix_title"),
        ("figure", "doxtr_roadmap_figure"),
        ("figure_caption", "doxtr_roadmap_figure_caption"),
    ):
        val = getattr(config, cfg_key, None)
        if val is not None:
            effective[simple_key] = val

    return effective
