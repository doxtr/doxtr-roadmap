"""Colour-expression resolution for doxtr_roadmap task colours.

A CSV ``color`` cell (after inheritance is resolved by
:func:`csv_parser._resolve_colors`) holds one of:

* ``None`` — use the roadmap default colour (``bar.done_color``).
* a raw ``#hex`` string — ``#RGB``, ``#RGBA``, ``#RRGGBB`` or ``#RRGGBBAA``.
* a semantic ``dd:`` expression understood by ``doxtr_pdf_theme_core``
  (e.g. ``dd:primary``, ``dd:#FFCC00:lighten:80``, ``dd:this:key``).

This module turns those expressions into concrete hex strings and derives the
matching bar *frame* colour, honouring dark mode:

* ``dd:`` expressions are resolved through theme-core's public colour engine
  against the *active* (light or dark) semantic palette.  When theme-core is
  not installed a warning is emitted (once per resolver) and the caller's
  default colour is used instead.
* Raw hex colours pass through unchanged in light mode and are soft-inverted
  (via theme-core's ``hex_dark_invert``) in dark mode so a literal accent stays
  legible on the dark page.  When theme-core is absent the hex is left as-is.

The frame colour is derived from the resolved done colour by lightening or
darkening it by a configurable delta (default 30%).  If the done colour is
already so dark that darkening would have little effect it is lightened
instead, and vice-versa, so the border always contrasts with the fill.

All heavy lifting is delegated to ``doxtr_pdf_theme_core`` when present; the
module degrades gracefully (identity transforms, default colours) when it is
not, so the extension keeps working without the theme installed.
"""

from sphinx.util import logging

logger = logging.getLogger(__name__)

#: Luminance threshold (0..1, WCAG relative luminance) above which a colour is
#: considered "light".  A light done colour is *darkened* to produce its frame;
#: a dark one is *lightened*.  0.5 is the natural midpoint.
_LUMINANCE_MIDPOINT = 0.5

#: Minimum RGB "distance" (sum of absolute channel deltas, 0..765) that a
#: derived frame must differ from its fill by.  When darkening a very dark fill
#: (or lightening a very light one) yields less change than this, the opposite
#: direction is used instead so the border always reads against the fill.
#: This encodes the "an 80%-black fill gets a lighter frame" requirement in
#: terms of the actual headroom left in the chosen direction.
_MIN_FRAME_DISTANCE = 24

#: Error sentinel returned by ``doxtr_pdf_theme_core.utils.resolve_color`` when
#: a ``dd:`` expression cannot be resolved (unknown palette key, unsupported
#: cross-config reference, …).  We detect this exact value to fall back to the
#: roadmap default colour rather than silently painting a bar bright red.  Kept
#: as a named constant so the coupling to theme-core's contract is greppable.
_THEME_CORE_ERROR_COLOR = "#ff0000"


def _theme_core():
    """Return the ``doxtr_pdf_theme_core`` module, or ``None`` when absent.

    Importing inside the function (rather than at module import time) keeps the
    optional dependency truly optional and lets tests monkeypatch the import.
    """
    try:
        import doxtr_pdf_theme_core as core
    except ImportError:
        return None
    return core


def _parse_rgb(hex_color):
    """Parse a hex colour string to ``((r, g, b), alpha_str)`` or ``None``.

    The single canonical hex parser used by every colour helper in this module
    (brightness adjustment, luminance, RGB distance) so hex handling lives in
    exactly one place and cannot drift between callers.

    Accepts ``#RGB``, ``#RGBA``, ``#RRGGBB`` and ``#RRGGBBAA`` (the leading
    ``#`` is optional; 3/4-digit forms are expanded).  The alpha channel, when
    present, is returned as its two-character hex string so callers that need
    to preserve it (e.g. brightness adjustment) can re-append it; callers that
    ignore alpha (luminance, distance) simply drop it.

    Parameters
    ----------
    hex_color:
        Hex colour string.

    Returns
    -------
    tuple | None
        ``((r, g, b), alpha_str)`` with integer channels in ``[0, 255]`` and
        *alpha_str* either a two-char hex string or ``""``; ``None`` when the
        input is empty or not a valid 6-digit (post-expansion) colour.
    """
    if not hex_color:
        return None
    clean = hex_color.lstrip("#")
    if len(clean) in (3, 4):
        clean = "".join(c * 2 for c in clean)
    alpha = ""
    if len(clean) == 8:
        alpha = clean[6:8]
        clean = clean[:6]
    if len(clean) != 6:
        return None
    try:
        r = int(clean[0:2], 16)
        g = int(clean[2:4], 16)
        b = int(clean[4:6], 16)
    except ValueError:
        return None
    return (r, g, b), alpha


