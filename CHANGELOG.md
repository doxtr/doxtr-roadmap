# Changelog

All notable changes to `doxtr-roadmap` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.4] — 2026-09-26

### Added

- **Automatic *undone* (remaining) bar colour derived from the *done* colour**
  — the remaining portion of every bar is now always
  `doxtr_roadmap_bar["undone_brightness_delta"]` percent *lighter* than the
  done colour in light mode and that much *darker* in dark mode, keeping the
  completed/remaining relationship consistent for any done colour. The new
  `undone_brightness_delta` key defaults to `88.7` (derived from the historical
  `done=#FF8C00` / `undone=#FFF3E0` pair); set it to `0` to disable derivation
  and use the literal `undone_color`. A genuine user `undone_color` override
  always wins. NOTE: PlantUML gantt exposes only a single *global* undone
  background (there is no per-task undone selector), so the derivation uses the
  global `done_color` and applies to every bar's remaining portion — even bars
  whose completed portion is individually coloured via the CSV `color` column.
- **Per-task / per-section colours via a CSV `color` column** — an optional
  `color` column lets each roadmap row set its bar's *done* (fill) colour
  directly from the data. Values may be a semantic `doxtr_pdf_theme_core`
  expression (`dd:primary`, `dd:#FFCC00:lighten:80`, …) or a hex colour
  (`#123456`, `#4567896F` with alpha). A matching *frame* border is derived
  automatically by lightening or darkening the fill; the direction is chosen
  for headroom (a near-black fill is lightened, a near-white fill darkened),
  and the magnitude is configurable via the new
  `doxtr_roadmap_bar["frame_brightness_delta"]` key (default `30`).
  Colour **inheritance**: a section's colour is the first coloured row in that
  section; a subtask with no colour inherits its parent's effective colour
  recursively (sub-sub-…tasks included); a mid-chain colour overrides from that
  task downward; and the sentinel `color=default` resets a task back to the
  roadmap default, stopping inheritance. Semantic colours resolve against the
  active light/dark palette, and raw hex colours are soft-inverted in dark
  mode. When `doxtr_pdf_theme_core` is not installed a `dd:` colour warns once
  and falls back to the default colour; raw hex still works. Delivered by a new
  `color_resolver` module and a matching optional `color_resolver` parameter on
  `generator.generate_puml` (custom renderers that predate it keep working — it
  is only passed when the renderer's signature accepts it).
- **Recursive subtask nesting** — a subtask may now itself parent deeper
  subtasks (sub-sub-…tasks) to arbitrary depth. Previously only one level of
  nesting was recognised and a row referencing a subtask as its parent was
  mis-detected as a new section.
- **Colour-engine replacement seam (`doxtr_roadmap_color_resolver`)** — a new
  config value (default `None`) accepting a dotted path to a factory
  `(config, frame_delta) -> resolver` (a callable with the same contract as
  `color_resolver.ColorResolver.resolve`). Lets a child theme replace the
  entire colour-expression engine (custom grammar, palette source, brightness
  algorithm) independently of the renderer, without monkeypatching or forking.
  The built-in *undone*-colour derivation now runs only for the built-in
  renderer, so a custom renderer receives the raw config and owns its colour
  maths.
- **Renderer replacement seam (`doxtr_roadmap_renderer`)** — a new config value
  (default `None`) accepting a dotted path (`module.callable` or
  `module:callable`) to a callable with the same signature as
  `generator.generate_puml`. When set, it fully replaces the built-in PlantUML
  generation, so a child theme can supply its own renderer without
  monkeypatching or forking. When unset the built-in generator is used
  unchanged.

### Fixed

- **Collision detection now accounts for `:column-zoom:`** — label
  day-footprints are divided by the effective zoom factor in
  `_estimate_label_days` (and threaded through `_bar_extent` / `_pack_lanes`).
  Because `zoom` physically widens every column without changing how many days
  a column represents, a label covers `zoom` times fewer calendar days on
  screen. Previously the detector over-estimated label width at high zoom,
  reported phantom collisions, and split same-row groups onto extra lanes;
  `:collision-char-width-factor:` no longer needs manual `1/zoom` compensation.
  The guard also treats non-finite (`NaN`/`inf`) and non-positive zoom values
  as `1.0`. Behaviour at zoom 1 is unchanged.

- **PlantUML special-character escaping / task-id sanitization** — task names
  and resolved link titles are now escaped/sanitized before being written into
  the generated PlantUML source, so characters that are structurally
  significant to PlantUML render verbatim instead of corrupting the diagram.
  Square brackets in a task name or its internal id are replaced with
  parentheses (they cannot break the `[name] as [pid]` delimiters), and
  structural characters in a link title (`& < > [ ] ' ~ "`) plus paired Creole
  formatting digraphs (`//`, `**`, `__`, `--`, escaped only when they appear in
  at least two non-overlapping occurrences) are replaced with HTML entities
  that PlantUML renders back as the original characters. Link titles such as
  `A & B <x>` are now safe.

## [0.1.3] — 2026-09-20

### Added

- **Automatic loading of `doxtr_pdf_theme_core`** — when the
  `doxtr_pdf_theme_core` package is installed, `doxtr_roadmap` now loads it
  automatically at extension setup (via `app.setup_extension`), so the palette
  / typography / dark-mode integration activates with zero configuration.
  Users no longer need to add `doxtr_pdf_theme_core` to their `conf.py`
  `extensions` list by hand. theme-core remains an *optional* dependency: when
  it is not installed the auto-load is silently skipped and the extension
  degrades to its own defaults. A new boolean config value
  `doxtr_roadmap_autoload_theme_core` (default `True`) opts out of the
  auto-load — e.g. for a child theme that supplies its own rendering and does
  not want theme-core pulled in. This is independent of
  `doxtr_roadmap_use_theme_core`, which continues to control whether a *loaded*
  theme-core's palette is *read* into the roadmap style (`"auto"` still
  activates whenever theme-core is loaded, whether listed explicitly or
  auto-loaded).

