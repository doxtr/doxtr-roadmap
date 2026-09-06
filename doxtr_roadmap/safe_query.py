"""Restricted AST-based query evaluator for the ``:query:`` directive option.

This module provides a pure Python evaluator that parses a filter expression
with :func:`ast.parse` (mode="eval"), validates every AST node against a
strict allowlist, and then walks the validated tree to compute a boolean
result.

It has **no** dependencies on Sphinx, docutils, or any third-party package and
is independently unit-testable.

Security properties
-------------------
* **No** ``eval()`` / ``exec()`` / ``compile()`` — the AST is walked
  manually.
* **No** attribute access (``obj.attr``) — :class:`ast.Attribute` nodes are
  forbidden.  This closes the classic CPython sandbox escape::

      ().__class__.__bases__[0].__subclasses__()   # → QueryError

* **No** subscript access (``obj[key]``).
* **No** lambdas, comprehensions, generator expressions, or f-strings.
* **No** implicit builtins — the expression's names are resolved *exclusively*
  from the caller-supplied ``names`` dict.  Calling ``__import__``, ``open``,
  or any name absent from ``names`` raises :class:`QueryError`.
* Only ``ast.Call`` nodes whose ``func`` is an :class:`ast.Name` that
  resolves to a *callable* value in ``names`` are permitted.
* Keyword arguments and starred arguments in calls are forbidden.
"""

from __future__ import annotations

import ast
import operator
from typing import Any


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class QueryError(Exception):
    """Raised when a query expression contains a disallowed construct,
    references an undefined name, or has a syntax error.
    """


# ---------------------------------------------------------------------------
# Allowlisted AST node types
# ---------------------------------------------------------------------------
# Every node produced by ast.walk() must be in this set.  Any node type NOT
# in this set causes _validate() to raise QueryError immediately, before any
# evaluation takes place.

_ALLOWED_NODES: frozenset[type] = frozenset({
    # Wrapper produced by ast.parse(mode="eval")
    ast.Expression,
    # Literals (Python 3.8+ unified Constant replaces Num/Str/NameConstant)
    ast.Constant,
    # Name lookup — only Load context is valid in an expression
    ast.Name,
    ast.Load,
    # Boolean operators
    ast.BoolOp,
    ast.And,
    ast.Or,
    # Unary operators
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    # Comparison operators and their node
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    # Collection literals (no comprehensions — ListComp/SetComp/DictComp
    # are intentionally absent)
    ast.List,
    ast.Tuple,
    ast.Set,
    # Function calls (only to whitelisted callables — see _eval)
    ast.Call,
})

# ---------------------------------------------------------------------------
# Operator dispatch tables
# ---------------------------------------------------------------------------

_CMP_OPS: dict[type, Any] = {
    ast.Eq:    operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt:    operator.lt,
    ast.LtE:   operator.le,
    ast.Gt:    operator.gt,
    ast.GtE:   operator.ge,
    ast.In:    lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is:    operator.is_,
    ast.IsNot: operator.is_not,
}

_UNARY_OPS: dict[type, Any] = {
    ast.Not:  operator.not_,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


# ---------------------------------------------------------------------------
# Pre-validation pass
# ---------------------------------------------------------------------------


def _validate(tree: ast.AST) -> None:
    """Walk *tree* and raise :class:`QueryError` for any disallowed node type.

    This pass runs **before** any evaluation so that expressions like
    ``(lambda: __import__("os"))()`` are rejected even though the outer
    ``Call`` node is individually allowed — the inner ``Lambda`` node is
    caught here first.
    """
    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            _explain_and_raise(node)


def _explain_and_raise(node: ast.AST) -> None:
    """Raise :class:`QueryError` with a human-readable message for *node*."""
    name = type(node).__name__

    # Provide specific guidance for the most common sandbox-escape patterns.
    if isinstance(node, ast.Attribute):
        raise QueryError(
            f"Attribute access is forbidden in query expressions "
            f"(got '.{node.attr}'). "
            "Use only the named values and helper functions provided."
        )
    if isinstance(node, ast.Subscript):
        raise QueryError(
            "Subscript access is forbidden in query expressions. "
            "Use 'in' comparisons for membership tests."
        )
    if isinstance(node, ast.Lambda):
        raise QueryError(
            "Lambda expressions are forbidden in query expressions."
        )
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                          ast.GeneratorExp)):
        raise QueryError(
            f"Comprehensions and generator expressions are forbidden "
            f"in query expressions (got {name!r})."
        )
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        raise QueryError(
            "Import statements are forbidden in query expressions."
        )
    if isinstance(node, ast.IfExp):
        raise QueryError(
            "Conditional (ternary) expressions are forbidden in query expressions."
        )
    if isinstance(node, ast.keyword):
        raise QueryError(
            "Keyword arguments are forbidden in query expressions."
        )
    if isinstance(node, ast.Starred):
        raise QueryError(
            "Starred arguments are forbidden in query expressions."
        )
    if isinstance(node, ast.NamedExpr):
        raise QueryError(
            "Walrus operator (:=) is forbidden in query expressions."
        )
    raise QueryError(
        f"Forbidden construct in query expression: {name!r}. "
        "Only boolean logic, comparisons, literals, collection literals, "
        "and calls to named safe helpers are allowed."
    )


