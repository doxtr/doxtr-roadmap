"""Tests for the dynamic period-expression resolver (``period_expr``)."""

import datetime

import pytest

from doxtr_roadmap import period_expr as pe
from doxtr_roadmap.period_expr import (
    ResolutionContext,
    PeriodExprError,
    add_business_days,
    business_weekdays_from_config,
    resolve_period_token,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TODAY = datetime.date(2026, 12, 15)  # a Tuesday


def ctx(config=None, load_calendar=None):
    return ResolutionContext(
        today=TODAY,
        config=config or {},
        srcdir="/src",
        docdir="doc",
        load_calendar=load_calendar,
    )


# A fake PI calendar loader: rows are (name, start, end, section).
def _pi_calendar_loader(_abspath):
    return [
        ("PI26-11", datetime.date(2026, 8, 31), datetime.date(2026, 11, 6), "PI Rhythm"),
        ("PI27-01", datetime.date(2026, 11, 9), datetime.date(2027, 1, 29), "PI Rhythm"),
        ("PI27-04", datetime.date(2027, 2, 1), datetime.date(2027, 4, 9), "PI Rhythm"),
        ("Noise", datetime.date(2026, 1, 1), datetime.date(2026, 1, 2), "Other"),
    ]


# ---------------------------------------------------------------------------
# Literal ISO dates (must never change behaviour)
# ---------------------------------------------------------------------------

def test_literal_iso_date():
    w = resolve_period_token("2027-03-01", ctx())
    assert w == (datetime.date(2027, 3, 1), datetime.date(2027, 3, 1))


def test_plain_name_falls_through():
    assert resolve_period_token("PI27-01", ctx()) is None
    assert resolve_period_token("Set27-04", ctx()) is None


# ---------------------------------------------------------------------------
# Calendar-math keywords
# ---------------------------------------------------------------------------

def test_current_year():
    assert resolve_period_token("current-year", ctx()) == (
        datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)
    )


def test_current_quarter():
    # Dec 15 2026 → Q4 (Oct 1 – Dec 31).
    assert resolve_period_token("current-quarter", ctx()) == (
        datetime.date(2026, 10, 1), datetime.date(2026, 12, 31)
    )


def test_current_month():
    assert resolve_period_token("current-month", ctx()) == (
        datetime.date(2026, 12, 1), datetime.date(2026, 12, 31)
    )


def test_current_week():
    # Dec 15 2026 is a Tuesday → Mon Dec 14 .. Sun Dec 20.
    assert resolve_period_token("current-week", ctx()) == (
        datetime.date(2026, 12, 14), datetime.date(2026, 12, 20)
    )


# ---------------------------------------------------------------------------
# Relative expressions
# ---------------------------------------------------------------------------

def test_now_and_today_are_synonyms():
    assert resolve_period_token("now()", ctx()) == (TODAY, TODAY)
    assert resolve_period_token("today", ctx()) == (TODAY, TODAY)


def test_relative_days():
    assert resolve_period_token("now()-63 days", ctx())[0] == TODAY - datetime.timedelta(days=63)
    assert resolve_period_token("today + 2 weeks", ctx())[0] == TODAY + datetime.timedelta(weeks=2)


def test_relative_months_clamp():
    # Jan 31 + 1 month → Feb 28 (2027 is not a leap year).
    c = ResolutionContext(today=datetime.date(2027, 1, 31), config={})
    assert resolve_period_token("today + 1 month", c)[0] == datetime.date(2027, 2, 28)


def test_relative_chained_terms():
    d = resolve_period_token("now() + 1 month - 3 days", ctx())[0]
    assert d == pe._add_months(TODAY, 1) - datetime.timedelta(days=3)


def test_relative_bad_tail_raises():
    with pytest.raises(PeriodExprError):
        resolve_period_token("now() + banana", ctx())


# ---------------------------------------------------------------------------
# Business-day arithmetic
# ---------------------------------------------------------------------------

