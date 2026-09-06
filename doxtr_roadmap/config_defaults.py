"""Default configuration values for doxtr_roadmap.

``DEFAULT_CONFIG`` is the single source of truth for all styling and generation
defaults.  ``_deep_merge`` is used to layer directive-level overrides on top of
the global Sphinx config dict before passing to :func:`generator.generate_puml`.
"""

DEFAULT_CONFIG = {
    # ----- Generation defaults ----------------------------------------
    # Default timeline unit: daily | weekly | monthly
    "default_scale": "monthly",
    # Overall diagram zoom factor (PlantUML top-level ``scale``).
    "scale_factor": 1.25,
    # Default project start date (ISO YYYY-MM-DD).
    # R-3: None means "fall back to datetime.date.today() in the generator".
    "default_start": None,
    # Default title for the full unclipped render.
    "default_title": "Roadmap",
    # Close Saturdays/Sundays automatically when a single period is rendered.
    "close_weekends_on_single_period": True,
    # Hide the per-task Start / End / Duration columns (avoids overlap on
    # same-row grouped tasks).  Requires PlantUML V1.2026.7+ (the extension's
    # baseline); defaults to True now that 1.2026.7 is the minimum.
    "clean_style": True,

    # ----- Global bar colours -----------------------------------------
    "bar": {
        "done_color": "#FF8C00",
        "undone_color": "#FFF3E0",
        "frame_color": None,
    },

    # ----- Per-section bar colours ------------------------------------
    # Keyed by exact section name. Each entry may set "done", "frame",
    # and "frame_overrides" (map of task name → frame colour).
    "sections": {},

    # ----- Today marker -----------------------------------------------
    "today": {"color": "#E53935"},

    # ----- Fonts / text styling ---------------------------------------
    "fonts": {
        "title":     {"name": None, "size": 24, "style": "bold",  "color": None},
        "task":      {"name": None, "size": 14, "style": None,    "color": None},
        "separator": {"name": None, "size": 16, "style": "bold",  "color": None},
        "month":     {"name": None, "size": None, "style": None,  "color": None},
        "year":      {"name": None, "size": None, "style": None,  "color": None},
    },

    # ----- Closed (non-working) day styling ---------------------------
    "closed": {"background_color": None},

    # ----- Theme-core integration -------------------------------------
    # "auto"  → active iff "doxtr_pdf_theme_core" is in config.extensions
    # True    → always active (warns if core absent)
    # False   → never active
    "use_theme_core": "auto",

    # ----- Tag allow-lists --------------------------------------------
    "allowed_tags": {},
    "allowed_tag_patterns": {},

    # ----- Collision detection for same-row groups -------------------
    # When True (default), tasks sharing a row_group are split onto
    # additional Gantt rows whenever their bars or text labels would
    # collide horizontally.  Set to False to force all same-group tasks
    # onto a single row regardless of overlap.
    "collision_detection": True,
    # Tuning knob: higher values reserve more horizontal space for each
    # label (split earlier); lower values allow labels to be packed
    # more tightly.  Default 1.0 corresponds to the calibrated base
    # days-per-character for each projectscale.
    "collision_char_width_factor": 1.0,
    # Minimum gap (in calendar days) that must remain between two tasks
    # on the same lane after accounting for the left task's label.
    "collision_gap_days": 2,

    # ----- Column zoom (gantt column width) --------------------------
    # Multiplier appended to the projectscale line as `zoom <factor>`.
    # 1 (or absent) = current default PlantUML column width.
    # E.g. 3 → `projectscale monthly zoom 3` (each month column ~3× wider).
    # Requires PlantUML v1.2026.7+ (already the extension minimum).
    "column_zoom": 1,

    # ----- Figure / List-of-Figures support ----------------------------
    # When True every roadmap is wrapped in a docutils figure node even if
    # no per-directive :caption: is given.  The caption defaults to the
    # chart title (or doxtr_roadmap_figure_caption when set).
    "figure": False,
    # Optional default caption text used when figure=True and no per-
    # directive :caption: is present.  None → fall back to chart title.
    "figure_caption": None,

    # ----- Link appendix --------------------------------------------------
    # Render task links as real docutils nodes appended after the chart image.
    # Useful for PDF/LaTeX output where links embedded in the PlantUML image
    # are not clickable.
    #
    # Values:
    #   False / "off" / "none" (default) → no appendix.
    #   "list"     → bullet list of task → link.
    #   "footnote" → numbered (enumerated) list of task → link.
    #   False / "off" → no appendix.
    # Default "list": links embedded in the PlantUML image are not clickable
    # in PDF output, so a real link list is rendered below the chart.  The
    # link_appendix_builders default (below) restricts this to PDF/latex, so
    # HTML and epub are unaffected by default (their image links work).
    "link_appendix": "list",
    # Builder names/formats that render the appendix (checked against both
    # builder.name and builder.format).  Special value "all" (or list
    # containing "*") renders for every builder.
    # Default ["latex"] so PDF output gets the appendix; HTML/epub don't.
    "link_appendix_builders": ["latex"],
    # Optional heading rendered above the appendix list.
    # Empty string or None → no heading.
    "link_appendix_title": "Links",
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a shallow copy of *base*.

    Dict values are merged recursively; all other values are replaced by the
    override value.  Neither *base* nor *override* is mutated.

    Parameters
    ----------
    base:
        The base dictionary to start from.
    override:
        Values to layer on top of *base*.

    Returns
    -------
    dict
        New dict with *base* as the foundation and *override* applied on top.
    """
    result = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result
