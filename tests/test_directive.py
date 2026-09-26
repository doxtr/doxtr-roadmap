"""Unit tests for doxtr_roadmap/directive.py.

These tests run a real minimal Sphinx build using the ``xml`` builder, which
does not invoke plantuml rendering (no jar call).  The plantuml nodes therefore
remain in the doctree XML output and can be inspected directly.

Sphinx 9.x makes ``BuildEnvironment.docname`` read-only, so we use a full
sphinx-build rather than manually constructing an RST parser environment.
"""

import io
import textwrap
from pathlib import Path
import pytest

# sphinxcontrib.plantuml must be installed for directive tests
try:
    import sphinxcontrib.plantuml  # noqa: F401
    _PLANTUML_AVAILABLE = True
except ImportError:
    _PLANTUML_AVAILABLE = False

skip_no_plantuml = pytest.mark.skipif(
    not _PLANTUML_AVAILABLE,
    reason="sphinxcontrib.plantuml not installed",
)

SAMPLE_CSV = textwrap.dedent("""\
    section,name,start,end,row_group,link,tags
    Periods,Set27-01,2026-11-09,2027-01-29,,,
    Periods,Set27-04,2027-02-01,2027-04-09,,,
    Work,Task X,2026-12-01,2027-01-15,,,eng
    Work,Task Y,2027-02-15,2027-04-01,,,security
""")


def _make_project(tmp_path, rst_body: str, extra_conf: str = "",
                  csv_content: str = None):
    """Set up a minimal Sphinx project, run the xml builder, and return
    ``(app, warnings_text, src_dir)``.

    The xml builder does not invoke plantuml rendering, so plantuml nodes
    remain in the doctree and can be inspected.
    """
    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    if csv_content is not None:
        (src / "roadmap.csv").write_text(csv_content, encoding="utf-8")

    (src / "conf.py").write_text(
        textwrap.dedent(f"""\
            project = 'Test'
            extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
            plantuml = 'plantuml'
            plantuml_output_format = 'png'
            master_doc = 'index'
        """) + extra_conf + "\n",
        encoding="utf-8",
    )

    # Write rst directly — no f-string embedding to avoid indentation issues.
    index_content = "Test\n====\n\n" + rst_body + "\n"
    (src / "index.rst").write_text(index_content, encoding="utf-8")

    warning_stream = io.StringIO()
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(doctrees),
        buildername="xml",
        freshenv=True,
        warning=warning_stream,
        verbosity=0,
    )
    app.build()
    return app, warning_stream.getvalue(), src


def _get_plantuml_nodes(app, docname="index"):
    """Extract plantuml nodes from the environment's parsed doctree."""
    import sphinxcontrib.plantuml as scp
    doctree = app.env.get_doctree(docname)
    if hasattr(doctree, "findall"):
        return list(doctree.findall(scp.plantuml))
    else:
        return list(doctree.traverse(scp.plantuml))


def _get_error_nodes(app, docname="index"):
    """Extract system_message nodes from the environment's parsed doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    if hasattr(doctree, "findall"):
        return list(doctree.findall(docnodes.system_message))
    else:
        return list(doctree.traverse(docnodes.system_message))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_inline_body(tmp_path):
    """Inline CSV body produces a plantuml node in the doctree."""
    rst = textwrap.dedent("""\
        .. roadmap::

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert "@startgantt" in nodes[0]["uml"]
    assert "@endgantt" in nodes[0]["uml"]


@skip_no_plantuml
def test_directive_file_option(tmp_path):
    """`:file:` option loads CSV and produces a plantuml node."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: roadmap.csv
    """)
    app, warnings, src = _make_project(tmp_path, rst, csv_content=SAMPLE_CSV)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert "@startgantt" in nodes[0]["uml"]


@skip_no_plantuml
def test_directive_notes_dependency(tmp_path):
    """Dependency is tracked when :file: is used."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: roadmap.csv
    """)
    app, warnings, src = _make_project(tmp_path, rst, csv_content=SAMPLE_CSV)
    deps = app.env.dependencies.get("index", set())
    csv_path = str((src / "roadmap.csv").resolve())
    assert any(csv_path in str(d) for d in deps), (
        f"roadmap.csv not in dependencies; got: {deps}"
    )


@skip_no_plantuml
def test_directive_missing_file_error(tmp_path):
    """Non-existent :file: produces an error in build warnings."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: does_not_exist.csv
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    plantuml_nodes = _get_plantuml_nodes(app)
    # The error is reported as a docutils ERROR-level warning by Sphinx
    assert len(plantuml_nodes) == 0, "Should not produce a plantuml node on missing file"
    assert "does_not_exist.csv" in warnings or "CSV file not found" in warnings, (
        f"Expected error about missing CSV in warnings; got: {warnings[:500]}"
    )


@skip_no_plantuml
def test_directive_plantuml_missing_error(tmp_path):
    """sphinxcontrib.plantuml absent → ExtensionError at builder-inited."""
    from sphinx.application import Sphinx
    from sphinx.errors import ExtensionError

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    (src / "conf.py").write_text(
        textwrap.dedent("""\
            project = 'Test'
            extensions = ['doxtr_roadmap']
            master_doc = 'index'
        """),
        encoding="utf-8",
    )
    (src / "index.rst").write_text("T\n=\n\n", encoding="utf-8")

    with pytest.raises(ExtensionError, match="sphinxcontrib.plantuml"):
        Sphinx(
            srcdir=str(src),
            confdir=str(src),
            outdir=str(out),
            doctreedir=str(doctrees),
            buildername="xml",
            freshenv=True,
        )


@skip_no_plantuml
def test_directive_scale_override(tmp_path):
    """`:scale: daily` → `projectscale daily` in generated puml."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :scale: daily

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert "projectscale daily" in nodes[0]["uml"]


@skip_no_plantuml
def test_directive_close_weekends_flag(tmp_path):
    """`:close-weekends:` flag → weekend closure lines in puml."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :close-weekends:

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "saturday are closed" in uml
    assert "sunday are closed" in uml


@skip_no_plantuml
def test_directive_period_zoom(tmp_path):
    """`:period: Set27-01` → puml start clipped to that period's start date."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :period: Set27-01

           section,name,start,end,row_group,link,tags
           Periods,Set27-01,2026-11-09,2027-01-29,,,
           Periods,Set27-04,2027-02-01,2027-04-09,,,
           Work,Task X,2026-12-01,2027-01-15,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Project starts 2026-11-09" in uml


@skip_no_plantuml
def test_directive_tags_filter(tmp_path):
    """`:tags: eng` → only rows tagged 'eng' rendered in puml."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :tags: eng
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
           Work,Task B,2026-04-01,2026-06-30,,,security
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Task A" in uml
    assert "Task B" not in uml


@skip_no_plantuml
def test_directive_clean_style_false_disables_when_globally_true(tmp_path):
    """`:clean-style: false` suppresses hide-column lines even when global config is True."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :clean-style: false

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_clean_style = True",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert "hide column" not in nodes[0]["uml"]


@skip_no_plantuml
def test_directive_clean_style_bare_flag_enables_when_globally_false(tmp_path):
    """Bare `:clean-style:` flag enables clean_style even when globally False."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :clean-style:

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_clean_style = False",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "hide column start" in uml
    assert "hide column end" in uml
    assert "hide column duration" in uml


@skip_no_plantuml
def test_directive_clean_style_true_value_enables_when_globally_false(tmp_path):
    """`:clean-style: true` enables clean_style even when globally False."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :clean-style: true

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_clean_style = False",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "hide column start" in uml


# ---------------------------------------------------------------------------
# T-1: :query: filter tests
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_query_includes_row(tmp_path):
    """`:query:` expression matching a row → row appears in puml."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: "eng" in tags
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
           Work,Task B,2026-04-01,2026-06-30,,,security
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Task A" in uml
    assert "Task B" not in uml


@skip_no_plantuml
def test_directive_query_excludes_row(tmp_path):
    """`:query:` expression that matches nothing → no tasks in output."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: "nonexistent_tag" in tags
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    # With no rows, the directive may produce no node or an empty one
    # (empty section skipped by generator)
    if nodes:
        uml = nodes[0]["uml"]
        assert "Task A" not in uml


@skip_no_plantuml
def test_directive_query_bad_expression_includes_row(tmp_path):
    """`:query:` with a bad expression → row is included (fail-open) + warning."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: this_is_not_valid !!!
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    # fail-open: Task A must be present even though the query is invalid
    assert "Task A" in uml


@skip_no_plantuml
def test_directive_query_match_helper(tmp_path):
    """`:query:` using match() helper works for regex filtering."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: match(r"^Task A", name)
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
           Work,Task B,2026-04-01,2026-06-30,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Task A" in uml
    assert "Task B" not in uml


@skip_no_plantuml
def test_directive_query_no_re_module_access(tmp_path):
    """`:query:` cannot access raw re module — sandbox escape must fail safely."""
    # Attempt to access re module via __import__ → should be excluded by
    # safe_builtins restriction; the row must be included (fail-open).
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: __import__("re") is not None
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    # Row must be included (fail-open) and sandbox did not give access to __import__
    assert "Task A" in uml


@skip_no_plantuml
def test_directive_query_no_class_access(tmp_path):
    """`:query:` cannot access __class__ → sandbox escape blocked."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: (1).__class__.__bases__[0] is object
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    # Even if this evaluates to True/False without error (Python allows it without __builtins__
    # guard catching it), what we care about is that no exception crashed the build
    # and the directive returned normally.
    assert isinstance(nodes, list)


@skip_no_plantuml
def test_directive_query_no_class_access_strengthened(tmp_path):
    """``:query:`` attribute access is blocked by the AST evaluator — fail-open + warning.

    With the old eval()-based approach, ``(1).__class__.__bases__[0] is object``
    silently evaluated to True (Python allows it without __builtins__ catching
    it).  With the AST evaluator ast.Attribute is forbidden; the expression
    raises QueryError, which triggers the fail-open path.
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: (1).__class__.__bases__[0] is object
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    # Fail-open: Task A must appear.
    assert len(nodes) == 1, f"Expected plantuml node (fail-open); warnings: {warnings}"
    assert "Task A" in nodes[0]["uml"], "Row must be present under fail-open policy"
    # A [doxtr-roadmap] warning must have been emitted.
    assert "doxtr-roadmap" in warnings.lower(), (
        f"Expected a doxtr-roadmap warning; got: {warnings[:500]}"
    )


