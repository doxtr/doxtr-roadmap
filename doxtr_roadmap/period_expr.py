"""Dynamic period-expression resolution for the ``.. roadmap::`` directive.

This module turns *period expression tokens* — the individual comma-separated
values a user writes in ``:period:``, ``:start:`` and ``:end:`` — into concrete
date windows.  It is the single seam through which "dynamic" periods such as
``current-pi``, ``current-quarter`` or ``now()-63 businessdays`` are expanded
before :func:`generator.resolve_window` runs.

Design
------
A *token* is resolved by trying, in order:

1. **A literal ISO date** (``YYYY-MM-DD``) — returned verbatim as a
   zero-width window ``(date, date)``.  This is checked first so the existing
   behaviour of ``:start:`` / ``:end:`` is never altered.
2. **User resolver hooks** (``doxtr_roadmap_period_resolver_hooks``) — dotted
   paths to callables ``(token, ctx) -> (start, end) | date | None``.  Trying
   these first (after literal dates) lets users *override* any built-in.
3. **CSV-backed calendars** (``doxtr_roadmap_period_calendars``) — a mapping
   of trigger keyword → calendar spec.  The keyword's calendar file is loaded,
   optionally filtered to one section, and the row whose window brackets a
   reference date is selected.
4. **Built-in calendar-math resolvers** — ``current-year``,
   ``current-quarter``, ``current-month``, ``current-week``, ``today`` and any
   relative expression (``now() ± N <unit>`` / ``today ± N <unit>``).
5. **Fall through** — the token is returned untouched so the caller treats it
   as a plain CSV task/period name (the historical behaviour).  This keeps all
   existing roadmaps working with zero configuration.

Nothing in this module imports Sphinx or docutils; it takes an explicit
*context* object so it stays independently unit-testable.

Security
--------
Relative-date expressions are parsed by a small hand-written tokenizer /
grammar, **not** :func:`eval`.  There is no attribute access, no imports and
no arbitrary call surface, matching the security posture of
:mod:`doxtr_roadmap.safe_query`.
"""

from __future__ import annotations

import datetime
import importlib
import os
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

# A resolved window: (start, end).  Both inclusive; a single date yields
# (date, date).
Window = Tuple[datetime.date, datetime.date]


class PeriodExprError(Exception):
    """Raised when a period expression is syntactically valid for a resolver
    but cannot be satisfied (e.g. a CSV calendar file is missing, or a
    relative expression uses an unknown unit).

    A token that simply is not claimed by any resolver does *not* raise; it
    falls through to be treated as a plain CSV task name.
    """


@dataclass
class ResolutionContext:
    """Everything a resolver needs, passed explicitly for testability.

    Parameters
    ----------
    today:
        The reference "now" date.  Injectable so tests are deterministic and
        so a per-directive / per-calendar ``reference`` override can supply a
        different anchor.
    config:
        The effective merged config dict (see :mod:`config_defaults`).  Used to
        read ``period_calendars``, ``period_resolver_hooks`` and the
        business-day weekday mask.
    srcdir:
        Sphinx source root as a string, used to resolve calendar file paths.
    docdir:
        Directory of the current document (relative to *srcdir*), tried first
        when resolving a calendar file path.
    note_dependency:
        Optional callable ``(abspath: str) -> None`` used to register loaded
        calendar files as build dependencies so edits trigger a rebuild.
    load_calendar:
        Optional callable ``(abspath: str) -> list[(name, start, end[, section])]``
        used to parse a calendar CSV.  Injectable so tests need not touch the
        CSV parser; the directive supplies the real loader.
    """

    today: datetime.date
    config: dict = field(default_factory=dict)
    srcdir: Optional[str] = None
    docdir: Optional[str] = None
    note_dependency: Optional[Callable[[str], None]] = None
    load_calendar: Optional[Callable[[str], List[Tuple]]] = None


