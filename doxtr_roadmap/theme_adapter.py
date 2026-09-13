"""Theme-core adapter for doxtr_roadmap.

Isolates all interaction with ``doxtr_pdf_theme_core``.  The extension operates
correctly without theme-core installed; when theme-core is active its semantic
palette and typography are mapped to roadmap style knobs.

In dark mode a guarded dynamic import of ``get_dark_mode_context`` is attempted
at runtime (with graceful fallback on older cores that do not expose the
helper).  All other interaction with theme-core reads config attributes set by
theme-core's own ``setup()`` via ``getattr(config, 'doxtr_semantic_palette',
None)``, avoiding a hard build-time dependency on the package.
"""

from sphinx.util import logging
from .config_defaults import DEFAULT_CONFIG, _deep_merge

logger = logging.getLogger(__name__)

# Seed colour used when the dark-mode context provides no text_color and we
# must derive a readable label by soft-inverting the default black.
_DARK_LABEL_INVERT_SEED = "#000000"


def _dict_diff(default: dict, actual: dict) -> dict:
    """Return the sub-tree of *actual* that differs from *default*.

    Used to recover the user's genuine ``conf.py`` overrides from a config
    value that was registered with a non-None default dict. Keys whose value
    equals the default are dropped; nested dicts are diffed recursively; keys
    present in *actual* but not *default* are kept as-is.

    A ``None`` value in *actual* is treated as a genuine override and
    included in the diff — it overrides the default / theme-core value.

    Examples
    --------
    >>> _dict_diff({"a": 1, "b": 2}, {"a": 1, "b": 9})
    {'b': 9}
    >>> _dict_diff({"x": {"y": 1}}, {"x": {"y": 1, "z": 2}})
    {'x': {'z': 2}}
    >>> _dict_diff({"a": 1}, {"a": 1})
    {}
    """
    diff: dict = {}
    for key, act_val in actual.items():
        if key not in default:
            diff[key] = act_val
            continue
        def_val = default[key]
        if isinstance(act_val, dict) and isinstance(def_val, dict):
            nested = _dict_diff(def_val, act_val)
            if nested:
                diff[key] = nested
        elif act_val != def_val:
            diff[key] = act_val
    return diff


def _get_dark_mode_context(config):
    """Guarded call to ``doxtr_pdf_theme_core.get_dark_mode_context``.

    This is the sole integration point used by ``_read_theme_core`` to
    determine whether dark mode is active and to retrieve the dark palette.

    Returns the context dict (containing at least an ``"active"`` key) or
    ``None`` when the helper is not available (older core, not installed).
    On any ``Exception`` raised by the call the error is logged at DEBUG
    level and ``None`` is returned, degrading to the light palette rather
    than failing the whole Sphinx build.  Importing inside the function
    ensures monkeypatching in tests is respected.
    """
    try:
        from doxtr_pdf_theme_core import get_dark_mode_context
    except ImportError:
        return None
    try:
        return get_dark_mode_context(config)
    except Exception:
        logger.debug(
            "[doxtr-roadmap] get_dark_mode_context failed; "
            "falling back to light palette",
            exc_info=True,
        )
        return None