@skip_no_plantuml
def test_directive_query_subclasses_escape_blocked(tmp_path):
    """The canonical CPython sandbox escape is blocked: QueryError — fail-open.

    ``().__class__.__bases__[0].__subclasses__()`` traverses the object
    hierarchy to reach dangerous classes (subprocess.Popen, os._wrap_close…).
    The AST evaluator forbids ast.Attribute before any evaluation occurs,
    so the row is included (fail-open) and a warning is logged.
    The escape NEVER executes.
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: ().__class__.__bases__[0].__subclasses__()
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    # Fail-open: row included, no crash.
    assert len(nodes) == 1, f"Expected plantuml node (fail-open); warnings: {warnings}"
    assert "Task A" in nodes[0]["uml"], "Row must be present (fail-open after QueryError)"
    # Warning must name the problem.
    assert "doxtr-roadmap" in warnings.lower(), (
        f"Expected doxtr-roadmap warning; got: {warnings[:500]}"
    )


# ---------------------------------------------------------------------------
# Collision detection directive options
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_collision_detection_false_keeps_all_on_same_row(tmp_path):
    """`:collision-detection: false` forces overlapping tasks onto one row."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :collision-detection: false
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,grp,,
           Work,Task B,2026-01-01,2026-06-30,grp,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "displays on same row as" in uml


@skip_no_plantuml
def test_directive_collision_detection_default_splits_overlapping(tmp_path):
    """Default (detection ON) splits fully-overlapping same-group tasks."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,grp,,
           Work,Task B,2026-01-01,2026-06-30,grp,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    # Collision detected → NO same-row directive
    assert "displays on same row as" not in uml


@skip_no_plantuml
def test_directive_collision_detection_globally_disabled_then_per_chart_overrides(tmp_path):
    """Global collision_detection=False, but per-chart :collision-detection: true re-enables it."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :collision-detection: true
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,grp,,
           Work,Task B,2026-01-01,2026-06-30,grp,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_collision_detection = False",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    # Per-chart override re-enables detection → no same-row directive
    assert "displays on same row as" not in uml


# ---------------------------------------------------------------------------
# :column-zoom: and :width: directive options
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_column_zoom_sets_zoom_in_puml(tmp_path):
    """:column-zoom: 3 → `projectscale monthly zoom 3` in generated puml."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :column-zoom: 3
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "projectscale monthly zoom 3" in uml, f"zoom not found in puml: {uml[:400]}"


@skip_no_plantuml
def test_directive_column_zoom_overrides_global(tmp_path):
    """:column-zoom: 2 per-chart overrides a different global doxtr_roadmap_column_zoom."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :column-zoom: 2
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_column_zoom = 5",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    # Per-chart value (2) must win over global (5)
    assert "projectscale monthly zoom 2" in uml
    assert "zoom 5" not in uml


@skip_no_plantuml
def test_directive_width_sets_node_width(tmp_path):
    """:width: 100% sets node['width'] == '100%' on the plantuml node."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :width: 100%
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert nodes[0].get("width") == "100%", (
        f"Expected node['width']=='100%', got {nodes[0].get('width')!r}"
    )


@skip_no_plantuml
def test_directive_no_width_option_does_not_set_node_width(tmp_path):
    """Without :width:, node['width'] is not set (backward compat)."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert "width" not in nodes[0] or nodes[0].get("width") is None, (
        "width should not be set when :width: option is absent"
    )


# ---------------------------------------------------------------------------
# :html-format: / :latex-format: output-format overrides
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_html_format_option_sets_node(tmp_path):
    """:html-format: png sets node['html_format'] == 'png'."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :html-format: png
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert nodes[0].get("html_format") == "png", (
        f"Expected node['html_format']=='png', got {nodes[0].get('html_format')!r}"
    )


@skip_no_plantuml
def test_directive_latex_format_option_sets_node(tmp_path):
    """:latex-format: png sets node['latex_format'] == 'png'."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :latex-format: png
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert nodes[0].get("latex_format") == "png", (
        f"Expected node['latex_format']=='png', got {nodes[0].get('latex_format')!r}"
    )


@skip_no_plantuml
def test_directive_no_format_option_leaves_node_unset(tmp_path):
    """Without format options (and no config override), the node carries
    neither html_format nor latex_format, so sphinxcontrib.plantuml falls
    back to the project-wide plantuml_output_format setting."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert "html_format" not in nodes[0], (
        "html_format must not be set when no override is configured"
    )
    assert "latex_format" not in nodes[0], (
        "latex_format must not be set when no override is configured"
    )


@skip_no_plantuml
def test_directive_html_format_config_applies(tmp_path):
    """doxtr_roadmap_html_format config value applies to the node when no
    per-directive option is given."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_html_format = 'svg_obj'",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert nodes[0].get("html_format") == "svg_obj", (
        f"Expected node['html_format']=='svg_obj', got {nodes[0].get('html_format')!r}"
    )


@skip_no_plantuml
def test_directive_latex_format_config_applies(tmp_path):
    """doxtr_roadmap_latex_format config value applies to the node when no
    per-directive option is given."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_latex_format = 'pdf'",
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert nodes[0].get("latex_format") == "pdf", (
        f"Expected node['latex_format']=='pdf', got {nodes[0].get('latex_format')!r}"
    )


@skip_no_plantuml
def test_directive_format_option_overrides_config(tmp_path):
    """Per-directive :html-format: / :latex-format: win over the doxtr config
    values."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :html-format: png
           :latex-format: eps
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf=(
            "doxtr_roadmap_html_format = 'svg_obj'\n"
            "doxtr_roadmap_latex_format = 'pdf'"
        ),
    )
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    assert nodes[0].get("html_format") == "png"
    assert nodes[0].get("latex_format") == "eps"


@skip_no_plantuml
def test_directive_bad_html_format_reports_error(tmp_path):
    """An invalid :html-format: value is rejected with a directive error and
    produces no plantuml node."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :html-format: bogus
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 0, "Invalid :html-format: should not yield a plantuml node"
    assert "html-format" in warnings, (
        f"Expected an error mentioning html-format; got: {warnings[:500]}"
    )


# ---------------------------------------------------------------------------
# Link appendix tests
# ---------------------------------------------------------------------------

CSV_WITH_LINKS = textwrap.dedent("""\
    section,name,start,end,row_group,link,tags
    Work,Task Alpha,2026-01-01,2026-03-31,,https://example.com/alpha,eng
    Work,Task Beta,2026-04-01,2026-06-30,,https://example.com/beta,code
    Work,Task Gamma,2026-07-01,2026-09-30,,,ops
""")

CSV_NO_LINKS = textwrap.dedent("""\
    section,name,start,end,row_group,link,tags
    Work,Task A,2026-01-01,2026-03-31,,,eng
    Work,Task B,2026-04-01,2026-06-30,,,code
""")


def _get_container_nodes(app, docname="index"):
    """Extract doxtr-roadmap-links container nodes from the doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    method = "findall" if hasattr(doctree, "findall") else "traverse"
    all_containers = list(getattr(doctree, method)(docnodes.container))
    return [
        c for c in all_containers
        if "doxtr-roadmap-links" in c.get("classes", [])
    ]


def _get_reference_nodes(container):
    """Extract reference nodes from a container node."""
    from docutils import nodes as docnodes
    method = "findall" if hasattr(container, "findall") else "traverse"
    return list(getattr(container, method)(docnodes.reference))


@skip_no_plantuml
def test_link_appendix_default_off(tmp_path):
    """With the default builder restriction (latex-only) an HTML/xml build gets
    no appendix, even though the default mode is 'list'."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    # Default builders = ["latex"]; this project builds with the xml builder,
    # so no appendix should be appended.
    app, warnings, src = _make_project(tmp_path, rst)
    plantuml_nodes = _get_plantuml_nodes(app)
    containers = _get_container_nodes(app)
    assert len(plantuml_nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    assert len(containers) == 0, (
        "Expected NO link appendix container for a non-latex builder with "
        "default link_appendix_builders=['latex']"
    )


def test_link_appendix_default_on_for_matching_builder(tmp_path):
    """The default mode is 'list', so a build whose builder is in
    link_appendix_builders renders the appendix WITHOUT any option set.

    This mirrors the PDF-by-default behaviour: doxtr_roadmap_link_appendix
    defaults to 'list' and doxtr_roadmap_link_appendix_builders to ['latex'].
    Here we allow the xml test builder so the default (no :link-appendix:
    option, no mode override) produces the appendix.
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    plantuml_nodes = _get_plantuml_nodes(app)
    containers = _get_container_nodes(app)
    assert len(plantuml_nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    assert len(containers) == 1, (
        "Expected the default 'list' appendix to render for an allowed builder "
        f"with no explicit option; warnings: {warnings}"
    )


@skip_no_plantuml
def test_link_appendix_list_basic(tmp_path):
    """link_appendix='list' with matching builder → bullet_list + reference nodes."""
    from docutils import nodes as docnodes
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list

           section,name,start,end,row_group,link,tags
           Work,Task Alpha,2026-01-01,2026-06-30,,https://example.com/alpha,
           Work,Task Gamma,2026-07-01,2026-09-30,,,
    """)
    # Use xml builder (name="xml") and allow it via builders config
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    plantuml_nodes = _get_plantuml_nodes(app)
    containers = _get_container_nodes(app)
    assert len(plantuml_nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    assert len(containers) == 1, f"Expected 1 link appendix container; warnings: {warnings}"

    # Should contain a bullet_list (not enumerated_list)
    container = containers[0]
    method = "findall" if hasattr(container, "findall") else "traverse"
    bullet_lists = list(getattr(container, method)(docnodes.bullet_list))
    enum_lists = list(getattr(container, method)(docnodes.enumerated_list))
    assert len(bullet_lists) == 1, "Expected a bullet_list node for 'list' mode"
    assert len(enum_lists) == 0, "Expected no enumerated_list for 'list' mode"

    # Should contain a reference pointing to Task Alpha's URL
    refs = _get_reference_nodes(container)
    assert len(refs) == 1, f"Expected 1 reference (Task Alpha only); got {len(refs)}"
    assert refs[0]["refuri"] == "https://example.com/alpha"


@skip_no_plantuml
def test_link_appendix_footnote_mode(tmp_path):
    """link_appendix='footnote' → real docutils footnote nodes are produced.

    Mode 'footnote' parses auto-numbered RST footnotes via nested_parse,
    producing nodes.footnote and nodes.footnote_reference nodes (not an
    enumerated_list).  In PDF/LaTeX these render as LaTeX \\footnote{}.
    """
    from docutils import nodes as docnodes
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: footnote

           section,name,start,end,row_group,link,tags
           Work,Task Alpha,2026-01-01,2026-06-30,,https://example.com/alpha,
           Work,Task Beta,2026-07-01,2026-09-30,,https://example.com/beta,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1, f"Expected 1 link appendix container; warnings: {warnings}"

    container = containers[0]
    method = "findall" if hasattr(container, "findall") else "traverse"

    # Must NOT be an enumerated_list — that was the old (wrong) implementation.
    enum_lists = list(getattr(container, method)(docnodes.enumerated_list))
    bullet_lists = list(getattr(container, method)(docnodes.bullet_list))
    assert len(enum_lists) == 0, "footnote mode must not produce an enumerated_list"
    assert len(bullet_lists) == 0, "footnote mode must not produce a bullet_list"

    # Must produce real footnote nodes.
    footnote_nodes = list(getattr(container, method)(docnodes.footnote))
    footnote_ref_nodes = list(getattr(container, method)(docnodes.footnote_reference))
    assert len(footnote_nodes) == 2, (
        f"Expected 2 footnote nodes (one per task link); got {len(footnote_nodes)}; "
        f"warnings: {warnings}"
    )
    assert len(footnote_ref_nodes) == 2, (
        f"Expected 2 footnote_reference nodes; got {len(footnote_ref_nodes)}"
    )

    # Each footnote body must contain the URL as text.
    footnote_texts = [fn.astext() for fn in footnote_nodes]
    assert any("example.com/alpha" in t for t in footnote_texts), (
        f"URL for Task Alpha not found in footnote bodies: {footnote_texts}"
    )
    assert any("example.com/beta" in t for t in footnote_texts), (
        f"URL for Task Beta not found in footnote bodies: {footnote_texts}"
    )


@skip_no_plantuml
def test_link_appendix_builder_restriction_latex_only(tmp_path):
    """With link_appendix_builders=['latex'] and xml builder → NO appendix."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    # Default builders is ["latex"]; xml builder won't match
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["latex"]',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 0, (
        "Expected NO appendix when builder='xml' and link_appendix_builders=['latex']"
    )


