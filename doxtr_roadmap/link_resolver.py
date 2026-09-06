"""Link resolution for doxtr_roadmap.

Resolves the ``link`` CSV column to ``(url, title)`` tuples, handling both
plain URLs and :xlink:`id` role expressions.

xlink integration
-----------------
When ``sphinxcontrib.xlink`` is present in the project's extensions, the
:class:`LinkResolver` calls ``sphinxcontrib.xlink._get_xlink_data(app, key)``
directly to resolve xlink IDs.  This is an internal API (leading underscore)
but is used intentionally here because we own the ecosystem and test both
packages together.  The import is guarded by ``try/except (ImportError,
AttributeError)`` per OQ-3: if the function is absent in a future xlink
release, a local minimal fallback scans ``.xlink`` files from
``config.xlink_directory`` using the same ``id :: title :: url :: tags`` format.

Per-build warning deduplication
--------------------------------
The warned set is stored per-build on the Sphinx env object (key
``_doxtr_roadmap_warned``) so that multiple Sphinx applications in one process
do not share state.  Unit tests may inject a plain ``set`` directly via the
``_warned`` constructor argument.
"""

import re
import os
from sphinx.util import logging

logger = logging.getLogger(__name__)

# Matches the xlink role body, mirroring sphinxcontrib.xlink.roles.xlink_role.
# The leading colon is optional so a stray ``xlink:`id``` typo still resolves.
_ROLE_RE = re.compile(r":?xlink:`(?P<body>[^`]*)`")
_LABEL_RE = re.compile(r"^(?P<label>.*)\s*<(?P<key>.*)>$")


# ---------------------------------------------------------------------------
# Type alias (re-exported so generator.py can reference it)
# ---------------------------------------------------------------------------
# (actual Callable alias lives in generator.py; kept here for completeness)


def parse_xlink_role(cell: str):
    """Parse a full xlink role expression from a CSV cell.

    Accepts any of the forms the sphinxcontrib.xlink role accepts:

    * ``:xlink:`some-id```
    * ``:xlink:`Custom title <some-id>```
    * ``some-id``  (bare id)
    * ``Custom title <some-id>``  (bare label+id form)

    Parameters
    ----------
    cell:
        Raw CSV cell value.

    Returns
    -------
    tuple
        ``(key, label)`` where *label* is ``None`` when no custom title was
        supplied (so the resolved xlink title should be used instead).
        Returns ``(None, None)`` for an empty cell.
    """
    cell = (cell or "").strip()
    if not cell:
        return None, None

    role_match = _ROLE_RE.search(cell)
    body = role_match.group("body").strip() if role_match else cell

    label_match = _LABEL_RE.search(body)
    if label_match:
        label = label_match.group("label").strip()
        key = label_match.group("key").strip()
        return key, (label or None)
    return body, None


def _local_xlink_scan(app, link_id: str):
    """Minimal local fallback that scans ``.xlink`` files for *link_id*.

    This is the AttributeError fallback for OQ-3: used only when
    ``sphinxcontrib.xlink._get_xlink_data`` is absent (e.g. future API
    change).  Mirrors the ``id :: title :: url :: tags`` line format.

    Parameters
    ----------
    app:
        Sphinx application object.
    link_id:
        The xlink ID to look up.

    Returns
    -------
    tuple
        ``(title, url)`` or ``(None, None)`` if not found.
    """
    env = app.env
    config = env.config
    xlink_dir_name = getattr(config, "xlink_directory", "xlinks")
    source_dir = os.path.normpath(
        os.path.join(env.srcdir, xlink_dir_name)
    )
    if not os.path.isdir(source_dir):
        return None, None

    for root, dirs, files in os.walk(source_dir):
        if ".xlink" in dirs:
            dirs.remove(".xlink")
        for filename in files:
            if not filename.endswith(".xlink"):
                continue
            with open(
                os.path.join(root, filename), "r", encoding="utf-8-sig"
            ) as fh:
                for line in fh:
                    clean = line.strip()
                    if not clean or clean.startswith("#"):
                        continue
                    if " :: " in clean:
                        parts = [p.strip() for p in clean.split(" :: ", 3)]
                        if len(parts) >= 3 and parts[0] == link_id:
                            return parts[1], parts[2]
    return None, None


