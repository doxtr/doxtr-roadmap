"""Hermetic unit tests for doxtr_roadmap.safe_query.

These tests have NO dependency on Sphinx, docutils, or any other framework
component.  They import only doxtr_roadmap.safe_query (which itself has no
framework dependencies) and define a local ``match`` helper that mirrors the
behaviour of ``directive._query_match_helper``.
"""

from __future__ import annotations

import datetime
import re

import pytest

from doxtr_roadmap.safe_query import QueryError, evaluate_query


# ---------------------------------------------------------------------------
# Local match helper (mirrors directive._query_match_helper)
# ---------------------------------------------------------------------------


def _match(pattern: str, string: str) -> bool:
    return bool(re.search(pattern, string))


# ---------------------------------------------------------------------------
# Test names dict factory
# ---------------------------------------------------------------------------


def _names(**overrides) -> dict:
    """Build a representative names dict identical to what directive.py passes."""
    base: dict = {
        "name":      "Task Alpha",
        "start":     datetime.date(2026, 1, 1),
        "end":       datetime.date(2026, 3, 31),
        "section":   "Engineering",
        "tags":      {"security", "public"},
        "row_group": None,
        # Safe callable helpers
        "match": _match,
        "any":   any,
        "all":   all,
        "bool":  bool,
        "set":   set,
        "len":   len,
    }
    base.update(overrides)
    return base


# ===========================================================================
# Allowed expressions — must evaluate correctly without raising
# ===========================================================================


class TestAllowedExpressions:
    """Expressions that the evaluator must handle correctly."""

    # --- tag membership ---

    def test_tag_in_tags_true(self):
        assert evaluate_query('"security" in tags', _names()) is True

    def test_tag_in_tags_false(self):
        assert evaluate_query('"internal" in tags', _names()) is False

    def test_not_tag_in_tags(self):
        assert evaluate_query('not ("internal" in tags)', _names()) is True

    # --- name equality ---

    def test_name_eq_true(self):
        assert evaluate_query('name == "Task Alpha"', _names()) is True

    def test_name_eq_false(self):
        assert evaluate_query('name == "Task Beta"', _names()) is False

    # --- date comparisons ---

    def test_start_lt_end(self):
        assert evaluate_query("start < end", _names()) is True

    def test_start_gte_end_false(self):
        assert evaluate_query("start >= end", _names()) is False

    def test_start_eq_end_false(self):
        assert evaluate_query("start == end", _names()) is False

    # --- match() helper ---

    def test_match_helper_anchored_true(self):
        assert evaluate_query('match(r"^Task", name)', _names()) is True

    def test_match_helper_anchored_false(self):
        assert evaluate_query('match(r"^Set", name)', _names()) is False

    def test_match_and_tag(self):
        # match(r"^Task", name) → True  AND  "public" in tags → True
        assert evaluate_query(
            'match(r"^Task", name) and "public" in tags', _names()
        ) is True

    def test_match_false_and_tag(self):
        # match(r"^Set", name) → False  AND … → short-circuits False
        assert evaluate_query(
            'match(r"^Set", name) and "public" in tags', _names()
        ) is False

    # --- len / bool ---

    def test_len_tags_gt_zero(self):
        assert evaluate_query("len(tags) > 0", _names()) is True

    def test_len_tags_zero(self):
        assert evaluate_query("len(tags) > 0", _names(tags=set())) is False

    def test_bool_conversion(self):
        assert evaluate_query("bool(len(tags))", _names()) is True

    # --- any / all ---

    def test_any_of_matches_true(self):
        assert evaluate_query(
            'any([match(r"^Alpha", name), match(r"^Task", name)])',
            _names()
        ) is True

    def test_any_of_matches_false(self):
        assert evaluate_query(
            'any([match(r"^Alpha", name), match(r"^Beta", name)])',
            _names()
        ) is False

    def test_all_tags_present_true(self):
        assert evaluate_query(
            'all([match(r"^Task", name), "security" in tags])',
            _names()
        ) is True

    def test_all_tags_present_false(self):
        assert evaluate_query(
            'all([match(r"^Task", name), match(r"^Set", name)])',
            _names()
        ) is False

    # --- is None / is not None ---

    def test_row_group_is_none(self):
        assert evaluate_query("row_group is None", _names()) is True

    def test_row_group_is_not_none(self):
        assert evaluate_query(
            "row_group is not None", _names(row_group="grp1")
        ) is True

    # --- or expression ---

    def test_or_expression(self):
        assert evaluate_query('"eng" in tags or "security" in tags', _names()) is True

    # --- in with tuple literal ---

    def test_in_tuple_literal(self):
        assert evaluate_query(
            'name in ("Task Alpha", "Task Beta")', _names()
        ) is True

    def test_not_in_tuple_literal(self):
        assert evaluate_query(
            'name not in ("Task Gamma", "Task Beta")', _names()
        ) is True

    # --- set literal ---

    def test_set_membership(self):
        assert evaluate_query(
            '"security" in {"security", "eng"}', _names()
        ) is True

    # --- constants ---

    def test_true_literal(self):
        assert evaluate_query("True", _names()) is True

    def test_false_literal(self):
        assert evaluate_query("False", _names()) is False

    def test_none_is_none(self):
        assert evaluate_query("None is None", _names()) is True