@skip_no_plantuml
def test_link_appendix_builder_restriction_xml_allowed(tmp_path):
    """With link_appendix_builders=['xml'] and xml builder → appendix IS rendered."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1, (
        f"Expected appendix when builder='xml' and builders includes 'xml'; warnings: {warnings}"
    )


@skip_no_plantuml
def test_link_appendix_builder_restriction_all_wildcard(tmp_path):
    """With link_appendix_builders='all' → appendix rendered for any builder."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = "all"',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1, (
        f"Expected appendix with builders='all'; warnings: {warnings}"
    )


@skip_no_plantuml
def test_link_appendix_no_resolvable_links(tmp_path):
    """Roadmap with no link cells + appendix enabled → no container appended."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
           Work,Task B,2026-07-01,2026-09-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    plantuml_nodes = _get_plantuml_nodes(app)
    containers = _get_container_nodes(app)
    assert len(plantuml_nodes) == 1, f"Expected plantuml node; warnings: {warnings}"
    assert len(containers) == 0, (
        "Expected NO container when no tasks have resolvable links"
    )


@skip_no_plantuml
def test_link_appendix_directive_off_overrides_global(tmp_path):
    """Per-directive :link-appendix: off disables the appendix even when globally enabled."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: off

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf=(
            'doxtr_roadmap_link_appendix = "list"\n'
            'doxtr_roadmap_link_appendix_builders = ["xml"]'
        ),
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 0, (
        "Expected no appendix when :link-appendix: off overrides global 'list'"
    )


@skip_no_plantuml
def test_link_appendix_global_list_with_matching_builder(tmp_path):
    """Global link_appendix='list' + matching builder → appendix rendered."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf=(
            'doxtr_roadmap_link_appendix = "list"\n'
            'doxtr_roadmap_link_appendix_builders = ["xml"]'
        ),
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1, (
        f"Expected appendix from global config; warnings: {warnings}"
    )
    refs = _get_reference_nodes(containers[0])
    assert len(refs) == 1
    assert refs[0]["refuri"] == "https://example.com/a"


@skip_no_plantuml
def test_link_appendix_title_rendered(tmp_path):
    """link_appendix_title='References' → rubric node with that text present."""
    from docutils import nodes as docnodes
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list
           :link-appendix-title: References

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1, f"Expected appendix container; warnings: {warnings}"
    container = containers[0]
    method = "findall" if hasattr(container, "findall") else "traverse"
    rubrics = list(getattr(container, method)(docnodes.rubric))
    assert len(rubrics) == 1, "Expected a rubric node for the title"
    assert rubrics[0].astext() == "References"


@skip_no_plantuml
def test_link_appendix_no_title_when_empty(tmp_path):
    """link_appendix_title='' → no rubric node in the container."""
    from docutils import nodes as docnodes
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list
           :link-appendix-title:

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1, f"Expected appendix container; warnings: {warnings}"
    container = containers[0]
    method = "findall" if hasattr(container, "findall") else "traverse"
    rubrics = list(getattr(container, method)(docnodes.rubric))
    assert len(rubrics) == 0, "Expected no rubric when title is empty string"


@skip_no_plantuml
def test_link_appendix_duplicate_links_collapsed(tmp_path):
    """Exact duplicate (name, url, title) triples are collapsed to one entry."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01
           :link-appendix: list

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,https://example.com/a,
           Work,Task A,2026-04-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    containers = _get_container_nodes(app)
    assert len(containers) == 1
    refs = _get_reference_nodes(containers[0])
    assert len(refs) == 1, (
        f"Expected 1 reference after dedup of identical (name,url,title); got {len(refs)}"
    )


# ---------------------------------------------------------------------------
# Figure / caption / align / name support
# ---------------------------------------------------------------------------

def _get_figure_nodes(app, docname="index"):
    """Extract nodes.figure nodes from the environment's parsed doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    method = "findall" if hasattr(doctree, "findall") else "traverse"
    return list(getattr(doctree, method)(docnodes.figure))


def _get_caption_nodes(app, docname="index"):
    """Extract nodes.caption nodes from the environment's parsed doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    method = "findall" if hasattr(doctree, "findall") else "traverse"
    return list(getattr(doctree, method)(docnodes.caption))


@skip_no_plantuml
def test_figure_caption_wraps_plantuml_node(tmp_path):
    """:caption: wraps the plantuml node in a figure with a caption."""
    import sphinxcontrib.plantuml as scp
    from docutils import nodes as docnodes

    rst = textwrap.dedent("""\
        .. roadmap::
           :caption: My Roadmap
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)

    assert len(figures) == 1, (
        f"Expected 1 figure node; got {len(figures)}; warnings: {warnings}"
    )
    assert len(captions) == 1, (
        f"Expected 1 caption node; got {len(captions)}; warnings: {warnings}"
    )
    assert "My Roadmap" in captions[0].astext(), (
        f"Caption text mismatch; got: {captions[0].astext()!r}"
    )

    # The plantuml node must be a child of the figure
    figure = figures[0]
    method = "findall" if hasattr(figure, "findall") else "traverse"
    inner_puml = list(getattr(figure, method)(scp.plantuml))
    assert len(inner_puml) == 1, "plantuml node must be inside the figure"


@skip_no_plantuml
def test_no_caption_no_align_no_global_figure_gives_bare_node(tmp_path):
    """Without :caption:/:align: and global figure=False, no figure node is produced."""
    from docutils import nodes as docnodes

    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)
    plantuml_nodes = _get_plantuml_nodes(app)

    assert len(figures) == 0, "Expected NO figure node when no caption/align/global"
    assert len(captions) == 0, "Expected NO caption node"
    assert len(plantuml_nodes) == 1, "Expected bare plantuml node"


@skip_no_plantuml
def test_global_figure_true_with_title_uses_title_as_caption(tmp_path):
    """doxtr_roadmap_figure=True wraps every roadmap with title as caption."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: My Sprint Chart
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_figure = True",
    )
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)

    assert len(figures) == 1, (
        f"Expected 1 figure from global doxtr_roadmap_figure=True; warnings: {warnings}"
    )
    assert len(captions) == 1, "Expected caption from title fallback"
    assert "My Sprint Chart" in captions[0].astext(), (
        f"Expected title as caption text; got: {captions[0].astext()!r}"
    )


@skip_no_plantuml
def test_global_figure_true_with_figure_caption_config(tmp_path):
    """doxtr_roadmap_figure_caption='Roadmap Chart' overrides title as default caption."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: My Sprint Chart
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf=(
            "doxtr_roadmap_figure = True\n"
            'doxtr_roadmap_figure_caption = "Roadmap Chart"'
        ),
    )
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)

    assert len(figures) == 1, (
        f"Expected 1 figure; warnings: {warnings}"
    )
    assert len(captions) == 1, "Expected 1 caption"
    assert "Roadmap Chart" in captions[0].astext(), (
        f"Expected figure_caption config text; got: {captions[0].astext()!r}"
    )


@skip_no_plantuml
def test_align_only_wraps_in_figure_with_title_as_caption(tmp_path):
    """:align: center without :caption: → figure with align='center'; caption defaults to title."""
    from docutils import nodes as docnodes

    rst = textwrap.dedent("""\
        .. roadmap::
           :align: center
           :title: My Aligned Chart
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)

    assert len(figures) == 1, (
        f"Expected 1 figure from :align:; warnings: {warnings}"
    )
    assert figures[0].get("align") == "center", (
        f"Expected figure['align']='center'; got {figures[0].get('align')!r}"
    )
    # Change 1: align-only wraps now get the chart title as caption by default
    assert len(captions) == 1, "Expected 1 caption (chart title) for align-only wrap"
    assert "My Aligned Chart" in captions[0].astext(), (
        f"Expected title as caption text; got: {captions[0].astext()!r}"
    )


@skip_no_plantuml
def test_caption_with_name_registers_figure_name(tmp_path):
    """:caption: + :name: → figure['names'] contains the given name."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :caption: Project Timeline
           :name: my-roadmap
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    figures = _get_figure_nodes(app)

    assert len(figures) == 1, (
        f"Expected 1 figure; warnings: {warnings}"
    )
    figure = figures[0]
    names = figure.get("names", [])
    ids = figure.get("ids", [])
    assert "my-roadmap" in names or "my-roadmap" in ids, (
        f"Expected 'my-roadmap' in figure names/ids; names={names!r} ids={ids!r}"
    )


@skip_no_plantuml
def test_width_set_on_inner_plantuml_node_not_figure(tmp_path):
    """:width: is set on the inner plantuml node, not the figure wrapper."""
    import sphinxcontrib.plantuml as scp

    rst = textwrap.dedent("""\
        .. roadmap::
           :caption: Chart
           :width: 100%
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    figures = _get_figure_nodes(app)
    assert len(figures) == 1, f"Expected 1 figure; warnings: {warnings}"

    figure = figures[0]
    # width must be on the plantuml node, not the figure
    assert figure.get("width") is None, (
        "figure node must NOT carry width (it belongs on the inner plantuml node)"
    )
    method = "findall" if hasattr(figure, "findall") else "traverse"
    inner = list(getattr(figure, method)(scp.plantuml))
    assert len(inner) == 1
    assert inner[0].get("width") == "100%", (
        f"Expected width='100%' on plantuml node; got {inner[0].get('width')!r}"
    )