# ---------------------------------------------------------------------------
# Business-day arithmetic
# ---------------------------------------------------------------------------

# Map weekday names to Python's ``date.weekday()`` numbering (Mon=0 .. Sun=6).
_WEEKDAY_NAMES = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "weds": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Default working week: Monday–Friday.
_DEFAULT_BUSINESS_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


def business_weekdays_from_config(config: dict) -> frozenset:
    """Return the set of weekday integers (Mon=0 .. Sun=6) that count as
    business days, read from ``config["business_days"]``.

    Accepts, in ``config["business_days"]``:

    * ``None`` / missing → Monday–Friday (the default).
    * A list/tuple/set of weekday names (case-insensitive, full or common
      abbreviations), e.g. ``["monday", "wednesday", "saturday"]``.
    * A list/tuple/set of integers ``0..6`` (Mon=0), e.g. ``[0, 2, 5]``.

    Unknown names raise :class:`PeriodExprError` so a typo in ``conf.py`` is
    surfaced loudly rather than silently producing wrong business-day math.
    """
    raw = config.get("business_days")
    if not raw:
        return _DEFAULT_BUSINESS_WEEKDAYS
    result = set()
    for entry in raw:
        if isinstance(entry, int):
            if 0 <= entry <= 6:
                result.add(entry)
            else:
                raise PeriodExprError(
                    f"business_days integer must be 0..6 (Mon=0), got {entry!r}"
                )
        else:
            key = str(entry).strip().lower()
            if key not in _WEEKDAY_NAMES:
                raise PeriodExprError(
                    f"unknown business_days weekday name {entry!r}; "
                    f"use full names or common abbreviations "
                    f"(monday, tue, weds, …) or integers 0..6"
                )
            result.add(_WEEKDAY_NAMES[key])
    if not result:
        return _DEFAULT_BUSINESS_WEEKDAYS
    return frozenset(result)


def add_business_days(
    anchor: datetime.date,
    n: int,
    business_weekdays: frozenset = _DEFAULT_BUSINESS_WEEKDAYS,
) -> datetime.date:
    """Return *anchor* shifted by *n* business days.

    Positive *n* moves forward, negative *n* moves backward.  Only weekdays in
    *business_weekdays* are counted; non-business days are skipped without
    consuming from *n*.  ``n == 0`` returns *anchor* unchanged even if it is a
    non-business day (no snapping).

    Works for any custom working-week definition, e.g. a Mon/Wed/Sat week.
    """
    if n == 0:
        return anchor
    if not business_weekdays:
        # Degenerate: no business days at all — cannot make progress.
        raise PeriodExprError(
            "business-day arithmetic requires at least one business weekday"
        )
    step = 1 if n > 0 else -1
    remaining = abs(n)
    d = anchor
    one = datetime.timedelta(days=1)
    while remaining > 0:
        d = d + (one if step > 0 else -one)
        if d.weekday() in business_weekdays:
            remaining -= 1
    return d


# ---------------------------------------------------------------------------
# Relative / calendar-math parsing
# ---------------------------------------------------------------------------

# Relative expression grammar:
#   (now() | today) ([+-] N unit)*
# unit ∈ {day(s), week(s), month(s), year(s), businessday(s)/business-day(s)}
_ANCHOR_RE = re.compile(r"^\s*(now\(\)|today)\s*", re.IGNORECASE)
_TERM_RE = re.compile(
    r"([+-])\s*(\d+)\s*"
    r"(business[\s-]?days?|businessdays?|days?|weeks?|months?|years?)\s*",
    re.IGNORECASE,
)


def _add_months(d: datetime.date, months: int) -> datetime.date:
    """Add *months* calendar months to *d*, clamping the day to month length."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    # Clamp day (e.g. Jan 31 + 1 month → Feb 28/29).
    day = min(d.day, _days_in_month(year, month))
    return datetime.date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in the given *year*/*month*."""
    if month == 12:
        nxt = datetime.date(year + 1, 1, 1)
    else:
        nxt = datetime.date(year, month + 1, 1)
    return (nxt - datetime.date(year, month, 1)).days