def test_business_days_default_monfri():
    # From Tue 2026-12-15, minus 3 business days → Thu 2026-12-10.
    assert resolve_period_token("now()-3 businessdays", ctx())[0] == datetime.date(2026, 12, 10)


def test_business_days_forward_skips_weekend():
    # From Fri 2026-12-18, +1 business day → Mon 2026-12-21.
    c = ResolutionContext(today=datetime.date(2026, 12, 18), config={})
    assert resolve_period_token("today + 1 businessday", c)[0] == datetime.date(2026, 12, 21)


def test_business_days_custom_week_mon_wed_sat():
    # Working week Mon(0)/Wed(2)/Sat(5). From Tue 2026-12-15:
    #   +1 → Wed 16, +2 → Sat 19, +3 → Mon 21.
    cfg = {"business_days": ["monday", "wednesday", "saturday"]}
    c = ResolutionContext(today=datetime.date(2026, 12, 15), config=cfg)
    assert resolve_period_token("today + 3 businessdays", c)[0] == datetime.date(2026, 12, 21)


def test_business_days_integer_mask():
    assert business_weekdays_from_config({"business_days": [0, 2, 5]}) == frozenset({0, 2, 5})


def test_business_days_unknown_name_raises():
    with pytest.raises(PeriodExprError):
        business_weekdays_from_config({"business_days": ["funday"]})


def test_add_business_days_zero_is_identity():
    d = datetime.date(2026, 12, 19)  # Saturday, not a business day
    assert add_business_days(d, 0) == d


# ---------------------------------------------------------------------------
# CSV-backed calendars
# ---------------------------------------------------------------------------

def _cal_config(**extra):
    spec = {"file": "pi.csv", "section": "PI Rhythm"}
    spec.update(extra)
    return {"period_calendars": {"current-pi": spec}}


def test_calendar_contains_reference():
    # Dec 15 2026 is inside PI27-01 (Nov 9 2026 – Jan 29 2027).
    w = resolve_period_token(
        "current-pi",
        ctx(config=_cal_config(), load_calendar=_pi_calendar_loader),
    )
    assert w == (datetime.date(2026, 11, 9), datetime.date(2027, 1, 29))


def test_calendar_section_filter_excludes_noise():
    # "Noise" row is in section "Other" and must be ignored.
    w = resolve_period_token(
        "current-pi",
        ctx(config=_cal_config(), load_calendar=_pi_calendar_loader),
    )
    assert w[0].year == 2026 and w[0].month == 11


def test_calendar_miss_defaults_to_future_with_warning():
    warnings = []
    # Reference between PI26-11 (ends Nov 6) and PI27-01 (starts Nov 9):
    # Nov 7 2026 is a gap → default on_miss=future → PI27-01.
    c = ResolutionContext(
        today=datetime.date(2026, 11, 7),
        config=_cal_config(),
        srcdir="/src", docdir="doc",
        load_calendar=_pi_calendar_loader,
    )
    w = resolve_period_token("current-pi", c, warn=warnings.append)
    assert w == (datetime.date(2026, 11, 9), datetime.date(2027, 1, 29))
    assert warnings and "upcoming" in warnings[0]


def test_calendar_miss_past_fallback():
    warnings = []
    c = ResolutionContext(
        today=datetime.date(2026, 11, 7),
        config=_cal_config(on_miss="past"),
        srcdir="/src", docdir="doc",
        load_calendar=_pi_calendar_loader,
    )
    w = resolve_period_token("current-pi", c, warn=warnings.append)
    assert w == (datetime.date(2026, 8, 31), datetime.date(2026, 11, 6))
    assert warnings and "most recent" in warnings[0]


def test_calendar_miss_error():
    c = ResolutionContext(
        today=datetime.date(2026, 11, 7),
        config=_cal_config(on_miss="error"),
        srcdir="/src", docdir="doc",
        load_calendar=_pi_calendar_loader,
    )
    with pytest.raises(PeriodExprError):
        resolve_period_token("current-pi", c)