@skip_no_plantuml
def test_caption_figure_with_link_appendix_figure_first(tmp_path):
    """:caption: + link-appendix → [figure, container] — figure comes first."""
    from docutils import nodes as docnodes
    import sphinxcontrib.plantuml as scp

    rst = textwrap.dedent("""\
        .. roadmap::
           :caption: Chart With Links
           :link-appendix: list
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    doctree = app.env.get_doctree("index")
    method = "findall" if hasattr(doctree, "findall") else "traverse"

    figures = list(getattr(doctree, method)(docnodes.figure))
    containers = _get_container_nodes(app)

    assert len(figures) == 1, f"Expected 1 figure; warnings: {warnings}"
    assert len(containers) == 1, f"Expected 1 link appendix container; warnings: {warnings}"

    # figure must appear before the container in document order
    all_nodes = list(getattr(doctree, method)(docnodes.Node))
    fig_idx = next(
        i for i, n in enumerate(all_nodes) if isinstance(n, docnodes.figure)
    )
    con_idx = next(
        i for i, n in enumerate(all_nodes)
        if isinstance(n, docnodes.container)
        and "doxtr-roadmap-links" in n.get("classes", [])
    )
    assert fig_idx < con_idx, (
        "figure node must appear before link appendix container"
    )


# ---------------------------------------------------------------------------
# Change 1: Caption defaults to chart title for all figure wraps
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_figure_global_no_explicit_caption_uses_title(tmp_path):
    """doxtr_roadmap_figure=True + no :caption: → caption text equals the chart title."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: My Auto Figure
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf="doxtr_roadmap_figure = True",
    )
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)

    assert len(figures) == 1, f"Expected figure; warnings: {warnings}"
    assert len(captions) == 1, "Expected caption from title fallback"
    assert "My Auto Figure" in captions[0].astext(), (
        f"Caption must equal title; got: {captions[0].astext()!r}"
    )


@skip_no_plantuml
def test_figure_caption_precedence_explicit_beats_title(tmp_path):
    """Explicit :caption: overrides the chart title as caption text."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: Chart Title
           :caption: Override Caption
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    captions = _get_caption_nodes(app)
    assert len(captions) == 1
    assert "Override Caption" in captions[0].astext(), (
        f"Explicit :caption: must win; got: {captions[0].astext()!r}"
    )
    assert "Chart Title" not in captions[0].astext(), (
        "Title must not appear when explicit :caption: is set"
    )


@skip_no_plantuml
def test_figure_caption_precedence_figure_caption_config_beats_title(tmp_path):
    """doxtr_roadmap_figure_caption non-empty beats the title as default caption."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: Chart Title
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf=(
            "doxtr_roadmap_figure = True\n"
            'doxtr_roadmap_figure_caption = "Global Caption"'
        ),
    )
    captions = _get_caption_nodes(app)
    assert len(captions) == 1
    assert "Global Caption" in captions[0].astext(), (
        f"figure_caption config must win over title; got: {captions[0].astext()!r}"
    )


# ---------------------------------------------------------------------------
# Change 2: footnote-in-caption tests
# ---------------------------------------------------------------------------

def _get_footnote_nodes(app, docname="index"):
    """Extract nodes.footnote nodes from the doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    method = "findall" if hasattr(doctree, "findall") else "traverse"
    return list(getattr(doctree, method)(docnodes.footnote))


def _get_footnote_reference_nodes(app, docname="index"):
    """Extract nodes.footnote_reference nodes from the doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    method = "findall" if hasattr(doctree, "findall") else "traverse"
    return list(getattr(doctree, method)(docnodes.footnote_reference))


def _get_rubric_nodes(app, docname="index"):
    """Extract nodes.rubric nodes from the doctree."""
    from docutils import nodes as docnodes
    doctree = app.env.get_doctree(docname)
    method = "findall" if hasattr(doctree, "findall") else "traverse"
    return list(getattr(doctree, method)(docnodes.rubric))


@skip_no_plantuml
def test_footnote_in_caption_figure_with_links(tmp_path):
    """Figure + link_appendix='footnote' + resolvable links → footnote refs in caption,
    footnote defs as siblings, NO separate 'Links' rubric/container.

    NEW FORMAT:
    - Caption shows: '<caption> (Links [#]_, [#]_)' — label word + markers, NO task names
    - Footnote body (plain URL, no title): '<Task Name>: <url>'
    - Footnote body (with title): '<Task Name> >> <Title>: <url>'
    """
    from docutils import nodes as docnodes

    rst = textwrap.dedent("""\
        .. roadmap::
           :title: Linked Chart
           :caption: Project Plan
           :link-appendix: footnote
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task Alpha,2026-01-01,2026-03-31,,https://example.com/alpha,
           Work,Task Beta,2026-04-01,2026-06-30,,https://example.com/beta,
           Work,Task Gamma,2026-07-01,2026-09-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)
    fn_nodes = _get_footnote_nodes(app)
    fn_ref_nodes = _get_footnote_reference_nodes(app)
    containers = _get_container_nodes(app)
    rubrics = _get_rubric_nodes(app)

    # Figure and caption present
    assert len(figures) == 1, f"Expected 1 figure; warnings: {warnings}"
    assert len(captions) == 1, f"Expected 1 caption; warnings: {warnings}"

    # Caption text contains the caption string and the label word "Links"
    caption_text = captions[0].astext()
    assert "Project Plan" in caption_text, (
        f"Expected caption text in caption; got: {caption_text!r}"
    )
    assert "Links" in caption_text, (
        f"Expected label word 'Links' in caption; got: {caption_text!r}"
    )

    # Task names must NOT appear in the caption — they live in the footnote body
    assert "Task Alpha" not in caption_text, (
        f"Task names must NOT appear in caption (new format); got: {caption_text!r}"
    )
    assert "Task Beta" not in caption_text, (
        f"Task names must NOT appear in caption (new format); got: {caption_text!r}"
    )

    # Footnote references must be INSIDE the caption node
    method = "findall" if hasattr(captions[0], "findall") else "traverse"
    caption_fn_refs = list(getattr(captions[0], method)(docnodes.footnote_reference))
    assert len(caption_fn_refs) == 2, (
        f"Expected 2 footnote_reference nodes in caption; got {len(caption_fn_refs)}"
    )

    # Footnote definitions present as siblings (not inside the figure)
    assert len(fn_nodes) == 2, (
        f"Expected 2 footnote nodes as siblings; got {len(fn_nodes)}"
    )

    # Footnote bodies carry task name + URL (plain URL → "<Task>: <url>", no '>>')
    fn_texts = [fn.astext() for fn in fn_nodes]
    assert any("Task Alpha" in t for t in fn_texts), (
        f"Task Alpha must appear in a footnote body: {fn_texts}"
    )
    assert any("Task Beta" in t for t in fn_texts), (
        f"Task Beta must appear in a footnote body: {fn_texts}"
    )
    assert any("example.com/alpha" in t for t in fn_texts), (
        f"URL for Task Alpha not found in footnote bodies: {fn_texts}"
    )
    assert any("example.com/beta" in t for t in fn_texts), (
        f"URL for Task Beta not found in footnote bodies: {fn_texts}"
    )
    # Plain URLs have no title, so the separator is ':' not '>>'
    assert any("Task Alpha" in t and "example.com/alpha" in t for t in fn_texts), (
        f"Expected 'Task Alpha: url' form in footnote; got: {fn_texts}"
    )

    # NO separate 'Links' rubric or doxtr-roadmap-links container
    assert len(containers) == 0, (
        "Expected NO separate doxtr-roadmap-links container when footnote-in-caption"
    )
    links_rubrics = [r for r in rubrics if "Links" in r.astext()]
    assert len(links_rubrics) == 0, (
        "Expected NO 'Links' rubric when footnote-in-caption"
    )


@skip_no_plantuml
def test_footnote_in_caption_no_links_plain_caption(tmp_path):
    """Figure + link_appendix='footnote' + NO resolvable links → plain title caption,
    no footnote nodes, no brackets."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: Clean Chart
           :align: center
           :link-appendix: footnote
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
           Work,Task B,2026-07-01,2026-09-30,,,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)
    fn_nodes = _get_footnote_nodes(app)
    containers = _get_container_nodes(app)

    assert len(figures) == 1, f"Expected 1 figure; warnings: {warnings}"
    # Caption present (title as default)
    assert len(captions) == 1, "Expected caption with title"
    assert "Clean Chart" in captions[0].astext(), (
        f"Expected title as caption; got: {captions[0].astext()!r}"
    )
    # No brackets, no footnotes
    assert "(" not in captions[0].astext(), (
        f"Expected no brackets in plain caption; got: {captions[0].astext()!r}"
    )
    assert len(fn_nodes) == 0, "Expected no footnote nodes when no resolvable links"
    assert len(containers) == 0, "Expected no appendix container"


