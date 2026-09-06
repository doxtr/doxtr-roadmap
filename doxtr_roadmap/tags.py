"""Tag parsing and filtering helpers for doxtr_roadmap.

Provides local implementations of the tag functions required by the extension.
When ``sphinxcontrib.xlink`` is available its ``parse_tag_list``,
``match_tag_pattern``, and ``resolve_tag_info`` are used directly (they are
identical in behaviour); local copies are used otherwise.

The :func:`parse_nested_tags` and :func:`row_matches_filter` functions are
always local (the xlink version is a method on a class, not importable as a
standalone function).

Source note: the local implementations are verbatim copies of the equivalents
in sphinxcontrib.xlink (directives.XLinkListDirective._parse_nested_tags and
__init__.parse_tag_list / match_tag_pattern / resolve_tag_info).  They must be
kept in sync with xlink if xlink updates the tag syntax.

Per-build warning deduplication
---------------------------------
Warning deduplication uses the Sphinx env object (key ``_doxtr_roadmap_warned``)
when one is available, so multiple Sphinx apps in one process don't share state.
Unit tests may pass a plain ``set`` directly to the functions that accept one.
"""

import re
from sphinx.util import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local implementations (used when xlink is absent)
# ---------------------------------------------------------------------------

def _local_parse_tag_list(raw: str) -> list:
    """Split a comma-separated tag string, respecting double-quoted values.

    Commas inside double quotes are not treated as separators.  Quotes are
    preserved in the returned tag strings.  Whitespace around each tag is
    stripped.  Empty strings are excluded.

    Parameters
    ----------
    raw:
        Raw comma-separated tags string (e.g. from the ``tags`` CSV column).

    Returns
    -------
    list[str]
        List of tag strings.

    Examples
    --------
    >>> _local_parse_tag_list('engineer, code')
    ['engineer', 'code']
    >>> _local_parse_tag_list('bib:author:"van Beethoven, Ludwig", bib:year:2021')
    ['bib:author:"van Beethoven, Ludwig"', 'bib:year:2021']
    >>> _local_parse_tag_list('')
    []
    """
    if not raw:
        return []
    tags = []
    current = []
    in_quotes = False
    for ch in raw:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == "," and not in_quotes:
            tag = "".join(current).strip()
            if tag:
                tags.append(tag)
            current = []
        else:
            current.append(ch)
    tag = "".join(current).strip()
    if tag:
        tags.append(tag)
    return tags


def _compile_tag_patterns(patterns: dict) -> list:
    """Compile regex patterns from a patterns dict.

    Accepts the raw ``doxtr_roadmap_allowed_tag_patterns`` dict (or any
    equivalent mapping of pattern-string → metadata) and returns a list of
    ``(compiled_pattern, pattern_str, metadata)`` triples.

    No module-level cache is used — patterns are small and compilation is fast.
    The caller is responsible for caching on the config/env object if needed.

    Parameters
    ----------
    patterns:
        Dict mapping regex pattern strings to metadata values.

    Returns
    -------
    list
        List of ``(compiled, pattern_str, metadata)`` triples.
    """
    result = []
    for pattern_str, metadata in patterns.items():
        try:
            compiled = re.compile(pattern_str)
            result.append((compiled, pattern_str, metadata))
        except re.error as e:
            logger.warning(
                f"doxtr-roadmap: Invalid regex in "
                f"doxtr_roadmap_allowed_tag_patterns: '{pattern_str}': {e}"
            )
    return result


def _local_match_tag_pattern(tag: str, config) -> object:
    """Check if *tag* matches any pattern in the allowed tag patterns config.

    Compiles patterns fresh from config on each call (patterns are small;
    no module-level cache to avoid cross-build contamination).

    Parameters
    ----------
    tag:
        Tag string to check.
    config:
        Sphinx config object (checked for ``doxtr_roadmap_allowed_tag_patterns``).

    Returns
    -------
    object or None
        The pattern's metadata if matched, ``None`` otherwise.
    """
    patterns = getattr(config, "doxtr_roadmap_allowed_tag_patterns", {}) or {}
    compiled_patterns = _compile_tag_patterns(patterns)
    for compiled, _pattern_str, metadata in compiled_patterns:
        if compiled.fullmatch(tag):
            return metadata
    return None