This release also consolidates the previously-unreleased work below.

### Fixed

- **Dark-mode rendering when theme-core is loaded transitively** — the
  `"auto"` value of `doxtr_roadmap_use_theme_core` now detects
  `doxtr_pdf_theme_core` even when it is *not* listed in `conf.py`'s
  `extensions` but is pulled in transitively by another extension via
  `app.setup_extension('doxtr_pdf_theme_core')`. Previously the detection
  only checked `config.extensions`, which lists user-declared extensions
  only, so a transitively-loaded core was missed: the theme palette (and, in
  particular, the dark-mode diagram background / foreground colours) was
  never applied and dark PDFs rendered the Gantt with light colours. Users
  had to add theme-core to `extensions` (or force
  `doxtr_roadmap_use_theme_core=True`) by hand in `conf.py` to work around
  it. Detection now also treats the presence of theme-core's resolved
  `doxtr_dark_mode_strategy_resolved` config value (set by theme-core's
  `config-inited` hook) as proof that the core is loaded and initialised, so
  no `conf.py` workaround is needed. Explicit `True` / `False` settings are
  unchanged.

### Added

- **Period references in `start` / `end` cells** — a task row's `start` or
  `end` cell may be written as `@<period>` instead of a literal ISO date. The
  reference is expanded before rendering to the referenced period's **start**
  edge (in a `start` cell) or **end** edge (in an `end` cell), so a row with
  `start=@PI27-01` and `end=@PI27-08` spans from the start of PI27-01 to the
  end of PI27-08. `<period>` may be a dynamic expression (a literal ISO date,
  a `doxtr_roadmap_period_calendars` keyword such as `@current-pi`, or
  calendar math such as `@now()+2 weeks`) or a plain period **name** matched
  case-insensitively against the loaded roadmap rows (including rows from a
  `norender` reference file). Cells without a leading `@` are still parsed
  strictly as ISO dates, so existing CSVs are unaffected; an unresolvable
  reference raises a clear build error. New public helpers
  `period_expr.is_period_ref` and `period_expr.resolve_cell_edge`.
- **Configured calendar files resolve plain period names** — a bare `:period:`
  name (e.g. `:period: current-pi, PI28-01`) and a `@<name>` cell reference
  now resolve against the rows of every configured
  `doxtr_roadmap_period_calendars` file, not just the rows loaded via
  `:file:`. Previously a name that lived only in `pi-periods.csv` failed with
  `unknown period name(s)` unless that file was also listed in `:file:`
  (typically with `norender`). A loaded row still wins over a calendar row on
  a name clash.
- **Per-file `:file:` options** — each `:file:` spec may carry a trailing
  `[...]` option bracket (e.g. `sprint-01.csv[ignore=section,link;norender]`).
  Options are `;`-separated; each is a bare flag or a `key=value` pair whose
  value is a comma-separated list. Options apply to every file a glob matches
  and are independent per spec.
  - `ignore=<col>[,<col>...]` blanks the named non-essential column(s) for
    that spec's rows **at parse time**, so the data stays fully documented in
    the CSV while being suppressed uniformly from rendering, `:tags:` /
    `:query:` filtering, and the link appendix. Ignoring `section` flattens
    the rows (no header, no subtask parenting); ignoring `row_group` drops
    same-row grouping. The strictly-required columns (`name` / `start` /
    `end`) cannot be ignored.
  - `norender` loads and parses a file (so its rows remain usable for a named
    `:period:` / `:start:` / `:end:` and stay documented) but emits no bars
    from it — e.g. to load a period-calendar file purely as a reference.
- **`doxtr_roadmap_ignorable_columns` config value** — the list of columns a
  user is allowed to suppress via `ignore=`. Defaults to every non-required
  column (`section`, `row_group`, `link`, `tags`); the required columns can
  never be ignored regardless of this list. Exposed so future columns can be
  made ignorable without a code change.