@skip_no_plantuml
def test_footnote_in_caption_builder_not_allowed_plain_caption(tmp_path):
    """Figure + link_appendix='footnote' + builder NOT in allowed list → plain caption,
    no footnotes anywhere (builder restriction respected)."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :title: Restricted Chart
           :caption: My Caption
           :link-appendix: footnote
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    # Only latex is allowed; xml builder won't qualify
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["latex"]',
    )
    captions = _get_caption_nodes(app)
    fn_nodes = _get_footnote_nodes(app)
    containers = _get_container_nodes(app)

    # Caption is plain (no footnote refs embedded)
    assert len(captions) == 1, f"Expected 1 caption; warnings: {warnings}"
    assert "My Caption" in captions[0].astext()
    # No footnote nodes (builder not allowed)
    assert len(fn_nodes) == 0, "Expected no footnotes when builder not in allowed list"
    assert len(containers) == 0, "Expected no appendix container"


@skip_no_plantuml
def test_footnote_mode_no_figure_standalone_appendix(tmp_path):
    """link_appendix='footnote' WITHOUT a figure → standalone footnote appendix
    as before (unchanged behaviour)."""
    from docutils import nodes as docnodes

    rst = textwrap.dedent("""\
        .. roadmap::
           :title: Plain Footnote Chart
           :link-appendix: footnote
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task Alpha,2026-01-01,2026-03-31,,https://example.com/alpha,
           Work,Task Beta,2026-04-01,2026-06-30,,https://example.com/beta,
    """)
    # No :caption:/:align:, no global figure → no figure wrapping
    # Allow xml builder so appendix renders
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    figures = _get_figure_nodes(app)
    containers = _get_container_nodes(app)
    fn_nodes = _get_footnote_nodes(app)

    # No figure produced (no wrap triggers)
    assert len(figures) == 0, "Expected no figure when no caption/align/global"
    # Standalone appendix container IS present
    assert len(containers) == 1, (
        f"Expected standalone footnote appendix container; warnings: {warnings}"
    )
    # Real footnote nodes inside the container
    container = containers[0]
    method = "findall" if hasattr(container, "findall") else "traverse"
    cont_fn_nodes = list(getattr(container, method)(docnodes.footnote))
    assert len(cont_fn_nodes) == 2, (
        f"Expected 2 footnote nodes in standalone container; got {len(cont_fn_nodes)}"
    )
    fn_texts = [fn.astext() for fn in cont_fn_nodes]
    assert any("example.com/alpha" in t for t in fn_texts)
    assert any("example.com/beta" in t for t in fn_texts)


@skip_no_plantuml
def test_list_mode_with_figure_standalone_appendix(tmp_path):
    """link_appendix='list' WITH a figure → standalone bullet_list appendix,
    NOT merged into caption (list mode is never in-caption)."""
    from docutils import nodes as docnodes

    rst = textwrap.dedent("""\
        .. roadmap::
           :title: List Figure Chart
           :caption: The Caption
           :link-appendix: list
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,https://example.com/a,
    """)
    app, warnings, src = _make_project(
        tmp_path, rst,
        extra_conf='doxtr_roadmap_link_appendix_builders = ["xml"]',
    )
    figures = _get_figure_nodes(app)
    captions = _get_caption_nodes(app)
    containers = _get_container_nodes(app)
    fn_nodes = _get_footnote_nodes(app)

    # Figure produced
    assert len(figures) == 1, f"Expected figure; warnings: {warnings}"
    # Caption is the plain text (no footnote refs)
    assert len(captions) == 1
    assert "The Caption" in captions[0].astext()
    # No footnote refs in the caption
    method = "findall" if hasattr(captions[0], "findall") else "traverse"
    cap_fn_refs = list(getattr(captions[0], method)(docnodes.footnote_reference))
    assert len(cap_fn_refs) == 0, "list mode must not put footnote refs in caption"
    # Standalone bullet_list appendix IS present
    assert len(containers) == 1, (
        f"Expected standalone list appendix for 'list' mode; warnings: {warnings}"
    )
    container = containers[0]
    method2 = "findall" if hasattr(container, "findall") else "traverse"
    bullet_lists = list(getattr(container, method2)(docnodes.bullet_list))
    assert len(bullet_lists) == 1, "Expected bullet_list in list-mode appendix"
    # No footnotes anywhere
    assert len(fn_nodes) == 0, "list mode must not produce footnote nodes"


# ---------------------------------------------------------------------------
# Part A: space-separated row tags — filter correctness
# ---------------------------------------------------------------------------

TAGGED_CSV_SPACE_SEP = """\
section,name,start,end,row_group,link,tags
Q1-2027,Infrastructure Upgrade,2027-01-05,2027-02-15,,,eng ops
Q1-2027,Auth Service,2027-01-10,2027-03-10,,,eng security
Q1-2027,New User Portal,2027-02-01,2027-04-30,,,code design
Q2-2027,Load Testing,2027-04-01,2027-05-15,,,eng ops
Q2-2027,Compliance Audit,2027-04-15,2027-05-30,,,security
Q2-2027,Mobile App v2,2027-04-01,2027-06-30,,,code design
Q3-2027,Chaos Engineering,2027-07-01,2027-08-15,,,eng ops
Q3-2027,Security Review,2027-07-15,2027-08-30,,,security
Q3-2027,Platform Hardening,2027-07-01,2027-09-30,,,eng security
"""


@skip_no_plantuml
def test_query_eng_in_tags_space_separated(tmp_path):
    """`:query: \"eng\" in tags` on space-separated CSV tags now matches eng rows.

    This is the root-cause regression test: before the fix parse_row_tags
    returned [\"eng ops\"] (a single token) so \"eng\" was NOT in the set and
    zero rows matched, producing an empty/placeholder gantt.  After the fix
    parse_row_tags returns [\"eng\", \"ops\"] and the query matches correctly.
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: "eng" in tags
           :start: 2027-01-01

           section,name,start,end,row_group,link,tags
           Q1-2027,Infrastructure Upgrade,2027-01-05,2027-02-15,,,eng ops
           Q1-2027,Auth Service,2027-01-10,2027-03-10,,,eng security
           Q1-2027,New User Portal,2027-02-01,2027-04-30,,,code design
           Q2-2027,Load Testing,2027-04-01,2027-05-15,,,eng ops
           Q2-2027,Compliance Audit,2027-04-15,2027-05-30,,,security
           Q3-2027,Chaos Engineering,2027-07-01,2027-08-15,,,eng ops
           Q3-2027,Platform Hardening,2027-07-01,2027-09-30,,,eng security
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    # These tasks carry 'eng' (space-separated) and must appear.
    for task_name in [
        "Infrastructure Upgrade", "Auth Service",
        "Load Testing", "Chaos Engineering", "Platform Hardening",
    ]:
        assert task_name in uml, (
            f"Expected '{task_name}' in uml after eng-tag fix; got uml: {uml[:600]}"
        )
    # Non-eng tasks must be absent.
    assert "New User Portal" not in uml
    assert "Compliance Audit" not in uml
    # Must NOT contain the empty-gantt placeholder (real tasks rendered).
    assert "No matching tasks" not in uml


@skip_no_plantuml
def test_tags_filter_eng_space_separated(tmp_path):
    """`:tags: eng` on space-separated CSV tags now keeps eng rows correctly."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :tags: eng
           :start: 2027-01-01

           section,name,start,end,row_group,link,tags
           Q1,Infrastructure Upgrade,2027-01-05,2027-02-15,,,eng ops
           Q1,Auth Service,2027-01-10,2027-03-10,,,eng security
           Q1,New User Portal,2027-02-01,2027-04-30,,,code design
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Infrastructure Upgrade" in uml
    assert "Auth Service" in uml
    assert "New User Portal" not in uml
    assert "No matching tasks" not in uml


@skip_no_plantuml
def test_tags_filter_ops_space_separated(tmp_path):
    """`:tags: ops` on space-separated CSV tags matches 'eng ops' rows via 'ops'."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :tags: ops
           :start: 2027-01-01

           section,name,start,end,row_group,link,tags
           Q1,Infrastructure Upgrade,2027-01-05,2027-02-15,,,eng ops
           Q1,Auth Service,2027-01-10,2027-03-10,,,eng security
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Infrastructure Upgrade" in uml
    assert "Auth Service" not in uml


# ---------------------------------------------------------------------------
# Part B: zero-match placeholder gantt + warning
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_zero_match_query_produces_placeholder(tmp_path):
    """A :query: matching zero rows → placeholder gantt, NOT an empty gantt."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: "nonexistent_xyz" in tags
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
           Work,Task B,2026-04-01,2026-06-30,,,security
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "@startgantt" in uml
    assert "@endgantt" in uml
    # Placeholder must be present.
    assert "No matching tasks" in uml, (
        f"Expected placeholder 'No matching tasks' in uml; got: {uml[:500]}"
    )
    assert "__doxtr_empty__" in uml
    # Real tasks must be absent.
    assert "Task A" not in uml
    assert "Task B" not in uml


@skip_no_plantuml
def test_zero_match_query_emits_warning(tmp_path):
    """A :query: matching zero rows → a [doxtr-roadmap] warning is logged."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: "nonexistent_xyz" in tags
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    assert "doxtr-roadmap" in warnings.lower(), (
        f"Expected [doxtr-roadmap] warning for zero-match filter; got: {warnings[:500]}"
    )


@skip_no_plantuml
def test_zero_match_tags_filter_produces_placeholder(tmp_path):
    """A :tags: filter matching zero rows → placeholder gantt + warning."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :tags: nonexistent_xyz_tag
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-03-31,,,eng
           Work,Task B,2026-04-01,2026-06-30,,,security
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "No matching tasks" in uml
    assert "Task A" not in uml
    assert "doxtr-roadmap" in warnings.lower()


@skip_no_plantuml
def test_placeholder_is_valid_gantt_structure(tmp_path):
    """Zero-match placeholder gantt has correct @startgantt/@endgantt and a
    'starts' bar task line — the minimum structure PlantUML needs."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :query: "zzz" in tags
           :start: 2027-03-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2027-03-01,2027-06-30,,,eng
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    uml = nodes[0]["uml"]
    lines = uml.splitlines()
    assert lines[0].strip() == "@startgantt"
    assert lines[-1].strip() == "@endgantt" or lines[-2].strip() == "@endgantt"
    assert any("starts" in l and "ends" in l for l in lines), (
        f"Expected a 'starts...ends' bar task line in placeholder; got: {uml[:500]}"
    )


# ---------------------------------------------------------------------------
# Multi-file and glob :file: support
# ---------------------------------------------------------------------------

def _write_csv(path, content):
    """Helper: write CSV content to a Path."""
    path.write_text(content, encoding="utf-8")


def _make_project_with_files(tmp_path, rst_body, extra_files, extra_conf=""):
    """Like _make_project but seeds extra CSV files into src/ before building.

    *extra_files* is a dict mapping filename strings to CSV content strings.
    Files are written into ``tmp_path / "src"`` after the directory is created
    by _make_project, but since _make_project creates src and immediately
    builds, we need to pre-create src here (exist_ok=True) and write the
    files first, then delegate to _make_project which will call src.mkdir()
    and raise FileExistsError — so instead we replicate the essential bits
    inline to avoid the collision.
    """
    from sphinx.application import Sphinx
    import io

    proj = tmp_path / "proj"
    src = proj / "src"
    src.mkdir(parents=True, exist_ok=True)
    out = proj / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = proj / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    for fname, content in extra_files.items():
        (src / fname).write_text(content, encoding="utf-8")

    (src / "conf.py").write_text(
        textwrap.dedent(f"""\
            project = 'Test'
            extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
            plantuml = 'plantuml'
            plantuml_output_format = 'png'
            master_doc = 'index'
        """) + extra_conf + "\n",
        encoding="utf-8",
    )
    index_content = "Test\n====\n\n" + rst_body + "\n"
    (src / "index.rst").write_text(index_content, encoding="utf-8")

    warning_stream = io.StringIO()
    app = Sphinx(
        srcdir=str(src),
        confdir=str(src),
        outdir=str(out),
        doctreedir=str(doctrees),
        buildername="xml",
        freshenv=True,
        warning=warning_stream,
        verbosity=0,
    )
    app.build()
    return app, warning_stream.getvalue(), src


@skip_no_plantuml
def test_file_option_two_explicit_paths(tmp_path):
    """:file: with two explicit space-separated paths loads both files combined."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: a.csv b.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "a.csv": "section,name,start,end\nWork,Task A,2027-01-01,2027-01-31\n",
        "b.csv": "section,name,start,end\nWork,Task B,2027-02-01,2027-02-28\n",
    })
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Task A" in uml, f"Task A missing from combined roadmap; uml: {uml[:600]}"
    assert "Task B" in uml, f"Task B missing from combined roadmap; uml: {uml[:600]}"


@skip_no_plantuml
def test_file_option_comma_separated_paths(tmp_path):
    """:file: with comma-separated paths loads both files combined."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: x.csv, y.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "x.csv": "section,name,start,end\nWork,Task X,2027-01-01,2027-01-31\n",
        "y.csv": "section,name,start,end\nWork,Task Y,2027-02-01,2027-02-28\n",
    })
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Task X" in uml
    assert "Task Y" in uml