def _quarter_window(d: datetime.date) -> Window:
    q = (d.month - 1) // 3            # 0..3
    start_month = q * 3 + 1
    start = datetime.date(d.year, start_month, 1)
    end_month = start_month + 2
    end = datetime.date(d.year, end_month, _days_in_month(d.year, end_month))
    return (start, end)


def _year_window(d: datetime.date) -> Window:
    return (datetime.date(d.year, 1, 1), datetime.date(d.year, 12, 31))


def _month_window(d: datetime.date) -> Window:
    start = datetime.date(d.year, d.month, 1)
    end = datetime.date(d.year, d.month, _days_in_month(d.year, d.month))
    return (start, end)


def _week_window(d: datetime.date) -> Window:
    """ISO week window: Monday through Sunday containing *d*."""
    monday = d - datetime.timedelta(days=d.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return (monday, sunday)


# Dispatch table mapping built-in calendar keywords to window functions.
_CALENDAR_PERIOD_DISPATCH = {
    "current-year": _year_window,
    "current-quarter": _quarter_window,
    "current-month": _month_window,
    "current-week": _week_window,
}

def try_parse_relative_date(
    token: str,
    ctx: ResolutionContext,
) -> Optional[datetime.date]:
    """Parse a relative expression to a single date, or return ``None``.

    Grammar (case-insensitive, whitespace-tolerant)::

        (now() | today) ([+-] <int> <unit>)*

    where ``<unit>`` is one of ``day(s)``, ``week(s)``, ``month(s)``,
    ``year(s)``, ``businessday(s)`` (also spelled ``business day`` /
    ``business-day``).  ``now()`` and ``today`` are synonyms for the reference
    date in *ctx*.

    Examples::

        now()
        today
        now() - 63 days
        today + 2 weeks
        now() - 45 businessdays
        now() + 1 month - 3 businessdays

    Returns the computed :class:`datetime.date`, or ``None`` if *token* does
    not begin with a recognised anchor (so the caller can try other
    resolvers).  A syntactically-anchored but malformed tail raises
    :class:`PeriodExprError`.
    """
    m = _ANCHOR_RE.match(token)
    if not m:
        return None

    d = ctx.today
    rest = token[m.end():]
    business_weekdays = business_weekdays_from_config(ctx.config)

    pos = 0
    while pos < len(rest):
        if rest[pos].isspace():
            pos += 1
            continue
        term = _TERM_RE.match(rest, pos)
        if not term:
            raise PeriodExprError(
                f"invalid relative period expression near {rest[pos:]!r} "
                f"in {token!r}"
            )
        sign = 1 if term.group(1) == "+" else -1
        amount = sign * int(term.group(2))
        unit = term.group(3).lower().replace(" ", "").replace("-", "")
        if unit.startswith("businessday"):
            d = add_business_days(d, amount, business_weekdays)
        elif unit.startswith("day"):
            d = d + datetime.timedelta(days=amount)
        elif unit.startswith("week"):
            d = d + datetime.timedelta(weeks=amount)
        elif unit.startswith("month"):
            d = _add_months(d, amount)
        elif unit.startswith("year"):
            d = _add_months(d, amount * 12)
        else:  # pragma: no cover - regex already constrains the unit
            raise PeriodExprError(f"unknown period unit {unit!r} in {token!r}")
        pos = term.end()

    return d


def try_resolve_calendar_math(
    token: str,
    ctx: ResolutionContext,
) -> Optional[Window]:
    """Resolve built-in calendar-math tokens to a window, or return ``None``.

    Handles the fixed keywords ``current-year``, ``current-quarter``,
    ``current-month``, ``current-week`` and any relative expression accepted by
    :func:`try_parse_relative_date` (which yields a zero-width window).
    """
    key = token.strip().lower()
    fn = _CALENDAR_PERIOD_DISPATCH.get(key)
    if fn:
        return fn(ctx.today)

    single = try_parse_relative_date(token, ctx)
    if single is not None:
        return (single, single)
    return None


# ---------------------------------------------------------------------------
# CSV-backed calendars
# ---------------------------------------------------------------------------

# How to pick the "active" row of a calendar and what to do when the reference
# date lands in a gap between rows.
_VALID_ON_MISS = {"future", "past", "error"}


def _pick_neighbor(
    rows: list,
    key: str,
    reference: datetime.date,
    kind: str,
    warn: Optional[Callable[[str], None]],
) -> Optional[Window]:
    """Return the nearest *kind* row window or its double-fallback, emitting a warning.

    *kind* must be ``"upcoming"`` or ``"recent"``.
    ``"upcoming"`` prefers future rows (falls back to the most recent past).
    ``"recent"`` prefers past rows (falls back to the next upcoming).
    Returns ``None`` when *rows* is empty (caller raises the hard error).
    """
    future = sorted((w for w in rows if w[1] > reference), key=lambda w: w[1])
    past = sorted((w for w in rows if w[2] < reference), key=lambda w: w[2], reverse=True)

    if kind == "upcoming":
        if future:
            if warn:
                warn(
                    f"[doxtr-roadmap] period {key!r}: {reference.isoformat()} "
                    f"is not inside any period; using the next upcoming period "
                    f"({future[0][0]!r})."
                )
            return (future[0][1], future[0][2])
        if past:
            if warn:
                warn(
                    f"[doxtr-roadmap] period {key!r}: {reference.isoformat()} "
                    f"is after the last period; using the most recent period "
                    f"({past[0][0]!r})."
                )
            return (past[0][1], past[0][2])
    else:  # kind == "recent"
        if past:
            if warn:
                warn(
                    f"[doxtr-roadmap] period {key!r}: {reference.isoformat()} "
                    f"is not inside any period; using the most recent past "
                    f"period ({past[0][0]!r})."
                )
            return (past[0][1], past[0][2])
        if future:
            if warn:
                warn(
                    f"[doxtr-roadmap] period {key!r}: {reference.isoformat()} "
                    f"is before the first period; using the next upcoming "
                    f"period ({future[0][0]!r})."
                )
            return (future[0][1], future[0][2])
    return None


def _resolve_calendar_file(spec_file: str, ctx: ResolutionContext) -> str:
    """Resolve a calendar file path to a usable path for the loader.

    Tries, in order: document-relative (``<srcdir>/<docdir>/<file>``) then
    srcdir-relative (``<srcdir>/<file>``); an absolute path is used verbatim.
    Returns the first candidate that exists on disk.  If none exists, the
    best-effort candidate (document-relative when a srcdir is known, else the
    raw spec) is returned so that an injected or virtual ``load_calendar`` can
    still handle it; a disk-backed loader will then raise a clear error.
    """
    if os.path.isabs(spec_file):
        return spec_file

    candidates = []
    if ctx.srcdir and ctx.docdir:
        candidates.append(os.path.join(ctx.srcdir, ctx.docdir, spec_file))
    if ctx.srcdir:
        candidates.append(os.path.join(ctx.srcdir, spec_file))
    candidates.append(spec_file)  # last resort: cwd-relative

    for cand in candidates:
        if os.path.isfile(cand):
            return os.path.abspath(cand)

    # Nothing on disk: return the best-effort candidate and let the loader
    # decide (injected loaders may ignore the path; disk loaders will raise).
    return candidates[0]


def try_resolve_named_calendar(
    token: str,
    ctx: ResolutionContext,
    warn: Optional[Callable[[str], None]] = None,
) -> Optional[Window]:
    """Resolve a CSV-calendar trigger keyword to a window, or return ``None``.

    The keyword is looked up in ``ctx.config["period_calendars"]`` (a mapping
    of ``keyword -> spec``).  A *spec* is a dict with keys:

    ``file`` (required)
        Path to the calendar CSV.  Resolved relative to the document, then
        srcdir.
    ``section`` (optional)
        If set, only rows in this CSV section are considered.
    ``match`` (optional, default ``"contains"``)
        How a row's window is compared against the reference date:
        ``"contains"`` selects the row whose ``[start, end]`` brackets the
        reference date.
    ``on_miss`` (optional, default ``"future"``)
        What to do when no row contains the reference date: ``"future"``
        selects the next upcoming row, ``"past"`` selects the most recent
        past row, ``"error"`` raises.  A warning is always emitted on a miss
        for the ``future`` / ``past`` fallbacks.
    ``reference`` (optional)
        A date expression (any value accepted by
        :func:`try_parse_relative_date`, or an ISO date) used as the reference
        date instead of "today".  Lets a calendar be anchored to, say,
        ``now()+2 weeks``.

    Returns the selected row's ``(start, end)`` window, or ``None`` if *token*
    is not a configured calendar keyword.
    """
    calendars = (ctx.config or {}).get("period_calendars") or {}
    key = token.strip()
    spec = calendars.get(key)
    if spec is None:
        # Case-insensitive fallback so "current-pi" and "Current-PI" both work.
        lower = key.lower()
        for k, v in calendars.items():
            if k.lower() == lower:
                spec = v
                break
    if spec is None:
        return None

    if isinstance(spec, str):
        spec = {"file": spec}
    if not isinstance(spec, dict) or "file" not in spec:
        raise PeriodExprError(
            f"period calendar {key!r} must be a dict with a 'file' key "
            f"(got {spec!r})"
        )

    on_miss = str(spec.get("on_miss", "future")).lower()
    if on_miss not in _VALID_ON_MISS:
        raise PeriodExprError(
            f"period calendar {key!r}: on_miss must be one of "
            f"{sorted(_VALID_ON_MISS)}, got {on_miss!r}"
        )

    match_mode = str(spec.get("match", "contains")).lower()
    if match_mode != "contains":
        raise PeriodExprError(
            f"period calendar {key!r}: only 'contains' is currently implemented "
            f"for the 'match' key (got {match_mode!r})"
        )

    # Reference date for this calendar (defaults to ctx.today).
    reference = ctx.today
    ref_expr = spec.get("reference")
    if ref_expr:
        ref_date = try_parse_relative_date(str(ref_expr), ctx)
        if ref_date is None:
            try:
                ref_date = datetime.date.fromisoformat(str(ref_expr))
            except ValueError:
                raise PeriodExprError(
                    f"period calendar {key!r}: invalid reference "
                    f"{ref_expr!r} (expected an ISO date or a relative "
                    f"expression like 'now()+2 weeks')"
                )
        reference = ref_date

    if ctx.load_calendar is None:
        raise PeriodExprError(
            f"period calendar {key!r} configured but no calendar loader is "
            f"available in this context"
        )

    abspath = _resolve_calendar_file(spec["file"], ctx)
    if ctx.note_dependency is not None:
        ctx.note_dependency(abspath)

    rows = ctx.load_calendar(abspath)  # list of (name, start, end[, section])

    section = spec.get("section")
    if section is not None:
        want = section.strip().lower()
        rows = [
            r for r in rows
            if len(r) > 3 and str(r[3]).strip().lower() == want
        ]

    # Normalise to (name, start, end) triples (loader may include section).
    norm = [(r[0], r[1], r[2]) for r in rows]
    if not norm:
        raise PeriodExprError(
            f"period calendar {key!r}: no rows found in {spec['file']!r}"
            + (f" for section {section!r}" if section else "")
        )

    # 1) Row that contains the reference date.
    containing = [w for w in norm if w[1] <= reference <= w[2]]
    if containing:
        # If several overlap, prefer the earliest-starting one for stability.
        chosen = min(containing, key=lambda w: (w[1], w[2]))
        return (chosen[1], chosen[2])

    # 2) Miss: reference date is in a gap (or before/after all rows).
    if on_miss == "error":
        raise PeriodExprError(
            f"period calendar {key!r}: reference date {reference.isoformat()} "
            f"falls outside every period in {spec['file']!r}"
        )

    kind = "upcoming" if on_miss == "future" else "recent"
    result = _pick_neighbor(norm, key, reference, kind, warn)
    if result is not None:
        return result

    # Unreachable in practice (norm is non-empty), but fail loudly if reached.
    raise PeriodExprError(
        f"period calendar {key!r}: could not select a period for reference "
        f"date {reference.isoformat()}"
    )


# ---------------------------------------------------------------------------
# User resolver hooks
# ---------------------------------------------------------------------------

def _load_hook(dotted: str) -> Callable:
    """Import a ``module.attr`` dotted path and return the callable."""
    if ":" in dotted:
        mod_name, _, attr = dotted.partition(":")
    else:
        mod_name, _, attr = dotted.rpartition(".")
    if not mod_name or not attr:
        raise PeriodExprError(
            f"invalid resolver hook path {dotted!r}; expected 'module.callable'"
        )
    module = importlib.import_module(mod_name)
    fn = getattr(module, attr, None)
    if not callable(fn):
        raise PeriodExprError(
            f"resolver hook {dotted!r} is not a callable"
        )
    return fn


def _coerce_hook_result(result, token: str) -> Optional[Window]:
    """Normalise a hook return value to a ``Window`` or ``None``."""
    if result is None:
        return None
    if isinstance(result, datetime.date):
        return (result, result)
    if (
        isinstance(result, (tuple, list))
        and len(result) == 2
        and all(isinstance(x, datetime.date) for x in result)
    ):
        return (result[0], result[1])
    raise PeriodExprError(
        f"resolver hook returned an unsupported value for token {token!r}: "
        f"{result!r} (expected a date, a (start, end) date pair, or None)"
    )


def try_resolve_hooks(
    token: str,
    ctx: ResolutionContext,
) -> Optional[Window]:
    """Try each configured resolver hook in order; return the first window."""
    hooks = (ctx.config or {}).get("period_resolver_hooks") or []
    for dotted in hooks:
        fn = _load_hook(dotted)
        window = _coerce_hook_result(fn(token, ctx), token)
        if window is not None:
            return window
    return None


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def resolve_period_token(
    token: str,
    ctx: ResolutionContext,
    warn: Optional[Callable[[str], None]] = None,
) -> Optional[Window]:
    """Resolve a single period token to a ``(start, end)`` window.

    Resolution order (see module docstring):

    1. Literal ISO date → zero-width window.
    2. User resolver hooks.
    3. CSV-backed named calendars.
    4. Built-in calendar-math / relative expressions.
    5. ``None`` — token is not a dynamic expression; caller treats it as a
       plain CSV task/period name.

    *warn* is an optional callback used to surface non-fatal diagnostics
    (e.g. a calendar reference-date miss falling back to a neighbouring
    period).
    """
    tok = token.strip()
    if not tok:
        return None

    # 1) Literal ISO date.
    try:
        d = datetime.date.fromisoformat(tok)
        return (d, d)
    except ValueError:
        pass

    # 2) User hooks (override built-ins).
    window = try_resolve_hooks(tok, ctx)
    if window is not None:
        return window

    # 3) CSV-backed calendars.
    window = try_resolve_named_calendar(tok, ctx, warn=warn)
    if window is not None:
        return window

    # 4) Built-in calendar math / relative expressions.
    window = try_resolve_calendar_math(tok, ctx)
    if window is not None:
        return window

    # 5) Fall through — plain CSV name.
    return None