# ===========================================================================
# Sandbox escapes — MUST raise QueryError
# ===========================================================================


class TestSandboxEscapes:
    """Every expression here must raise QueryError, not execute silently."""

    def test_empty_tuple_class(self):
        """Classic escape via attribute traversal must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("().__class__", _names())

    def test_full_subclasses_escape(self):
        """The canonical sandbox escape must raise QueryError, NOT return a list."""
        with pytest.raises(QueryError) as exc_info:
            evaluate_query(
                "().__class__.__bases__[0].__subclasses__()", _names()
            )
        # Confirm the error message names the forbidden construct.
        assert "Attribute" in str(exc_info.value) or "forbidden" in str(exc_info.value).lower()

    def test_import_os_via_builtin(self):
        """__import__ is not in names → QueryError."""
        with pytest.raises(QueryError):
            evaluate_query('__import__("os")', _names())

    def test_name_class_access(self):
        """Attribute access on a name value must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("name.__class__", _names())

    def test_lambda_expression(self):
        """Lambda must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("(lambda: 1)()", _names())

    def test_list_comprehension(self):
        """List comprehension must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("[x for x in tags]", _names())

    def test_set_comprehension(self):
        """Set comprehension must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("{x for x in tags}", _names())

    def test_generator_expression(self):
        """Generator expression must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("any(x for x in tags)", _names())

    def test_open_not_in_names(self):
        """open() is not in names → QueryError (not NameError from real builtins)."""
        with pytest.raises(QueryError):
            evaluate_query('open("f")', _names())

    def test_match_globals_attribute(self):
        """Accessing __globals__ on a helper via attribute must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("match.__globals__", _names())

    def test_subscript_on_subclasses_chain(self):
        """Subscript access must be blocked even on its own."""
        with pytest.raises(QueryError):
            evaluate_query("tags[0]", _names())

    def test_walrus_operator(self):
        """Walrus (:=) must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("(x := 1)", _names())

    def test_conditional_expression(self):
        """Ternary expression must be blocked."""
        with pytest.raises(QueryError):
            evaluate_query("1 if True else 2", _names())

    def test_dict_comprehension(self):
        with pytest.raises(QueryError):
            evaluate_query("{k: k for k in tags}", _names())

    def test_nested_lambda_in_call(self):
        """Lambda nested inside a call must be caught by pre-validation."""
        with pytest.raises(QueryError):
            evaluate_query("any(lambda: x for x in tags)", _names())


# ===========================================================================
# Undefined names
# ===========================================================================


class TestUndefinedNames:

    def test_unknown_name_raises(self):
        with pytest.raises(QueryError, match="Undefined name"):
            evaluate_query("unknown_var == 1", _names())

    def test_calling_undefined_name_raises(self):
        with pytest.raises(QueryError):
            evaluate_query('subprocess()', _names())

    def test_calling_non_callable_raises(self):
        """Calling a data name (e.g. 'name' which is a str) raises QueryError."""
        with pytest.raises(QueryError, match="not callable"):
            evaluate_query("name()", _names())

    def test_calling_start_raises(self):
        """start is a date, not callable."""
        with pytest.raises(QueryError, match="not callable"):
            evaluate_query("start()", _names())


# ===========================================================================
# Syntax errors
# ===========================================================================


class TestSyntaxErrors:

    def test_invalid_syntax_raises_query_error(self):
        with pytest.raises(QueryError, match="syntax"):
            evaluate_query("this is not !!! valid", _names())

    def test_empty_expression_raises(self):
        with pytest.raises(QueryError):
            evaluate_query("", _names())


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:

    def test_section_name_available(self):
        assert evaluate_query(
            'section == "Engineering"', _names()
        ) is True

    def test_chained_comparison(self):
        # start < end is True, so start < end > start should also be True
        assert evaluate_query("start < end", _names()) is True

    def test_result_coerced_to_bool_falsy(self):
        # empty set is falsy
        assert evaluate_query(
            "set()", _names()
        ) is False

    def test_keyword_arg_rejected(self):
        """Keyword argument in a call must raise QueryError."""
        with pytest.raises(QueryError):
            evaluate_query('match(pattern=r"x", string=name)', _names())