def _read_theme_core(config) -> dict:
    """Extract style knobs from a loaded doxtr_pdf_theme_core config.

    Reads ``config.doxtr_semantic_palette`` and
    ``config.doxtr_globals['light']`` and maps them to roadmap style keys.
    Returns only the keys that could be read; missing keys are not included,
    so callers can merge with a lower-priority base dict.

    Dark mode
    ~~~~~~~~~
    When theme-core reports that dark mode is active (via its public
    ``get_dark_mode_context`` helper), the *dark* semantic palette is used
    instead of the light one, and additional dark-appropriate knobs are set:
    the diagram background is set to the dark page colour, and task /
    separator / timeline fonts are given a readable light colour. This lets
    the generated Gantt render natively for the dark PDF instead of relying on
    theme-core's lossy per-pixel image inversion (roadmap generates its
    PlantUML source *inline*, so the ``_dark`` file-swap cannot help it).

    Parameters
    ----------
    config:
        Sphinx config object (already confirmed to have theme-core attributes).

    Returns
    -------
    dict
        Partial style dict with any of: ``bar.done_color``, ``bar.frame_color``,
        ``today.color``, ``diagram_background_color``, ``foreground_color``,
        ``fonts.*.name``, ``fonts.*.color``, ``fonts.task.size``.
    """
    doxtr_globals = getattr(config, "doxtr_globals", None) or {}
    globals_light = doxtr_globals.get("light", {}) or {}

    partial: dict = {
        "bar": {},
        "today": {},
        "fonts": {
            "task": {},
            "separator": {},
        },
    }

    # --- Resolve the effective palette (light vs dark) --------------------
    # Prefer theme-core's public dark-mode context helper. It encodes the
    # correct activation logic (dark mode on AND strategy 'invert'); in
    # 'passthrough' mode it reports inactive so light colours stay in use.
    # Fall back gracefully if the installed core predates the helper.
    dark_ctx = _get_dark_mode_context(config)

    dark_active = bool(dark_ctx and dark_ctx.get("active"))
    if dark_active:
        palette = dark_ctx.get("palette") or {}
        page_color = dark_ctx.get("page_color")
        text_color = dark_ctx.get("text_color")
        _raw_invert = dark_ctx.get("invert_color")
        invert = _raw_invert if callable(_raw_invert) else (lambda c: c)
    else:
        palette = getattr(config, "doxtr_semantic_palette", None) or {}
        page_color = None
        text_color = None
        invert = lambda c: c  # noqa: E731  (identity; never called in light mode)

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

    # --- Dark-mode-only knobs --------------------------------------------
    if dark_active:
        # Dark diagram background so the Gantt matches the dark PDF page.
        if page_color:
            partial["diagram_background_color"] = page_color
        # Give the frame a subtle light border so bars read on dark bg.
        if primary:
            partial["bar"].setdefault("frame_color", text_color or primary)
        # Invert the "undone" (remaining-work) bar background so the light task
        # label rendered on top of it stays legible. The default undone colour
        # is a light cream (#FFF3E0); left unchanged it would be light-on-light
        # with the dark-mode label colour. Soft-invert the effective default to
        # a dark shade. A genuine user override in doxtr_roadmap_bar still wins
        # via the _dict_diff merge in get_effective_style.
        _default_undone = DEFAULT_CONFIG["bar"].get("undone_color")
        if _default_undone:
            _dark_undone = invert(_default_undone)
            if _dark_undone:
                partial["bar"]["undone_color"] = _dark_undone
        # Readable light font colour for task labels, section separators and
        # the month/year timeline. Derive from the body text colour when
        # available; otherwise soft-invert black to the standard off-white.
        # _DARK_LABEL_INVERT_SEED is #000000 (black): theme-core's
        # hex_dark_invert maps black → the standard off-white label colour
        # (e.g. #DBDBDB), giving a legible default when text_color is absent.
        label_color = text_color or invert(_DARK_LABEL_INVERT_SEED)
        if label_color:
            # Root-level foreground: fixes the timeline header (year/month) and
            # milestone labels, which PlantUML renders in the diagram's default
            # (black) colour regardless of the timeline.*/milestone selectors.
            partial["foreground_color"] = label_color
            partial["fonts"]["task"]["color"] = label_color
            partial["fonts"]["separator"]["color"] = label_color
            partial["fonts"]["month"] = {"color": label_color}
            partial["fonts"]["year"] = {"color": label_color}
            # Title colour is applied via inline creole (the ganttDiagram
            # title style selector is ignored by PlantUML), so set it on the
            # title font spec which _creole_title consumes.
            partial["fonts"].setdefault("title", {})["color"] = label_color

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
        "diagram_background_color": DEFAULT_CONFIG["diagram_background_color"],
        "foreground_color": DEFAULT_CONFIG["foreground_color"],
        "sections": dict(DEFAULT_CONFIG["sections"]),
        "today":   dict(DEFAULT_CONFIG["today"]),
        "fonts":   {k: dict(v) for k, v in DEFAULT_CONFIG["fonts"].items()},
        "closed":  dict(DEFAULT_CONFIG["closed"]),
        "collision_detection": DEFAULT_CONFIG["collision_detection"],
        "collision_char_width_factor": DEFAULT_CONFIG["collision_char_width_factor"],
        "collision_gap_days": DEFAULT_CONFIG["collision_gap_days"],
        "column_zoom": DEFAULT_CONFIG["column_zoom"],
        "html_format": DEFAULT_CONFIG["html_format"],
        "latex_format": DEFAULT_CONFIG["latex_format"],
        "link_appendix": DEFAULT_CONFIG["link_appendix"],
        "link_appendix_builders": list(DEFAULT_CONFIG["link_appendix_builders"]),
        "link_appendix_title": DEFAULT_CONFIG["link_appendix_title"],
        "figure": DEFAULT_CONFIG["figure"],
        "figure_caption": DEFAULT_CONFIG["figure_caption"],
        "period_calendars": dict(DEFAULT_CONFIG["period_calendars"]),
        "period_calendars_options": dict(DEFAULT_CONFIG["period_calendars_options"]),
        "period_resolver_hooks": list(DEFAULT_CONFIG["period_resolver_hooks"]),
        "business_days": DEFAULT_CONFIG["business_days"],
        "ignorable_columns": list(DEFAULT_CONFIG["ignorable_columns"]),
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

    def _user_delta(name, default_dict):
        """Return only the sub-keys the user actually changed from the default.

        ``doxtr_roadmap_bar`` / ``_today`` / ``_fonts`` / ``_closed`` /
        ``_sections`` are registered with ``DEFAULT_CONFIG`` values as their
        Sphinx config defaults, so ``getattr`` returns a *non-None* dict even
        when the user set nothing in ``conf.py``. Merging that whole default
        dict on top of the theme-core partial would clobber theme-core's
        colours (e.g. re-apply the light ``#FF8C00`` done-bar over the dark
        palette). Instead we diff the config value against the registered
        default and return only the genuinely-overridden sub-keys, recursing
        into nested dicts. Returns ``{}`` when the user changed nothing.
        """
        val = getattr(config, name, None)
        if not isinstance(val, dict):
            return {}
        return _dict_diff(default_dict or {}, val)

    user_bar = _user_delta("doxtr_roadmap_bar", DEFAULT_CONFIG["bar"])
    if user_bar:
        effective["bar"] = _deep_merge(effective["bar"], user_bar)

    user_fonts = _user_delta("doxtr_roadmap_fonts", DEFAULT_CONFIG["fonts"])
    if user_fonts:
        effective["fonts"] = _deep_merge(effective["fonts"], user_fonts)

    user_today = _user_delta("doxtr_roadmap_today", DEFAULT_CONFIG["today"])
    if user_today:
        effective["today"] = _deep_merge(effective["today"], user_today)

    user_closed = _user_delta("doxtr_roadmap_closed", DEFAULT_CONFIG["closed"])
    if user_closed:
        effective["closed"] = _deep_merge(effective["closed"], user_closed)

    user_sections = _user_delta("doxtr_roadmap_sections", DEFAULT_CONFIG["sections"])
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
        ("diagram_background_color", "doxtr_roadmap_diagram_background_color"),
        ("foreground_color", "doxtr_roadmap_foreground_color"),
        ("html_format", "doxtr_roadmap_html_format"),
        ("latex_format", "doxtr_roadmap_latex_format"),
        ("link_appendix", "doxtr_roadmap_link_appendix"),
        ("link_appendix_builders", "doxtr_roadmap_link_appendix_builders"),
        ("link_appendix_title", "doxtr_roadmap_link_appendix_title"),
        ("figure", "doxtr_roadmap_figure"),
        ("figure_caption", "doxtr_roadmap_figure_caption"),
        ("period_calendars", "doxtr_roadmap_period_calendars"),
        ("period_calendars_options", "doxtr_roadmap_period_calendars_options"),
        ("period_resolver_hooks", "doxtr_roadmap_period_resolver_hooks"),
        ("business_days", "doxtr_roadmap_business_days"),
        ("ignorable_columns", "doxtr_roadmap_ignorable_columns"),
    ):
        val = getattr(config, cfg_key, None)
        if val is not None:
            effective[simple_key] = val

    return effective
