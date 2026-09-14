"""RoadmapDirective — the ``.. roadmap::`` Sphinx directive.

This module contains the docutils/Sphinx directive class that ties together
CSV parsing, tag filtering, link resolution, style adaptation, PlantUML
generation, and the sphinxcontrib.plantuml node construction.
"""

import csv
import glob
import hashlib
import os
import re
import datetime
from pathlib import Path

from docutils import nodes as docutils_nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import ViewList
from sphinx.util import logging

from . import csv_parser, generator
from . import period_expr
from .file_options import split_spec_and_options, parse_file_options, FileOptionError
from .theme_adapter import get_effective_style
from .link_resolver import LinkResolver
from .tags import parse_tag_list, parse_row_tags, parse_nested_tags, row_matches_filter
from .config_defaults import _deep_merge
from .safe_query import evaluate_query, QueryError

logger = logging.getLogger(__name__)

# Constants for the plantuml output-filename scheme used by sphinxcontrib.plantuml.
# The filename is: plantuml-<sha1(incdir + _PLANTUML_HASH_SEP + uml)>.png
_PLANTUML_FNAME_PREFIX = "plantuml-"
_PLANTUML_HASH_SEP = b"\0"

# Compiled pattern guard for the :query: match() helper — cache compiled
# patterns per-call to avoid repeated re.compile on the same pattern.
_MATCH_PATTERN_CACHE: dict = {}


def _query_match_helper(pattern: str, string: str) -> bool:
    """Safe ``match(pattern, string)`` helper exposed to :query: eval context.

    Returns ``bool(re.search(pattern, string))``.  Uses a per-process compiled
    pattern cache (keyed by pattern string) to avoid repeated compilation on
    the same expression.  An invalid pattern raises ``re.error`` which is
    caught by the eval try/except, causing the row to be included (fail-open).

    Why the raw ``re`` module must NOT be exposed
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Passing the ``re`` module object into eval locals would allow sandbox
    escape via ``re.compile.__class__.__bases__`` (object traversal) and
    ReDoS attacks via unbounded nested quantifiers.  We expose only this
    single-function interface so callers can do regex checks without gaining
    access to the module itself.
    """
    if pattern not in _MATCH_PATTERN_CACHE:
        _MATCH_PATTERN_CACHE[pattern] = re.compile(pattern)
    return bool(_MATCH_PATTERN_CACHE[pattern].search(string))


def _split_file_specs(file_opt: str) -> list:
    """Split a raw ``:file:`` option value into individual spec tokens.

    Splitting is on runs of whitespace and/or commas, **except** inside a
    trailing ``[...]`` option bracket so that a comma-separated ``ignore=``
    list is not treated as a spec separator.  Bracket depth is tracked so::

        "a.csv[ignore=section,link] b.csv[norender], c.csv"

    yields ``["a.csv[ignore=section,link]", "b.csv[norender]", "c.csv"]``.

    Parameters
    ----------
    file_opt:
        Raw ``:file:`` option string.

    Returns
    -------
    list[str]
        Non-empty spec tokens in source order.
    """
    specs: list = []
    buf: list = []
    depth = 0
    for ch in file_opt.strip():
        if ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            if depth > 0:
                depth -= 1
            buf.append(ch)
        elif depth == 0 and (ch.isspace() or ch == ","):
            if buf:
                specs.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        specs.append("".join(buf))
    return [s for s in (t.strip() for t in specs) if s]


def _clean_style_validator(argument):
    """Validator for the :clean-style: directive option.

    Accepts:
    - bare flag (no value / empty string) → ``True``
    - ``"true"`` / ``"1"`` / ``"yes"``    → ``True``
    - ``"false"`` / ``"0"`` / ``"no"``    → ``False``

    This lets users override the global ``doxtr_roadmap_clean_style`` per
    directive in either direction::

        .. roadmap::          # bare flag — enables clean_style
           :clean-style:

        .. roadmap::          # explicit true
           :clean-style: true

        .. roadmap::          # explicit false — disables even when globally True
           :clean-style: false
    """
    if argument is None or argument.strip() == "":
        return True
    val = argument.strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    raise ValueError(
        f":clean-style: value must be 'true' or 'false' (got {argument!r})"
    )


def _collision_detection_validator(argument):
    """Validator for the :collision-detection: directive option.

    Accepts:
    - bare flag (no value / empty string) → ``True``
    - ``"true"`` / ``"1"`` / ``"yes"``    → ``True``
    - ``"false"`` / ``"0"`` / ``"no"``    → ``False``

    This lets users override the global ``doxtr_roadmap_collision_detection``
    per directive in either direction::

        .. roadmap::          # bare flag — enables collision detection
           :collision-detection:

        .. roadmap::          # explicit false — disables for this chart only
           :collision-detection: false
    """
    if argument is None or argument.strip() == "":
        return True
    val = argument.strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    raise ValueError(
        f":collision-detection: value must be 'true' or 'false' (got {argument!r})"
    )


def _float_validator(argument):
    """Validator for directive options that expect a positive float."""
    if argument is None:
        raise ValueError("Expected a float value, got None")
    try:
        return float(argument.strip())
    except (ValueError, AttributeError):
        raise ValueError(f"Expected a float value, got {argument!r}")


def _html_format_validator(argument):
    """Validator for the :html-format: directive option.

    Accepts any of the HTML output formats understood by
    sphinxcontrib.plantuml (``png``, ``svg``, ``svg_img``, ``svg_obj``,
    ``none``).  The value is passed through verbatim as the ``html_format``
    node attribute, which sphinxcontrib.plantuml honours in preference to the
    global ``plantuml_output_format`` setting.
    """
    if argument is None or argument.strip() == "":
        raise ValueError(":html-format: requires a value")
    val = argument.strip()
    valid = ("png", "svg", "svg_img", "svg_obj", "none")
    if val not in valid:
        raise ValueError(
            f":html-format: value must be one of {', '.join(valid)} "
            f"(got {argument!r})"
        )
    return val


def _latex_format_validator(argument):
    """Validator for the :latex-format: directive option.

    Accepts any of the LaTeX output formats understood by
    sphinxcontrib.plantuml (``eps``, ``pdf``, ``eps_pdf``, ``svg_pdf``,
    ``png``, ``tikz``).  The value is passed through verbatim as the
    ``latex_format`` node attribute, which sphinxcontrib.plantuml honours in
    preference to the global ``plantuml_latex_output_format`` setting.
    """
    if argument is None or argument.strip() == "":
        raise ValueError(":latex-format: requires a value")
    val = argument.strip()
    valid = ("eps", "pdf", "eps_pdf", "svg_pdf", "png", "tikz")
    if val not in valid:
        raise ValueError(
            f":latex-format: value must be one of {', '.join(valid)} "
            f"(got {argument!r})"
        )
    return val


def _link_appendix_validator(argument):
    """Validator for the :link-appendix: directive option.

    Accepts:
    - bare flag (no value / empty string) → ``"list"`` (default when flag is given)
    - ``"off"`` / ``"none"`` / ``"false"``  → ``False`` (disable)
    - ``"list"``                            → ``"list"``
    - ``"footnote"``                        → ``"footnote"``

    Per-directive examples::

        .. roadmap::          # bare flag — renders a bullet list
           :link-appendix:

        .. roadmap::          # explicit list
           :link-appendix: list

        .. roadmap::          # numbered list
           :link-appendix: footnote

        .. roadmap::          # disable even when globally enabled
           :link-appendix: off
    """
    if argument is None or argument.strip() == "":
        return "list"  # bare flag → default to "list"
    val = argument.strip().lower()
    if val in ("off", "none", "false", "0"):
        return False
    if val == "list":
        return "list"
    if val == "footnote":
        return "footnote"
    raise ValueError(
        f":link-appendix: value must be 'off', 'list', or 'footnote' (got {argument!r})"
    )