def _local_resolve_tag_info(tag, config):
    """Resolve a tag to ``(display_name, description)`` using doxtr_roadmap config.

    Parameters
    ----------
    tag:
        Tag string to resolve, or ``None`` for the default untagged name.
    config:
        Sphinx config object.

    Returns
    -------
    tuple
        ``(display_name, description)`` strings.
    """
    if tag is None:
        return "Untagged", ""
    static = getattr(config, "doxtr_roadmap_allowed_tags", {})
    if static and tag in static:
        val = static[tag]
        if isinstance(val, (list, tuple)):
            return str(val[0]), str(val[1]) if len(val) > 1 else ""
        return str(val), ""
    metadata = _local_match_tag_pattern(tag, config)
    if metadata is not None:
        if isinstance(metadata, (list, tuple)):
            return str(tag), str(metadata[1]) if len(metadata) > 1 else ""
        return str(tag), ""
    return str(tag), ""


def parse_row_tags(raw: str) -> list:
    """Tokenise a CSV ``tags`` cell using commas AND whitespace as delimiters.

    The documented CSV ``tags`` column format is *space- or comma-separated*.
    This function extends :func:`parse_tag_list` (which only splits on commas)
    by also splitting each comma-delimited token on runs of unquoted whitespace.
    Double-quoted spans are never split — so a tag like
    ``bib:author:"van B, L"`` remains a single token even if the quoted value
    contains spaces.

    This function is used to tokenise the **row's** ``tags`` cell (the values
    coming from the CSV data).  The directive-option filter expressions
    (``parse_nested_tags``) are parsed separately and are unaffected.

    Parameters
    ----------
    raw:
        Raw tags cell value (e.g. from the CSV ``tags`` column).

    Returns
    -------
    list[str]
        List of individual tag strings, stripped and de-duplicated of empties.

    Examples
    --------
    >>> parse_row_tags("eng ops")
    ['eng', 'ops']
    >>> parse_row_tags("eng, ops")
    ['eng', 'ops']
    >>> parse_row_tags("eng,ops security")
    ['eng', 'ops', 'security']
    >>> parse_row_tags('bib:author:"van B, L" ops')
    ['bib:author:"van B, L"', 'ops']
    >>> parse_row_tags("")
    []
    """
    if not raw:
        return []
    # Step 1: comma-split with quote-awareness (same as parse_tag_list).
    comma_tokens = _local_parse_tag_list(raw)
    # Step 2: within each comma-token, split on runs of unquoted whitespace.
    result = []
    for token in comma_tokens:
        # Walk through the token and collect sub-tokens split on whitespace,
        # respecting double-quoted spans (never split inside quotes).
        sub_tokens = []
        current: list = []
        in_quotes = False
        for ch in token:
            if ch == '"':
                in_quotes = not in_quotes
                current.append(ch)
            elif ch in (' ', '\t', '\n', '\r') and not in_quotes:
                piece = ''.join(current).strip()
                if piece:
                    sub_tokens.append(piece)
                current = []
            else:
                current.append(ch)
        # Flush any remaining characters.
        piece = ''.join(current).strip()
        if piece:
            sub_tokens.append(piece)
        result.extend(sub_tokens)
    return result


# ---------------------------------------------------------------------------
# Module-level function binding (xlink wins when available)
# ---------------------------------------------------------------------------

_xlink_present = False
try:
    from sphinxcontrib.xlink import (
        parse_tag_list,
        match_tag_pattern,
        resolve_tag_info,
    )
    _xlink_present = True
except ImportError:
    parse_tag_list = _local_parse_tag_list
    match_tag_pattern = _local_match_tag_pattern
    resolve_tag_info = _local_resolve_tag_info


# ---------------------------------------------------------------------------
# Always-local functions
# ---------------------------------------------------------------------------