def _adjust_brightness(hex_color: str, percentage: float):
    """Lighten (positive) or darken (negative) a hex colour by *percentage*.

    Prefers ``doxtr_pdf_theme_core.utils.adjust_hex_brightness`` when the theme
    is installed (so results match the rest of the PDF), and otherwise falls
    back to an equivalent pure-Python implementation using :func:`_parse_rgb`.
    This keeps automatic frame / undone derivation working even when theme-core
    is not present.

    The formula matches theme-core: for a lighten factor ``f = pct/100`` each
    channel becomes ``c + (255 - c) * f``; for darken (``f < 0``) it becomes
    ``c * (1 + f)``.  3/4/6/8-digit hex is accepted and an 8-digit alpha
    channel is preserved unchanged.

    Parameters
    ----------
    hex_color:
        Hex colour string (``#`` optional; 3/4/6/8 digits).
    percentage:
        Signed brightness adjustment in percent.

    Returns
    -------
    str | None
        Adjusted hex colour, or ``None`` for empty input.
    """
    core = _theme_core()
    if core is not None:
        try:
            from doxtr_pdf_theme_core.utils import adjust_hex_brightness
        except ImportError:
            adjust_hex_brightness = None
        if adjust_hex_brightness is not None:
            return adjust_hex_brightness(hex_color, percentage)
    # Pure-Python fallback (theme-core absent / older layout).
    parsed = _parse_rgb(hex_color)
    if parsed is None:
        return None
    (r, g, b), alpha = parsed
    factor = percentage / 100.0
    if factor > 0:
        r = r + (255 - r) * factor
        g = g + (255 - g) * factor
        b = b + (255 - b) * factor
    elif factor < 0:
        r = r * (1 + factor)
        g = g * (1 + factor)
        b = b * (1 + factor)
    r = max(0, min(255, int(round(r))))
    g = max(0, min(255, int(round(g))))
    b = max(0, min(255, int(round(b))))
    out = f"#{r:02X}{g:02X}{b:02X}"
    return out + alpha if alpha else out


def _merged_light_palette(config, core) -> dict:
    """Return the fully-merged *light* semantic palette for this build.

    theme-core's ``config.doxtr_semantic_palette`` config value holds only the
    *user's* overrides (it defaults to ``{}``); theme-core merges it with its
    built-in ``DOXTR_SEMANTIC_PALETTE`` core defaults and any theme-tier
    ``doxtr_theme_defaults['semantic_palette']`` internally, but never writes
    the merged result back to a public config attribute.  Reading the config
    value alone therefore misses standard keys such as ``primary`` unless the
    user re-declared them.

    This helper reproduces theme-core's light-palette merge order
    (core ← theme ← user, each with the ``dark`` sub-key stripped) so semantic
    expressions like ``dd:primary`` resolve against the same palette the rest
    of the PDF uses.  It degrades to the user config value (or ``{}``) when the
    core defaults cannot be imported (e.g. a future theme-core layout change).

    Parameters
    ----------
    config:
        The Sphinx ``config`` object.
    core:
        The ``doxtr_pdf_theme_core`` module.

    Returns
    -------
    dict
        The merged light semantic palette.
    """
    user_raw = getattr(config, "doxtr_semantic_palette", None) or {}
    theme_defaults = getattr(config, "doxtr_theme_defaults", None) or {}
    theme_raw = theme_defaults.get("semantic_palette", {}) or {}
    try:
        from doxtr_pdf_theme_core.core_config import DOXTR_SEMANTIC_PALETTE
        core_defaults = DOXTR_SEMANTIC_PALETTE
    except ImportError:
        core_defaults = getattr(core, "DOXTR_SEMANTIC_PALETTE", {}) or {}

    def _strip_dark(d):
        return {k: v for k, v in d.items() if k != "dark"}

    merged = dict(_strip_dark(core_defaults))
    merged.update(_strip_dark(theme_raw))
    merged.update(_strip_dark(user_raw))
    return merged


