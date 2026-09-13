"""doxtr_roadmap — Sphinx extension that generates PlantUML Gantt roadmaps from CSV data.

Entry point: ``setup(app)`` registers all config values and the ``.. roadmap::`` directive.

Public API
----------
setup(app)
    Sphinx extension entry point.
__version__
    Package version string.
"""

__version__ = "0.1.1"

import shlex
import subprocess

from sphinx.util import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config defaults (canonical source of truth)
# ---------------------------------------------------------------------------
from .config_defaults import DEFAULT_CONFIG

def _check_plantuml_loaded(app):
    """Verify sphinxcontrib.plantuml is in extensions; raise ExtensionError if not."""
    if "sphinxcontrib.plantuml" not in app.config.extensions:
        from sphinx.errors import ExtensionError
        raise ExtensionError(
            "doxtr-roadmap requires sphinxcontrib.plantuml. "
            "Add 'sphinxcontrib.plantuml' to extensions in conf.py."
        )


def _check_plantuml_version(app):
    """Check that the configured PlantUML binary meets the minimum version requirement.

    Reads ``app.config.plantuml`` (the sphinxcontrib.plantuml command string),
    invokes it with ``-version``, and compares the result against
    :data:`~doxtr_roadmap.plantuml_version.MIN_PLANTUML_VERSION`.

    Behavior is controlled by the ``doxtr_roadmap_require_plantuml_version``
    config value (default ``"error"``):

    * ``"error"`` — raise :class:`sphinx.errors.ExtensionError` if the version
      is below the minimum (default; fails the build on PlantUML < v1.2026.7).
    * ``"warn"``  — emit a :func:`logger.warning` if the version is below the
      minimum, but continue the build.
    * ``"off"`` / ``False`` — skip the check entirely (no subprocess call).

    If the version cannot be determined (subprocess failure, unrecognised
    output, or a timeout) an :func:`logger.info` message is emitted and the
    build continues regardless of the ``require`` setting.  The check is
    deduplicated so it runs at most once per Sphinx app instance, preventing
    contamination across multiple apps in one process.
    """
    # [M-1] Per-app dedup flag instead of module-level bool, so multiple Sphinx
    # apps in one process (e.g. parallel test runs) don't skip each other's check.
    if getattr(app, "_doxtr_roadmap_version_checked", False):
        return
    app._doxtr_roadmap_version_checked = True

    from .plantuml_version import (
        MIN_PLANTUML_VERSION,
        MIN_PLANTUML_VERSION_STR,
        is_version_sufficient,
        parse_plantuml_version,
    )

    # Defensive fallback matches the registered default ("error"); in practice
    # setup() always registers this config value so the fallback is never used.
    require = getattr(app.config, "doxtr_roadmap_require_plantuml_version", "error")

    # Normalise "off" / False to skip
    if require is False or (isinstance(require, str) and require.lower() == "off"):
        return

    plantuml_cmd = getattr(app.config, "plantuml", "plantuml")
    try:
        argv = shlex.split(plantuml_cmd) + ["-version"]
    except Exception:
        argv = ["plantuml", "-version"]

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = result.stdout + result.stderr
    except FileNotFoundError:
        logger.info(
            "[doxtr-roadmap] PlantUML version could not be determined "
            "(command not found: %s). "
            "PlantUML >= v%s is recommended for full feature support "
            "(clean_style / hide column, same-name task bars).",
            argv[0],
            MIN_PLANTUML_VERSION_STR,
        )
        return
    except subprocess.TimeoutExpired:
        # [S-2] Handle timeout explicitly — log info and continue; never crash.
        logger.info(
            "[doxtr-roadmap] PlantUML version check timed out after 15 s "
            "(command: %s). "
            "PlantUML >= v%s is recommended for full feature support "
            "(clean_style / hide column, same-name task bars).",
            argv[0],
            MIN_PLANTUML_VERSION_STR,
        )
        return
    except Exception as exc:
        logger.info(
            "[doxtr-roadmap] PlantUML version could not be determined (%s). "
            "PlantUML >= v%s is recommended for full feature support "
            "(clean_style / hide column, same-name task bars).",
            exc,
            MIN_PLANTUML_VERSION_STR,
        )
        return

    version = parse_plantuml_version(output)
    if version is None:
        logger.info(
            "[doxtr-roadmap] PlantUML version could not be determined "
            "(unrecognised -version output). "
            "PlantUML >= v%s is recommended for full feature support "
            "(clean_style / hide column, same-name task bars).",
            MIN_PLANTUML_VERSION_STR,
        )
        return

    if is_version_sufficient(version, MIN_PLANTUML_VERSION):
        # Version is fine — nothing to report.
        return

    found_str = ".".join(str(x) for x in version)
    msg = (
        f"[doxtr-roadmap] PlantUML {found_str} is below the recommended "
        f"minimum v{MIN_PLANTUML_VERSION_STR}. "
        f"Features that require v{MIN_PLANTUML_VERSION_STR}+ "
        f"(clean_style / hide column, same-name task bars) may not work correctly. "
        f"Upgrade PlantUML to v{MIN_PLANTUML_VERSION_STR} or newer."
    )

    if require == "error":
        from sphinx.errors import ExtensionError
        raise ExtensionError(msg)
    else:
        # "warn" or any unrecognised value → warning, never fail the build
        logger.warning(msg)


def _init_per_build_warned(app):
    """Initialise (or reset) the per-build warning-deduplication set on env.

    Connected to ``builder-inited`` so the set is fresh for every build.
    This replaces the previous module-level ``_WARNED_ENTRIES`` sets in
    link_resolver.py and tags.py, ensuring multiple Sphinx apps in one process
    (e.g. parallel test suites) do not share warning state.
    """
    if hasattr(app, "env") and app.env is not None:
        app.env._doxtr_roadmap_warned = set()