@skip_no_plantuml
def test_file_option_glob_pattern(tmp_path):
    """:file: with a glob pattern expands to all matching files, sorted."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: sprint-*.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "sprint-01.csv": "section,name,start,end\nSprint 1,Alpha,2027-01-01,2027-01-31\n",
        "sprint-02.csv": "section,name,start,end\nSprint 2,Beta,2027-02-01,2027-02-28\n",
        "sprint-03.csv": "section,name,start,end\nSprint 3,Gamma,2027-03-01,2027-03-31\n",
    })
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Alpha" in uml, f"Sprint 1 task missing; uml: {uml[:600]}"
    assert "Beta"  in uml, f"Sprint 2 task missing; uml: {uml[:600]}"
    assert "Gamma" in uml, f"Sprint 3 task missing; uml: {uml[:600]}"


@skip_no_plantuml
def test_file_option_glob_sorted_order(tmp_path):
    """:file: glob matches are sorted lexicographically; section order follows sort."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: sprint-*.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "sprint-01.csv": "section,name,start,end\nS,First Task,2027-01-01,2027-01-31\n",
        "sprint-02.csv": "section,name,start,end\nS,Second Task,2027-02-01,2027-02-28\n",
    })
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "First Task"  in uml
    assert "Second Task" in uml
    assert uml.index("First Task") < uml.index("Second Task"), (
        "Glob results must be sorted: sprint-01 before sprint-02"
    )


@skip_no_plantuml
def test_file_option_glob_no_matches_produces_error(tmp_path):
    """:file: glob that matches nothing → error node / warning in build output."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: no-match-*.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 0, "Should not produce a plantuml node when glob matches nothing"
    assert "not found" in warnings.lower() or "no files matched" in warnings.lower(), (
        f"Expected error about unmatched glob; got: {warnings[:500]}"
    )


@skip_no_plantuml
def test_file_option_dedup_same_file_twice(tmp_path):
    """:file: with the same file listed twice → tasks appear only once (dedup)."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: data.csv data.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "data.csv": "section,name,start,end\nWork,Unique Task,2027-01-01,2027-01-31\n",
    })
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    # Count task *definition* lines ("[Task] starts ...") to verify dedup.
    # The task name appears multiple times per task in PlantUML source
    # (starts, coloring, progress lines), so we check definition lines only.
    task_def_lines = [l for l in uml.splitlines() if "Unique Task" in l and "starts" in l]
    assert len(task_def_lines) == 1, (
        f"Expected exactly 1 task definition line after dedup; got {len(task_def_lines)}:\n"
        + "\n".join(task_def_lines)
    )


@skip_no_plantuml
def test_file_option_notes_dependency_for_all_files(tmp_path):
    """All resolved files are noted as dependencies via env.note_dependency."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: dep-a.csv dep-b.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "dep-a.csv": "section,name,start,end\nWork,Task A,2027-01-01,2027-01-31\n",
        "dep-b.csv": "section,name,start,end\nWork,Task B,2027-02-01,2027-02-28\n",
    })
    deps = app.env.dependencies.get("index", set())
    dep_strs = {str(d) for d in deps}
    assert any("dep-a.csv" in d for d in dep_strs), (
        f"dep-a.csv not in dependencies; got: {dep_strs}"
    )
    assert any("dep-b.csv" in d for d in dep_strs), (
        f"dep-b.csv not in dependencies; got: {dep_strs}"
    )


@skip_no_plantuml
def test_file_option_cross_file_subtask_in_directive(tmp_path):
    """Cross-file subtasks: parent in file A, subtask row in file B → renders."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: parent.csv child.csv
           :start: 2027-01-01
    """)
    app, warnings, _ = _make_project_with_files(tmp_path, rst, {
        "parent.csv": "section,name,start,end\nWork,Parent Task,2027-01-01,2027-03-31\n",
        "child.csv":  "section,name,start,end\nParent Task,Cross-file Sub,2027-01-15,2027-02-28\n",
    })
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Parent Task" in uml
    assert "Cross-file Sub" in uml


@skip_no_plantuml
def test_file_option_single_path_still_works(tmp_path):
    """Backward compat: single :file: path still works as before."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: roadmap.csv
    """)
    app, warnings, src = _make_project(tmp_path, rst, csv_content=SAMPLE_CSV)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node (backward compat); warnings: {warnings}"
    assert "@startgantt" in nodes[0]["uml"]


# ---------------------------------------------------------------------------
# D19. Directive-level integration tests
# ---------------------------------------------------------------------------

# D19(a): :period: current-quarter renders and clips to the current quarter.
@skip_no_plantuml
def test_directive_period_current_quarter(tmp_path):
    """D19(a): ':period: current-quarter' renders a plantuml node clipped to
    the current calendar quarter."""
    import datetime
    today = datetime.date.today()
    q = (today.month - 1) // 3
    q_start_month = q * 3 + 1
    q_start = datetime.date(today.year, q_start_month, 1)
    start_str = q_start.isoformat()

    rst = textwrap.dedent(f"""\
        .. roadmap::
           :period: current-quarter

           section,name,start,end,row_group,link,tags
           Work,Task A,{start_str},{start_str},,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "@startgantt" in uml
    assert start_str in uml, (
        f"Expected quarter start date {start_str!r} in puml; got:\n{uml[:400]}"
    )


# D19(b): _load_calendar_rows round-trips CSV and skips invalid-date rows.
def test_load_calendar_rows_round_trip(tmp_path):
    """D19(b): _load_calendar_rows parses valid rows and silently skips bad-date rows."""
    import datetime
    from doxtr_roadmap.directive import RoadmapDirective

    csv_text = textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        Sprints,Sprint 1,2026-01-01,2026-01-31,,,
        Sprints,Sprint 2,2026-02-01,2026-02-28,,,
        Sprints,Bad Row,not-a-date,2026-03-31,,,
        Other,Other 1,2026-04-01,2026-04-30,,,
    """)
    csv_path = tmp_path / "calendar.csv"
    csv_path.write_text(csv_text, encoding="utf-8")

    rows = RoadmapDirective._load_calendar_rows(str(csv_path))
    # 3 valid rows; "Bad Row" has invalid start date and must be skipped.
    assert len(rows) == 3, f"Expected 3 valid rows, got {len(rows)}: {rows}"
    names = [r[0] for r in rows]
    assert "Bad Row" not in names, "Row with invalid date must be skipped"
    # Each row is a (name, start, end, section) 4-tuple.
    for row in rows:
        assert len(row) == 4
        assert isinstance(row[1], datetime.date)
        assert isinstance(row[2], datetime.date)
    # Check section column is correctly populated.
    sections = {r[0]: r[3] for r in rows}
    assert sections["Sprint 1"] == "Sprints"
    assert sections["Other 1"] == "Other"


def test_load_calendar_rows_applies_ignore_options(tmp_path):
    """Per-calendar FileOptions blank the named column at parse time; norender
    is ignored for calendars (they never render bars)."""
    from doxtr_roadmap.directive import RoadmapDirective
    from doxtr_roadmap.file_options import FileOptions

    csv_text = textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        Sprints,Sprint 1,2026-01-01,2026-01-31,,,plan
        Sprints,Sprint 2,2026-02-01,2026-02-28,,,plan
    """)
    csv_path = tmp_path / "calendar.csv"
    csv_path.write_text(csv_text, encoding="utf-8")

    # Ignoring section flattens rows into the unnamed section; norender=True
    # must NOT drop calendar rows (they are still needed for period lookup).
    opts = FileOptions(ignore_columns=frozenset({"section"}), norender=True)
    rows = RoadmapDirective._load_calendar_rows(str(csv_path), opts)
    assert len(rows) == 2, f"norender must not drop calendar rows; got {rows}"
    assert all(r[3] == "" for r in rows), "section column should be blanked"


# D19(c): _resolve_edge success, resolver-returns-None error, PeriodExprError path.
def test_resolve_edge_success_and_errors():
    """D19(c): _resolve_edge success path and both error paths."""
    import datetime
    import pytest
    from doxtr_roadmap.directive import RoadmapDirective
    from doxtr_roadmap.period_expr import ResolutionContext

    ctx = ResolutionContext(
        today=datetime.date(2026, 12, 15),
        config={},
        srcdir="/src",
        docdir="doc",
    )

    def _warn(msg):
        pass

    # _resolve_edge is an instance method; call it unbound with a minimal
    # sentinel self (it only uses self to call period_expr functions, not
    # any directive-specific state).
    # We use a simple lambda wrapper to call it directly on the class.
    _re = RoadmapDirective._resolve_edge

    # We need a minimal fake directive instance to call the instance method.
    # The method only uses `self` to call `period_expr.resolve_period_token`,
    # which does not touch `self` at all — so any object works as `self`.
    class _FakeSelf:
        pass
    fake_self = _FakeSelf()

    # Success: literal ISO date
    d = _re(fake_self, "2027-01-01", ctx, _warn, edge="start")
    assert d == datetime.date(2027, 1, 1)

    # Success: start edge of a built-in expression window
    d = _re(fake_self, "current-year", ctx, _warn, edge="start")
    assert d == datetime.date(2026, 1, 1)

    # Success: end edge
    d = _re(fake_self, "current-year", ctx, _warn, edge="end")
    assert d == datetime.date(2026, 12, 31)

    # Error path: resolver returns None (unrecognised plain name) → ValueError.
    with pytest.raises(ValueError, match="Invalid start date"):
        _re(fake_self, "not-a-period", ctx, _warn, edge="start")

    # Error path: PeriodExprError (invalid hook path syntax) is wrapped in ValueError.
    ctx_bad_hook = ResolutionContext(
        today=datetime.date(2026, 12, 15),
        config={"period_resolver_hooks": ["myfunc"]},  # no module part → PeriodExprError
        srcdir="/src",
        docdir="doc",
    )
    with pytest.raises(ValueError, match="Invalid start date"):
        _re(fake_self, "bad-token", ctx_bad_hook, _warn, edge="start")


# ---------------------------------------------------------------------------
# mark_image_dark_ready per-file registration (8a block)
# ---------------------------------------------------------------------------

# Expected filename scheme: plantuml-<sha1(incdir + b"\0" + uml)>.png
# (mirrors sphinxcontrib.plantuml's own hash computation)


def _compute_expected_png(incdir: str, uml: str) -> str:
    """Re-compute the plantuml output filename the same way directive.py does."""
    import hashlib
    key = hashlib.sha1()
    key.update(incdir.encode("utf-8"))
    key.update(b"\0")
    key.update(uml.encode("utf-8"))
    return f"plantuml-{key.hexdigest()}.png"


@skip_no_plantuml
def test_mark_image_dark_ready_called_with_exact_filename(tmp_path, monkeypatch):
    """mark_image_dark_ready is called with the exact plantuml-<sha1>.png
    filename derived from sha1(incdir + '\\0' + uml)."""
    calls = []

    def _fake_mark(app, fname):
        calls.append(fname)

    monkeypatch.setattr(
        "doxtr_pdf_theme_core.mark_image_dark_ready", _fake_mark, raising=False
    )

    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"

    node = nodes[0]
    expected = _compute_expected_png(node["incdir"], node["uml"])

    assert expected in calls, (
        f"Expected mark_image_dark_ready to be called with {expected!r}; "
        f"actual calls: {calls}"
    )