def _relative_luminance(hex_color: str) -> float:
    """Return the WCAG relative luminance (0..1) of a hex colour.

    Prefers ``doxtr_pdf_theme_core.utils._get_luminance`` when the theme is
    installed, so the light/dark frame-direction decision at
    :data:`_LUMINANCE_MIDPOINT` stays aligned with the luminance curve the rest
    of the PDF uses.  Falls back to an equivalent local WCAG implementation
    (via :func:`_parse_rgb`) when theme-core is absent.  Because
    ``_get_luminance`` is a private theme-core helper, it is accessed defensively
    (``getattr`` + fallback) rather than imported hard.

    Alpha (if present) is ignored.  Invalid input returns ``0.0`` (treated as
    fully dark) so the frame derivation still produces a sensible result.

    Parameters
    ----------
    hex_color:
        Hex colour string, with or without a leading ``#``; 3/4/6/8 digits.

    Returns
    -------
    float
        Relative luminance in ``[0.0, 1.0]``.
    """
    core = _theme_core()
    if core is not None:
        try:
            from doxtr_pdf_theme_core import utils as _core_utils
            fn = getattr(_core_utils, "_get_luminance", None)
        except ImportError:
            fn = None
        if fn is not None:
            try:
                return fn(hex_color)
            except Exception:
                pass  # fall through to the local implementation
    parsed = _parse_rgb(hex_color)
    if parsed is None:
        return 0.0
    (r8, g8, b8), _alpha = parsed
    r, g, b = r8 / 255.0, g8 / 255.0, b8 / 255.0

    def _lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _rgb_distance(hex_a: str, hex_b: str) -> int:
    """Return the summed absolute per-channel RGB difference of two hex colours.

    Alpha is ignored.  Range is ``0`` (identical) to ``765`` (black vs white).
    Invalid input contributes ``(0, 0, 0)`` for that colour.

    Parameters
    ----------
    hex_a, hex_b:
        Hex colour strings (3/4/6/8 digits, ``#`` optional).

    Returns
    -------
    int
        Summed absolute channel delta in ``[0, 765]``.
    """
    pa = _parse_rgb(hex_a)
    pb = _parse_rgb(hex_b)
    ra, ga, ba = pa[0] if pa else (0, 0, 0)
    rb, gb, bb = pb[0] if pb else (0, 0, 0)
    return abs(ra - rb) + abs(ga - gb) + abs(ba - bb)


def derive_frame_color(done_hex: str, delta_percent: float):
    """Derive a contrasting frame colour from a resolved done colour.

    The frame is the done colour lightened or darkened by *delta_percent*.  The
    direction is chosen for **headroom**:

    * A *light* done colour (relative luminance ``>= 0.5``) is **darkened**;
      a *dark* one is **lightened** — so the border reads as a shade of the
      fill rather than washing out.
    * If the chosen direction has too little headroom to make a visible
      difference (e.g. darkening a near-black fill, or lightening a near-white
      one produces almost the same colour), the *opposite* direction is used
      instead.  This implements the requirement that a fill which is already
      ≈80% black gets a *lighter* frame (and a near-white fill a darker one),
      because there is no room to go further in the natural direction.

    Parameters
    ----------
    done_hex:
        The resolved done/fill colour as a hex string.
    delta_percent:
        Brightness adjustment magnitude in percent (e.g. ``30``).  Non-positive
        or non-numeric values disable frame derivation (returns ``None``).

    Returns
    -------
    str | None
        The derived frame hex colour, or ``None`` when no frame should be
        emitted (invalid delta, or invalid input).  Brightness math uses
        theme-core when installed and a pure-Python fallback otherwise (see
        :func:`_adjust_brightness`), so a frame is derived even without
        theme-core.
    """
    try:
        delta = float(delta_percent)
    except (TypeError, ValueError):
        return None
    if delta <= 0 or not done_hex:
        return None

    # Natural direction by luminance: light fill → darken, dark fill → lighten.
    if _relative_luminance(done_hex) >= _LUMINANCE_MIDPOINT:
        primary, fallback = -delta, delta
    else:
        primary, fallback = delta, -delta

    primary_frame = _adjust_brightness(done_hex, primary)
    if primary_frame is None:
        return None
    # If the natural direction barely changed the colour (no headroom), flip.
    if _rgb_distance(primary_frame, done_hex) < _MIN_FRAME_DISTANCE:
        fallback_frame = _adjust_brightness(done_hex, fallback)
        if fallback_frame and _rgb_distance(fallback_frame, done_hex) >= _rgb_distance(
            primary_frame, done_hex
        ):
            return fallback_frame
    return primary_frame