- **`doxtr_roadmap_period_calendars_options` config value** — per-calendar
  option strings keyed by the same trigger keyword as
  `doxtr_roadmap_period_calendars`, using the same option grammar as the
  `:file:` bracket (e.g. `{"current-pi": "ignore=tags,link"}`). Calendars
  never render bars, so `norender` is implicit and ignored there.

## [Unreleased] — Per-roadmap PlantUML output format overrides

### Added

- **`doxtr_roadmap_html_format` and `doxtr_roadmap_latex_format` config
  values** — override the PlantUML output format for roadmap diagrams only,
  without affecting ordinary `.. uml::` blocks.  Both default to `None`,
  meaning *defer to the project-wide `plantuml_output_format` /
  `plantuml_latex_output_format`* so existing projects are unaffected and
  roadmaps inherit the global format (e.g. `svg_obj` HTML, `pdf` LaTeX) by
  default.  Setting them lets a project render, say, roadmaps as `png` while
  every other diagram stays `svg`.

- **`:html-format:` and `:latex-format:` directive options** — per-chart
  overrides accepting the same values as `sphinxcontrib.plantuml`
  (`png`, `svg`, `svg_img`, `svg_obj`, `none` for HTML; `eps`, `pdf`,
  `eps_pdf`, `svg_pdf`, `png`, `tikz` for LaTeX).  These win over the
  `doxtr_roadmap_*` config values, which in turn win over the global
  `plantuml_*` settings.

- The overrides are applied by setting the `html_format` / `latex_format`
  attributes on the generated `sphinxcontrib.plantuml` node, which that
  extension already honours in preference to its global config.  The node
  attributes are set **only** when an override is configured, so the default
  behaviour is unchanged.

## [Unreleased] — Multi-file and glob `:file:` support

### Added

- **`:file:` accepts multiple CSV paths and/or glob patterns**, space- or
  comma-separated (e.g. `:file: sprint-01.csv sprint-02.csv` or
  `:file: sprints/*.csv`).  All matched files are loaded as a **single
  combined roadmap**: sections with the same name merge across files and
  subtasks / `row_group` references work even when the parent task is
  defined in a different file.  A single path with no separators behaves
  identically to before (fully backward compatible).

- **`csv_parser.load_items_from_files(paths)`** — new public function that
  accepts an ordered iterable of file paths, materialises each file's rows
  while the file handle is open, chains them into a single iterable, and
  passes the combined rows to `_parse_rows` in one call so the two-pass
  subtask/section logic operates over all rows as one roadmap.  Using
  `itertools.chain` or per-file parsing with individual `_parse_rows` calls
  would break cross-file subtasks; this implementation avoids that.

- **`csv_parser._parse_rows` now accepts any row-dict iterable** (not only
  `csv.DictReader`).  The parameter is renamed `rows_iter`; existing callers
  are unaffected because `DictReader` is already such an iterable.  This
  enables `load_items_from_files` to pass a combined list of dicts.

- **`load_items_from_file(path)` delegates to `load_items_from_files([path])`**
  for DRY internals; its public signature and behaviour are unchanged.

- **Glob-aware file resolution in `RoadmapDirective._load_from_file_option`**:
  - Each spec is tried against `<srcdir>/<doc_dir>/<spec>` then
    `<srcdir>/<spec>` using `glob.glob`.  Glob metacharacters (`*`, `?`,
    `[`) are expanded; plain filenames work via glob as well.
  - Matches within a glob are sorted lexicographically (predictable order).
  - Files matched by more than one spec are de-duplicated (first-seen order).
  - `env.note_dependency` is called for every resolved file.
  - Specs that match no files emit a warning (not an error) when other specs
    in the same `:file:` value do match; if **no** files are found at all a
    `ValueError` is raised and an error node is produced.

- **`:file:` option validator changed from `directives.path` to
  `directives.unchanged`** so the raw multi-spec/glob string is preserved
  as-is for processing by `_load_from_file_option`.

- **Example sprint CSV files** (`new-roadmap-docs/files/sprint-01.csv`,
  `sprint-02.csv`, `sprint-03.csv`) demonstrating split-sprint roadmaps,
  including a cross-file subtask in `sprint-01.csv`.

- **Documentation updates**:
  - `README.md`: updated `:file:` table row; added "Multiple files and
    globs" subsection.
  - `new-roadmap-docs/roadmap.rst`: added "Multiple files and globs"
    section with live rendered examples (explicit list and glob) and
    `literalinclude` blocks for the sprint CSV files; updated `:file:` row
    in the directive options reference table.

