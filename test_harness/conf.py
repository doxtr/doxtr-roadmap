"""Sphinx configuration for the doxtr_roadmap test harness.

This minimal conf.py drives HTML smoke-builds of the test-case RST files.
It requires sphinxcontrib.plantuml to be installed; if plantuml is not on
PATH or the jar is not found, the build will still succeed but images will
show as errors (acceptable for smoke-test purposes).
"""

import os

project = "doxtr-roadmap test harness"
author = "doxtr"
extensions = ["sphinxcontrib.plantuml", "doxtr_roadmap"]

# Point to the plantuml jar if available
plantuml = os.environ.get("PLANTUML_CMD", "plantuml")
plantuml_output_format = "png"

# Minimal HTML theme
html_theme = "alabaster"

# doxtr_roadmap config — use project-specific defaults for the harness
doxtr_roadmap_default_scale = "monthly"
doxtr_roadmap_default_title = "Test Roadmap"
# clean_style defaults to True (PlantUML v1.2026.7 is the baseline);
# no override needed here — the default hides Start/End/Duration columns.
# doxtr_roadmap_require_plantuml_version defaults to "error"; local plantuml
# is 1.2026.7 so the version check passes without any explicit opt-out.
doxtr_roadmap_bar = {
    "done_color": "#FF8C00",
    "undone_color": "#FFF3E0",
    "frame_color": None,
}
doxtr_roadmap_today = {"color": "#E53935"}

# Link appendix — render task links as a bullet list in HTML output
# (exercises the appendix feature in the HTML smoke build)
doxtr_roadmap_link_appendix = "list"
doxtr_roadmap_link_appendix_builders = ["html"]
doxtr_roadmap_link_appendix_title = "Links"