def derive_undone_color(done_hex: str, delta_percent: float, dark_mode: bool):
    """Derive the *undone* (remaining) bar colour from the *done* colour.

    The undone colour is always *lighter* than the done colour in light mode
    and *darker* in dark mode, by ``delta_percent`` percent.  This keeps the
    completed and remaining portions of every bar in a consistent visual
    relationship regardless of the done colour.

    .. note::
        PlantUML gantt exposes only a single, *global* undone background
        (there is no per-task undone selector).  Callers therefore pass the
        global ``done_color`` here; the result applies to every bar's
        remaining portion.

    Parameters
    ----------
    done_hex:
        The global done/completed colour as a hex string.
    delta_percent:
        Brightness adjustment magnitude in percent (e.g. ``88.7``).
        Non-positive or non-numeric values disable derivation (returns
        ``None`` so the caller keeps the literal ``undone_color``).
    dark_mode:
        When ``True`` the undone colour is darkened; when ``False`` it is
        lightened.

    Returns
    -------
    str | None
        The derived undone hex colour, or ``None`` when derivation is disabled.
        Brightness math uses theme-core when installed and a pure-Python
        fallback otherwise (see :func:`_adjust_brightness`), so derivation works
        without theme-core.
    """
    try:
        delta = float(delta_percent)
    except (TypeError, ValueError):
        return None
    if delta <= 0 or not done_hex:
        return None
    # Dark mode → darken (negative); light mode → lighten (positive).
    signed = -delta if dark_mode else delta
    return _adjust_brightness(done_hex, signed)