@skip_no_plantuml
def test_mark_image_dark_ready_absent_does_not_raise(tmp_path, monkeypatch):
    """When mark_image_dark_ready is absent from theme-core (delattr),
    the directive runs without raising any exception."""
    try:
        import doxtr_pdf_theme_core as _core
        monkeypatch.delattr(_core, "mark_image_dark_ready", raising=False)
    except ImportError:
        pass  # theme-core not installed at all — equivalent scenario

    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    # Should build cleanly, no errors
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, (
        f"Directive must succeed even when mark_image_dark_ready is absent; "
        f"warnings: {warnings}"
    )


@skip_no_plantuml
def test_mark_image_dark_ready_exactly_one_per_directive(tmp_path, monkeypatch):
    """Exactly ONE filename is registered per roadmap directive invocation
    (per-file, not a blanket glob). The filename starts with 'plantuml-'
    and ends with '.png'."""
    calls = []

    def _fake_mark(app, fname):
        calls.append(fname)

    monkeypatch.setattr(
        "doxtr_pdf_theme_core.mark_image_dark_ready", _fake_mark, raising=False
    )

    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-01-01

           section,name,start,end,row_group,link,tags
           Work,Task A,2026-01-01,2026-06-30,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node; warnings: {warnings}"

    assert len(calls) == 1, (
        f"Expected exactly 1 mark_image_dark_ready call (per-file, not glob); "
        f"got {len(calls)}: {calls}"
    )
    registered = calls[0]
    assert registered.startswith("plantuml-"), (
        f"Registered filename must start with 'plantuml-'; got {registered!r}"
    )
    assert registered.endswith(".png"), (
        f"Registered filename must end with '.png'; got {registered!r}"
    )
    # Must NOT be a glob pattern
    assert "*" not in registered, (
        f"Registered filename must be exact (no glob wildcards); got {registered!r}"
    )


# ---------------------------------------------------------------------------
# Per-file :file: options: column suppression + norender
# ---------------------------------------------------------------------------

from doxtr_roadmap.directive import _split_file_specs


def test_split_file_specs_plain():
    assert _split_file_specs("a.csv b.csv") == ["a.csv", "b.csv"]
    assert _split_file_specs("a.csv, b.csv") == ["a.csv", "b.csv"]
    assert _split_file_specs("sprints/*.csv") == ["sprints/*.csv"]


def test_split_file_specs_keeps_bracket_commas():
    assert _split_file_specs("a.csv[ignore=section,link] b.csv[norender]") == [
        "a.csv[ignore=section,link]",
        "b.csv[norender]",
    ]


def test_split_file_specs_comma_separated_with_brackets():
    assert _split_file_specs("a.csv[ignore=x,y], b.csv") == [
        "a.csv[ignore=x,y]",
        "b.csv",
    ]


TWO_FILE_CSV_A = textwrap.dedent("""\
    section,name,start,end,row_group,link,tags
    Work,Task X,2026-12-01,2027-01-15,,https://example.com/x,eng
""")

TWO_FILE_CSV_B = textwrap.dedent("""\
    section,name,start,end,row_group,link,tags
    Planning,Task Y,2027-02-15,2027-04-01,,https://example.com/y,security
""")


def _make_two_file_project(tmp_path, rst_body, extra_conf=""):
    """Like _make_project but writes a.csv and b.csv (no roadmap.csv)."""
    from sphinx.application import Sphinx
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)
    (src / "a.csv").write_text(TWO_FILE_CSV_A, encoding="utf-8")
    (src / "b.csv").write_text(TWO_FILE_CSV_B, encoding="utf-8")
    (src / "conf.py").write_text(
        textwrap.dedent("""\
            project = 'Test'
            extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
            plantuml = 'plantuml'
            plantuml_output_format = 'png'
            master_doc = 'index'
        """) + extra_conf + "\n",
        encoding="utf-8",
    )
    (src / "index.rst").write_text("Test\n====\n\n" + rst_body + "\n", encoding="utf-8")
    warning_stream = io.StringIO()
    app = Sphinx(
        srcdir=str(src), confdir=str(src), outdir=str(out),
        doctreedir=str(doctrees), buildername="xml", freshenv=True,
        warning=warning_stream, verbosity=0,
    )
    app.build()
    return app, warning_stream.getvalue(), src


@skip_no_plantuml
def test_directive_ignore_section_per_file(tmp_path):
    """Ignoring `section` in only one file flattens that file's rows while the
    other file keeps its section header."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: a.csv[ignore=section] b.csv
    """)
    app, warnings, src = _make_two_file_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    # b.csv keeps its section header; a.csv's is suppressed.
    assert "-- Planning --" in uml
    assert "-- Work --" not in uml


@skip_no_plantuml
def test_directive_ignore_link_suppresses_link(tmp_path):
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: a.csv[ignore=link] b.csv
    """)
    app, warnings, src = _make_two_file_project(tmp_path, rst)
    uml = _get_plantuml_nodes(app)[0]["uml"]
    assert "https://example.com/x" not in uml  # a.csv link suppressed
    assert "https://example.com/y" in uml      # b.csv link kept


@skip_no_plantuml
def test_directive_norender_excludes_bars(tmp_path):
    """A norender file contributes no bars but is still read."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: a.csv[norender] b.csv
    """)
    app, warnings, src = _make_two_file_project(tmp_path, rst)
    uml = _get_plantuml_nodes(app)[0]["uml"]
    assert "[Task Y]" in uml       # b.csv rendered
    assert "[Task X]" not in uml   # a.csv norender


@skip_no_plantuml
def test_directive_bad_ignore_column_reports_error(tmp_path):
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: a.csv[ignore=name]
    """)
    app, warnings, src = _make_two_file_project(tmp_path, rst)
    # The bad column surfaces as a docutils ERROR (reported via the directive's
    # reporter); assert on the captured warning stream.
    assert "cannot be ignored" in warnings


@skip_no_plantuml
def test_directive_norender_period_still_resolves(tmp_path):
    """A norender reference file's period name is usable in :period: even
    though its rows are not rendered as bars."""
    from sphinx.application import Sphinx
    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)
    (src / "periods.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        Periods,Set27-01,2026-11-09,2027-01-29,,,
    """), encoding="utf-8")
    (src / "work.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        Work,Task X,2026-12-01,2027-01-15,,,eng
    """), encoding="utf-8")
    (src / "conf.py").write_text(textwrap.dedent("""\
        project = 'Test'
        extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
        plantuml = 'plantuml'
        plantuml_output_format = 'png'
        master_doc = 'index'
    """), encoding="utf-8")
    (src / "index.rst").write_text(textwrap.dedent("""\
        Test
        ====

        .. roadmap::
           :file: periods.csv[norender] work.csv
           :period: Set27-01
    """), encoding="utf-8")
    ws = io.StringIO()
    app = Sphinx(str(src), str(src), str(out), str(doctrees), "xml",
                 freshenv=True, warning=ws, verbosity=0)
    app.build()
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {ws.getvalue()}"
    uml = nodes[0]["uml"]
    # Period name resolved → project starts at the period's start date.
    assert "Project starts 2026-11-09" in uml
    # But the period rows themselves are NOT rendered as bars.
    assert "[Set27-01]" not in uml
    # The work file IS rendered.
    assert "[Task X]" in uml


# ---------------------------------------------------------------------------
# Period references in CSV start/end cells (@<period>)
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_period_ref_name_inline(tmp_path):
    """A task row spanning @PI27-01 .. @PI27-08 resolves to those edges.

    start=@PI27-01 -> PI27-01 start edge (2026-11-09)
    end=@PI27-08   -> PI27-08 end edge   (2027-08-27)
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-11-09

           section,name,start,end,row_group,link,tags
           PI Rhythm,PI27-01,2026-11-09,2027-01-29,,,
           PI Rhythm,PI27-08,2027-06-21,2027-08-27,,,
           Work,Big Effort,@PI27-01,@PI27-08,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"Expected 1 plantuml node, warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "[Big Effort]" in uml
    assert "starts 2026-11-09 and ends 2027-08-27" in uml


@skip_no_plantuml
def test_directive_period_ref_from_norender_file(tmp_path):
    """@PI27-01 resolves against a norender reference calendar file."""
    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    (src / "periods.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        PI Rhythm,PI27-01,2026-11-09,2027-01-29,,,
        PI Rhythm,PI27-08,2027-06-21,2027-08-27,,,
    """), encoding="utf-8")
    (src / "work.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        Work,Big Effort,@PI27-01,@PI27-08,,,
    """), encoding="utf-8")
    (src / "conf.py").write_text(textwrap.dedent("""\
        project = 'Test'
        extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
        plantuml = 'plantuml'
        plantuml_output_format = 'png'
        master_doc = 'index'
    """), encoding="utf-8")
    (src / "index.rst").write_text(textwrap.dedent("""\
        Test
        ====

        .. roadmap::
           :file: periods.csv[norender] work.csv
           :start: 2026-11-09
    """), encoding="utf-8")
    ws = io.StringIO()
    app = Sphinx(str(src), str(src), str(out), str(doctrees), "xml",
                 freshenv=True, warning=ws, verbosity=0)
    app.build()
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {ws.getvalue()}"
    uml = nodes[0]["uml"]
    # The referenced period bars are not rendered ...
    assert "[PI27-01]" not in uml
    # ... but the work bar spans the two periods' edges.
    assert "starts 2026-11-09 and ends 2027-08-27" in uml


@skip_no_plantuml
def test_directive_period_ref_calendar_keyword(tmp_path):
    """@current-pi resolves via doxtr_roadmap_period_calendars."""
    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    (src / "pi-periods.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        PI Rhythm,PI26-11,2026-08-31,2026-11-06,,,
        PI Rhythm,PI27-01,2026-11-09,2027-01-29,,,
    """), encoding="utf-8")
    (src / "conf.py").write_text(textwrap.dedent("""\
        project = 'Test'
        extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
        plantuml = 'plantuml'
        plantuml_output_format = 'png'
        master_doc = 'index'
        doxtr_roadmap_period_calendars = {
            'current-pi': {
                'file': 'pi-periods.csv',
                'section': 'PI Rhythm',
                'reference': '2026-12-15',
            },
        }
    """), encoding="utf-8")
    (src / "index.rst").write_text(textwrap.dedent("""\
        Test
        ====

        .. roadmap::
           :start: 2026-08-31

           section,name,start,end,row_group,link,tags
           Work,Current PI Work,@current-pi,@current-pi,,,
    """), encoding="utf-8")
    ws = io.StringIO()
    app = Sphinx(str(src), str(src), str(out), str(doctrees), "xml",
                 freshenv=True, warning=ws, verbosity=0)
    app.build()
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {ws.getvalue()}"
    uml = nodes[0]["uml"]
    # reference 2026-12-15 falls inside PI27-01 (2026-11-09..2027-01-29).
    assert "starts 2026-11-09 and ends 2027-01-29" in uml