def test_calendar_reference_override():
    # Anchor the calendar to now()+2 months → Feb 15 2027 → inside PI27-04.
    c = ResolutionContext(
        today=TODAY,
        config=_cal_config(reference="now()+2 months"),
        srcdir="/src", docdir="doc",
        load_calendar=_pi_calendar_loader,
    )
    w = resolve_period_token("current-pi", c)
    assert w == (datetime.date(2027, 2, 1), datetime.date(2027, 4, 9))


def test_calendar_bare_string_spec():
    cfg = {"period_calendars": {"current-pi": "pi.csv"}}
    # No section filter → the Jan "Noise" row is also considered, but Dec 15
    # only falls inside PI27-01, so the result is unchanged.
    w = resolve_period_token(
        "current-pi",
        ctx(config=cfg, load_calendar=_pi_calendar_loader),
    )
    assert w == (datetime.date(2026, 11, 9), datetime.date(2027, 1, 29))


def test_calendar_case_insensitive_keyword():
    w = resolve_period_token(
        "Current-PI",
        ctx(config=_cal_config(), load_calendar=_pi_calendar_loader),
    )
    assert w is not None


# ---------------------------------------------------------------------------
# Resolver hooks
# ---------------------------------------------------------------------------

def test_hook_override(monkeypatch):
    import types, sys

    mod = types.ModuleType("fake_roadmap_hooks")

    def fiscal(token, c):
        if token == "fy":
            return (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31))
        return None

    mod.fiscal = fiscal
    sys.modules["fake_roadmap_hooks"] = mod
    try:
        cfg = {"period_resolver_hooks": ["fake_roadmap_hooks.fiscal"]}
        w = resolve_period_token("fy", ctx(config=cfg))
        assert w == (datetime.date(2026, 4, 1), datetime.date(2027, 3, 31))
    finally:
        del sys.modules["fake_roadmap_hooks"]


def test_hook_returns_none_falls_through(monkeypatch):
    import types, sys

    mod = types.ModuleType("fake_roadmap_hooks2")
    mod.noop = lambda token, c: None
    monkeypatch.setitem(sys.modules, "fake_roadmap_hooks2", mod)
    cfg = {"period_resolver_hooks": ["fake_roadmap_hooks2.noop"]}
    # Falls through to calendar-math.
    assert resolve_period_token("current-year", ctx(config=cfg)) is not None


# ---------------------------------------------------------------------------
# D1. Year unit in relative expressions
# ---------------------------------------------------------------------------

def test_relative_year_unit():
    """D1: 'year' unit in relative expressions is correctly handled."""
    # now() + 1 year from 2026-12-15 → 2027-12-15
    c = ctx()
    w = resolve_period_token("now() + 1 year", c)
    assert w == (datetime.date(2027, 12, 15), datetime.date(2027, 12, 15))

    # today - 2 years from 2026-12-15 → 2024-12-15
    w2 = resolve_period_token("today - 2 years", c)
    assert w2 == (datetime.date(2024, 12, 15), datetime.date(2024, 12, 15))


# ---------------------------------------------------------------------------
# D2. on_miss=future but no future rows → falls back to most recent past
# ---------------------------------------------------------------------------

def test_calendar_on_miss_future_no_future_rows():
    """D2: reference AFTER the last period with on_miss='future' → most recent past."""
    warnings = []
    # Reference date 2028-01-01 is after all PI rows → fall back to most recent past.
    c = ResolutionContext(
        today=datetime.date(2028, 1, 1),
        config=_cal_config(on_miss="future"),
        srcdir="/src", docdir="doc",
        load_calendar=_pi_calendar_loader,
    )
    w = resolve_period_token("current-pi", c, warn=warnings.append)
    # Most recent past in PI Rhythm is PI27-04 (ends 2027-04-09)
    assert w == (datetime.date(2027, 2, 1), datetime.date(2027, 4, 9))
    assert warnings and "most recent" in warnings[0]


# ---------------------------------------------------------------------------
# D3. on_miss=past but no past rows → falls back to next upcoming
# ---------------------------------------------------------------------------