class ColorResolver:
    """Resolve raw task colour expressions to ``(done_hex, frame_hex)`` pairs.

    A resolver captures the active palette / dark-mode context for one build so
    the generator can turn each task's inherited colour expression into two
    concrete hex colours.  Construct it via :func:`from_config` so it reads the
    theme-core palette and dark-mode state off the Sphinx config.

    Parameters
    ----------
    palette:
        The active semantic palette dict (light or dark), or ``{}``.
    page_bg:
        The active page background colour hex (used by ``dd:page`` /
        contrast operations), or ``None``.
    dark_active:
        Whether dark mode is active for this build.
    invert:
        Callable soft-inverting a hex colour for dark mode (``hex_dark_invert``
        when theme-core is present, else identity).
    frame_delta:
        Frame brightness delta in percent (see :func:`derive_frame_color`).
    core:
        The ``doxtr_pdf_theme_core`` module, or ``None`` when not installed.
    """

    def __init__(self, palette, page_bg, dark_active, invert, frame_delta, core):
        self._palette = palette or {}
        self._page_bg = page_bg
        self._dark_active = bool(dark_active)
        self._invert = invert or (lambda c: c)
        self._frame_delta = frame_delta
        self._core = core
        # Warn at most once per resolver when a dd: expression is used without
        # theme-core installed, to avoid flooding the build log.
        self._warned_no_core = False

    # -- construction ------------------------------------------------------

    @classmethod
    def from_config(cls, config, frame_delta):
        """Build a resolver from a Sphinx config object.

        Reads the active semantic palette and dark-mode context via theme-core's
        public helpers when the package is loaded, mirroring how
        :mod:`theme_adapter` resolves the effective bar colours.  Degrades to an
        empty palette / identity inversion when theme-core is absent, so
        ``dd:`` expressions warn-and-fall-back while raw hex still works.

        Parameters
        ----------
        config:
            The Sphinx ``config`` object.
        frame_delta:
            Frame brightness delta in percent.

        Returns
        -------
        ColorResolver
        """
        core = _theme_core()
        palette = {}
        page_bg = None
        dark_active = False
        invert = lambda c: c  # noqa: E731

        if core is not None:
            get_ctx = getattr(core, "get_dark_mode_context", None)
            ctx = None
            if get_ctx is not None:
                try:
                    ctx = get_ctx(config)
                except Exception:
                    logger.debug(
                        "[doxtr-roadmap] get_dark_mode_context failed during "
                        "colour resolver setup; using light palette",
                        exc_info=True,
                    )
                    ctx = None
            if ctx and ctx.get("active"):
                dark_active = True
                palette = ctx.get("palette") or {}
                page_bg = ctx.get("page_color")
                raw_invert = ctx.get("invert_color")
                if callable(raw_invert):
                    invert = raw_invert
            else:
                palette = _merged_light_palette(config, core)
                page_bg = palette.get("page")
                # Not dark: still expose hex_dark_invert if present (unused in
                # light mode, but keeps the attribute callable).
                invert = getattr(core, "hex_dark_invert", None) or invert

        return cls(palette, page_bg, dark_active, invert, frame_delta, core)

    # -- resolution --------------------------------------------------------

    def _resolve_expr(self, expr):
        """Resolve a single colour expression to a static hex string or ``None``.

        Returns ``None`` when the expression cannot be resolved (so the caller
        falls back to the roadmap default colour).

        Parameters
        ----------
        expr:
            A raw ``#hex`` string or ``dd:`` expression.
        """
        if not expr:
            return None
        expr = expr.strip()
        if not expr:
            return None

        if expr.startswith("#"):
            # Raw hex: invert in dark mode so a literal accent stays legible;
            # pass through unchanged in light mode.
            if self._dark_active:
                inverted = self._invert(expr)
                return inverted or expr
            return expr

        if expr.startswith("dd:"):
            if self._core is None:
                if not self._warned_no_core:
                    logger.warning(
                        "doxtr-roadmap: semantic colour '%s' requires "
                        "doxtr_pdf_theme_core to be installed; falling back to "
                        "the default colour. Install the theme or use a #hex "
                        "colour instead.",
                        expr,
                    )
                    self._warned_no_core = True
                return None
            return self._resolve_dd(expr)

        # Unknown format (e.g. a bare colour name): let theme-core try if it is
        # available (it treats unknown values as errors), otherwise pass
        # through so PlantUML can attempt to interpret a named colour.
        return expr

    def _resolve_dd(self, expr):
        """Resolve a ``dd:`` expression via theme-core's colour engine.

        Uses :func:`doxtr_pdf_theme_core.utils.resolve_color` with the active
        palette and page background.  The roadmap does not participate in
        theme-core's layered config staging, so the theme/core/user config
        dicts are passed empty — palette lookups (``dd:primary``) and inline
        operations (``dd:#FFCC00:lighten:80``) work without them; only
        cross-config references (``dd:theme:key`` etc.) are unsupported and
        resolve to theme-core's error colour.

        Returns the resolved hex string, or ``None`` on failure so the caller
        falls back to the default colour.
        """
        try:
            from doxtr_pdf_theme_core.utils import resolve_color
        except ImportError:
            if not self._warned_no_core:
                logger.warning(
                    "doxtr-roadmap: semantic colour '%s' requires "
                    "doxtr_pdf_theme_core to be installed; falling back to "
                    "the default colour.",
                    expr,
                )
                self._warned_no_core = True
            return None
        try:
            resolved = resolve_color(
                expr,
                self._palette,
                self._page_bg or "#FFFFFF",
                "roadmap",           # current_section (label only)
                {},                  # current_dict
                {},                  # theme_defaults
                {},                  # core_config
                {},                  # user_config
            )
        except Exception:
            logger.warning(
                "doxtr-roadmap: failed to resolve semantic colour '%s'; "
                "falling back to the default colour.",
                expr,
            )
            return None
        # theme-core returns its error sentinel '#ff0000' on a failed
        # resolution (e.g. an unknown palette key or an unsupported
        # cross-config reference). Treat that as a failure so the caller falls
        # back to the roadmap default colour, unless the expression genuinely
        # asked for that red (e.g. 'dd:#ff0000'). theme-core already logs the
        # specific cause at WARNING, so we add a concise roadmap-context note.
        if not resolved or not isinstance(resolved, str):
            return None
        if resolved.lower() == _THEME_CORE_ERROR_COLOR and "ff0000" not in expr.lower():
            logger.warning(
                "doxtr-roadmap: semantic colour '%s' could not be resolved "
                "(see the preceding theme-core warning); falling back to the "
                "default colour.",
                expr,
            )
            return None
        return resolved

    def resolve(self, expr, default_done, default_frame):
        """Resolve a task colour expression to a ``(done, frame)`` pair.

        Parameters
        ----------
        expr:
            The task's inherited colour expression (``None``, ``#hex`` or
            ``dd:...``).  ``None`` (the default sentinel / no colour) yields the
            supplied *default_done* / *default_frame* unchanged.
        default_done:
            The roadmap default done colour to use when *expr* is ``None`` or
            cannot be resolved.
        default_frame:
            The roadmap default frame colour to use alongside *default_done*.

        Returns
        -------
        tuple
            ``(done_hex, frame_hex_or_None)``.  When *expr* resolves to a
            concrete colour, *frame* is derived from it via
            :func:`derive_frame_color` (``None`` if derivation is disabled or
            unavailable).
        """
        if not expr:
            return default_done, default_frame
        done = self._resolve_expr(expr)
        if not done:
            return default_done, default_frame
        frame = derive_frame_color(done, self._frame_delta)
        return done, frame