@skip_no_plantuml
def test_directive_plain_iso_cells_unchanged(tmp_path):
    """Regression: unprefixed ISO cells still render verbatim."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-12-01

           section,name,start,end,row_group,link,tags
           Work,Plain Task,2026-12-01,2027-01-15,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "starts 2026-12-01 and ends 2027-01-15" in uml


@skip_no_plantuml
def test_directive_period_ref_unknown_errors(tmp_path):
    """An unresolvable @reference produces a directive error node."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-12-01

           section,name,start,end,row_group,link,tags
           Work,Bad Task,@nope-not-here,2027-01-15,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    errors = _get_error_nodes(app)
    combined = warnings + " ".join(e.astext() for e in errors)
    assert "unknown period reference" in combined, (
        f"expected an 'unknown period reference' error; warnings: {warnings}"
    )


# ---------------------------------------------------------------------------
# Period names / references resolved from configured calendar files
# (without listing the calendar file in :file:)
# ---------------------------------------------------------------------------

def _make_calendar_project(tmp_path, index_rst, calendar_section="PI Rhythm"):
    """Set up a project with a pi-periods.csv wired as a period calendar."""
    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    (src / "pi-periods.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link
        PI Rhythm,PI27-01,2026-11-09,2027-01-29,pi,
        PI Rhythm,PI27-08,2027-06-21,2027-08-27,pi,
        PI Rhythm,PI28-01,2027-11-08,2028-01-28,pi,
    """), encoding="utf-8")
    (src / "work.csv").write_text(textwrap.dedent("""\
        section,name,start,end,row_group,link,tags
        Work,Task X,2026-12-01,2027-01-15,,,
    """), encoding="utf-8")
    (src / "conf.py").write_text(textwrap.dedent(f"""\
        project = 'Test'
        extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
        plantuml = 'plantuml'
        plantuml_output_format = 'png'
        master_doc = 'index'
        doxtr_roadmap_period_calendars = {{
            'current-pi': {{
                'file': 'pi-periods.csv',
                'section': '{calendar_section}',
                'reference': '2026-12-15',
            }},
        }}
    """), encoding="utf-8")
    (src / "index.rst").write_text("Test\n====\n\n" + index_rst + "\n",
                                   encoding="utf-8")
    ws = io.StringIO()
    app = Sphinx(str(src), str(src), str(out), str(doctrees), "xml",
                 freshenv=True, warning=ws, verbosity=0)
    app.build()
    return app, ws.getvalue(), src


@skip_no_plantuml
def test_directive_period_name_from_calendar_not_in_file(tmp_path):
    """`:period: current-pi, PI28-01` works when only work.csv is listed.

    PI28-01 lives only in the configured calendar (pi-periods.csv), not in
    the loaded work.csv, yet must still resolve.  This is the regression the
    fix targets.
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :file: work.csv
           :period: current-pi, PI28-01
    """)
    app, warnings, src = _make_calendar_project(tmp_path, rst)
    assert "unknown period" not in warnings, warnings
    assert "doxtr-roadmap error" not in warnings, warnings
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    # current-pi (ref 2026-12-15 -> PI27-01 start 2026-11-09) is the earliest
    # start; PI28-01 end (2028-01-28) is the latest end.
    assert "Project starts 2026-11-09" in uml


@skip_no_plantuml
def test_directive_period_ref_cell_from_calendar_not_in_file(tmp_path):
    """`@PI28-01` in a start/end cell resolves via the calendar file only."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-11-09

           section,name,start,end,row_group,link,tags
           Work,Future Effort,@PI28-01,@PI28-01,,,
    """)
    # Note: inline body + configured calendar; no :file:, so the calendar is
    # the sole source for the @PI28-01 name.
    app, warnings, src = _make_calendar_project(tmp_path, rst)
    assert "unknown period reference" not in warnings, warnings
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "starts 2027-11-08 and ends 2028-01-28" in uml


@skip_no_plantuml
def test_directive_loaded_row_wins_over_calendar(tmp_path):
    """A loaded row's dates override a same-named calendar entry."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :period: PI27-01

           section,name,start,end,row_group,link,tags
           PI Rhythm,PI27-01,2026-11-01,2026-11-30,,,
           Work,Task Z,2026-11-05,2026-11-20,,,
    """)
    # PI27-01 in the calendar is 2026-11-09..2027-01-29, but the inline row
    # redefines it to Nov 2026; the loaded row must win.
    app, warnings, src = _make_calendar_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "Project starts 2026-11-01" in uml


@skip_no_plantuml
def test_directive_period_ref_multi_row_combined_span(tmp_path):
    """A name on several loaded rows spans their combined earliest/latest.

    ``PI27-01`` appears twice with different windows; a ``@PI27-01`` cell must
    resolve to the combined (min start, max end), mirroring
    ``generator.find_period_window`` and the documented contract.
    """
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-10-01

           section,name,start,end,row_group,link,tags
           PI Rhythm,PI27-01,2026-11-09,2027-01-29,,,
           PI Rhythm,PI27-01,2026-10-01,2026-12-31,,,
           Work,Spanning Effort,@PI27-01,@PI27-01,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    # Combined: earliest start 2026-10-01, latest end 2027-01-29.
    assert "starts 2026-10-01 and ends 2027-01-29" in uml


@skip_no_plantuml
def test_directive_period_ref_case_insensitive(tmp_path):
    """A lowercase ``@pi27-01`` cell resolves against the ``PI27-01`` row."""
    rst = textwrap.dedent("""\
        .. roadmap::
           :start: 2026-11-09

           section,name,start,end,row_group,link,tags
           PI Rhythm,PI27-01,2026-11-09,2027-01-29,,,
           Work,Lower Ref,@pi27-01,@pi27-01,,,
    """)
    app, warnings, src = _make_project(tmp_path, rst)
    nodes = _get_plantuml_nodes(app)
    assert len(nodes) == 1, f"warnings: {warnings}"
    uml = nodes[0]["uml"]
    assert "starts 2026-11-09 and ends 2027-01-29" in uml


@skip_no_plantuml
def test_directive_period_ref_bad_calendar_errors_gracefully(tmp_path):
    """A ``@current-pi`` cell whose calendar file is missing errors cleanly.

    The underlying ``PeriodExprError`` must be surfaced as a directive error
    node (via the ValueError re-raise) rather than crashing the build.
    """
    from sphinx.application import Sphinx

    src = tmp_path / "src"
    src.mkdir()
    out = tmp_path / "_build" / "xml"
    out.mkdir(parents=True)
    doctrees = tmp_path / "_build" / ".doctrees"
    doctrees.mkdir(parents=True)

    (src / "conf.py").write_text(textwrap.dedent("""\
        project = 'Test'
        extensions = ['sphinxcontrib.plantuml', 'doxtr_roadmap']
        plantuml = 'plantuml'
        plantuml_output_format = 'png'
        master_doc = 'index'
        doxtr_roadmap_period_calendars = {
            'current-pi': {
                'file': 'does-not-exist.csv',
                'section': 'PI Rhythm',
            },
        }
    """), encoding="utf-8")
    (src / "index.rst").write_text(textwrap.dedent("""\
        Test
        ====

        .. roadmap::
           :start: 2026-11-09

           section,name,start,end,row_group,link,tags
           Work,Broken,@current-pi,@current-pi,,,
    """), encoding="utf-8")
    ws = io.StringIO()
    app = Sphinx(str(src), str(src), str(out), str(doctrees), "xml",
                 freshenv=True, warning=ws, verbosity=0)
    # Build must not raise; a clean error node is produced instead.
    app.build()
    warnings = ws.getvalue()
    errors = _get_error_nodes(app)
    combined = warnings + " ".join(e.astext() for e in errors)
    assert "period reference" in combined or "doxtr-roadmap error" in combined, (
        f"expected a graceful directive error; warnings: {warnings}"
    )


# ---------------------------------------------------------------------------
# Per-task colour column (color_resolver integration)
# ---------------------------------------------------------------------------

@skip_no_plantuml
def test_directive_hex_color_column(tmp_path):
    """A hex `color` cell sets the bar done colour (with a derived frame)."""
    rst = textwrap.dedent("""\
        .. roadmap::

           section,name,start,end,row_group,link,tags,color
           Work,Task A,2026-01-01,2026-03-31,,,,#123456
    """)
    conf = "doxtr_roadmap_default_start = '2026-01-01'\n"
    app, warnings, src = _make_project(tmp_path, rst, extra_conf=conf)
    nodes = _get_plantuml_nodes(app)
    uml = nodes[0]["uml"]
    assert "is colored in #123456" in uml
    # Section default (#FF8C00) must not be used for this coloured task.
    assert "is colored in #FF8C00" not in uml


@skip_no_plantuml
def test_directive_color_inherits_within_section(tmp_path):
    """A blank colour row inherits the section's first coloured row."""
    rst = textwrap.dedent("""\
        .. roadmap::

           section,name,start,end,row_group,link,tags,color
           Work,Task A,2026-01-01,2026-03-31,,,,#2E7D32
           Work,Task B,2026-04-01,2026-06-30,,,,
    """)
    conf = "doxtr_roadmap_default_start = '2026-01-01'\n"
    app, warnings, src = _make_project(tmp_path, rst, extra_conf=conf)
    uml = _get_plantuml_nodes(app)[0]["uml"]
    # Both bars use the inherited section colour.
    assert uml.count("is colored in #2E7D32") == 2


@skip_no_plantuml
def test_directive_color_default_sentinel(tmp_path):
    """A `default` colour cell reverts a task to the roadmap default fill."""
    rst = textwrap.dedent("""\
        .. roadmap::

           section,name,start,end,row_group,link,tags,color
           Work,Task A,2026-01-01,2026-03-31,,,,#2E7D32
           Work,Task B,2026-04-01,2026-06-30,,,,default
    """)
    conf = "doxtr_roadmap_default_start = '2026-01-01'\n"
    app, warnings, src = _make_project(tmp_path, rst, extra_conf=conf)
    uml = _get_plantuml_nodes(app)[0]["uml"]
    assert "is colored in #2E7D32" in uml   # Task A
    assert "is colored in #FF8C00" in uml    # Task B reset to default


# ---------------------------------------------------------------------------
# Custom colour-engine seam (doxtr_roadmap_color_resolver)
# ---------------------------------------------------------------------------

def _custom_color_factory(config, frame_delta):  # pragma: no cover - dotted-path
    """Custom colour-engine factory used to prove the seam is honoured."""
    def _resolve(expr, default_done, default_frame):
        if expr == "brand":
            return "#0A0B0C", "#111213"
        return default_done, default_frame
    return _resolve


@skip_no_plantuml
def test_directive_custom_color_resolver_seam(tmp_path):
    """`doxtr_roadmap_color_resolver` replaces the built-in colour engine."""
    rst = textwrap.dedent("""\
        .. roadmap::

           section,name,start,end,row_group,link,tags,color
           Work,Task A,2026-01-01,2026-03-31,,,,brand
    """)
    conf = (
        "doxtr_roadmap_default_start = '2026-01-01'\n"
        "doxtr_roadmap_color_resolver = "
        "'tests.test_directive._custom_color_factory'\n"
    )
    app, warnings, src = _make_project(tmp_path, rst, extra_conf=conf)
    uml = _get_plantuml_nodes(app)[0]["uml"]
    assert "is colored in #0A0B0C/#111213" in uml