def test_calendar_on_miss_past_no_past_rows():
    """D3: reference BEFORE the first period with on_miss='past' → next upcoming."""
    warnings = []
    # Reference date 2026-01-01 is before all PI Rhythm rows.
    c = ResolutionContext(
        today=datetime.date(2026, 1, 1),
        config=_cal_config(on_miss="past"),
        srcdir="/src", docdir="doc",
        load_calendar=_pi_calendar_loader,
    )
    w = resolve_period_token("current-pi", c, warn=warnings.append)
    # Next upcoming is PI26-11 (starts 2026-08-31)
    assert w == (datetime.date(2026, 8, 31), datetime.date(2026, 11, 6))
    assert warnings and "upcoming" in warnings[0]


# ---------------------------------------------------------------------------
# D4. Missing 'file' key in calendar spec
# ---------------------------------------------------------------------------

def test_calendar_missing_file_key():
    """D4: a spec dict without 'file' raises PeriodExprError."""
    cfg = {"period_calendars": {"current-pi": {"section": "PI Rhythm"}}}
    with pytest.raises(PeriodExprError, match="'file'"):
        resolve_period_token(
            "current-pi",
            ctx(config=cfg, load_calendar=_pi_calendar_loader),
        )


# ---------------------------------------------------------------------------
# D5. Invalid on_miss value
# ---------------------------------------------------------------------------

def test_calendar_invalid_on_miss_value():
    """D5: on_miss='nearest' raises PeriodExprError."""
    cfg = {"period_calendars": {"current-pi": {"file": "pi.csv", "on_miss": "nearest"}}}
    with pytest.raises(PeriodExprError, match="on_miss"):
        resolve_period_token(
            "current-pi",
            ctx(config=cfg, load_calendar=_pi_calendar_loader),
        )


# ---------------------------------------------------------------------------
# D6. Invalid reference expression
# ---------------------------------------------------------------------------

def test_calendar_invalid_reference_expression():
    """D6: reference='not-a-date' raises PeriodExprError."""
    cfg = {"period_calendars": {"current-pi": {"file": "pi.csv", "reference": "not-a-date"}}}
    with pytest.raises(PeriodExprError, match="reference"):
        resolve_period_token(
            "current-pi",
            ctx(config=cfg, load_calendar=_pi_calendar_loader),
        )


# ---------------------------------------------------------------------------
# D7. load_calendar=None raises PeriodExprError
# ---------------------------------------------------------------------------

def test_calendar_no_loader_raises():
    """D7: a configured calendar keyword with load_calendar=None raises PeriodExprError."""
    with pytest.raises(PeriodExprError, match="no calendar loader"):
        resolve_period_token(
            "current-pi",
            ctx(config=_cal_config(), load_calendar=None),
        )


# ---------------------------------------------------------------------------
# D8. Section filter matches no rows
# ---------------------------------------------------------------------------

def test_calendar_empty_after_section_filter():
    """D8: a section filter matching no rows raises PeriodExprError."""
    cfg = {"period_calendars": {"current-pi": {"file": "pi.csv", "section": "NonExistent"}}}
    with pytest.raises(PeriodExprError, match="no rows found"):
        resolve_period_token(
            "current-pi",
            ctx(config=cfg, load_calendar=_pi_calendar_loader),
        )


# ---------------------------------------------------------------------------
# D9. business_days integer out of range
# ---------------------------------------------------------------------------

def test_business_days_out_of_range_integer():
    """D9: {"business_days": [7]} raises PeriodExprError."""
    with pytest.raises(PeriodExprError, match="0..6"):
        business_weekdays_from_config({"business_days": [7]})


# ---------------------------------------------------------------------------
# D10. add_business_days with empty frozenset
# ---------------------------------------------------------------------------

def test_business_days_empty_frozenset():
    """D10: add_business_days(d, 1, frozenset()) raises PeriodExprError."""
    d = datetime.date(2026, 12, 15)
    with pytest.raises(PeriodExprError, match="at least one business weekday"):
        add_business_days(d, 1, frozenset())