- **New tests**:
  - `tests/test_csv_parser.py`: 7 new tests for `load_items_from_files`
    covering two-file combine, cross-file section merge, cross-file subtask,
    file ordering, empty-file tolerance, equivalence with `load_items_from_file`,
    and mismatched optional columns.
  - `tests/test_directive.py`: 9 new integration tests for multi-file/glob
    `:file:` covering explicit space-separated paths, comma-separated paths,
    glob expansion, sorted glob order, no-match error, deduplication,
    `note_dependency` for all files, cross-file subtask rendering, and
    single-path backward compatibility.

### Notes

- Adding a *new* file matching an existing glob pattern is not detected by
  `env.note_dependency` (Sphinx does not watch for new files); a
  `make clean html` is required after adding files to a glob.
- Header rows are read per-file by `DictReader`; optional columns may be
  omitted independently in each file.


### Fixed

- Row `tags` cells are now tokenized on both whitespace and commas (matching
  the documented "space- or comma-separated" behaviour) via the new
  `parse_row_tags()` helper, used by the `:tags:` and `:query:` filters and the
  link appendix. Previously a space-separated cell like `eng ops` was treated
  as the single tag `"eng ops"`, so `:query: "eng" in tags` and `:tags: eng`
  matched no rows. Double-quoted spans (e.g. `bib:author:"van B, L"`) are
  preserved.
- A roadmap whose filters (tags/query/period/clip) leave zero tasks no longer
  emits an empty PlantUML gantt (which crashed PlantUML and produced an error
  image). Instead a "No matching tasks" placeholder is rendered and a warning
  is logged.

## [Unreleased] — Footnote-in-Caption: Task Name Moved to Footnote Body

### Changed

- **New footnote-in-caption format** (`directive.py` step 8b).  When a
  roadmap is rendered as a figure with `link_appendix = "footnote"` and the
  builder is in `link_appendix_builders`, the task names are now moved **out
  of the caption** and **into the footnote bodies**.  The caption shows only
  one label word (the `link_appendix_title`, default `"Links"`) followed by
  one auto-numbered footnote reference marker per link, comma-separated:

  ```
  Projects with Links (Links [1], [2])
  ```

  With `numfig = True` this renders as e.g.:
  *Fig. 13.19: Projects with Links (Links⁹,¹⁰)*

  Previously the caption contained the task name as an inline literal before
  each marker: `` (``Task A`` [1], ``Task B`` [2]) ``.

  Each footnote definition body now carries the task name, the link title
  (when available), and the URL:

  - Plain URL (no resolved title): `.. [#] <Task Name>: <url>`
  - xlink with resolved title: `.. [#] <Task Name> >> <Title>: <url>`

  The `>>` separator is literal text distinguishing task name from link title.
  The bare `https://…` URL auto-links in the rendered footnote body.

  **RST format strings (new):**
  - Caption: `f"{safe_caption} ({safe_label} " + ", ".join(["[#]_"] * len(links)) + ")"`
  - Footnote with title: `f".. [#] {safe_task} >> {safe_title}: {url}"`
  - Footnote without title: `f".. [#] {safe_task}: {url}"`

  **Escaping:** task name is escaped with `replace("\`", "\\\`")`,
  `replace("*", "\\*")`, `replace("_", "\\_")` before inclusion in the
  footnote body RST.  The label word is escaped similarly.  The caption text
  is escaped with `replace("*", "\\*")` and `replace("_", "\\_")` as before.

  Everything else is unchanged: footnote-in-caption still only triggers when
  `wrap_in_figure AND appendix_mode == "footnote" AND builder_allowed AND
  links`; the footnote definitions are still sibling nodes after the figure;
  no separate `doxtr-roadmap-links` container is emitted; `"list"` mode and
  non-figure footnote mode are unaffected.

- **Updated `test_footnote_in_caption_figure_with_links`** in
  `tests/test_directive.py` to assert the **new** format:
  - Caption contains `"Links"` (label word) and does **not** contain task
    names (`"Task Alpha"`, `"Task Beta"`).
  - Footnote bodies contain the task name and URL in `"<Task>: <url>"` form
    (plain-URL case, no `>>`).  Footnote reference nodes are still present
    inside the caption.  The separate `doxtr-roadmap-links` container and
    `"Links"` rubric are still absent.

---

## [Unreleased] — Caption Default and Footnote-in-Caption

### Changed

- **Caption defaults to the chart title for all figure wraps** (`directive.py`
  step 8b).  Previously an `:align:`-only wrap produced a figure with no
  caption, and `doxtr_roadmap_figure = True` fell back to the chart title only
  when `doxtr_roadmap_figure_caption` was absent.  The new precedence order is:

  1. Explicit `:caption:` option (verbatim) — highest.
  2. `doxtr_roadmap_figure_caption` if non-empty — global override.
  3. Chart title (`:title:` option or `doxtr_roadmap_default_title`) — default.

  This ensures every figure wrap always produces a caption (and therefore
  appears in the List of Figures) without any extra configuration.  An empty
  title produces no caption node (unchanged guard).

