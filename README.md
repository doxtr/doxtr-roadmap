# doxtr-roadmap

A Sphinx extension that generates PlantUML Gantt roadmaps from CSV data.

## Overview

`doxtr-roadmap` provides a `.. roadmap::` directive that reads roadmap items
from a CSV file (or inline CSV body), applies optional zoom/filter/tag
constraints, and emits a PlantUML Gantt chart node rendered via
`sphinxcontrib.plantuml`.

## Installation

```bash
pip install doxtr-roadmap
```

Requires `sphinxcontrib-plantuml>=0.9` (listed as a dependency).

## Quick Start

Add both extensions to your `conf.py`:

```python
extensions = [
    "sphinxcontrib.plantuml",
    "doxtr_roadmap",
]
```

Then use the directive in any RST document:

```rst
.. roadmap::
   :file: path/to/roadmap.csv
   :title: My Project Roadmap
```

Or with inline CSV content:

```rst
.. roadmap::
   :title: Sprint Overview

   section,name,start,end,row_group,link,tags
   Q1,Feature A,2026-01-01,2026-03-31,,,eng
   Q1,Feature B,2026-02-01,2026-04-30,,,code
```

## Multiple files and globs

The `:file:` option accepts one or more CSV paths and/or glob patterns,
space- or comma-separated.  All matched files are treated as **one combined
roadmap**: sections with the same name merge across files and subtasks /
`row_group` references work even when the parent task is defined in a
different file.

```rst
.. roadmap::
   :file: sprints/sprint-01.csv sprints/sprint-02.csv sprints/sprint-03.csv
   :title: All Sprints

.. roadmap::
   :file: sprints/sprint-*.csv   # equivalent glob
   :title: All Sprints
```

Both examples produce the **same** combined roadmap.  Key rules:

- Paths are resolved relative to the document directory first, then `srcdir`.
- Glob matches within a single pattern are sorted lexicographically
  (`sprint-01`, `sprint-02`, …) so the combination order is predictable.
- A file matched by more than one spec is read only once (de-duplicated,
  first-seen order preserved).
- If a spec matches no files the directive reports an error.
- `env.note_dependency` is called for each resolved file so editing any of
  them triggers an incremental rebuild.  *Adding a brand-new file* matching
  an existing glob is not detected automatically — run `make clean html`
  after adding files to a glob pattern.



The CSV must have a header row.  Only `name`, `start`, and `end` are
required; every other column is optional and may be omitted entirely:

| Column      | Required | Description |
|-------------|----------|-------------|
| `section`   | no       | Section/group name, or a parent task name for subtasks. Blank or omitted → the task renders with no section header |
| `name`      | yes      | Task display name |
| `start`     | yes      | Start date (ISO `YYYY-MM-DD`) |
| `end`       | yes      | End date (ISO `YYYY-MM-DD`). Same as `start` → milestone |
| `row_group` | no       | Tasks sharing this non-empty value render on one Gantt row |
| `link`      | no       | Plain URL or `:xlink:\`id\`` role expression |
| `tags`      | no       | Comma-separated tag list |

### Subtasks

A row whose `section` column matches an existing top-level task name becomes a
subtask, inserted directly beneath the parent task in the same section.

### Milestones

When `start == end`, the row is rendered as a Gantt milestone (diamond marker).
Milestones are never clamped to the clip window.

## Directive Options

