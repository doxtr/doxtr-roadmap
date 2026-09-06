"""Shared pytest fixtures for doxtr_roadmap tests."""

import datetime
import pytest


# ---------------------------------------------------------------------------
# Sample CSV data
# ---------------------------------------------------------------------------

SAMPLE_CSV_TEXT = """\
section,name,start,end,row_group,link,tags
Alpha,Task A,2026-01-01,2026-03-31,,https://example.com/a,eng
Alpha,Task B,2026-02-01,2026-04-30,grp1,,code
Alpha,Task B,2026-05-01,2026-06-30,grp1,,code
Beta,Milestone M,2026-03-15,2026-03-15,,,:xlink:`proj-milestone`
Beta,Task C,2026-03-01,2026-06-30,,https://example.com/c,
Gamma,Parent Task,2026-01-01,2026-12-31,,,
Parent Task,Subtask 1,2026-01-01,2026-06-30,,,
Parent Task,Subtask 2,2026-07-01,2026-12-31,,,
"""

SAMPLE_CSV_WITH_PERIODS = """\
section,name,start,end,row_group,link,tags
Periods,Set27-01,2026-11-09,2027-01-29,,, 
Periods,Set27-04,2027-02-01,2027-04-09,,,
Work,Task X,2026-12-01,2027-01-15,,,
Work,Task Y,2027-02-15,2027-04-01,,,
"""


# ---------------------------------------------------------------------------
# Fake config / app objects for unit tests (no Sphinx app needed)
# ---------------------------------------------------------------------------

class FakeConfig:
    """Minimal config object with all doxtr_roadmap_* attributes at defaults."""

    extensions = []
    doxtr_roadmap_default_scale = "monthly"
    doxtr_roadmap_scale_factor = 1.25
    doxtr_roadmap_default_start = None
    doxtr_roadmap_default_title = "Roadmap"
    doxtr_roadmap_clean_style = False
    doxtr_roadmap_close_weekends_on_single_period = True
    doxtr_roadmap_bar = {
        "done_color": "#FF8C00",
        "undone_color": "#FFF3E0",
        "frame_color": None,
    }
    doxtr_roadmap_sections = {}
    doxtr_roadmap_today = {"color": "#E53935"}
    doxtr_roadmap_fonts = {
        "title":     {"name": None, "size": 24, "style": "bold",  "color": None},
        "task":      {"name": None, "size": 14, "style": None,    "color": None},
        "separator": {"name": None, "size": 16, "style": "bold",  "color": None},
        "month":     {"name": None, "size": None, "style": None,  "color": None},
        "year":      {"name": None, "size": None, "style": None,  "color": None},
    }
    doxtr_roadmap_closed = {"background_color": None}
    doxtr_roadmap_use_theme_core = "auto"
    doxtr_roadmap_allowed_tags = {}
    doxtr_roadmap_allowed_tag_patterns = {}
    doxtr_roadmap_collision_detection = True
    doxtr_roadmap_collision_char_width_factor = 1.0
    doxtr_roadmap_collision_gap_days = 2
    doxtr_roadmap_link_appendix = False
    doxtr_roadmap_link_appendix_builders = ["latex"]
    doxtr_roadmap_link_appendix_title = "Links"


class FakeEnv:
    """Minimal Sphinx env stub."""

    def __init__(self, config=None, srcdir="/tmp"):
        self.config = config or FakeConfig()
        self.srcdir = srcdir
        self.docname = "index"

    def note_dependency(self, path):
        pass


class FakeApp:
    """Minimal Sphinx app stub."""

    def __init__(self, config=None):
        self.config = config or FakeConfig()
        self.env = FakeEnv(config=self.config)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_csv_text():
    return SAMPLE_CSV_TEXT


@pytest.fixture
def sample_csv_with_periods():
    return SAMPLE_CSV_WITH_PERIODS


@pytest.fixture
def fake_config():
    return FakeConfig()


@pytest.fixture
def fake_app(fake_config):
    return FakeApp(config=fake_config)


@pytest.fixture
def sample_items(sample_csv_text):
    """Parsed items from SAMPLE_CSV_TEXT."""
    from doxtr_roadmap import csv_parser
    return csv_parser.load_items_from_string(sample_csv_text)


@pytest.fixture
def period_items(sample_csv_with_periods):
    """Parsed items from SAMPLE_CSV_WITH_PERIODS."""
    from doxtr_roadmap import csv_parser
    return csv_parser.load_items_from_string(sample_csv_with_periods)


@pytest.fixture
def default_config_dict():
    """The DEFAULT_CONFIG dict."""
    from doxtr_roadmap.config_defaults import DEFAULT_CONFIG
    return dict(DEFAULT_CONFIG)


@pytest.fixture
def base_gen_config():
    """A minimal generator config dict (from DEFAULT_CONFIG with today as start)."""
    from doxtr_roadmap.config_defaults import DEFAULT_CONFIG
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["default_start"] = "2026-01-01"
    return cfg
