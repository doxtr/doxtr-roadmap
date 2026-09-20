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

Add the extension to your `conf.py`:

```python
extensions = [
    "sphinxcontrib.plantuml",
    "doxtr_roadmap",
]
```

`doxtr_roadmap` loads the optional `doxtr_pdf_theme_core` integration
automatically when that package is installed — you do **not** need to add
`doxtr_pdf_theme_core` to `extensions` yourself. When theme-core is not
installed the extension works exactly the same, just without the palette /
dark-mode integration. To opt out of the auto-load, set
`doxtr_roadmap_autoload_theme_core = False` (see [Theme-core
integration](#theme-core-integration)).

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

### Per-file options: ignoring columns and reference-only files

Each `:file:` spec may carry per-file processing options in a `[...]` bracket
appended directly after the filename (or glob).  Options are `;`-separated;
each is either a bare flag or a `key=value` pair whose value is a
comma-separated list:

```rst
.. roadmap::
   :file: sprints/sprint-01.csv[ignore=section,link] sprints/sprint-02.csv
```

This lets you keep every column fully documented in the CSV while suppressing
non-essential ones from a *specific* file's rendering. Options apply to every
file a glob matches and are independent per spec, so a column can be ignored
in one file but kept in another.

Supported options:

- **`ignore=<col>[,<col>...]`** — blank the named column(s) for that spec's
  rows at parse time. The suppression is uniform: an ignored `tags`/`link`
  column is invisible to `:tags:` / `:query:` filtering and the link appendix,
  an ignored `section` flattens those rows (no section header, and they no
  longer parent subtasks), and an ignored `row_group` drops those rows from
  same-row grouping. Only non-essential columns may be ignored — see
  [`doxtr_roadmap_ignorable_columns`](#configuration); attempting to ignore
  `name`, `start`, or `end` is an error.
- **`norender`** (flag) — load and parse the file (so its rows stay documented
  and remain usable for a *named* `:period:` / `:start:` / `:end:`) but emit
  **no bars** from it. Useful to load a period-calendar file purely as a
  reference for a named time frame without drawing its periods:

  ```rst
  .. roadmap::
     :file: files/pi-calendar.csv[norender] files/work.csv
     :period: Set27-01        # resolves against the norender calendar file
  ```



The CSV must have a header row.  Only `name`, `start`, and `end` are
required; every other column is optional and may be omitted entirely:

| Column      | Required | Description |
|-------------|----------|-------------|
| `section`   | no       | Section/group name, or a parent task name for subtasks. Blank or omitted → the task renders with no section header |
| `name`      | yes      | Task display name |
| `start`     | yes      | Start date (ISO `YYYY-MM-DD`) or a [period reference](#period-references-in-startend-cells) (`@PI27-01`) |
| `end`       | yes      | End date (ISO `YYYY-MM-DD`). Same as `start` → milestone. Also accepts a [period reference](#period-references-in-startend-cells) (`@PI27-08`) |
| `row_group` | no       | Tasks sharing this non-empty value render on one Gantt row |
| `link`      | no       | Plain URL or `:xlink:\`id\`` role expression |
| `tags`      | no       | Comma-separated tag list |

### Subtasks

A row whose `section` column matches an existing top-level task name becomes a
subtask, inserted directly beneath the parent task in the same section.

### Milestones

When `start == end`, the row is rendered as a Gantt milestone (diamond marker).
Milestones are never clamped to the clip window.

### Period references in start/end cells

Instead of a literal ISO date, a `start` or `end` cell may hold a **period
reference** of the form `@<period>`. The reference is expanded to a concrete
date before rendering: the referenced period's **start** edge is used in a
`start` cell and its **end** edge in an `end` cell. This lets a task be pinned
to named periods without copying their dates by hand.

```
section,name,start,end,row_group,link,tags
PI Rhythm,PI27-01,2026-11-09,2027-01-29,,,
PI Rhythm,PI27-08,2027-06-21,2027-08-27,,,
Work,Big Effort,@PI27-01,@PI27-08,,,
```

Here `Big Effort` spans from the **start of PI27-01** (`2026-11-09`) to the
**end of PI27-08** (`2027-08-27`).

`<period>` is resolved, in order, as:

1. Any [dynamic expression](#dynamic-period-expressions) — a literal ISO date
   (`@2027-01-05`), a configured `doxtr_roadmap_period_calendars` keyword
   (`@current-pi`), or built-in calendar math (`@now()+2 weeks`,
   `@current-quarter`).
2. A plain **period name** matched case-insensitively against the names of the
   loaded roadmap rows (including rows from a file loaded with the `norender`
   flag) **and** the rows of every configured `doxtr_roadmap_period_calendars`
   file. So a dedicated `pi-periods.csv` wired as a calendar can define the
   periods that other rows reference, even when it is not listed in `:file:`.
   A loaded row wins over a calendar row on a name clash; when a name occurs
   on several rows the reference spans their combined earliest-start /
   latest-end.

Only cells that begin with `@` are treated as references; every other cell is
still parsed strictly as an ISO date, so existing CSVs are unaffected. An
unresolvable reference raises a clear build error.

## Directive Options

| Option           | Type              | Description |
|------------------|-------------------|-------------|
| `:file:`         | path(s)/glob(s)   | One or more CSV paths and/or glob patterns, space- or comma-separated. All matched files are combined into a single roadmap (sections merge by name; subtasks and row-groups work across files). Glob metacharacters (`*`, `?`, `[…]`) are expanded; within each glob matches are sorted lexicographically. A single path with no separators behaves as before. Each spec may carry per-file options in a trailing `[...]` bracket — `ignore=<col>[,<col>...]` to blank non-essential columns at parse time, and/or the `norender` flag to load a file for reference (e.g. named `:period:` lookup) without drawing it. See [Per-file options](#per-file-options-ignoring-columns-and-reference-only-files). |
| `:title:`        | string            | Override diagram title |
| `:scale:`        | choice            | `daily`, `weekly`, `monthly` |
| `:start:`        | ISO date / expr   | Clip window start. Accepts an ISO date or a [dynamic expression](#dynamic-period-expressions) (`now()-63 businessdays`, `current-quarter`, a calendar keyword) resolved to its start edge |
| `:end:`          | ISO date / expr   | Clip window end. Accepts an ISO date or a [dynamic expression](#dynamic-period-expressions) resolved to its end edge |
| `:period:`       | string            | Comma-separated period name(s) to zoom to. Each token may be a CSV period name (matched against the loaded rows **or** any configured `doxtr_roadmap_period_calendars` file) or a [dynamic expression](#dynamic-period-expressions) (`current-pi`, `current-quarter`, `now()-2 weeks`) |
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

### Dynamic period expressions

`:period:`, `:start:` and `:end:` accept **dynamic expressions** in addition
to literal ISO dates and CSV period names. Each comma-separated token is
resolved in this order (the first match wins):

1. A literal ISO date (`2027-03-01`) — unchanged behaviour.
2. A user resolver hook (`doxtr_roadmap_period_resolver_hooks`).
3. A CSV-backed calendar keyword (`doxtr_roadmap_period_calendars`).
4. A built-in calendar-math or relative expression.
5. Otherwise the token is treated as a plain CSV period name (unchanged
   behaviour, so existing roadmaps keep working).

This lets a roadmap re-render itself against the *current* period every build
without editing the RST:

```rst
.. roadmap::
   :file: files/roadmap.csv
   :period: current-pi

.. roadmap::
   :file: files/roadmap.csv
   :start: now()-63 businessdays
   :end: current-quarter

.. roadmap::
   :file: files/roadmap.csv
   :period: current-pi, current-quarter
```

#### Built-in calendar-math tokens (no configuration)

| Token | Window |
|-------|--------|
| `current-year` | Jan 1 – Dec 31 of the current year |
| `current-quarter` | first–last day of the current calendar quarter |
| `current-month` | first–last day of the current month |
| `current-week` | Monday–Sunday of the current ISO week |
| `now()` / `today` | today (a zero-width window) |

#### Relative expressions (no configuration)

```
(now() | today) ([+-] <int> <unit>)*
```

where `<unit>` is `day(s)`, `week(s)`, `month(s)`, `year(s)` or
`businessday(s)` (also spelled `business day` / `business-day`). Terms may be
chained: `now() + 1 month - 3 businessdays`. Expressions are parsed by a small
hand-written grammar, **not** `eval` (same security posture as `:query:`).

Business days default to Monday–Friday and are configurable — see
`doxtr_roadmap_business_days` below (supports arbitrary working weeks such as
Mon/Wed/Sat).

#### CSV-backed calendars (`current-pi` and friends)

Map a trigger keyword to a calendar CSV once in `conf.py`; the keyword then
resolves to whichever row's `[start, end]` brackets the reference date. The
calendar data lives in its own file (or an existing roadmap CSV filtered by
`section`), so it is configured once and reused by every directive:

```python
doxtr_roadmap_period_calendars = {
    "current-pi": {
        "file": "files/pi-calendar.csv",   # required
        "section": "PI Rhythm",            # optional CSV section filter
        "on_miss": "future",               # future (default) | past | error
        # "match":     "contains",         # row-match mode (only "contains" currently supported)
        # "reference": "now()",            # optional anchor (date or expression)
    },
    # A team using sprints instead of PIs:
    # "current-sprint": {"file": "planning/sprints.csv"},
}
```

The calendar CSV uses the same format as a roadmap CSV (`section,name,start,end`);
a dedicated file may contain only the period rows.

**Gap handling.** When the reference date falls in a gap between periods (or
before/after all of them), `on_miss` decides the fallback and a warning is
emitted:

- `future` (default) — use the next upcoming period.  When there is no
  upcoming period (reference is after the last row), falls back to the most
  recent past period.
- `past` — use the most recent past period.  When there is no past period
  (reference is before the first row), falls back to the next upcoming period.
- `error` — fail the build.

#### Custom resolver hooks (advanced)

For anything the built-ins do not cover (fiscal calendars, custom business
logic), register dotted paths to callables `(token, ctx) -> (start, end) |
date | None`. Hooks run *before* the built-ins, so they can override any
built-in keyword:

```python
doxtr_roadmap_period_resolver_hooks = [
    "mypackage.roadmap_ext.fiscal_year_resolver",
]
```

A hook returns a `datetime.date`, a `(start, end)` date pair, or `None` to
decline the token.

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

# Diagram background colour override (theme-core dark mode sets this
# automatically in dark builds; override manually when needed).
doxtr_roadmap_diagram_background_color = None  # None = auto; set a hex colour like "#101010" to override

# Diagram foreground colour override (root FontColor + LineColor; theme-core
# dark mode sets this automatically in dark builds).
doxtr_roadmap_foreground_color = None  # None = auto; set a hex colour like "#DBDBDB" to override

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

# Dynamic period expressions (see "Dynamic period expressions" above)
# CSV-backed "current period" calendars. Maps a :period:/:start:/:end:
# trigger keyword to a calendar CSV whose row bracketing the reference date
# defines the window.
doxtr_roadmap_period_calendars = {}
#   e.g. {"current-pi": {"file": "files/pi-calendar.csv",
#                        "section": "PI Rhythm",
#                        "on_miss": "future"}}   # future | past | error

# Per-calendar processing options, keyed by the same trigger keyword used in
# doxtr_roadmap_period_calendars. Each value is an option string using the
# same grammar as the per-file :file: bracket (ignore=col1,col2). Since
# calendars never render bars, the norender flag is implicit here.
#   e.g. {"current-pi": "ignore=tags,link"}
doxtr_roadmap_period_calendars_options = {}

# Columns a user may suppress via a per-file `ignore=` option (and via
# doxtr_roadmap_period_calendars_options). Defaults to every non-required
# column; name/start/end can never be ignored regardless of this list.
doxtr_roadmap_ignorable_columns = ["section", "row_group", "link", "tags"]

# Advanced: dotted paths to custom resolver callables (token, ctx) ->
# (start, end) | date | None, tried before the built-in resolvers.
doxtr_roadmap_period_resolver_hooks = []

# Business-day definition for "now()-N businessdays" expressions.
# None → Monday–Friday. Otherwise a list of weekday names (case-insensitive,
# full or common abbreviations) or integers (Mon=0 .. Sun=6), e.g.
# ["monday", "wednesday", "saturday"] or [0, 2, 5] for a Mon/Wed/Sat week.
doxtr_roadmap_business_days = None

# Tag allow-lists (optional)
doxtr_roadmap_allowed_tags = {
    "eng": "Engineering",
    "code": "Code",
    "security": "Security",
}
doxtr_roadmap_allowed_tag_patterns = {}

# Theme-core auto-loading (default True). When doxtr_pdf_theme_core is
# installed it is loaded automatically so its palette / dark-mode integration
# activates without listing it in `extensions`. Set to False to opt out (a
# child theme with its own rendering, or a build that must not pull in
# theme-core). No effect when theme-core is not installed.
# See the "Theme-core integration" section.
doxtr_roadmap_autoload_theme_core = True
```

### Theme-core integration

When `doxtr_pdf_theme_core` is installed, the roadmap extension **loads it
automatically** (via `app.setup_extension`) and reads its semantic palette and
typography — you do not need to add `doxtr_pdf_theme_core` to `extensions` in
your `conf.py`:

```python
# Auto-load theme-core when it is installed (default True). Set to False to
# opt out — e.g. a child theme that supplies its own rendering / palette and
# does not want theme-core pulled in behind its back. When theme-core is not
# installed this option has no effect (nothing is loaded and the extension
# degrades to its own defaults).
doxtr_roadmap_autoload_theme_core = True

doxtr_roadmap_use_theme_core = "auto"  # "auto" | True | False
```

The two options are independent levers:

- `doxtr_roadmap_autoload_theme_core` controls whether theme-core is *loaded*
  automatically when installed.
- `doxtr_roadmap_use_theme_core` controls whether a *loaded* theme-core's
  palette / typography is *read* into the roadmap style. With the default
  `"auto"`, the integration activates whenever theme-core is loaded — whether
  you listed it in `extensions` yourself or it was auto-loaded.

To get the integration you now only need theme-core installed; to disable it
entirely, either uninstall theme-core, set
`doxtr_roadmap_autoload_theme_core = False` (and don't list it in
`extensions`), or set `doxtr_roadmap_use_theme_core = False`.

| Palette key  | Maps to              |
|--------------|----------------------|
| `primary`    | bar `done_color`     |
| `secondary`  | today line `color`   |
| `main_font`  | task font name       |
| `sans_font`  | separator font name  |

User-configured `doxtr_roadmap_*` values always win over theme-core.

#### Dark mode

When theme-core dark mode is active (a genuinely dark page — `doxtr_dark_mode`
on with the resolved `invert` strategy), the roadmap extension generates its
PlantUML source with dark-appropriate colours directly:

| Dark source                    | Maps to                                  |
|--------------------------------|------------------------------------------|
| dark palette `primary`         | bar `done_color`                         |
| dark palette `secondary`       | today line `color`                       |
| dark palette `page`            | diagram `BackGroundColor` (dark)         |
| theme-core dark context `text_color` | root `FontColor`/`LineColor` (title, timeline header, milestone & task labels) |
| soft-inverted `undone_color`   | remaining-work bar background (dark, so light in-bar labels read) |
| dark context `text_color` or dark `primary` | bar `frame_color` (subtle light border) |

The root `FontColor`/`LineColor` is the single lever that makes the timeline
header row (year/month) and milestone labels legible: PlantUML ignores the
more specific `timeline.*` / `milestone` font-colour selectors but honours the
root colour for those elements. The title colour is applied via inline creole
(`<color:...>`), since the gantt `title` style selector is also ignored.

Because the diagram is *regenerated* from dark source, the result matches the
rest of the dark PDF exactly — unlike relying on theme-core's per-pixel image
inversion (which cannot help roadmap because it generates PlantUML source
inline, with no `_dark` source file to swap).

The extension registers each generated PNG with theme-core's public
`mark_image_dark_ready()` API (using the exact `plantuml-<hash>.png` filename
that sphinxcontrib.plantuml will produce) so theme-core's dark image pipeline
skips *only* the roadmap-generated diagrams. This is necessary because a dark,
largely-achromatic Gantt would otherwise be misclassified as grayscale
line-art and remapped, inverting its colours. It is a precise per-file skip —
hand-authored `.. uml::` diagrams (which *do* need dark recolouring) are
unaffected. (A blanket `plantuml-*.png` exclude would wrongly suppress those
hand-authored diagrams, so it is deliberately not used.)

Requires theme-core ≥ 1.1.9 (which exposes the public `get_dark_mode_context`
and `mark_image_dark_ready` helpers). Older cores degrade
gracefully: the roadmap falls back to the light palette in dark builds.

Override the diagram background explicitly if needed:

```python
doxtr_roadmap_diagram_background_color = "#101010"  # None = auto (dark page in dark mode)
doxtr_roadmap_foreground_color = "#DBDBDB"  # None = auto (theme-core text colour in dark mode)
```

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