- **`"footnote"` link appendix mode merges into the figure caption** when the
  roadmap is rendered as a figure and the builder is in
  `link_appendix_builders`.  Instead of a separate "Links" rubric/container
  below the chart, the task names and auto-numbered footnote references are
  appended to the end of the caption in a compact bracketed form:

  ```
  <caption text> (``Task A`` [1], ``Task B`` [2])
  ```

  The footnote definitions are emitted as sibling nodes immediately after the
  figure so docutils pairs them with the in-caption references by document
  order.  The separate `doxtr-roadmap-links` container is **not** emitted in
  this case.  If there are no resolvable links the caption is the plain title
  (no empty parentheses).  `"list"` mode is unaffected and always produces
  the standalone bullet list.  `"footnote"` mode **without** a figure still
  produces the standalone footnote appendix as before.

### Added

- **`_collect_appendix_links(items, resolve_fn)` helper method** on
  `RoadmapDirective`.  Extracts the shared link-collection logic (encounter
  order, deduplication) previously duplicated inside `_build_link_appendix`.
  Called from both `_build_link_appendix` and the new footnote-in-caption
  path to ensure consistent behaviour.

- **Six new tests** in `tests/test_directive.py`:
  - `test_figure_global_no_explicit_caption_uses_title` — global figure + no
    caption → caption equals title.
  - `test_figure_caption_precedence_explicit_beats_title` — explicit `:caption:`
    wins over title.
  - `test_figure_caption_precedence_figure_caption_config_beats_title` —
    `doxtr_roadmap_figure_caption` wins over title.
  - `test_footnote_in_caption_figure_with_links` — figure + footnote mode +
    links → footnote refs in caption, footnote defs as siblings, no separate
    Links block.
  - `test_footnote_in_caption_no_links_plain_caption` — figure + footnote mode
    + no links → plain title caption, no footnotes.
  - `test_footnote_in_caption_builder_not_allowed_plain_caption` — builder not
    in allowed list → plain caption, no footnotes anywhere.
  - `test_footnote_mode_no_figure_standalone_appendix` — footnote mode without
    figure → standalone appendix as before (regression guard).
  - `test_list_mode_with_figure_standalone_appendix` — list mode with figure →
    standalone bullet list, not in caption.

- Updated `test_align_only_wraps_in_figure_no_caption` → renamed to
  `test_align_only_wraps_in_figure_with_title_as_caption` reflecting the new
  default-title behaviour for align-only wraps.

---

## [Unreleased] — Figure/Caption Support and List of Figures

### Added

- **`:caption:` directive option** (`directives.unchanged`).  When present,
  the `plantuml` image node is wrapped in a `docutils.nodes.figure` containing
  a `nodes.caption`.  Sphinx numbers the figure ("Fig. N" with `numfig = True`)
  and includes it in the List of Figures.  Caption text is parsed through
  `state.inline_text` so inline RST markup works.

- **`:align:` directive option** (`left | center | right`).  Sets
  `figure['align']` on the wrapper figure and also triggers figure wrapping
  even when `:caption:` is absent — matching `sphinxcontrib.plantuml`\'s
  behaviour.

- **`:name:` directive option** (`directives.unchanged`).  Registers a
  cross-reference target on the figure via `self.add_name(figure)`, enabling
  `:numref:\`name\`` and `:ref:\`name\`` in the document.

- **`doxtr_roadmap_figure` config value** (bool, default `False`).  When
  `True`, every `.. roadmap::` is automatically wrapped as a figure even
  without a per-directive `:caption:`.  The caption defaults to the chart
  title (`:title:` option or `doxtr_roadmap_default_title`).

- **`doxtr_roadmap_figure_caption` config value** (str or `None`, default
  `None`).  Optional default caption text used when `doxtr_roadmap_figure`
  is `True` and no per-directive `:caption:` is given.  `None` → fall back
  to the chart title; any non-empty string → use verbatim.

### Changed

- **`:width:` is applied to the inner `plantuml` node before figure wrapping**
  so the width always targets the image, not the `figure` container.  No
  behaviour change when `:caption:`/`:align:` are absent.

- `DEFAULT_CONFIG` in `config_defaults.py` carries the two new keys
  (`figure`, `figure_caption`).

- `theme_adapter.get_effective_style` threads both new keys through the
  effective config dict and the simple-key user-override loop.

- `setup()` in `__init__.py` registers `doxtr_roadmap_figure` and
  `doxtr_roadmap_figure_caption` with `add_config_value(…, 'env')`.

### Implementation notes

- Figure-wrapping logic mirrors the `sphinxcontrib.plantuml` idiom exactly:
  `nodes.figure('', plantuml_node)` → optional `nodes.caption` via
  `state.inline_text` → `set_source_info` → `self.add_name(figure)`.
- The link-appendix (step 9) still appends its nodes after the (possibly
  figure-wrapped) primary node — no behavioural change.