| Option           | Type              | Description |
|------------------|-------------------|-------------|
| `:file:`         | path(s)/glob(s)   | One or more CSV paths and/or glob patterns, space- or comma-separated. All matched files are combined into a single roadmap (sections merge by name; subtasks and row-groups work across files). Glob metacharacters (`*`, `?`, `[…]`) are expanded; within each glob matches are sorted lexicographically. A single path with no separators behaves as before. |
| `:title:`        | string            | Override diagram title |
| `:scale:`        | choice            | `daily`, `weekly`, `monthly` |
| `:start:`        | ISO date          | Clip window start |
| `:end:`          | ISO date          | Clip window end |
| `:period:`       | string            | Comma-separated period name(s) to zoom to |
| `:close-weekends:` | flag            | Force weekend closure |
| `:clean-style:`    | true/false      | Override `clean_style` for this directive; bare flag or `true` enables, `false` disables (see [clean_style](#clean_style-and-the-hide-column-directives)) |
| `:tags:`         | string            | Tag filter (nested `[ ]` / `!` / `!!` syntax) |
| `:query:`        | Python expression | Safe-eval row filter; available names: `name`, `start`, `end`, `section`, `tags`, `row_group`, `match(pattern, string)`; safe builtins: `any`, `all`, `bool`, `set`, `len` |
| `:collision-detection:` | true/false | Override collision detection for this chart; bare flag or `true` enables, `false` disables (see [Collision detection](#collision-detection)) |
| `:collision-char-width-factor:` | float | Per-chart label-width tuning knob (overrides `doxtr_roadmap_collision_char_width_factor`) |
| `:column-zoom:` | float | Per-chart gantt column width multiplier; overrides `doxtr_roadmap_column_zoom` (see [Column width (zoom)](#column-width-zoom)) |
| `:width:` | length/% | Force the rendered image to fill a specific width in HTML and PDF (e.g. `100%`); not set by default |
| `:link-appendix:` | mode | Render task links as a real list below the chart. Values: `list` (bullet list), `footnote` (real RST auto-numbered footnotes — LaTeX `\footnote` in PDF), `off` (disable). Bare flag → `list`. Overrides the global `doxtr_roadmap_link_appendix` for this chart. |
| `:link-appendix-title:` | string | Heading text placed above the link appendix. Overrides `doxtr_roadmap_link_appendix_title` for this chart. |
| `:caption:` | string | Caption text; presence wraps the chart in a `nodes.figure` so it appears in the List of Figures and can be cross-referenced. |
| `:align:` | `left`\|`center`\|`right` | Horizontal alignment of the figure; also triggers figure wrapping even without `:caption:`. |
| `:name:` | string | Cross-reference target for the figure (e.g. `:numref:\`my-fig\`` or `:ref:\`my-fig\``). Requires `:caption:` or `:align:` to produce a figure node. |

### Period zoom

A "period" is any named task in the CSV (typically a sprint or increment row).
Specifying `:period: Set27-01` clips the diagram to exactly that task's
date range. Multiple periods are comma-separated:

```rst
.. roadmap::
   :period: Set27-01, Set27-04
```

When exactly one distinct period is rendered and `:scale:` is not set, the
extension automatically switches to `daily` scale and closes weekends.

### Tag filter

Uses the same nested-bracket syntax as `sphinxcontrib.xlink`:

```rst
.. roadmap::
   :tags: eng [ backend !! ], public
```

Rows are included if at least one of their tags satisfies the filter tree.
`!tag` hides a tag; `!!` cascades to children.

### Query filter

A Python expression evaluated per row with safe builtins:

```rst
.. roadmap::
   :query: "eng" in tags and end > start
```

Available variables: `name`, `start` (date), `end` (date), `section`, `tags`
(set), `row_group`, `match(pattern, string)` (safe regex helper — returns
`bool(re.search(pattern, string))` without exposing the `re` module).

Safe builtins: `any`, `all`, `bool`, `set`, `len`.

## Configuration

All config values are prefixed `doxtr_roadmap_` and set in `conf.py`:

```python
doxtr_roadmap_default_scale = "monthly"     # daily | weekly | monthly
doxtr_roadmap_scale_factor = 1.25           # PlantUML diagram scale
doxtr_roadmap_default_start = None          # ISO date or None (→ today)
doxtr_roadmap_default_title = "Roadmap"
doxtr_roadmap_clean_style = True            # hide start/end/duration columns — default True; requires PlantUML V1.2026.7+
doxtr_roadmap_close_weekends_on_single_period = True

doxtr_roadmap_bar = {
    "done_color": "#FF8C00",
    "undone_color": "#FFF3E0",
    "frame_color": None,
}

doxtr_roadmap_sections = {
    "My Section": {
        "done": "#1976D2",
        "frame": None,
        "frame_overrides": {"Special Task": "#E53935"},
    },
}

doxtr_roadmap_today = {"color": "#E53935"}

doxtr_roadmap_fonts = {
    "title":     {"name": None, "size": 24, "style": "bold",  "color": None},
    "task":      {"name": None, "size": 14, "style": None,    "color": None},
    "separator": {"name": None, "size": 16, "style": "bold",  "color": None},
}

doxtr_roadmap_closed = {"background_color": None}

# PlantUML version check (default: fail build if PlantUML < v1.2026.7)
# Values: "error" (default) | "warn" | "off" / False
# See [PlantUML Version](#plantuml-version) section.
doxtr_roadmap_require_plantuml_version = "error"

# Collision detection (default: True — split same-row-group tasks that collide)
doxtr_roadmap_collision_detection = True
doxtr_roadmap_collision_char_width_factor = 1.0   # label-width tuning knob
doxtr_roadmap_collision_gap_days = 2              # minimum gap between tasks on a lane

# Column zoom — widen each gantt time column (default 1 = unchanged)
doxtr_roadmap_column_zoom = 1

# Link appendix — render task links as a list below the chart.
# Defaults to "list" but only for PDF/latex (see builders below); set to
# False to disable it everywhere including PDF.
doxtr_roadmap_link_appendix = "list"    # "list" | "footnote" | False
doxtr_roadmap_link_appendix_builders = ["latex"]   # default: PDF only
doxtr_roadmap_link_appendix_title = "Links"

# Figure / List-of-Figures (default off)
# Set True to wrap every roadmap as a numbered figure automatically.
doxtr_roadmap_figure = False
# Optional default caption when doxtr_roadmap_figure=True and no :caption: given.
# None → use the chart title as the caption.
doxtr_roadmap_figure_caption = None

# Tag allow-lists (optional)
doxtr_roadmap_allowed_tags = {
    "eng": "Engineering",
    "code": "Code",
    "security": "Security",
}
doxtr_roadmap_allowed_tag_patterns = {}
```

### Theme-core integration

When `doxtr_pdf_theme_core` is in `extensions`, the roadmap extension
automatically reads its semantic palette and typography:

```python
doxtr_roadmap_use_theme_core = "auto"  # "auto" | True | False
```

| Palette key  | Maps to              |
|--------------|----------------------|
| `primary`    | bar `done_color`     |
| `secondary`  | today line `color`   |
| `main_font`  | task font name       |
| `sans_font`  | separator font name  |

User-configured `doxtr_roadmap_*` values always win over theme-core.

### xlink integration

When `sphinxcontrib.xlink` is in `extensions`, the `link` CSV column accepts
`:xlink:\`id\`` role expressions that are resolved against the project's
`.xlink` files. The resolved URL and title are emitted as a PlantUML hyperlink:

```
[Task] links to [[https://... Resolved Title]]
```

If xlink is not loaded, xlink-style cells produce a one-time warning and the
link is silently skipped.

## Figures and the List of Figures

To render a roadmap as a **numbered figure** that appears in the List of
Figures (`\listoffigures` in PDF, or via Sphinx's `numfig` feature in HTML),
add a `:caption:` to the directive:

```rst
.. roadmap::
   :caption: Q1 Sprint Roadmap
   :name: fig-q1-sprint
   :align: center
   :start: 2026-01-01

   section,name,start,end,row_group,link,tags
   Work,Task A,2026-01-01,2026-03-31,,,
```

With `numfig = True` in `conf.py`, Sphinx numbers the figure automatically
("Fig. 1", "Fig. 2", …) and you can cross-reference it:

```rst
See :numref:`fig-q1-sprint` for the full timeline.
```

**Caption default.** When a roadmap is rendered as a figure, the caption text
follows this precedence:

1. Explicit `:caption:` option — highest priority (used verbatim).
2. `doxtr_roadmap_figure_caption` if non-empty — global override.
3. The chart `:title:` (or `doxtr_roadmap_default_title`) — default.

This means that an `:align:`-only wrap (no explicit `:caption:`) now also
gets the chart title as its caption, making the roadmap appear in the List
of Figures without any extra configuration.

### Options

| Option | Description |
|--------|-------------|
| `:caption:` | Caption text; presence wraps the chart in a `nodes.figure` so it appears in the List of Figures. |
| `:align:` | `left`, `center`, or `right`; also triggers figure wrapping with the chart title as the default caption. |
| `:name:` | Cross-reference target (`:numref:` / `:ref:`). |

### Making all roadmaps figures automatically

Set `doxtr_roadmap_figure = True` in `conf.py` to wrap **every** roadmap as a
figure without adding `:caption:` to each directive. The chart's `:title:`
becomes the caption by default:

```python
# conf.py
doxtr_roadmap_figure = True
# Optional: override the default caption text for all auto-wrapped figures.
# None (default) → use each chart's :title: as the caption.
doxtr_roadmap_figure_caption = None
```

When `doxtr_roadmap_figure_caption` is set to a non-empty string, that string
is used verbatim as the caption for every roadmap that does not carry its own
per-directive `:caption:`.

### numfig and the List of Figures

- Enable `numfig = True` in `conf.py` for "Figure N" numbering and
  `:numref:` cross-references.
- The HTML builder does not generate a standalone List of Figures page by
  default; use a `.. contents::` directive or an additional index page.
- The **LaTeX/PDF builder** emits `\begin{figure}...\caption{...}\end{figure}`
  for every captioned roadmap, which feeds into `\listoffigures` automatically
  when your LaTeX preamble includes it.
- If `doxtr_pdf_theme_core` is in use, its `doxtr_globals` `show_list_of_figures`
  key controls whether `\listoffigures` is emitted in the generated PDF.

## Link appendix

Links embedded inside the PlantUML image are **not clickable in PDF/LaTeX
output** — the image is a static graphic with no active hyperlink areas.  The
link appendix feature solves this by rendering task links as real, clickable
docutils nodes placed *after* the chart image.

By default the appendix is **on for PDF/LaTeX output** (rendered as a bullet
list) and **off for every other builder** (HTML, epub, etc.), whose image
links are already clickable.  It is controlled by three config values:

```python
# conf.py

# Appendix mode. Defaults to "list"; the builder restriction below limits it
# to PDF by default. Set to False to disable it everywhere (including PDF).
doxtr_roadmap_link_appendix = "list"        # "list" | "footnote" | False

# Which builders render the appendix. Checked against builder.name AND
# builder.format. Default ["latex"] → PDF only. Use "all" (or ["*"]) for
# every builder, or e.g. ["latex", "epub"] to add more.
doxtr_roadmap_link_appendix_builders = ["latex"]   # default: PDF only

# Heading shown above the list (empty string → no heading)
doxtr_roadmap_link_appendix_title = "Links"  # default
```

To turn the appendix off for PDF as well, set
``doxtr_roadmap_link_appendix = False`` (or ``:link-appendix: off`` on an
individual chart).  To also show it in HTML/epub, add those builders to
``doxtr_roadmap_link_appendix_builders`` (or use ``"all"``).

**Mode `"list"`** renders a `nodes.bullet_list`; each item is
`<Task Name>: <clickable link>`. **Mode `"footnote"`** renders real
reStructuredText auto-numbered footnotes.  In PDF/LaTeX output Sphinx's LaTeX
writer emits these as page-bottom `\footnote{}` commands.  In HTML they
render as standard numbered footnotes with back-references.

**Footnote mode with a figure caption.** When the roadmap is rendered as a
figure (via `:caption:`, `:align:`, or `doxtr_roadmap_figure = True`) *and*
`link_appendix = "footnote"` *and* the builder is in `link_appendix_builders`,
the footnote links are embedded **compactly inside the figure caption** instead
of a separate "Links" block below the chart.  The caption shows a single
label word (the `link_appendix_title`, default `"Links"`) followed by one
auto-numbered footnote marker per link:

```
<caption text> (Links [1], [2])
```

For example, with `numfig = True`: `Fig. 13.19: Projects with Links (Links⁹,¹⁰)`.

Each footnote body carries the task name, the link title (when available),
and the URL:

```
[1] API Redesign: https://example.com/api         ← plain URL, no title
[2] Sphinx Migration >> Sphinx Docs: https://...  ← xlink with resolved title
```

The footnote definitions are emitted as sibling nodes after the figure.  The
separate "Links" heading/container is **not** emitted in this case.  If there
are no resolvable links the caption is the plain title with no brackets.

`"list"` mode always produces the standalone bullet list regardless of whether
a figure is present — list links are not compact enough for a caption.

The same source produces an image-only HTML page and an image-plus-appendix
PDF page — no per-format conditionals needed.

Per-directive overrides (`:link-appendix:` and `:link-appendix-title:`) let
you enable, change, or disable the appendix for a single chart:

```rst
.. roadmap::
   :file: roadmap.csv
   :link-appendix: footnote
   :link-appendix-title: External References

.. roadmap::
   :file: roadmap.csv
   :link-appendix: off     ← disable even when globally enabled
```

A bare `:link-appendix:` flag (no value) defaults to `"list"`.

Tasks with no `link` cell, or whose link cell does not resolve, are silently
skipped. If no tasks have resolvable links, no container or heading is
appended.

## PlantUML Version

### Minimum version requirement — v1.2026.7

The extension requires **PlantUML v1.2026.7 or newer** for full feature
support (see [release notes](https://github.com/plantuml/plantuml/releases/tag/v1.2026.7)).
At startup (`builder-inited`) the extension runs `plantuml -version` and
compares the result against the minimum tuple `(1, 2026, 7)`.

The check behaviour is controlled by the `doxtr_roadmap_require_plantuml_version`
config value:

| Value | Effect |
|-------|--------|
| `"error"` (default) | An `ExtensionError` is raised, aborting the build if the version is below the minimum. |
| `"warn"` | A `WARNING` is emitted if the installed version is below the minimum; the build continues normally. |
| `"off"` / `False` | The check is skipped entirely; no subprocess call is made. |

```python
# conf.py
# Default — fail the build if PlantUML is below v1.2026.7:
doxtr_roadmap_require_plantuml_version = "error"

# Lenient — warn but never fail the build:
doxtr_roadmap_require_plantuml_version = "warn"

# Opt out — skip the check entirely:
doxtr_roadmap_require_plantuml_version = "off"
```

If the PlantUML binary cannot be found or its version output is unrecognisable,
an informational message is logged and the build continues regardless of the
setting — the check never crashes a build over an undeterminable version.

`[Display] as [pid]` same-name-distinct-bar support requires **PlantUML
V1.2024.6 or newer**. Older versions will silently merge tasks that share a
display name (e.g. duplicate period rows).

### `clean_style` and the `hide column` directives

`doxtr_roadmap_clean_style = True` hides the per-task **Start**, **End**, and
**Duration** columns in the rendered Gantt table. This is especially important
when `row_group` same-row grouping is used: without it the date stamps from
multiple tasks sharing a row overlap and become unreadable.

`clean_style` **defaults to `True`** because PlantUML v1.2026.7 is the
extension's minimum baseline and fully supports the `hide column
start/end/duration` syntax.

To disable it globally:

```python
# conf.py
doxtr_roadmap_clean_style = False
```

The `:clean-style:` directive option overrides the global setting per
directive instance:

```rst
.. roadmap::           # bare flag or explicit true — enables clean_style
   :clean-style:
   :file: roadmap.csv

.. roadmap::           # explicit false — disables clean_style for this block
   :clean-style: false
   :file: roadmap.csv
```


## Collision detection

When two or more tasks share a `row_group`, PlantUML draws their text labels
starting at (or across) their bars.  If the bars overlap in time, or if an
earlier bar's label is long enough to overrun rightward into a later bar, the
labels collide and become unreadable.

By default, the extension detects these collisions and automatically splits
tasks within a `row_group` onto as few additional rows as needed so that no
two tasks on the same row would have overlapping labels.  Tasks that fit
together stay together (no unnecessary splits); only tasks that would collide
are moved to a new row.  This preserves the space-saving intent of `row_group`
while keeping text readable.

```python
# conf.py

# Default True — split same-row-group tasks onto extra rows when they collide.
doxtr_roadmap_collision_detection = True

# Set False to force ALL same-row-group tasks onto one row regardless of
# overlap (for users who deliberately want overlap / the old behaviour).
doxtr_roadmap_collision_detection = False

# Tuning knob: higher value reserves more space per character → splits sooner.
# Default 1.0 corresponds to the calibrated base days-per-character.
doxtr_roadmap_collision_char_width_factor = 1.0

# Minimum gap (calendar days) between adjacent tasks on the same lane.
doxtr_roadmap_collision_gap_days = 2
```

The `:collision-detection:` directive option overrides the global setting for
a single chart:

```rst
.. roadmap::                       # detection on for this chart only
   :collision-detection: true
   :file: roadmap.csv

.. roadmap::                       # detection off — force overlap for this chart
   :collision-detection: false
   :file: roadmap.csv

.. roadmap::                       # widen label estimate for this chart
   :collision-char-width-factor: 1.5
   :file: roadmap.csv
```

The detection algorithm estimates each label's horizontal footprint using a
per-scale days-per-character mapping (`daily` ≈ 1.1, `weekly` ≈ 4, `monthly`
≈ 9), multiplied by `collision_char_width_factor`.  Within each `row_group`
tasks are packed into lanes using a greedy first-fit strategy: each task is
placed on the first lane whose last task's footprint does not overlap; if all
lanes are blocked, a new lane is opened.  Different lanes render as separate
Gantt rows.


## Column width (zoom)

By default PlantUML sizes Gantt columns compactly.  On wide pages the chart
may not use the full available width, resulting in a horizontally compressed
look — especially on monthly or weekly scale.

The `doxtr_roadmap_column_zoom` config value (default `1`) multiplies the
width of each time column by appending `zoom <factor>` to the PlantUML
`projectscale` line.  A value of `1` (or absent) produces the current
unchanged behaviour.  Example:

```python
# conf.py — make each month column 3× wider
doxtr_roadmap_column_zoom = 3
```

The `:column-zoom:` directive option overrides the global setting per chart:

```rst
.. roadmap::
   :column-zoom: 3
   :file: roadmap.csv
```

The `:width:` directive option (e.g. `:width: 100%`) forces the rendered
image to fill the available text/page width in HTML and PDF.  This is handled
by `sphinxcontrib.plantuml` (maps to an HTML `style="width:100%"` attribute
or a LaTeX `adjustbox` width).  By default no width is set (current
behaviour).

```rst
.. roadmap::
   :column-zoom: 3
   :width: 100%
   :file: roadmap.csv
```

Combining both options gives full control: `:column-zoom:` widens each source
column so the chart is drawn at the desired detail level, and `:width: 100%`
stretches the resulting image to fill the page.

> **PlantUML version note:** The `zoom <factor>` keyword form requires
> PlantUML v1.2026.7 or newer — already the extension's minimum baseline.
> The older `projectscale monthly 3` form (no `zoom` keyword) errors on
> v1.2026.7 and is never emitted by this extension.


## Development

```bash
git clone https://github.com/doxtr/doxtr-roadmap
cd doxtr-roadmap
pip install -e ".[dev]"
pip install sphinxcontrib-plantuml
python -m pytest tests/ -v
```

Run the Sphinx HTML smoke-build:

```bash
cd test_harness
python test_runner.py
```

## License

MIT
