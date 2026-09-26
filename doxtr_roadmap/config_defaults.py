"""Default configuration values for doxtr_roadmap.

``DEFAULT_CONFIG`` is the single source of truth for all styling and generation
defaults.  ``_deep_merge`` is used to layer directive-level overrides on top of
the global Sphinx config dict before passing to :func:`generator.generate_puml`.
"""

from .csv_parser import DEFAULT_IGNORABLE_COLUMNS

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
        # Brightness delta (percent) used to derive a per-task bar *frame*
        # colour from its resolved done/fill colour when a task sets a
        # ``color`` (CSV ``color`` column).  A light fill is darkened by this
        # amount, a dark fill is lightened by it, so the border always
        # contrasts with the fill (an 80%-black fill gets a lighter frame and
        # vice-versa).  0 disables per-task frame derivation (the bar keeps
        # ``frame_color`` / PlantUML's default border).
        "frame_brightness_delta": 30,
        # Brightness delta (percent) used to derive the *undone* (remaining)
        # bar background from the *done* (completed) colour.  The undone colour
        # is ALWAYS this much lighter than the done colour in light mode and
        # this much darker in dark mode, so the two portions of every bar keep
        # a consistent relationship regardless of the done colour.
        #
        # The default 88.7 is derived from the historical light-mode pair
        # done=#FF8C00 / undone=#FFF3E0: lightening #FF8C00 by 88.7% reproduces
        # ~#FFF3E0 (the average of the informative green/blue channels; red is
        # already maxed).  Set to 0 to disable derivation and use the literal
        # ``undone_color`` instead.
        #
        # NOTE: PlantUML gantt exposes only a *single, global* undone
        # background (the ``undone`` style selector); it cannot be set per
        # task.  The derivation therefore uses the *global* ``done_color`` and
        # applies to every bar's remaining portion, even bars whose completed
        # portion is individually coloured via the CSV ``color`` column.
        "undone_brightness_delta": 88.7,
    },

    # ----- Diagram-level background -----------------------------------
    # PlantUML ganttDiagram BackGroundColor. None → PlantUML default (white).
    # The theme-core adapter sets this to the dark page colour when the core
    # reports dark mode is active, so the generated Gantt renders on a dark
    # background that matches the rest of the PDF (rather than relying on the
    # core's lossy per-pixel image inversion).
    "diagram_background_color": None,

    # ----- Diagram-level foreground -----------------------------------
    # PlantUML ganttDiagram root FontColor + LineColor. None → PlantUML
    # defaults (black). The theme-core adapter sets this to a readable light
    # colour in dark mode. This is the single lever that makes the timeline
    # header (year/month) and milestone labels legible on a dark background —
    # PlantUML ignores the more specific timeline.*/milestone FontColor
    # selectors but honours the root FontColor for those elements.
    "foreground_color": None,

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

    # ----- Theme-core auto-loading ------------------------------------
    # When True (default) doxtr_roadmap loads ``doxtr_pdf_theme_core``
    # automatically at setup() time via ``app.setup_extension`` *if* the
    # package is importable, so users no longer have to add it to their
    # conf.py ``extensions`` list to get the palette / dark-mode integration.
    # theme-core remains an optional dependency: when it is not installed the
    # auto-load is silently skipped and the extension degrades to its own
    # defaults.  Set to False to opt out of auto-loading entirely (e.g. a child
    # theme that supplies its own rendering / palette and does not want
    # theme-core pulled in behind its back).
    "autoload_theme_core": True,

    # ----- Theme-core integration -------------------------------------
    # "auto"  → active iff doxtr_pdf_theme_core is loaded for this build
    #            (either listed in config.extensions OR pulled in transitively
    #            by another extension via app.setup_extension(); detected via
    #            theme_adapter._theme_core_loaded).
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

    # ----- Dynamic period expressions -------------------------------------
    # CSV-backed "named period" calendars.  Maps a trigger keyword (used in
    # :period: / :start: / :end:) to a calendar spec that resolves to a date
    # window by locating the row whose [start, end] brackets a reference date.
    #
    # Each value is either a bare file path string or a dict:
    #   {
    #     "file":      "path/to/calendar.csv",   # required
    #     "section":   "PI Rhythm",              # optional CSV section filter
    #     "match":     "contains",               # contains (default)
    #     "on_miss":   "future",                 # future (default) | past | error
    #     "reference": "now()",                  # optional date expression anchor
    #   }
    #
    # Example:
    #   "period_calendars": {
    #       "current-pi": {"file": "files/pi-calendar.csv", "section": "PI Rhythm"},
    #   }
    "period_calendars": {},

    # Per-calendar processing options, keyed by the same trigger keyword used
    # in ``period_calendars``.  Each value is an option string using the same
    # grammar as the per-file ``:file:`` bracket (see file_options.py), e.g.
    #   {"current-pi": "ignore=tags,link"}
    # Since period calendars only ever supply date windows (they never render
    # bars), the ``norender`` flag is implicit; ``ignore=`` lets you drop
    # columns from calendar parsing for consistency with :file: options.
    "period_calendars_options": {},

    # Columns a user is allowed to suppress via a per-file ``ignore=`` option
    # (and via ``period_calendars_options``).  Defaults to every non-required
    # column; the strictly-required columns (name/start/end) can never be
    # ignored regardless of this list.  Exposed as config so new columns added
    # in future can be made ignorable without a code change.
    "ignorable_columns": list(DEFAULT_IGNORABLE_COLUMNS),

    # Advanced: dotted paths to callables (token, ctx) -> (start, end) | date
    # | None, tried before the built-in resolvers so users can override any
    # built-in behaviour.  Example: ["mypkg.roadmap_ext.fiscal_year"].
    "period_resolver_hooks": [],

    # Renderer override: dotted path (``module.callable`` or ``module:callable``)
    # to a function with the same signature as
    # :func:`generator.generate_puml`.  ``None`` (default) uses the built-in
    # generator.  A child theme can point this at its own renderer to replace
    # the entire PlantUML generation without monkeypatching or forking.
    "renderer": None,

    # Colour-engine override: dotted path (``module.callable`` or
    # ``module:callable``) to a factory ``(config, frame_delta) -> resolver``
    # where *resolver* is a callable
    # ``(expr, default_done, default_frame) -> (done_hex, frame_hex|None)``
    # (the same contract as :meth:`color_resolver.ColorResolver.resolve`).
    # ``None`` (default) uses the built-in
    # :meth:`color_resolver.ColorResolver.from_config`.  A child theme can
    # point this at its own factory to replace the entire colour-expression
    # engine (custom grammar, palette source, brightness algorithm) without
    # monkeypatching or forking, independently of ``renderer``.
    "color_resolver": None,

    # Business-day definition used by relative expressions such as
    # "now()-45 businessdays".  None → Monday–Friday.  Otherwise a list of
    # weekday names (case-insensitive; full or common abbreviations) or
    # integers (Mon=0 .. Sun=6), e.g. ["monday", "wednesday", "saturday"] or
    # [0, 2, 5] for a Mon/Wed/Sat working week.
    "business_days": None,

    # ----- PlantUML output format overrides ------------------------------
    # Override the sphinxcontrib.plantuml output format specifically for
    # roadmap diagrams, leaving the format of ordinary ``.. uml::`` blocks
    # untouched.
    #
    # These map directly onto the per-node ``html_format`` / ``latex_format``
    # attributes that sphinxcontrib.plantuml already honours (they take
    # precedence over the global ``plantuml_output_format`` /
    # ``plantuml_latex_output_format`` settings).
    #
    #   None (default) → do not override; defer to the sphinxcontrib.plantuml
    #                    global setting (so a project configured for
    #                    ``svg_obj`` renders roadmaps as ``svg_obj`` too).
    #   str            → force this format for every roadmap, e.g. "png".
    #
    # Valid html values mirror sphinxcontrib.plantuml:
    #   "png", "svg", "svg_img", "svg_obj", "none".
    # Valid latex values mirror sphinxcontrib.plantuml:
    #   "eps", "pdf", "eps_pdf", "svg_pdf", "png", "tikz".
    "html_format": None,
    "latex_format": None,

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