class LinkResolver:
    """Resolves ``link`` CSV column values to ``(url, title)`` tuples.

    Handles plain URLs and ``:xlink:`id``` role expressions.  When
    ``sphinxcontrib.xlink`` is not loaded, xlink role expressions produce a
    one-time warning and return ``None``.

    Per-build warning deduplication is stored on the Sphinx env object under
    the key ``_doxtr_roadmap_warned`` so that multiple Sphinx applications in
    one process do not share state.  Unit tests may pass a plain ``set`` via
    the *_warned* parameter.

    Parameters
    ----------
    app:
        The Sphinx application object, used for config inspection and xlink
        data resolution.
    _warned:
        Optional pre-existing set used for warning deduplication (primarily
        for unit tests that want to inject their own set).
    """

    def __init__(self, app, _warned=None):
        self.app = app
        self._xlink_available = (
            "sphinxcontrib.xlink" in app.config.extensions
        )
        # Per-build dedup: store on env so multiple apps don't share state.
        # Unit tests may pass their own set via _warned.
        if _warned is not None:
            self._warned = _warned
        else:
            env = getattr(app, "env", None)
            if env is not None:
                if not hasattr(env, "_doxtr_roadmap_warned"):
                    env._doxtr_roadmap_warned = set()
                self._warned = env._doxtr_roadmap_warned
            else:
                # Fallback for stubs without env
                self._warned = set()

        # OQ-3: check whether _get_xlink_data is accessible
        self._get_xlink_data = None
        if self._xlink_available:
            try:
                from sphinxcontrib.xlink import _get_xlink_data
                self._get_xlink_data = _get_xlink_data
            except (ImportError, AttributeError):
                logger.warning(
                    "doxtr-roadmap: sphinxcontrib.xlink._get_xlink_data is "
                    "unavailable (API changed?); falling back to local .xlink "
                    "file scan for link resolution."
                )
                self._get_xlink_data = _local_xlink_scan

    def resolve(self, cell: str):
        """Resolve a ``link`` CSV cell value to ``(url, title)`` or ``None``.

        Parameters
        ----------
        cell:
            Raw cell string from the ``link`` CSV column.

        Returns
        -------
        tuple or None
            ``(url, title)`` on success, where *title* may be an empty string.
            ``None`` when the cell is empty, malformed, or unresolvable.
        """
        cell = (cell or "").strip()
        if not cell:
            return None

        # Detect xlink role syntax SOLELY via regex — no fragile string
        # heuristics like ``"<" in cell``.  A cell like ``Feature <pending>``
        # (no ``xlink:`` role prefix) must be treated as NOT-an-xlink.  [S-5]
        is_xlink = bool(_ROLE_RE.search(cell))

        if not is_xlink:
            # Plain URL
            if cell.startswith(("http://", "https://")):
                return (cell, "")
            # Bare string that isn't a URL and doesn't look like xlink → skip
            return None

        # xlink role expression
        key, label = parse_xlink_role(cell)
        if not key:
            return None

        if not self._xlink_available:
            wkey = f"xlink_missing:{key}"
            if wkey not in self._warned:
                logger.warning(
                    f"doxtr-roadmap: link cell '{cell}' looks like an xlink "
                    f"role but sphinxcontrib.xlink is not loaded; skipping."
                )
                self._warned.add(wkey)
            return None

        title_resolved, url = self._get_xlink_data(self.app, key)
        if not url:
            wkey = f"xlink_notfound:{key}"
            if wkey not in self._warned:
                logger.warning(
                    f"doxtr-roadmap: unknown xlink id '{key}' in link column."
                )
                self._warned.add(wkey)
            return None

        effective_title = label or title_resolved or ""
        return (url, effective_title)