# ---------------------------------------------------------------------------
# D11. Hook colon syntax ("module:attr")
# ---------------------------------------------------------------------------

def test_hook_colon_syntax(monkeypatch):
    """D11: a 'module:attr' hook path resolves and is called correctly."""
    import types, sys

    mod = types.ModuleType("fake_colon_mod")
    def my_hook(token, c):
        if token == "colon-test":
            return (datetime.date(2027, 1, 1), datetime.date(2027, 3, 31))
        return None
    mod.my_hook = my_hook
    monkeypatch.setitem(sys.modules, "fake_colon_mod", mod)

    cfg = {"period_resolver_hooks": ["fake_colon_mod:my_hook"]}
    w = resolve_period_token("colon-test", ctx(config=cfg))
    assert w == (datetime.date(2027, 1, 1), datetime.date(2027, 3, 31))


# ---------------------------------------------------------------------------
# D12. Hook returning a bare datetime.date → zero-width window
# ---------------------------------------------------------------------------

def test_hook_returns_date(monkeypatch):
    """D12: a hook returning a bare datetime.date is coerced to a zero-width window."""
    import types, sys

    mod = types.ModuleType("fake_date_hook")
    mod.hook = lambda token, c: datetime.date(2027, 6, 1) if token == "d-hook" else None
    monkeypatch.setitem(sys.modules, "fake_date_hook", mod)

    cfg = {"period_resolver_hooks": ["fake_date_hook.hook"]}
    w = resolve_period_token("d-hook", ctx(config=cfg))
    assert w == (datetime.date(2027, 6, 1), datetime.date(2027, 6, 1))


# ---------------------------------------------------------------------------
# D13. Hook returning bad type raises PeriodExprError
# ---------------------------------------------------------------------------

def test_hook_bad_return_raises(monkeypatch):
    """D13: a hook returning a string raises PeriodExprError."""
    import types, sys

    mod = types.ModuleType("fake_bad_hook")
    mod.hook = lambda token, c: "not-a-date"
    monkeypatch.setitem(sys.modules, "fake_bad_hook", mod)

    cfg = {"period_resolver_hooks": ["fake_bad_hook.hook"]}
    with pytest.raises(PeriodExprError, match="unsupported value"):
        resolve_period_token("anything", ctx(config=cfg))


# ---------------------------------------------------------------------------
# D14. Hook invalid path (no module part)
# ---------------------------------------------------------------------------

def test_hook_invalid_path():
    """D14: a hook path with no module part (e.g. 'myfunc') raises PeriodExprError."""
    cfg = {"period_resolver_hooks": ["myfunc"]}
    with pytest.raises(PeriodExprError, match="invalid resolver hook path"):
        resolve_period_token("anything", ctx(config=cfg))


# ---------------------------------------------------------------------------
# D15. Hook pointing to a non-callable raises PeriodExprError
# ---------------------------------------------------------------------------

def test_hook_noncallable_attr(monkeypatch):
    """D15: a hook path pointing to a non-callable raises PeriodExprError."""
    import types, sys

    mod = types.ModuleType("fake_noncallable")
    mod.not_a_function = 42  # not callable
    monkeypatch.setitem(sys.modules, "fake_noncallable", mod)

    cfg = {"period_resolver_hooks": ["fake_noncallable.not_a_function"]}
    with pytest.raises(PeriodExprError, match="not a callable"):
        resolve_period_token("anything", ctx(config=cfg))


# ---------------------------------------------------------------------------
# D16. Empty token returns None
# ---------------------------------------------------------------------------

def test_empty_token():
    """D16: resolve_period_token('', ctx()) returns None."""
    assert resolve_period_token("", ctx()) is None
    assert resolve_period_token("   ", ctx()) is None


# ---------------------------------------------------------------------------
# D17. match key with invalid value raises PeriodExprError (A1 test)
# ---------------------------------------------------------------------------