# ---------------------------------------------------------------------------
# Recursive evaluator
# ---------------------------------------------------------------------------


def _eval(node: ast.AST, names: dict) -> Any:
    """Recursively evaluate a **pre-validated** AST *node*.

    All node types have already been checked by :func:`_validate`; this
    function only needs to handle the allowed subset.
    """
    if isinstance(node, ast.Expression):
        return _eval(node.body, names)

    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        # ctx is ast.Load — guaranteed by _validate (ast.Store/ast.Del are
        # not in _ALLOWED_NODES and would have been rejected).
        if node.id not in names:
            raise QueryError(
                f"Undefined name {node.id!r} in query expression. "
                f"Available names: {sorted(names)}"
            )
        return names[node.id]

    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: Any = True
            for val in node.values:
                result = _eval(val, names)
                if not result:
                    return result
            return result
        # ast.Or
        result = False
        for val in node.values:
            result = _eval(val, names)
            if result:
                return result
        return result

    if isinstance(node, ast.UnaryOp):
        op_fn = _UNARY_OPS[type(node.op)]
        return op_fn(_eval(node.operand, names))

    if isinstance(node, ast.Compare):
        left = _eval(node.left, names)
        for op_node, comparator in zip(node.ops, node.comparators):
            op_fn = _CMP_OPS[type(op_node)]
            right = _eval(comparator, names)
            if not op_fn(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.List):
        return [_eval(e, names) for e in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval(e, names) for e in node.elts)

    if isinstance(node, ast.Set):
        return {_eval(e, names) for e in node.elts}

    if isinstance(node, ast.Call):
        # Belt-and-suspenders: _validate already rejected non-Name func nodes
        # (e.g. ast.Attribute), but be explicit here too.
        if not isinstance(node.func, ast.Name):
            raise QueryError(
                "Calls to arbitrary expressions are forbidden; "
                "only named safe helpers may be called."
            )
        func_name = node.func.id
        if func_name not in names:
            raise QueryError(
                f"Undefined callable {func_name!r} in query expression. "
                f"Available names: {sorted(names)}"
            )
        func = names[func_name]
        if not callable(func):
            raise QueryError(
                f"'{func_name}' is not callable. "
                "Only helper functions (match, any, all, bool, set, len) "
                "may be called."
            )
        # _validate rejected ast.keyword nodes so node.keywords is always [].
        # Starred args were also rejected.
        args = [_eval(a, names) for a in node.args]
        return func(*args)

    # Should be unreachable after _validate, but be defensive.
    raise QueryError(
        f"Internal evaluator error: unexpected node {type(node).__name__!r}. "
        "This is a bug in safe_query."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_query(expr: str, names: dict) -> bool:
    """Parse and evaluate *expr* as a restricted Python boolean expression.

    *names* is the **only** source of values and callables.  The expression
    may reference any key in *names*; any other identifier raises
    :class:`QueryError`.

    Parameters
    ----------
    expr:
        The filter expression string (e.g. ``'"eng" in tags and end > start'``).
    names:
        Mapping of allowed names to their runtime values.  Typically contains
        the row fields (``name``, ``start``, ``end``, ``section``, ``tags``,
        ``row_group``) plus safe callable helpers (``match``, ``any``,
        ``all``, ``bool``, ``set``, ``len``).

    Returns
    -------
    bool
        ``bool(result)`` of the expression.

    Raises
    ------
    QueryError
        On any disallowed construct, undefined name, or syntax error.

    Allowed constructs
    ------------------
    - Boolean operators: ``and``, ``or``, ``not``
    - Comparisons: ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``,
      ``in``, ``not in``, ``is``, ``is not``
    - Literals: strings, numbers, booleans, ``None``
    - Collection literals: ``[...]``, ``(...)``, ``{...}`` (set literal)
    - Calls to named *callable* values in *names* (positional args only)

    Forbidden constructs (raise :class:`QueryError`)
    -------------------------------------------------
    - Attribute access (``obj.attr``) — closes the ``__subclasses__`` escape
    - Subscript access (``obj[key]``)
    - Lambdas
    - Comprehensions and generator expressions
    - Walrus operator (``:=``)
    - ``__import__`` or any name absent from *names*
    - Keyword arguments in calls
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise QueryError(f"Query syntax error: {exc}") from exc

    _validate(tree)
    result = _eval(tree, names)
    return bool(result)
