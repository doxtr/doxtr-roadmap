"""RoadmapDirective — the ``.. roadmap::`` Sphinx directive.

This module contains the docutils/Sphinx directive class that ties together
CSV parsing, tag filtering, link resolution, style adaptation, PlantUML
generation, and the sphinxcontrib.plantuml node construction.
"""

import csv
import glob
import re
import datetime
from pathlib import Path

from docutils import nodes as docutils_nodes
from docutils.parsers.rst import Directive, directives
from docutils.statemachine import ViewList
from sphinx.util import logging

from . import csv_parser, generator
from .theme_adapter import get_effective_style
from .link_resolver import LinkResolver
from .tags import parse_tag_list, parse_row_tags, parse_nested_tags, row_matches_filter
from .config_defaults import _deep_merge
from .safe_query import evaluate_query, QueryError

logger = logging.getLogger(__name__)

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
    :title:         Override the diagram title.
    :scale:         ``daily``, ``weekly``, or ``monthly``.
    :start:         Clip window start (ISO date YYYY-MM-DD).
    :end:           Clip window end (ISO date YYYY-MM-DD).
    :period:        Comma-separated period name(s) to zoom to.
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
        # close-weekends flag just means True; handled in step 5

        # :link-appendix: / :link-appendix-title: per-chart overrides
        if "link-appendix" in self.options:
            effective_config["link_appendix"] = self.options["link-appendix"]
        if "link-appendix-title" in self.options:
            effective_config["link_appendix_title"] = self.options["link-appendix-title"]

        # ---- 2. Load items ----
        file_opt = self.options.get("file")
        if file_opt:
            items = self._load_from_file_option(env, file_opt)
        else:
            content_text = "\n".join(self.content)
            if not content_text.strip():
                raise ValueError(
                    ".. roadmap:: requires either a :file: option or an "
                    "inline CSV body."
                )
            items = csv_parser.load_items_from_string(content_text)

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
        start_date = None
        end_date = None
        if "start" in self.options:
            try:
                start_date = datetime.date.fromisoformat(self.options["start"])
            except ValueError:
                raise ValueError(
                    f"Invalid start date: {self.options['start']!r}"
                )
        if "end" in self.options:
            try:
                end_date = datetime.date.fromisoformat(self.options["end"])
            except ValueError:
                raise ValueError(
                    f"Invalid end date: {self.options['end']!r}"
                )

        # OQ-2: comma-separated period names
        period_names = []
        if "period" in self.options:
            raw_period = self.options["period"]
            period_names = [p.strip() for p in raw_period.split(",") if p.strip()]

        project_start, project_end = generator.resolve_window(
            period_names=period_names or None,
            start=start_date,
            end=end_date,
            items=items,
            config=effective_config,
        )

        # D-6: auto-scale logic for single distinct period
        scale = self.options.get("scale") or effective_config.get("default_scale")
        close_weekends = "close-weekends" in self.options

        if period_names and not close_weekends and "scale" not in self.options:
            distinct = {p.lower() for p in period_names}
            if len(distinct) == 1:
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
        # :width: forces the rendered image to fill a specific width in HTML
        # and PDF (sphinxcontrib.plantuml maps this to style width / adjustbox).
        # Apply width to the INNER plantuml node before any figure wrapping.
        if "width" in self.options:
            node["width"] = self.options["width"]

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
    # Multi-file / glob file loading
    # ------------------------------------------------------------------

    def _load_from_file_option(self, env, file_opt: str) -> list:
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
        list
            Parsed sections list from :func:`csv_parser.load_items_from_files`.

        Raises
        ------
        ValueError
            If, after expanding all specs, zero files were found.
        """
        import glob as _glob

        # Split on commas and whitespace.  This handles:
        #   "a.csv b.csv"  → ["a.csv", "b.csv"]
        #   "a.csv, b.csv" → ["a.csv", "b.csv"]
        #   "sprints/*.csv" → ["sprints/*.csv"]
        raw_specs = [s.strip() for s in re.split(r"[,\s]+", file_opt.strip()) if s.strip()]

        doc_dir = Path(env.docname).parent
        base_doc = Path(env.srcdir) / doc_dir   # document-relative base
        base_src = Path(env.srcdir)             # srcdir-relative base

        resolved_paths: list = []  # ordered, deduped
        seen_paths: set = set()

        unmatched_specs: list = []

        for spec in raw_specs:
            matches: list = []

            # Try document-relative base first, then srcdir base.
            for base in (base_doc, base_src):
                raw_matches = sorted(_glob.glob(str(base / spec)))
                if raw_matches:
                    for m in raw_matches:
                        p = Path(m).resolve()
                        if p not in seen_paths:
                            seen_paths.add(p)
                            resolved_paths.append(p)
                    matches = raw_matches
                    break  # found at this base; do not try next

            if not matches:
                unmatched_specs.append(spec)

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

        return csv_parser.load_items_from_files(resolved_paths)

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