def setup(app):
    """Sphinx extension entry point.

    Registers all ``doxtr_roadmap_*`` config values (including
    ``doxtr_roadmap_diagram_background_color`` and
    ``doxtr_roadmap_foreground_color``), the ``.. roadmap::`` directive, and
    ``builder-inited`` hooks that verify sphinxcontrib.plantuml is loaded and
    that the installed PlantUML meets the minimum version requirement.

    Parameters
    ----------
    app:
        The Sphinx application object passed by Sphinx at extension load time.

    Returns
    -------
    dict
        Extension metadata dict with version and parallel-safe flags.
    """
    from .directive import RoadmapDirective

    cfg = DEFAULT_CONFIG

    # Register all 14 config values (all 'env' rebuild type so changes trigger
    # a full environment rebuild, matching the prototype's per-directive nature).
    app.add_config_value("doxtr_roadmap_default_scale",
                         cfg["default_scale"], "env")
    app.add_config_value("doxtr_roadmap_scale_factor",
                         cfg["scale_factor"], "env")
    # R-3: default is None; generator falls back to datetime.date.today() when None.
    app.add_config_value("doxtr_roadmap_default_start",
                         None, "env")
    app.add_config_value("doxtr_roadmap_default_title",
                         cfg["default_title"], "env")
    app.add_config_value("doxtr_roadmap_clean_style",
                         cfg["clean_style"], "env")
    app.add_config_value("doxtr_roadmap_close_weekends_on_single_period",
                         cfg["close_weekends_on_single_period"], "env")
    app.add_config_value("doxtr_roadmap_bar",
                         cfg["bar"], "env")
    app.add_config_value("doxtr_roadmap_sections",
                         cfg["sections"], "env")
    app.add_config_value("doxtr_roadmap_today",
                         cfg["today"], "env")
    app.add_config_value("doxtr_roadmap_fonts",
                         cfg["fonts"], "env")
    app.add_config_value("doxtr_roadmap_closed",
                         cfg["closed"], "env")
    app.add_config_value("doxtr_roadmap_use_theme_core",
                         cfg["use_theme_core"], "env")
    app.add_config_value("doxtr_roadmap_allowed_tags",
                         cfg["allowed_tags"], "env")
    app.add_config_value("doxtr_roadmap_allowed_tag_patterns",
                         cfg["allowed_tag_patterns"], "env")

    # Collision-detection config values (16th–18th config values)
    app.add_config_value("doxtr_roadmap_collision_detection",
                         cfg["collision_detection"], "env")
    app.add_config_value("doxtr_roadmap_collision_char_width_factor",
                         cfg["collision_char_width_factor"], "env")
    app.add_config_value("doxtr_roadmap_collision_gap_days",
                         cfg["collision_gap_days"], "env")

    # Column-zoom config value
    app.add_config_value("doxtr_roadmap_column_zoom",
                         cfg["column_zoom"], "env")

    # Diagram-level background colour override. None → use the theme adapter's
    # value (dark page colour in dark mode) or PlantUML's default (white).
    app.add_config_value("doxtr_roadmap_diagram_background_color",
                         cfg["diagram_background_color"], "env")

    # Diagram-level foreground colour override (root FontColor + LineColor).
    # None → use the theme adapter's value (readable light colour in dark mode)
    # or PlantUML's default (black).
    app.add_config_value("doxtr_roadmap_foreground_color",
                         cfg["foreground_color"], "env")

    # PlantUML output-format overrides (defer to sphinxcontrib.plantuml global
    # settings when None).
    app.add_config_value("doxtr_roadmap_html_format",
                         cfg["html_format"], "env", types=(str, type(None)))
    app.add_config_value("doxtr_roadmap_latex_format",
                         cfg["latex_format"], "env", types=(str, type(None)))

    # Link-appendix config values
    app.add_config_value("doxtr_roadmap_link_appendix",
                         cfg["link_appendix"], "env", types=(bool, str))
    app.add_config_value("doxtr_roadmap_link_appendix_builders",
                         cfg["link_appendix_builders"], "env")
    app.add_config_value("doxtr_roadmap_link_appendix_title",
                         cfg["link_appendix_title"], "env")

    # Figure / List-of-Figures config values
    app.add_config_value("doxtr_roadmap_figure",
                         cfg["figure"], "env")
    app.add_config_value("doxtr_roadmap_figure_caption",
                         cfg["figure_caption"], "env")

    # Dynamic period-expression config values
    app.add_config_value("doxtr_roadmap_period_calendars",
                         cfg["period_calendars"], "env", types=(dict,))
    app.add_config_value("doxtr_roadmap_period_calendars_options",
                         cfg["period_calendars_options"], "env", types=(dict,))
    app.add_config_value("doxtr_roadmap_ignorable_columns",
                         cfg["ignorable_columns"], "env", types=(list, tuple))
    app.add_config_value("doxtr_roadmap_period_resolver_hooks",
                         cfg["period_resolver_hooks"], "env", types=(list,))
    app.add_config_value("doxtr_roadmap_business_days",
                         cfg["business_days"], "env")

    # PlantUML version check config value
    app.add_config_value(
        "doxtr_roadmap_require_plantuml_version",
        "error",  # default: fail the build if PlantUML is below v1.2026.7
        "env",
    )

    app.add_directive("roadmap", RoadmapDirective)

    # Connection order matters: per-build state init first, then loaded-check,
    # then version-check.
    app.connect("builder-inited", _init_per_build_warned)
    app.connect("builder-inited", _check_plantuml_loaded)
    app.connect("builder-inited", _check_plantuml_version)

    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