- Without `:caption:`, `:align:`, and `doxtr_roadmap_figure=False`, the
  output is an unchanged bare `plantuml` node (fully backward compatible).

---

## [Unreleased] — Link Appendix for PDF Output

### Added

- **`doxtr_roadmap_link_appendix` config value** (default `"list"`).  Task
  links from the CSV are rendered as real, clickable docutils nodes appended
  *after* the PlantUML chart image.  This solves the problem that links
  embedded in the PlantUML image are not clickable in PDF/LaTeX output.  The
  default `"list"` combined with the `["latex"]` builder restriction below
  means the appendix is rendered for PDF output by default and omitted for
  HTML/epub (whose image links already work).  Set to `False` to disable it
  everywhere, or `"footnote"` for real reStructuredText footnotes (rendered
  as page-bottom `\footnote` in PDF).

- **`doxtr_roadmap_link_appendix_builders` config value** (default
  `["latex"]`).  A list of builder names/formats that render the appendix.
  Checked against both `builder.name` (e.g. `"latex"`, `"html"`) and
  `builder.format` (e.g. `"latex"`, `"html"`).  Use the special value
  `"all"` (or a list containing `"*"`) to render for every builder.  The
  default `["latex"]` means PDF output gets the appendix while HTML/epub
  output doesn't — no per-format conditionals needed in source.

- **`doxtr_roadmap_link_appendix_title` config value** (default `"Links"`).
  Heading text placed above the appendix list, rendered as a
  `nodes.rubric`.  Set to an empty string or `None` to suppress the
  heading.

- **`:link-appendix:` directive option**.  Per-directive override for the
  appendix mode.  Accepts `list`, `footnote`, or `off`/`none`/`false` (to
  disable even when globally enabled).  A bare flag (no value) defaults to
  `"list"`.

- **`:link-appendix-title:` directive option**.  Per-directive heading
  override; accepts any string.

- **`_build_link_appendix()` helper method** on `RoadmapDirective`.  Collects
  resolved links from the (already tag/query-filtered) `items` list, builds
  a `nodes.container(classes=['doxtr-roadmap-links'])` wrapping an optional
  `nodes.rubric` heading and a `nodes.bullet_list` (mode `"list"`) or
  real RST auto-numbered footnotes (mode `"footnote"`).  Returns `[]` when no tasks
  have resolvable links so no empty container is ever appended.

### Changed

- **`"footnote"` mode now emits real reStructuredText auto-numbered footnotes**
  instead of a `nodes.enumerated_list`.  `_build_link_appendix` builds RST
  text (a lead-in paragraph with `[#]_` markers and matching `.. [#]`
  footnote definitions) and parses it via `self.state.nested_parse`, letting
  docutils create proper `nodes.footnote` / `nodes.footnote_reference` nodes.
  In PDF/LaTeX output Sphinx's LaTeX writer renders these as page-bottom
  `\footnote{}` commands.  In HTML they render as standard numbered
  footnotes with back-references.  Task names are emitted as inline literals
  (`` ``name`` ``) to neutralise RST special characters.

- **Builder restriction** is evaluated at directive run-time against the
  live `builder.name` and `builder.format` attributes, so the same source
  file produces different output trees for HTML (image only) and LaTeX
  (image + appendix) in a single `make` invocation.

- **Duplicate links** (identical task name + URL + title) are collapsed to
  one entry in encounter order.

- New config values registered in `setup()` with `add_config_value(...,
  'env')`.  `doxtr_roadmap_link_appendix` is registered with
  `types=(bool, str)` to avoid a Sphinx type-mismatch warning when the
  user sets it to a string value.

---

## [Unreleased] — Configurable Gantt Column Width (Zoom)

### Added

- **`doxtr_roadmap_column_zoom` config value** (default `1`).  Multiplies the
  width of each PlantUML Gantt time column by appending `zoom <factor>` to the
  `projectscale` line.  A value of `1` (or absent) leaves the column width
  unchanged (fully backward compatible).  Example: `doxtr_roadmap_column_zoom = 3`
  produces `projectscale monthly zoom 3`.

- **`:column-zoom:` directive option** on `.. roadmap::`.  Accepts a float;
  overrides the global `doxtr_roadmap_column_zoom` for a single chart instance.

- **`:width:` directive option** on `.. roadmap::`.  Accepts any
  `docutils`-style length/percentage value (e.g. `100%`, `800px`).  When
  present, sets `node["width"]` on the `sphinxcontrib.plantuml` node so the
  rendered image fills the specified width in HTML (inline `style`) and PDF
  (LaTeX `adjustbox`).  Not set by default — no change in behaviour when the
  option is absent.

- Integer-formatting helper in `generator.py`: whole-number zoom values are
  emitted without a trailing `.0` (e.g. `zoom 3` not `zoom 3.0`); non-whole
  floats use their natural string representation (`zoom 2.5`).