class RoadmapDirective(Directive):
    """The ``.. roadmap::`` directive.

    Generates a PlantUML Gantt roadmap from CSV data (file or inline body),
    applies tag/query filters, resolves the clip window, and returns a
    ``sphinxcontrib.plantuml.plantuml`` node.

    Directive options
    -----------------
    :file:          One or more CSV paths and/or glob patterns, space- or
                    comma-separated.  All matched files are loaded as a single
                    combined roadmap: sections merge by name and subtasks /
                    row-groups work across files.  Paths are resolved relative
                    to the document directory first, then ``srcdir``.  Glob
                    metacharacters (``*``, ``?``, ``[``) are expanded; within
                    each glob the matches are sorted lexicographically.  A
                    single path with no separators behaves as before.

                    .. note::

                       Adding a *new* file that matches an existing glob
                       pattern will **not** trigger an incremental rebuild
                       automatically; run ``make clean html`` after adding new
                       files to a glob pattern.

                    Per-file options may be attached to any spec by appending a
                    ``[...]`` bracket directly after the filename (or glob).
                    Options are ``;``-separated; each is either a bare flag or
                    a ``key=value`` pair whose value is a comma-separated list::

                        :file: sprints/sprint-01.csv[ignore=section,link]
                        :file: pi-calendar.csv[norender] work.csv

                    Supported options:

                    * ``ignore=<col>[,<col>...]`` — blank the named column(s)
                      for that spec's rows at parse time, so the data can stay
                      documented in the CSV while being suppressed from the
                      diagram (and from ``:tags:`` / ``:query:`` filtering and
                      the link appendix).  Only non-required columns may be
                      ignored (see ``doxtr_roadmap_ignorable_columns``);
                      ``name`` / ``start`` / ``end`` are rejected.
                    * ``norender`` — load the file (so its rows remain usable
                      for a named ``:period:`` / ``:start:`` / ``:end:`` and
                      stay documented) but emit no bars from it.

                    Options apply to every file a glob spec matches and are
                    independent per spec, so a column can be ignored in one
                    file but kept in another.
    :title:         Override the diagram title.
    :scale:         ``daily``, ``weekly``, or ``monthly``.
    :start:         Clip window start.  Accepts an ISO date (``YYYY-MM-DD``) or
                    a dynamic period expression (a configured
                    ``doxtr_roadmap_period_calendars`` keyword such as
                    ``current-pi``, or calendar math such as
                    ``now()-63 businessdays``) resolved to its start edge.
    :end:           Clip window end.  Accepts an ISO date (``YYYY-MM-DD``) or a
                    dynamic period expression resolved to its end edge.
    :period:        Comma-separated period name(s) to zoom to.  Each token may
                    be a period name (matched against the loaded rows or any
                    configured ``doxtr_roadmap_period_calendars`` file) or a
                    dynamic period expression (``current-pi``,
                    ``current-quarter``, ``now()-2 weeks``).
    :close-weekends: Flag — force weekend closure regardless of auto-scale.
    :tags:          Tag filter expression (xlink nested syntax).
    :query:         Python safe-eval filter expression.  The expression is
                    evaluated per row with these names available:

                    * ``name``      — task display name (``str``)
                    * ``start``     — task start date (``datetime.date``)
                    * ``end``       — task end date (``datetime.date``)
                    * ``section``   — section name (``str``)
                    * ``tags``      — set of tag strings (``set[str]``)
                    * ``row_group`` — row-group label or ``None``
                    * ``match(pattern, string)`` — safe regex helper;
                      returns ``bool(re.search(pattern, string))`` without
                      exposing the ``re`` module.

                    Safe helper callables available: ``match``, ``any``,
                    ``all``, ``bool``, ``set``, ``len``.

                    Expressions are evaluated by a **restricted AST
                    evaluator**: attribute access (``obj.attr``), subscript
                    access, calls to arbitrary objects, lambdas,
                    comprehensions, and imports are all forbidden.  Only
                    the names listed above and the helper callables are
                    available; any other identifier raises an error.
                    This closes the classic CPython sandbox escape
                    (``().__class__.__bases__[0].__subclasses__()``).

                    A row that raises an exception is **included**
                    (fail-open), and a deduplicated ``[doxtr-roadmap]``
                    warning is logged.

                    Example::

                        :query: "eng" in tags and end > start
                        :query: match(r"^Set\\d", name)

    **Period references in start/end cells.**  Instead of a literal ISO date,
    a ``start`` or ``end`` cell may be written as a *period reference*
    ``@<period>``.  The reference is expanded in place to a concrete date: the
    referenced period's **start** edge in a ``start`` cell and its **end**
    edge in an ``end`` cell.  So a row with ``start=@PI27-01`` and
    ``end=@PI27-08`` spans from the start of PI27-01 to the end of PI27-08.

    ``<period>`` is resolved as a plain period **name** matched
    case-insensitively against the loaded roadmap rows (e.g. a ``PI27-01`` row
    in a ``pi-periods.csv``, including one loaded with the ``norender`` flag)
    and every configured ``doxtr_roadmap_period_calendars`` file, or as a
    dynamic expression (a configured calendar keyword, calendar math such as
    ``@current-pi`` / ``@now()+2 weeks``, or even a literal ISO date).  Cells
    without a leading ``@`` are still parsed strictly as ISO dates, so existing
    CSVs are unaffected.
    """

    has_content = True
    required_arguments = 0
    optional_arguments = 0
    option_spec = {
        "file":           directives.unchanged,
        "title":          directives.unchanged,
        "scale":          lambda x: directives.choice(
                              x, ("daily", "weekly", "monthly")
                          ),
        "start":          directives.unchanged,
        "end":            directives.unchanged,
        # OQ-2: single comma-separated string (not truly repeatable in RST).
        "period":         directives.unchanged,
        "close-weekends": directives.flag,
        "clean-style":    _clean_style_validator,
        "tags":           directives.unchanged,
        "query":          directives.unchanged,
        "collision-detection":       _collision_detection_validator,
        "collision-char-width-factor": _float_validator,
        "column-zoom":                 _float_validator,
        "width":                       directives.length_or_percentage_or_unitless,
        "html-format":                 _html_format_validator,
        "latex-format":                _latex_format_validator,
        "link-appendix":               _link_appendix_validator,
        "link-appendix-title":         directives.unchanged,
        # Figure / List-of-Figures options (mirror sphinxcontrib.plantuml)
        "caption":                     directives.unchanged,
        "align":                       lambda x: directives.choice(
                                           x, ("left", "center", "right")
                                       ),
        "name":                        directives.unchanged,
    }

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self):
        """Execute the directive and return a list of docutils nodes."""
        env = self.state.document.settings.env

        try:
            return self._run(env)
        except (ValueError, csv.Error, OSError) as exc:
            msg = f"doxtr-roadmap error: {exc}"
            error_node = self.state.document.reporter.error(
                msg,
                line=self.lineno,
            )
            return [error_node]

    def _run(self, env):
        """Inner run — may raise ValueError / csv.Error on bad input."""
        # ---- 1. Build effective config ----
        effective_config = get_effective_style(env.config)

        # Apply directive-level overrides on top
        if "title" in self.options:
            effective_config["default_title"] = self.options["title"]
        if "scale" in self.options:
            effective_config["default_scale"] = self.options["scale"]
        # :clean-style: overrides global clean_style for this directive instance
        # (value is True/False from _clean_style_validator, or absent if not given)
        if "clean-style" in self.options:
            effective_config["clean_style"] = self.options["clean-style"]
        # :collision-detection: overrides global collision_detection per chart
        if "collision-detection" in self.options:
            effective_config["collision_detection"] = self.options["collision-detection"]
        # :collision-char-width-factor: per-chart label-width tuning
        if "collision-char-width-factor" in self.options:
            effective_config["collision_char_width_factor"] = (
                self.options["collision-char-width-factor"]
            )
        # :column-zoom: per-chart gantt column width multiplier
        if "column-zoom" in self.options:
            effective_config["column_zoom"] = self.options["column-zoom"]
        # :html-format: / :latex-format: per-chart PlantUML output format
        # overrides (fall back to the doxtr config value, then to the
        # sphinxcontrib.plantuml global setting when neither is set).
        if "html-format" in self.options:
            effective_config["html_format"] = self.options["html-format"]
        if "latex-format" in self.options:
            effective_config["latex_format"] = self.options["latex-format"]
        # close-weekends flag just means True; handled in step 5

        # :link-appendix: / :link-appendix-title: per-chart overrides
        if "link-appendix" in self.options:
            effective_config["link_appendix"] = self.options["link-appendix"]
        if "link-appendix-title" in self.options:
            effective_config["link_appendix_title"] = self.options["link-appendix-title"]

        # ---- 2. Load items ----
        # *items* are the rows that will be rendered as bars.  *lookup_items*
        # additionally include rows from norender files so that a named
        # :period: / :start: / :end: can still resolve against a
        # reference-only file that is not drawn.
        file_opt = self.options.get("file")
        if file_opt:
            items, lookup_items = self._load_from_file_option(
                env, file_opt, effective_config
            )
        else:
            content_text = "\n".join(self.content)
            if not content_text.strip():
                raise ValueError(
                    ".. roadmap:: requires either a :file: option or an "
                    "inline CSV body."
                )
            items = csv_parser.load_items_from_string(content_text)
            lookup_items = items

        # ---- 2b. Resolve period references in start/end cells ----
        # A start/end cell written as ``@<period-name-or-expression>`` (e.g.
        # ``@PI27-01``) is expanded in place to a concrete ISO date: the
        # referenced period's start edge for a start cell, its end edge for an
        # end cell.  This runs before every downstream consumer
        # (tag/query filters, find_period_window, the generator) so they all
        # continue to see valid ISO-date strings.  Plain (unprefixed) cells are
        # left untouched, preserving strict ISO-date behaviour.
        #
        # Built once here and reused for the clip-window resolution in step 5.
        expr_ctx = self._build_period_context(env, effective_config)

        def _expr_warn(msg):
            logger.warning(msg, location=(env.docname, self.lineno))

        # Combined case-insensitive period-name index: loaded rows plus every
        # configured period-calendar file.  Used both to expand ``@`` cell
        # references and to resolve plain :period: names that live only in a
        # calendar file (e.g. PI28-01 in pi-periods.csv).
        period_name_index = self._build_period_name_index(
            lookup_items, expr_ctx, _expr_warn
        )

        try:
            items, lookup_items = self._resolve_period_cells(
                items, lookup_items, expr_ctx, _expr_warn, period_name_index
            )
        except period_expr.PeriodExprError as exc:
            # A calendar-backed ``@`` cell whose calendar fails to resolve
            # raises PeriodExprError; re-raise as ValueError so run() renders a
            # clean directive error node instead of crashing the build (mirrors
            # the :period: / :start: / :end: handling below).
            raise ValueError(f"period reference: {exc}")

        # ---- 3. Apply tag filter ----
        tags_opt = self.options.get("tags")
        if tags_opt:
            filter_tree = parse_nested_tags(tags_opt)
            filtered_items = []
            for section, tasks in items:
                kept = []
                for task in tasks:
                    # TaskItem attribute access (index 4 = tags)
                    tags_cell = task.tags if hasattr(task, "tags") else task[4]
                    # parse_row_tags splits on commas AND whitespace (space-separated
                    # tags in the CSV are documented and supported).
                    row_tags = parse_row_tags(tags_cell)
                    if row_matches_filter(row_tags, filter_tree):
                        kept.append(task)
                if kept:
                    filtered_items.append((section, kept))
            items = filtered_items

        # ---- 4. Apply :query: filter ----
        query_opt = self.options.get("query")
        if query_opt:
            # SECURITY: expressions are evaluated by a restricted AST
            # evaluator (safe_query.evaluate_query) that whitelists node
            # types and explicitly forbids:
            #   • attribute access  → closes ().__class__.__bases__[0]... escape
            #   • subscript access
            #   • lambdas / comprehensions / generator expressions
            #   • any name not present in the `names` dict below
            # The raw `re` module is NOT passed in; only _query_match_helper
            # is exposed as the `match` callable.
            _warned_query: set = set()
            filtered_items = []
            for section, tasks in items:
                kept = []
                for task in tasks:
                    # TaskItem attribute access
                    if hasattr(task, "name"):
                        t_name      = task.name
                        start_str   = task.start
                        end_str     = task.end
                        tags_cell   = task.tags
                        t_row_group = task.row_group
                    else:
                        t_name      = task[0]
                        start_str   = task[1]
                        end_str     = task[2]
                        tags_cell   = task[4]
                        t_row_group = task[6]
                    try:
                        start_d = datetime.date.fromisoformat(start_str)
                        end_d   = datetime.date.fromisoformat(end_str)
                    except ValueError:
                        kept.append(task)
                        continue
                    # parse_row_tags splits on commas AND whitespace so that
                    # space-separated tags like "eng ops" produce {"eng", "ops"}.
                    row_tags = set(parse_row_tags(tags_cell))
                    # Names visible inside the query expression.
                    # Safe callable helpers are injected explicitly;
                    # no __builtins__ is used.
                    names = {
                        "name":      t_name,
                        "start":     start_d,
                        "end":       end_d,
                        "section":   section,
                        "tags":      row_tags,
                        "row_group": t_row_group,
                        # Regex helper — raw `re` module intentionally
                        # excluded (see _query_match_helper docstring).
                        "match": _query_match_helper,
                        # Safe built-in callables
                        "any":  any,
                        "all":  all,
                        "bool": bool,
                        "set":  set,
                        "len":  len,
                    }
                    try:
                        if evaluate_query(query_opt, names):
                            kept.append(task)
                    except (QueryError, Exception) as exc:
                        wkey = f"{query_opt}:{t_name}"
                        if wkey not in _warned_query:
                            _warned_query.add(wkey)
                            logger.warning(
                                f"[doxtr-roadmap] query evaluation failed for "
                                f"task '{t_name}': {exc}"
                            )
                        kept.append(task)  # include on error (fail-open)
                if kept:
                    filtered_items.append((section, kept))
            items = filtered_items

        # ---- 4b. Warn when all filters leave zero tasks ----
        # Emit a Sphinx warning so authors notice their filter matched nothing.
        # The build continues; generator.generate_puml will emit a placeholder
        # gantt so PlantUML does not crash on an empty diagram.
        if not items:
            logger.warning(
                "[doxtr-roadmap] roadmap filter produced zero tasks "
                "(all rows were filtered out); a placeholder diagram will be "
                "rendered.  Check your :tags: / :query: / :period: / :start: / "
                ":end: options."
            )

        # ---- 5. Resolve clip window ----
        # The dynamic period-expression context (expr_ctx) and the _expr_warn
        # callback were built in step 2b and are reused here so that the
        # :start: / :end: / :period: options expand consistently with the
        # period references resolved inside the CSV cells.  See period_expr.py.

        # :start: / :end: accept a literal ISO date OR any dynamic expression
        # that resolves to a window; for a window we take its start edge for
        # :start: and its end edge for :end:.
        start_date = None
        end_date = None
        if "start" in self.options:
            start_date = self._resolve_edge(
                self.options["start"], expr_ctx, _expr_warn, edge="start"
            )
        if "end" in self.options:
            end_date = self._resolve_edge(
                self.options["end"], expr_ctx, _expr_warn, edge="end"
            )

        # OQ-2: comma-separated period names.  Each token is routed through the
        # dynamic resolver first; tokens that resolve to a window contribute
        # explicit start/end dates (bypassing the CSV name lookup).  A token no
        # dynamic resolver claims is next tried against the combined
        # period-name index (loaded rows + configured calendar files), so a
        # name that lives only in a calendar file (e.g. PI28-01 in
        # pi-periods.csv) still resolves.  Anything still unresolved falls
        # through as a plain name for generator.find_period_window to match
        # against the loaded rows (preserving the original error on a miss).
        period_names = []
        expr_windows = []  # (start, end) windows from resolved dynamic tokens
        if "period" in self.options:
            raw_period = self.options["period"]
            for tok in (p.strip() for p in raw_period.split(",")):
                if not tok:
                    continue
                try:
                    window = period_expr.resolve_period_token(
                        tok, expr_ctx, warn=_expr_warn
                    )
                except period_expr.PeriodExprError as exc:
                    raise ValueError(f"period {tok!r}: {exc}")
                if window is None:
                    window = period_name_index.get(tok.strip().lower())
                if window is not None:
                    expr_windows.append(window)
                else:
                    period_names.append(tok)

        # Merge any dynamic-expression windows into explicit start/end edges.
        # The combined window spans the earliest start to the latest end of
        # all resolved expressions, mirroring find_period_window semantics.
        # Explicit :start: / :end: still take precedence over these.
        if expr_windows:
            expr_start = min(w[0] for w in expr_windows)
            expr_end = max(w[1] for w in expr_windows)
            if start_date is None:
                start_date = expr_start
            if end_date is None:
                end_date = expr_end

        project_start, project_end = generator.resolve_window(
            period_names=period_names or None,
            start=start_date,
            end=end_date,
            items=lookup_items,
            config=effective_config,
        )

        # D-6: auto-scale logic for single distinct period
        scale = self.options.get("scale") or effective_config.get("default_scale")
        close_weekends = "close-weekends" in self.options

        # A single dynamic-expression window with no CSV period names counts as
        # a single distinct period for auto-scale purposes too.
        single_expr_period = (
            not period_names and len(expr_windows) == 1
        )
        if (period_names or single_expr_period) and not close_weekends \
                and "scale" not in self.options:
            is_single = single_expr_period or (
                len({p.lower() for p in period_names}) == 1
            )
            if is_single:
                scale = "daily"
                if effective_config.get("close_weekends_on_single_period", True):
                    close_weekends = True

        title = self.options.get(
            "title", effective_config.get("default_title", "Roadmap")
        )

        # ---- 6. Build link resolver ----
        # Prefer the public env.app API (Sphinx 9); fall back to the private
        # _app attribute for older Sphinx versions.  Accessing env.app emits a
        # RemovedInSphinx11Warning in Sphinx ≥10.x; we suppress that specific
        # deprecation warning here since we have no better cross-version API.
        # [S-11]
        import warnings as _warnings
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            sphinx_app = getattr(env, "app", None) or getattr(env, "_app", None)
        resolver = LinkResolver(sphinx_app)

        # ---- 7. Generate PlantUML source ----
        puml_string = generator.generate_puml(
            items=items,
            config=effective_config,
            project_start=project_start,
            project_end=project_end,
            scale=scale,
            close_weekends=close_weekends,
            title=title,
            link_resolver=resolver.resolve,
        )

        # ---- 8. Construct plantuml node ----
        import os
        import sphinxcontrib.plantuml as scp
        node = scp.plantuml(self.block_text, uml=puml_string)
        node["alt"] = title
        # sphinxcontrib.plantuml requires 'incdir' and 'filename' on the node
        # so it can hash the node correctly; we set them to the document's path.
        relfn = env.doc2path(env.docname, base=None)
        node["incdir"] = os.path.dirname(relfn)
        node["filename"] = os.path.split(relfn)[1]

        # ---- 8a. Dark mode: mark our generated PNG as already-dark-themed ----
        # In dark mode the theme adapter emitted dark-appropriate colours into
        # puml_string (dark background, light labels, dark palette bars). The
        # resulting PlantUML PNG is therefore already correct for the dark page
        # and must NOT be re-processed by theme-core's dark image pipeline:
        # a dark, largely-achromatic Gantt would be misclassified as grayscale
        # line-art and remapped (black->text / white->page), inverting its
        # colours to a light grey.
        #
        # We cannot use a filename glob (sphinxcontrib.plantuml writes ALL
        # diagrams as plantuml-<hash>.png, including hand-authored ones that DO
        # need recolouring). Instead we compute the exact output filename the
        # same way sphinxcontrib.plantuml does -- sha1(incdir + '\0' + uml) --
        # and register only that basename via theme-core's public API. This is
        # a no-op when theme-core is absent, dark mode is off, or
        # sphinx_app is None.
        #
        # hashlib is stdlib and cannot fail, so compute the hash unconditionally
        # outside any try block. Only the theme-core import and API call are
        # guarded: ImportError → theme-core absent (silent); other Exception
        # → unexpected API break, logged at DEBUG so it is diagnosable.
        _key = hashlib.sha1()
        _key.update(node["incdir"].encode("utf-8"))
        _key.update(_PLANTUML_HASH_SEP)
        _key.update(node["uml"].encode("utf-8"))
        _dark_png_name = f"{_PLANTUML_FNAME_PREFIX}{_key.hexdigest()}.png"
        if sphinx_app is not None:
            try:
                from doxtr_pdf_theme_core import mark_image_dark_ready
            except ImportError:
                pass  # theme-core not installed — skip registration silently
            else:
                try:
                    mark_image_dark_ready(sphinx_app, _dark_png_name)
                except Exception:
                    logger.debug(
                        "[doxtr-roadmap] mark_image_dark_ready(%r) failed; "
                        "dark PNG exclusion skipped",
                        _dark_png_name,
                        exc_info=True,
                    )
        # :width: forces the rendered image to fill a specific width in HTML
        # and PDF (sphinxcontrib.plantuml maps this to style width / adjustbox).
        # Apply width to the INNER plantuml node before any figure wrapping.
        if "width" in self.options:
            node["width"] = self.options["width"]

        # PlantUML output-format overrides.  sphinxcontrib.plantuml checks the
        # node's 'html_format' / 'latex_format' attributes first and only falls
        # back to the global plantuml_output_format / plantuml_latex_output_format
        # when they are absent.  We therefore set them on the node ONLY when an
        # override is configured (per-directive option or doxtr config value);
        # leaving them unset preserves the project-wide PlantUML defaults so a
        # 'normal' .. uml:: block and a roadmap can render in different formats.
        html_fmt = effective_config.get("html_format")
        if html_fmt:
            node["html_format"] = html_fmt
        latex_fmt = effective_config.get("latex_format")
        if latex_fmt:
            node["latex_format"] = latex_fmt

        # ---- 8b. Optionally wrap in a figure node ----
        # Mirror the sphinxcontrib.plantuml idiom exactly:
        # nodes.figure('', plantuml_node) + nodes.caption + add_name.
        # Triggers: explicit :caption:, :align:, or global doxtr_roadmap_figure=True.
        explicit_caption = "caption" in self.options
        has_align = "align" in self.options
        global_figure = bool(effective_config.get("figure", False))
        wrap_in_figure = explicit_caption or has_align or global_figure

        # ---- Pre-compute builder allowance for link appendix (needed by
        #      both step 8b footnote-in-caption and step 9) ----
        mode = effective_config.get("link_appendix", False)
        # Normalise falsy / "off" modes
        if not mode or (
            isinstance(mode, str) and mode.lower() in ("off", "none", "false")
        ):
            appendix_mode = False
        else:
            appendix_mode = mode  # "list" or "footnote"

        import warnings as _w2
        with _w2.catch_warnings():
            _w2.simplefilter("ignore")
            _builder = getattr(sphinx_app, "builder", None)
        bname = getattr(_builder, "name", "") or ""
        bfmt  = getattr(_builder, "format", "") or ""
        allowed = effective_config.get("link_appendix_builders", ["latex"])
        if allowed == "all" or (isinstance(allowed, list) and "*" in allowed):
            appendix_allowed_for_builder = True
        else:
            appendix_allowed_for_builder = bname in allowed or bfmt in allowed

        # footnote-in-caption: merge footnote refs into figure caption when:
        #   - the chart is a figure
        #   - appendix mode is "footnote"
        #   - the builder is in the allowed list
        footnote_in_caption = (
            wrap_in_figure
            and appendix_mode == "footnote"
            and appendix_allowed_for_builder
        )

        if wrap_in_figure:
            # Determine caption text — precedence:
            #   1. explicit :caption: option (verbatim)
            #   2. effective_config["figure_caption"] if non-empty
            #   3. chart title (default)
            if explicit_caption:
                caption_text = self.options["caption"]
            elif effective_config.get("figure_caption"):
                caption_text = effective_config["figure_caption"]
            else:
                # title is the default for any figure wrap (including align-only)
                caption_text = title

            figure = docutils_nodes.figure("", node)
            if has_align:
                figure["align"] = self.options["align"]

            if footnote_in_caption:
                # Collect resolvable links (same logic as _build_link_appendix)
                links = self._collect_appendix_links(items, resolver.resolve)
            else:
                links = []

            if caption_text and footnote_in_caption and links:
                # Build caption + footnote-references as a parsed RST fragment
                # so docutils creates real footnote_reference nodes inside the
                # caption.  The footnote DEFINITIONS are emitted as sibling
                # nodes after the figure.
                #
                # Caption RST:
                #   <caption_text> (<label> [#]_, [#]_, [#]_)
                # One <label> word (the appendix title, e.g. "Links") then one
                # auto-numbered footnote reference marker per link,
                # comma-separated.  Example: "Projects with Links (Links [1], [2])"
                #
                # Footnote definition body (same order as caption markers):
                #   with title:    .. [#] {safe_task} >> {safe_title}: {url}
                #   without title: .. [#] {safe_task}: {url}
                # The task name is moved OUT of the caption and INTO the
                # footnote body.  The bare https URL autlinks in the footnote.

                # Determine the label word from the appendix title config
                raw_label = effective_config.get("link_appendix_title", "Links")
                label_word = (raw_label or "").strip() or "Links"
                # Escape RST inline-markup chars in the label
                safe_label = (
                    label_word
                    .replace("*", "\\*")
                    .replace("_", "\\_")
                )

                # Build "<safe_label> [#]_, [#]_, ..." bracket string
                marker_str = ", ".join(["[#]_"] * len(links))
                bracket_str = f"{safe_label} {marker_str}"

                # Escape any inline-markup chars in the plain caption text
                safe_caption = (
                    caption_text
                    .replace("*", "\\*")
                    .replace("_", "\\_")
                )
                caption_rst = f"{safe_caption} ({bracket_str})"

                # Parse via nested_parse: yields a paragraph whose children
                # become the caption node's children.
                vl = ViewList()
                src_loc = "<doxtr-roadmap-caption>"
                vl.append(caption_rst, src_loc, 0)
                vl.append("", src_loc, 1)  # blank line to close paragraph

                tmp_container = docutils_nodes.container()
                self.state.nested_parse(vl, self.content_offset, tmp_container)

                caption_node = docutils_nodes.caption(caption_text, "")
                if tmp_container.children:
                    first = tmp_container.children[0]
                    if isinstance(first, docutils_nodes.paragraph):
                        caption_node.extend(first.children)
                    else:
                        caption_node += docutils_nodes.Text(caption_text)
                try:
                    from sphinx.util.nodes import set_source_info
                    set_source_info(self, caption_node)
                except Exception:
                    pass
                figure += caption_node

                # Build footnote DEFINITIONS as sibling nodes after the figure.
                # Each definition carries: <task_name> >> <title>: <url>  (with title)
                #                      or: <task_name>: <url>             (plain URL)
                # The Nth [#]_ marker in the caption binds to the Nth .. [#] def.
                fn_lines = []
                for task_name, url, link_title in links:
                    # Escape RST inline-markup chars in the task name so
                    # nested_parse doesn't choke (backticks, *, _).
                    safe_task = (
                        task_name
                        .replace("`", "\\`")
                        .replace("*", "\\*")
                        .replace("_", "\\_")
                    )
                    if link_title:
                        safe_title = (
                            link_title
                            .replace("`", "\\`")
                            .replace("*", "\\*")
                        )
                        fn_lines.append(f".. [#] {safe_task} >> {safe_title}: {url}")
                    else:
                        fn_lines.append(f".. [#] {safe_task}: {url}")

                fn_vl = ViewList()
                fn_src = "<doxtr-roadmap-footnotes>"
                for i, line in enumerate(fn_lines):
                    fn_vl.append(line, fn_src, i)

                fn_container = docutils_nodes.container()
                self.state.nested_parse(fn_vl, self.content_offset, fn_container)
                footnote_def_nodes = fn_container.children[:]

                # Register cross-reference name
                self.add_name(figure)
                # Return: figure + footnote definition nodes (NO separate appendix)
                return [figure] + list(footnote_def_nodes)

            elif caption_text:
                # Plain caption (no footnote refs) — parse via inline_text
                inodes, messages = self.state.inline_text(
                    caption_text, self.lineno
                )
                caption_node = docutils_nodes.caption(
                    caption_text, "", *inodes
                )
                caption_node.extend(messages)
                try:
                    from sphinx.util.nodes import set_source_info
                    set_source_info(self, caption_node)
                except Exception:
                    pass
                figure += caption_node

            # Register cross-reference name (reads self.options['name'] if set)
            self.add_name(figure)
            node = figure

        # ---- 9. Optionally build link appendix ----
        # Skip if mode is off or builder not allowed
        if not appendix_mode or not appendix_allowed_for_builder:
            return [node]

        # If footnote-in-caption applied, the appendix was already embedded;
        # skip the standalone appendix block.
        if footnote_in_caption:
            return [node]

        appendix_title = effective_config.get("link_appendix_title", "Links")
        appendix_nodes = self._build_link_appendix(
            items, resolver.resolve, appendix_mode, appendix_title
        )
        return [node] + appendix_nodes

    # ------------------------------------------------------------------
    # Dynamic period-expression support
    # ------------------------------------------------------------------

    def _build_period_context(self, env, effective_config):
        """Construct a :class:`period_expr.ResolutionContext` for this run.

        Wires the directive into the resolver engine: supplies today's date,
        the effective config (for calendars / hooks / business days), the
        srcdir + document directory for file resolution, a dependency-note
        callback (so calendar edits trigger rebuilds), and a calendar loader
        that reuses the existing CSV parser.

        Per-calendar options (``doxtr_roadmap_period_calendars_options``) using
        the same grammar as the per-file ``:file:`` bracket are pre-resolved
        here into an abspath -> :class:`FileOptions` map, so the injected
        calendar loader can apply column-suppression consistently.  Since a
        calendar never renders bars, the ``norender`` flag is meaningless for
        calendars and is ignored.
        """
        docdir = str(Path(env.docname).parent)

        def _note_dep(abspath):
            try:
                env.note_dependency(abspath)
            except AttributeError:
                pass

        ctx = period_expr.ResolutionContext(
            today=datetime.date.today(),
            config=effective_config,
            srcdir=str(env.srcdir),
            docdir=docdir,
            note_dependency=_note_dep,
            load_calendar=None,  # set below once ctx exists (needs path resolver)
        )

        # Build an abspath -> FileOptions map from the per-calendar option
        # strings.  Each entry in period_calendars_options is keyed by the same
        # trigger keyword used in period_calendars; we resolve that calendar's
        # file to an absolute path so the loader (which only sees a path) can
        # look the options up.
        calendars = effective_config.get("period_calendars") or {}
        cal_options = effective_config.get("period_calendars_options") or {}
        ignorable_columns = effective_config.get(
            "ignorable_columns", list(csv_parser.DEFAULT_IGNORABLE_COLUMNS)
        )
        opts_by_path: dict = {}
        for key, opt_str in cal_options.items():
            spec = calendars.get(key)
            # Case-insensitive keyword fallback, mirroring the resolver.
            if spec is None:
                for k, v in calendars.items():
                    if k.lower() == key.lower():
                        spec = v
                        break
            if spec is None:
                raise ValueError(
                    f"doxtr_roadmap_period_calendars_options key {key!r} does "
                    f"not match any doxtr_roadmap_period_calendars entry"
                )
            spec_file = spec if isinstance(spec, str) else spec.get("file")
            if not spec_file:
                continue
            try:
                file_opts = parse_file_options(opt_str, ignorable_columns)
            except FileOptionError as exc:
                raise ValueError(
                    f"doxtr_roadmap_period_calendars_options[{key!r}]: {exc}"
                )
            abspath = period_expr._resolve_calendar_file(spec_file, ctx)
            opts_by_path[os.path.abspath(abspath)] = file_opts

        def _load_calendar(abspath):
            return self._load_calendar_rows(
                abspath, opts_by_path.get(os.path.abspath(abspath))
            )

        ctx.load_calendar = _load_calendar
        return ctx

    @staticmethod
    def _load_calendar_rows(abspath, options=None):
        """Load a period-calendar CSV into ``(name, start, end, section)`` rows.

        Reuses :func:`csv_parser.load_items_from_file` so a calendar file has
        exactly the same format as a roadmap file (a dedicated calendar can
        contain only the period rows, or an existing roadmap CSV can be reused
        together with a ``section`` filter).  Rows whose ``start`` / ``end``
        are not valid ISO dates are skipped.

        *options*, when given, is a
        :class:`~doxtr_roadmap.file_options.FileOptions` whose
        ``ignore_columns`` are blanked at parse time (the ``norender`` flag is
        ignored for calendars, which never render bars).
        """
        # Calendars are never rendered as bars, so norender is meaningless here
        # and must not cause the rows to be skipped by the loader.  Strip it
        # while preserving any ignore_columns.
        if options is not None and getattr(options, "norender", False):
            options = options._replace(norender=False)
        sections = csv_parser.load_items_from_files([abspath], [options])
        rows = []
        for section_name, tasks in sections:
            for task in tasks:
                name = task.name if hasattr(task, "name") else task[0]
                start_str = task.start if hasattr(task, "start") else task[1]
                end_str = task.end if hasattr(task, "end") else task[2]
                try:
                    start_d = datetime.date.fromisoformat(start_str)
                    end_d = datetime.date.fromisoformat(end_str)
                except (ValueError, TypeError):
                    continue
                rows.append((name, start_d, end_d, section_name))
        return rows

    def _resolve_edge(self, raw_value, expr_ctx, warn, edge):
        """Resolve a ``:start:`` / ``:end:`` option value to a single date.

        A literal ISO date is returned verbatim.  A dynamic expression that
        resolves to a window contributes its *start* edge when *edge* is
        ``"start"`` and its *end* edge when *edge* is ``"end"``.  A value that
        no resolver claims is a hard error (unlike :period:, an edge cannot
        fall through to a CSV task name).
        """
        try:
            window = period_expr.resolve_period_token(
                raw_value, expr_ctx, warn=warn
            )
        except period_expr.PeriodExprError as exc:
            raise ValueError(f"Invalid {edge} date {raw_value!r}: {exc}")
        if window is None:
            raise ValueError(
                f"Invalid {edge} date: {raw_value!r} "
                f"(expected an ISO date or a period expression such as "
                f"'now()-63 days', 'current-quarter', or a configured "
                f"calendar keyword)"
            )
        return window[0] if edge == "start" else window[1]

    # ------------------------------------------------------------------
    # Period-name index (loaded rows + configured calendar files)
    # ------------------------------------------------------------------

    def _build_period_name_index(self, lookup_items, expr_ctx, warn):
        """Return a case-insensitive ``name -> (start, end)`` window index.

        The index is built from two sources, in order of precedence:

        1. **Loaded roadmap rows** (*lookup_items*) whose ``start`` / ``end``
           cells are concrete ISO dates — including rows from ``norender``
           reference files.
        2. **Configured period-calendar files**
           (``doxtr_roadmap_period_calendars``).  Every calendar file is
           loaded once (via the injected ``expr_ctx.load_calendar``) and its
           rows contribute their names too.  This lets a bare period *name*
           such as ``PI28-01`` — or a ``@PI28-01`` cell reference — resolve
           against the same ``pi-periods.csv`` that backs the ``current-pi``
           keyword, **without** having to list that file in ``:file:``.

        Loaded rows win over calendar rows on a name clash (the explicitly
        loaded data is authoritative).  When a name occurs on several rows the
        window spans their combined earliest-start / latest-end, mirroring
        :func:`generator.find_period_window`.

        Parameters
        ----------
        lookup_items:
            Parsed sections list (rendered rows plus ``norender`` rows).
        expr_ctx:
            :class:`period_expr.ResolutionContext` — supplies the calendar
            loader, srcdir/docdir, and dependency-note callback.
        warn:
            Non-fatal diagnostic callback (calendar-load problems are warned,
            not raised, so a broken calendar never blocks name resolution
            against the loaded rows).

        Returns
        -------
        dict
            ``{lower_name: (datetime.date, datetime.date)}``.
        """
        index: dict = {}

        def _add(name, start_d, end_d):
            key = (name or "").strip().lower()
            if not key:
                return
            if key in index:
                prev_s, prev_e = index[key]
                index[key] = (min(prev_s, start_d), max(prev_e, end_d))
            else:
                index[key] = (start_d, end_d)

        # Step 1 (lower precedence): configured period-calendar files, added
        # first so the loaded rows below can overwrite them on a name clash.
        calendars = (expr_ctx.config or {}).get("period_calendars") or {}
        seen_paths: set = set()
        for key, spec in calendars.items():
            spec_file = spec if isinstance(spec, str) else (
                spec.get("file") if isinstance(spec, dict) else None
            )
            if not spec_file:
                continue
            section = None
            if isinstance(spec, dict):
                section = spec.get("section")
            try:
                abspath = period_expr._resolve_calendar_file(spec_file, expr_ctx)
                abspath = os.path.abspath(abspath)
                if abspath in seen_paths:
                    continue
                seen_paths.add(abspath)
                if expr_ctx.load_calendar is None:
                    continue
                rows = expr_ctx.load_calendar(abspath)
            except (OSError, csv.Error, ValueError,
                    period_expr.PeriodExprError) as exc:
                # Non-fatal: a broken/unreadable calendar must not block name
                # resolution against the loaded rows.  Genuinely unexpected
                # exceptions (e.g. programming errors) are left to propagate.
                if warn is not None:
                    warn(
                        f"[doxtr-roadmap] could not load period calendar "
                        f"{key!r} ({spec_file!r}) for name resolution: {exc}"
                    )
                continue
            want = section.strip().lower() if section else None
            for row in rows:
                r_name, r_start, r_end = row[0], row[1], row[2]
                if want is not None:
                    r_section = row[3] if len(row) > 3 else None
                    if (r_section or "").strip().lower() != want:
                        continue
                _add(r_name, r_start, r_end)

        # Step 2 (higher precedence): loaded rows, added last so they override
        # calendar entries on a name clash.  The first loaded row for a name
        # *replaces* any calendar entry (loaded data is authoritative), while
        # subsequent loaded rows for that same name merge into the combined
        # earliest-start / latest-end span, mirroring
        # :func:`generator.find_period_window`.
        loaded_keys: set = set()
        for _section, tasks in lookup_items:
            for task in tasks:
                name = task.name if hasattr(task, "name") else task[0]
                start_str = task.start if hasattr(task, "start") else task[1]
                end_str = task.end if hasattr(task, "end") else task[2]
                try:
                    s = datetime.date.fromisoformat(start_str)
                    e = datetime.date.fromisoformat(end_str)
                except (ValueError, TypeError):
                    continue
                key = (name or "").strip().lower()
                if not key:
                    continue
                if key in loaded_keys:
                    # Another loaded row for this name: widen the span.
                    prev_s, prev_e = index[key]
                    index[key] = (min(prev_s, s), max(prev_e, e))
                else:
                    # First loaded row for this name: replace any calendar entry.
                    index[key] = (s, e)
                    loaded_keys.add(key)

        return index

    # ------------------------------------------------------------------
    # Period references in CSV start/end cells
    # ------------------------------------------------------------------

    def _resolve_period_cells(self, items, lookup_items, expr_ctx, warn,
                              name_index):
        """Expand ``@<period>`` references in every task's start/end cell.

        A start/end cell written as ``@PI27-01`` (or any dynamic expression
        such as ``@current-pi`` / ``@now()+2 weeks``) is replaced in place with
        a concrete ISO date: the referenced period's **start** edge for a
        start cell, its **end** edge for an end cell.  Plain cells (no leading
        ``@``) are left untouched so strict ISO-date parsing is preserved.

        Plain period *names* (tokens no dynamic resolver claims) are matched
        case-insensitively against *name_index* — the combined index of the
        loaded roadmap rows (including ``norender`` reference files) **and**
        every configured period-calendar file (see
        :meth:`_build_period_name_index`).  So ``@PI28-01`` resolves against
        ``pi-periods.csv`` even when only ``roadmap.csv`` is listed in
        ``:file:``.

        Parameters
        ----------
        items:
            Sections list of rendered rows (mutated copy returned).
        lookup_items:
            Sections list; when it is the same object as *items* one rewrite
            covers both.
        expr_ctx:
            :class:`period_expr.ResolutionContext` for dynamic resolution.
        warn:
            Non-fatal diagnostic callback.
        name_index:
            Prebuilt case-insensitive ``name -> (start, end)`` map from
            :meth:`_build_period_name_index`.

        Returns
        -------
        tuple
            ``(items, lookup_items)`` with period references expanded.  When no
            cell needed rewriting the original objects are returned unchanged.
        """
        def _name_lookup(token):
            return name_index.get(token.strip().lower())

        def _rewrite(sections):
            changed = False
            out_sections = []
            for section, tasks in sections:
                out_tasks = []
                for task in tasks:
                    start_cell = task.start if hasattr(task, "start") else task[1]
                    end_cell = task.end if hasattr(task, "end") else task[2]
                    new_start = start_cell
                    new_end = end_cell
                    if period_expr.is_period_ref(start_cell):
                        new_start = period_expr.resolve_cell_edge(
                            start_cell, "start", expr_ctx,
                            name_lookup=_name_lookup, warn=warn,
                        )
                    if period_expr.is_period_ref(end_cell):
                        new_end = period_expr.resolve_cell_edge(
                            end_cell, "end", expr_ctx,
                            name_lookup=_name_lookup, warn=warn,
                        )
                    if new_start != start_cell or new_end != end_cell:
                        changed = True
                        if hasattr(task, "_replace"):
                            task = task._replace(start=new_start, end=new_end)
                        else:
                            task = list(task)
                            task[1] = new_start
                            task[2] = new_end
                    out_tasks.append(task)
                out_sections.append((section, out_tasks))
            return (out_sections if changed else sections), changed

        same_object = items is lookup_items
        new_items, items_changed = _rewrite(items)
        if same_object:
            # One rewrite covers both when they are the same list object.
            return new_items, new_items
        new_lookup, _ = _rewrite(lookup_items)
        return new_items, new_lookup

    # ------------------------------------------------------------------
    # Multi-file / glob file loading
    # ------------------------------------------------------------------

    def _load_from_file_option(self, env, file_opt: str, effective_config: dict) -> list:
        """Resolve, glob-expand, and load the ``:file:`` option value.

        *file_opt* is the raw option string — one or more CSV path specs
        separated by whitespace and/or commas.  Each spec may contain glob
        metacharacters (``*``, ``?``, ``[``).

        Resolution order per spec
        -------------------------
        1. Try ``<srcdir>/<doc_dir>/<spec>`` (relative to document).
        2. Try ``<srcdir>/<spec>`` (relative to srcdir).

        For each base directory the spec is treated as a glob pattern.  If
        neither base yields any matches for a given spec, a :exc:`ValueError`
        is raised listing all specs tried.

        Matching files are collected in spec order; within each glob match the
        results are sorted lexicographically.  Duplicate paths (a file matched
        by more than one spec) are de-duplicated while preserving first-seen
        order.

        :meth:`env.note_dependency` is called for every resolved file so that
        Sphinx rebuilds the page when any of those files change.  Adding a
        *new* file matching a glob pattern is not detected automatically by
        ``note_dependency``; a clean rebuild is required in that case.

        Parameters
        ----------
        env:
            Sphinx ``BuildEnvironment``.
        file_opt:
            Raw ``:file:`` option string.

        Returns
        -------
        tuple
            ``(items, lookup_items)`` — both parsed sections lists from
            :func:`csv_parser.load_items_from_files`.  *items* honours per-file
            ``norender`` (reference-only files contribute no rendered bars);
            *lookup_items* additionally includes those files' rows so a named
            ``:period:`` / ``:start:`` / ``:end:`` can still resolve against a
            reference-only file.  When no ``norender`` file is present the two
            are the same list object.

        Raises
        ------
        ValueError
            If, after expanding all specs, zero files were found.
        """
        import glob as _glob

        # Split on commas and whitespace, but NOT inside a trailing option
        # bracket (so "a.csv[ignore=section,link] b.csv" splits into two
        # specs, keeping the comma inside the bracket intact).  This handles:
        #   "a.csv b.csv"  → ["a.csv", "b.csv"]
        #   "a.csv, b.csv" → ["a.csv", "b.csv"]
        #   "sprints/*.csv" → ["sprints/*.csv"]
        #   "a.csv[ignore=x,y] b.csv[norender]"
        #     → ["a.csv[ignore=x,y]", "b.csv[norender]"]
        raw_specs = _split_file_specs(file_opt)

        # Columns the user is allowed to suppress via a per-file ignore= option.
        ignorable_columns = effective_config.get(
            "ignorable_columns", list(csv_parser.DEFAULT_IGNORABLE_COLUMNS)
        )

        doc_dir = Path(env.docname).parent
        base_doc = Path(env.srcdir) / doc_dir   # document-relative base
        base_src = Path(env.srcdir)             # srcdir-relative base

        resolved_paths: list = []  # ordered, deduped
        resolved_options: list = []  # parallel to resolved_paths
        seen_paths: set = set()

        unmatched_specs: list = []

        for spec in raw_specs:
            # Peel off the trailing [..] option bracket (if any) BEFORE globbing
            # so glob metacharacters in the path still work and the options are
            # not treated as part of the pattern.
            filename, opts_str = split_spec_and_options(spec)
            try:
                file_opts = parse_file_options(opts_str, ignorable_columns)
            except FileOptionError as exc:
                raise ValueError(f":file: spec {spec!r}: {exc}")

            matches: list = []

            # Try document-relative base first, then srcdir base.
            for base in (base_doc, base_src):
                raw_matches = sorted(_glob.glob(str(base / filename)))
                if raw_matches:
                    for m in raw_matches:
                        p = Path(m).resolve()
                        if p not in seen_paths:
                            seen_paths.add(p)
                            resolved_paths.append(p)
                            # Options attach to every file the glob matched.
                            resolved_options.append(file_opts)
                    matches = raw_matches
                    break  # found at this base; do not try next

            if not matches:
                unmatched_specs.append(filename)

        if not resolved_paths:
            specs_str = ", ".join(repr(s) for s in raw_specs)
            tried_str = ", ".join(repr(s) for s in unmatched_specs)
            raise ValueError(
                f"CSV file(s) not found: {specs_str} "
                f"(no files matched; tried relative to document and srcdir)"
            )

        # Warn (not error) when individual specs matched nothing but others did.
        if unmatched_specs:
            from sphinx.util import logging as _slog
            _lg = _slog.getLogger(__name__)
            for spec in unmatched_specs:
                _lg.warning(
                    f"[doxtr-roadmap] :file: spec {spec!r} matched no files "
                    f"(resolved relative to document and srcdir)"
                )

        # Register all resolved files as dependencies.
        for p in resolved_paths:
            env.note_dependency(str(p))

        # Rendered items honour per-file norender (those files contribute no
        # bars).  Lookup items additionally include norender files' rows so a
        # named :period: can resolve against a reference-only file.
        items = csv_parser.load_items_from_files(resolved_paths, resolved_options)

        has_norender = any(
            getattr(o, "norender", False) for o in resolved_options
        )
        if not has_norender:
            lookup_items = items
        else:
            # Re-load with norender stripped so reference-only files' periods
            # are available for name resolution (but never rendered).
            lookup_options = [
                (o._replace(norender=False) if o is not None else None)
                for o in resolved_options
            ]
            lookup_items = csv_parser.load_items_from_files(
                resolved_paths, lookup_options
            )

        return items, lookup_items

    # ------------------------------------------------------------------
    # Link-appendix helpers
    # ------------------------------------------------------------------

    def _collect_appendix_links(self, items, resolve_fn):
        """Collect resolved links from *items* in encounter order, deduped.

        Returns a list of ``(task_name, url, link_title)`` triples for every
        task that has a non-empty ``link`` cell that resolves to a URL.  Exact
        duplicate triples are collapsed to the first occurrence.

        Parameters
        ----------
        items:
            Filtered sections list as returned by the CSV parser.
        resolve_fn:
            ``LinkResolver.resolve`` callable.

        Returns
        -------
        list[tuple[str, str, str | None]]
        """
        seen: set = set()
        links: list = []
        for _section, tasks in items:
            for task in tasks:
                link_cell = task.link if hasattr(task, "link") else task[3]
                task_name = task.name if hasattr(task, "name") else task[0]
                if not link_cell:
                    continue
                result = resolve_fn(link_cell)
                if result is None:
                    continue
                url, link_title = result
                key = (task_name, url, link_title)
                if key in seen:
                    continue
                seen.add(key)
                links.append((task_name, url, link_title))
        return links

    def _build_link_appendix(self, items, resolve_fn, mode, title):
        """Build docutils nodes for the link appendix.

        Iterates *items* (list of ``(section, tasks)`` pairs), resolves each
        task's ``link`` cell via *resolve_fn*, and builds a
        ``nodes.container`` containing an optional ``nodes.rubric`` heading
        and either:

        - a ``nodes.bullet_list`` (mode ``'list'``): one item per task as
          ``<task name>: <clickable URL or title link>``.
        - real reStructuredText auto-numbered footnotes (mode
          ``'footnote'``): a lead-in paragraph naming each task with a
          ``[#]_`` reference marker, followed by ``.. [#]`` footnote
          definitions containing the URL (and title when available).
          Parsed via ``self.state.nested_parse`` so docutils creates
          proper ``nodes.footnote`` / ``nodes.footnote_reference`` nodes.
          In PDF/LaTeX output Sphinx's LaTeX writer emits these as
          ``\\footnote{}`` at the page bottom.  In HTML they render as
          standard numbered footnotes with back-references.

        Returns ``[]`` when no tasks have resolvable links so the caller
        never appends an empty heading/list.

        Parameters
        ----------
        items:
            Filtered sections list as returned by the CSV parser.
        resolve_fn:
            ``LinkResolver.resolve`` callable — maps a raw link cell to
            ``(url, title)`` or ``None``.
        mode:
            ``"list"`` for a bullet list; ``"footnote"`` for real
            reStructuredText auto-numbered footnotes (rendered as LaTeX
            ``\\footnote`` in PDF output).
        title:
            Heading text (``nodes.rubric``) placed above the list, or an
            empty string / ``None`` to omit the heading.

        Returns
        -------
        list
            Zero or one ``nodes.container`` node.
        """
        # Collect resolved links via shared helper.
        links = self._collect_appendix_links(items, resolve_fn)

        if not links:
            return []

        if mode == "footnote":
            # Build real RST auto-numbered footnotes and parse them with the
            # directive's state machine so docutils creates proper
            # nodes.footnote / nodes.footnote_reference nodes.
            #
            # Lead-in paragraph: each task name (as an inline literal to
            # neutralise RST special chars) followed by its [#]_ marker.
            # Footnote definitions follow in the same encounter order — docutils
            # auto-numbering matches the Nth [#]_ reference to the Nth .. [#]
            # definition in document order.
            lead_parts = []
            for task_name, _url, _lt in links:
                # Wrap in double-backtick inline literal so asterisks,
                # underscores, brackets, etc. are inert.  Replace any
                # embedded double-backtick (extremely rare) to avoid
                # prematurely closing the literal.
                safe_name = task_name.replace("``", "''")
                lead_parts.append(f"``{safe_name}`` [#]_")

            rst_lines = [" ".join(lead_parts), ""]

            for _task_name, url, link_title in links:
                if link_title:
                    # Escape inline-markup chars in the title so the
                    # footnote body parses cleanly.
                    safe_title = (
                        link_title
                        .replace("`", "\\`")
                        .replace("*", "\\*")
                    )
                    rst_lines.append(f".. [#] {safe_title}: {url}")
                else:
                    rst_lines.append(f".. [#] {url}")

            view_list = ViewList()
            src = "<doxtr-roadmap-link-appendix>"
            for i, line in enumerate(rst_lines):
                view_list.append(line, src, i)

            container = docutils_nodes.container(
                classes=["doxtr-roadmap-links"]
            )
            if title:
                rubric = docutils_nodes.rubric()
                rubric += docutils_nodes.Text(str(title))
                container += rubric

            self.state.nested_parse(view_list, self.content_offset, container)
            return [container]

        # mode == "list": bullet list with one item per resolved link.
        list_node = docutils_nodes.bullet_list()
        for task_name, url, link_title in links:
            item = docutils_nodes.list_item()
            para = docutils_nodes.paragraph()
            para += docutils_nodes.Text(task_name + ": ")
            ref_text = link_title if link_title else url
            ref = docutils_nodes.reference(
                refuri=url, internal=False
            )
            ref += docutils_nodes.Text(ref_text)
            para += ref
            item += para
            list_node += item

        container = docutils_nodes.container(
            classes=["doxtr-roadmap-links"]
        )
        if title:
            rubric = docutils_nodes.rubric()
            rubric += docutils_nodes.Text(str(title))
            container += rubric
        container += list_node

        return [container]