def test_match_invalid_value():
    """D17: a calendar spec with 'match': 'overlaps' raises PeriodExprError."""
    cfg = {"period_calendars": {"current-pi": {"file": "pi.csv", "match": "overlaps"}}}
    with pytest.raises(PeriodExprError, match="only 'contains' is currently implemented"):
        resolve_period_token(
            "current-pi",
            ctx(config=cfg, load_calendar=_pi_calendar_loader),
        )


# ---------------------------------------------------------------------------
# Period references in CSV start/end cells (resolve_cell_edge / is_period_ref)
# ---------------------------------------------------------------------------

from doxtr_roadmap.period_expr import is_period_ref, resolve_cell_edge


def test_is_period_ref():
    assert is_period_ref("@PI27-01")
    assert is_period_ref("  @PI27-01  ")
    assert is_period_ref("@current-pi")
    assert not is_period_ref("2027-01-05")
    assert not is_period_ref("PI27-01")
    assert not is_period_ref("")
    assert not is_period_ref(None)


def test_resolve_cell_edge_literal_iso():
    # A literal ISO date behind the sigil resolves to itself for both edges.
    assert resolve_cell_edge("@2027-01-05", "start", ctx()) == "2027-01-05"
    assert resolve_cell_edge("@2027-01-05", "end", ctx()) == "2027-01-05"


def test_resolve_cell_edge_name_lookup_edges():
    # A plain period name is resolved via the injected name_lookup, and the
    # correct edge is selected per the `edge` argument.
    window = (datetime.date(2026, 11, 9), datetime.date(2027, 1, 29))

    def _lookup(name):
        return window if name.strip().lower() == "pi27-01" else None

    assert resolve_cell_edge(
        "@PI27-01", "start", ctx(), name_lookup=_lookup
    ) == "2026-11-09"
    assert resolve_cell_edge(
        "@PI27-01", "end", ctx(), name_lookup=_lookup
    ) == "2027-01-29"


def test_resolve_cell_edge_calendar_keyword():
    # @current-pi resolves through the configured period_calendars.
    cfg = {"period_calendars": {"current-pi": {"file": "pi.csv"}}}
    c = ctx(config=cfg, load_calendar=_pi_calendar_loader)
    # TODAY (2026-12-15) falls inside PI27-01 (2026-11-09..2027-01-29).
    assert resolve_cell_edge("@current-pi", "start", c) == "2026-11-09"
    assert resolve_cell_edge("@current-pi", "end", c) == "2027-01-29"


def test_resolve_cell_edge_unknown_raises():
    with pytest.raises(ValueError, match="unknown period reference"):
        resolve_cell_edge("@does-not-exist", "start", ctx())


def test_resolve_cell_edge_empty_ref_raises():
    with pytest.raises(ValueError, match="empty period reference"):
        resolve_cell_edge("@", "start", ctx())


def test_resolve_cell_edge_bad_edge_raises():
    with pytest.raises(ValueError, match="edge must be"):
        resolve_cell_edge("@2027-01-05", "middle", ctx())


def test_resolve_cell_edge_calendar_math():
    # current-quarter for TODAY (2026-12-15) -> Q4 2026.
    assert resolve_cell_edge("@current-quarter", "start", ctx()) == "2026-10-01"
    assert resolve_cell_edge("@current-quarter", "end", ctx()) == "2026-12-31"


def test_resolve_cell_edge_relative_math():
    # now()+2 weeks from 2026-12-15 -> 2026-12-29 (zero-width window: both
    # edges are the same date).
    assert resolve_cell_edge("@now()+2 weeks", "start", ctx()) == "2026-12-29"
    assert resolve_cell_edge("@now()+2 weeks", "end", ctx()) == "2026-12-29"


def test_resolve_cell_edge_space_after_sigil():
    # A space between the sigil and the token is tolerated (both are stripped).
    assert resolve_cell_edge("@ 2027-01-05", "start", ctx()) == "2027-01-05"