- Guard in `generator.py`: zoom values ≤ 0 or non-numeric are silently treated
  as `1` (no zoom), so invalid user input never produces a broken PlantUML
  source file.

### Notes

- The `zoom <factor>` keyword form is used exclusively.  The legacy
  `projectscale monthly 3` form (no `zoom` keyword) errors on PlantUML
  v1.2026.7 and is never emitted.
- PlantUML v1.2026.7 is already the extension’s minimum baseline, so no
  version-requirement change is needed.

---

## [Unreleased] — Collision Detection for Same-Row Groups

### Fixed

- **Label collision on `row_group` same-row tasks** (`doxtr_roadmap/generator.py`).
  When two or more tasks shared a `row_group`, the generator packed them all
  onto the anchor's single Gantt row via PlantUML `displays on same row as`.
  PlantUML renders each task's label starting at/across its bar; when bars
  overlap in time, or when an earlier bar's label overruns into a later bar,
  the labels smear together and become unreadable.  This is now fixed by
  default.

### Added

- **Greedy lane-packing collision detection** in `generator.py`.
  New pure helpers (no Sphinx imports):

  - `_estimate_label_days(name, scale, char_width_factor)` — estimates how
    many calendar days a task's text label occupies horizontally at a given
    projectscale, using calibrated days-per-character constants
    (`daily` ≈ 1.1, `weekly` ≈ 4, `monthly` ≈ 9) multiplied by a tunable
    `char_width_factor`.
  - `_bar_extent(disp_start, disp_end, name, is_milestone, scale, ...)` —
    returns the full horizontal footprint `(left, right)` of a task bar,
    accounting for label overrun and a configurable gap.
  - `_extents_overlap(ext_a, ext_b)` — half-open interval overlap test.
  - `_pack_lanes(members, scale, char_width_factor, gap_days)` — greedy
    first-fit lane assignment.  Members are placed on the first lane they
    do not collide with; otherwise a new lane is opened.  Returns a list
    of lanes (each a list of member dicts).  Groups that fit on one lane
    behave exactly as before (no behaviour change for non-colliding groups).

- **Three new `doxtr_roadmap_*` config values** registered in `setup()`:

  | Config key | Default | Description |
  |---|---|---|
  | `doxtr_roadmap_collision_detection` | `True` | Enable/disable collision detection globally |
  | `doxtr_roadmap_collision_char_width_factor` | `1.0` | Label-width tuning knob |
  | `doxtr_roadmap_collision_gap_days` | `2` | Minimum gap (days) between tasks on a lane |

- **Two new directive options** on `.. roadmap::`:

  - `:collision-detection: true/false` — per-chart override (bare flag = `True`).
  - `:collision-char-width-factor: <float>` — per-chart label-width tuning.

- `DEFAULT_CONFIG` in `config_defaults.py` carries the three new keys.
- `theme_adapter.get_effective_style` threads all three collision keys through
  the effective config dict so `generate_puml` can read them.
- `tests/test_collision.py` — 40 new hermetic pure unit tests covering
  `_estimate_label_days`, `_bar_extent`, `_pack_lanes`, and generator
  integration (detection on/off, non-colliding regression guard).
- Existing `test_row_group_directive` updated to use `collision_detection=False`
  to preserve the original assertion about the old forcing behaviour; two new
  sibling tests cover the default-on splitting and non-colliding same-row cases.
- `test_theme_adapter.py` — four new assertions that `get_effective_style`
  carries collision defaults and respects user overrides.
- `test_directive.py` — three new integration tests for the
  `:collision-detection:` directive option.

### Behaviour

- **Default on**: collision detection is enabled by default.  Same-row groups
  whose tasks fit without collision are unaffected (identical PUML output).
  Groups whose tasks would collide are split onto the minimum number of
  additional rows.
- **Opt-out**: set `doxtr_roadmap_collision_detection = False` in `conf.py`,
  or use `:collision-detection: false` on a single chart, to restore the old
  behaviour (all same-row-group tasks on one row, regardless of overlap).

---

## [Unreleased] — Security Hardening

### Security

- **`:query:` evaluator replaced with a restricted AST evaluator** (`doxtr_roadmap/safe_query.py`).
  The previous `eval()`-based approach, even with a restricted `__builtins__` dict,
  was still vulnerable to the classic CPython sandbox escape via attribute traversal:
  `().__class__.__bases__[0].__subclasses__()` could reach `subprocess.Popen`,
  `os._wrap_close`, and other dangerous classes.
  The new evaluator uses `ast.parse(expr, mode="eval")` + a strict allowlist of
  AST node types, then walks the AST manually — no `eval()` / `exec()` is called.
  `ast.Attribute` nodes are **explicitly forbidden**, closing the `__subclasses__`
  escape entirely.  Other forbidden constructs: subscript access, lambdas,
  comprehensions, generator expressions, walrus operator, imports, f-strings,
  and any name not present in the caller-supplied `names` dict (so `__import__`,
  `open`, `subprocess`, etc. are all unreachable).
  The fail-open policy (include row on error, emit a `[doxtr-roadmap]` warning)
  is preserved.