def is_tag_allowed(tag: str, config) -> bool:
    """Check whether *tag* is permitted by the configured allow-lists.

    Checks both ``doxtr_roadmap_allowed_tags`` / ``doxtr_roadmap_allowed_tag_patterns``
    AND (when xlink is present) ``xlink_allowed_tags`` / ``xlink_allowed_tag_patterns``.
    ``doxtr_roadmap_*`` wins on conflict; xlink keys extend the allowed set.

    Returns ``True`` when no restrictions are configured at all.

    Parameters
    ----------
    tag:
        Tag string to validate.
    config:
        Sphinx config object.

    Returns
    -------
    bool
        ``True`` if the tag is allowed or no restrictions are defined.
    """
    roadmap_static = getattr(config, "doxtr_roadmap_allowed_tags", {}) or {}
    roadmap_patterns = (
        getattr(config, "doxtr_roadmap_allowed_tag_patterns", {}) or {}
    )
    xlink_static = (
        getattr(config, "xlink_allowed_tags", {}) or {}
    ) if _xlink_present else {}
    xlink_patterns = (
        getattr(config, "xlink_allowed_tag_patterns", {}) or {}
    ) if _xlink_present else {}

    all_static = {**xlink_static, **roadmap_static}   # roadmap wins
    all_patterns = {**xlink_patterns, **roadmap_patterns}

    if not all_static and not all_patterns:
        return True
    if tag in all_static:
        return True
    for pat in all_patterns:
        try:
            if re.fullmatch(pat, tag):
                return True
        except re.error:
            pass
    return False


def parse_nested_tags(tags_string: str) -> dict:
    """Parse a nested tag filter expression into a filter tree.

    Supports the same ``[ ]``-nested syntax with ``!``/``!!`` hide/cascade
    markers as ``XLinkListDirective._parse_nested_tags``.  This is a
    standalone copy of that method (with ``self`` removed).

    Parameters
    ----------
    tags_string:
        Filter expression string, e.g. ``"security [ compliance !! ], public"``.

    Returns
    -------
    dict
        Nested dict where each key is a tag name and each value is::

            {"children": {...}, "hide": bool, "cascade": bool}
    """
    root: dict = {}
    stack = [(root, False)]
    current_dict = root
    current_cascade = False
    buffer = ""

    def process_buffer(buf, c_dict, c_cascade):
        raw_tag = buf.strip()
        if not raw_tag:
            return None, False
        hide_self = False
        cascade_children = False
        if raw_tag.startswith("!!"):
            hide_self = True
            cascade_children = True
            raw_tag = raw_tag[2:]
        elif raw_tag.startswith("!"):
            hide_self = True
            raw_tag = raw_tag[1:]
        if raw_tag.endswith("!!"):
            cascade_children = True
            raw_tag = raw_tag[:-2]
        elif raw_tag.endswith("!"):
            hide_self = True
            raw_tag = raw_tag[:-1]
        clean_tag = raw_tag.strip()
        if c_cascade:
            hide_self = True
            cascade_children = True
        c_dict[clean_tag] = {
            "children": {},
            "hide": hide_self,
            "cascade": cascade_children,
        }
        return clean_tag, cascade_children

    for char in tags_string:
        if char == "[":
            tag_name, cascade = process_buffer(buffer, current_dict, current_cascade)
            buffer = ""
            if tag_name:
                stack.append((current_dict[tag_name]["children"], cascade))
                current_dict = current_dict[tag_name]["children"]
                current_cascade = cascade
        elif char == "]":
            process_buffer(buffer, current_dict, current_cascade)
            buffer = ""
            if len(stack) > 1:
                stack.pop()
                current_dict, current_cascade = stack[-1]
        elif char == ",":
            process_buffer(buffer, current_dict, current_cascade)
            buffer = ""
        else:
            buffer += char

    process_buffer(buffer, current_dict, current_cascade)
    return root


def row_matches_filter(row_tags: list, filter_tree: dict) -> bool:
    """Return ``True`` if *row_tags* satisfies the parsed *filter_tree*.

    A row is included if at least one of its tags appears in the filter tree
    and that tag is not hidden (``hide=True``).  A row with no tags passes only
    if the filter tree is empty (i.e. no filter is applied).

    Parameters
    ----------
    row_tags:
        List of tag strings for this CSV row.
    filter_tree:
        Parsed filter tree from :func:`parse_nested_tags`.

    Returns
    -------
    bool
        ``True`` if the row should be included in the rendered diagram.
    """
    if not filter_tree:
        return True
    tag_set = set(row_tags)

    def _matches(tree):
        for key, data in tree.items():
            if key in tag_set:
                if not data["hide"]:
                    return True
                # hidden but has children — check children
                if data["children"] and _matches(data["children"]):
                    return True
            if data["children"] and _matches(data["children"]):
                return True
        return False

    return _matches(filter_tree)