### Added

- `doxtr_roadmap/safe_query.py` — pure, Sphinx-free module exposing
  `evaluate_query(expr, names) -> bool` and `QueryError`.
- `tests/test_safe_query.py` — 53 hermetic unit tests covering allowed
  expressions, all major sandbox-escape patterns, undefined names, syntax
  errors, and edge cases.
- Two new directive-level tests in `tests/test_directive.py` explicitly
  asserting that `(1).__class__.__bases__[0] is object` and
  `().__class__.__bases__[0].__subclasses__()` both trigger fail-open
  (row included, `[doxtr-roadmap]` warning emitted).

---

## [0.1.0] — Initial Release

### Added

- `.. roadmap::` Sphinx directive that generates PlantUML Gantt diagrams from
  CSV data (`:file:` option or inline CSV body).
- CSV columns: `section`, `name`, `start`, `end`, `row_group`, `link`, `tags`.
- Two-pass subtask detection: rows whose `section` column matches a known
  top-level task name are attached as subtasks directly beneath that parent.
- Same-row grouping via the `row_group` column.
- Milestone support: rows where `start == end` render as diamond markers.
- Timeline clipping: tasks outside the clip window are omitted; partially
  overlapping tasks are clamped to the window edges. Milestones are never
  clamped.
- `find_period_window()` / `resolve_window()` for period-based zoom: the
  `:period:` directive option accepts a comma-separated list of period names.
- Auto-scale: when exactly one distinct period is selected and `:scale:` is
  not set, the diagram switches to daily scale and closes weekends automatically.
- Tag filtering via the `:tags:` directive option using the nested
  `[ ]` / `!` / `!!` syntax.
- Query filtering via the `:query:` directive option (safe Python eval).
  Available eval context: `name`, `start`, `end`, `section`, `tags`,
  `row_group`, safe `match(pattern, string)` regex helper, and builtins
  `any`/`all`/`bool`/`set`/`len`.  The raw `re` module is intentionally
  excluded to prevent sandbox escape and ReDoS attacks.
- `LinkResolver` class resolves plain URLs and `:xlink:\`id\`` role expressions
  when `sphinxcontrib.xlink` is in `extensions`.
- `TaskItem` typed NamedTuple replacing raw positional tuples in the CSV
  parser output — improves readability and IDE support.
- Optional `doxtr_pdf_theme_core` integration via `ThemeCoreAdapter`: maps
  semantic palette and typography to roadmap style knobs.
- 15 `doxtr_roadmap_*` Sphinx config values for global style customisation,
  including `doxtr_roadmap_require_plantuml_version`.
- `sphinxcontrib.plantuml` presence verified at `builder-inited` time with a
  clear `ExtensionError` if absent.
- PlantUML minimum-version check at `builder-inited` time. The extension
  now runs `plantuml -version` and compares the result against the required
  minimum `(1, 2026, 7)` (`v1.2026.7`). Behaviour is controlled by the new
  `doxtr_roadmap_require_plantuml_version` config value (`"error"` | `"warn"`
  | `"off"` / `False`; **default `"error"`**).  An undeterminable version
  (command not found, unrecognised output, subprocess timeout) logs an INFO
  message and never aborts the build.
- New pure helper module `doxtr_roadmap/plantuml_version.py` exposing
  `MIN_PLANTUML_VERSION = (1, 2026, 7)`, `MIN_PLANTUML_VERSION_STR`,
  `parse_plantuml_version(text)`, and `is_version_sufficient(found, minimum)`
  — all unit-testable without a subprocess.
- `parallel_read_safe = True` / `parallel_write_safe = True`.
- Complete unit test suite (`tests/`) and integration smoke-build harness
  (`test_harness/`).
- CI workflows: `test.yml`, `publish.yml`, `test-harness.yml`.

### Defaults (as shipped)

- `clean_style` defaults to **`True`**.  PlantUML v1.2026.7 is the confirmed
  minimum baseline and fully supports `hide column start/end/duration`.
  Enabling `clean_style` by default prevents overlapping date stamps when
  `row_group` same-row grouping is used.  Projects that need to opt out can
  set `doxtr_roadmap_clean_style = False` in `conf.py` or use the per-directive
  `:clean-style: false` option.
- `doxtr_roadmap_require_plantuml_version` defaults to **`"error"`**.  Builds
  that detect an older PlantUML installation fail with an `ExtensionError` by
  default rather than emitting a warning.  Projects intentionally running on
  an older PlantUML can set `doxtr_roadmap_require_plantuml_version = "warn"`
  or `"off"` to opt out.
- Minimum PlantUML version: **v1.2026.7**.
