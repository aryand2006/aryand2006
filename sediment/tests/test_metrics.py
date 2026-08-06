import textwrap

from sediment.metrics import THRESHOLDS, analyze_source


def units_of(source: str) -> dict:
    units, error = analyze_source("t.py", textwrap.dedent(source))
    assert error is None, error
    return {u.qualname: u for u in units}


def test_trivial_function_has_baseline_complexity():
    u = units_of("def f():\n    return 1\n")["f"]
    assert u.cyclomatic == 1
    assert u.cognitive == 0
    assert u.max_nesting == 0
    assert u.debt() == 0.0


def test_branches_raise_cyclomatic():
    u = units_of(
        """
        def f(a, b):
            if a:
                return 1
            for x in b:
                if x:
                    return x
            return 0
        """
    )["f"]
    # 1 base + 2 ifs + 1 for
    assert u.cyclomatic == 4


def test_boolop_counts_each_operand():
    u = units_of("def f(a, b, c):\n    return a and b and c\n")["f"]
    assert u.cyclomatic == 3


def test_cognitive_complexity_penalizes_nesting():
    flat = units_of(
        """
        def f(a, b, c):
            if a:
                return 1
            if b:
                return 2
            if c:
                return 3
        """
    )["f"]
    nested = units_of(
        """
        def f(a, b, c):
            if a:
                if b:
                    if c:
                        return 3
        """
    )["f"]
    assert flat.cyclomatic == nested.cyclomatic
    # Same branch count, but nesting is what actually costs a reader.
    assert nested.cognitive > flat.cognitive


def test_nested_function_is_its_own_unit():
    us = units_of(
        """
        def outer(a):
            def inner(b):
                if b:
                    return 1
                return 0
            return inner(a)
        """
    )
    assert "outer" in us and "outer.inner" in us
    # The branch belongs to inner, not to outer.
    assert us["outer"].cyclomatic == 1
    assert us["outer.inner"].cyclomatic == 2


def test_methods_are_labelled_and_skip_self():
    us = units_of(
        """
        class C:
            def m(self, a, b):
                return a + b
        """
    )
    assert us["C.m"].kind == "method"
    assert us["C.m"].params == 2


def test_loc_excludes_blanks_and_comments():
    u = units_of(
        """
        def f():
            # a comment

            x = 1

            return x
        """
    )["f"]
    assert u.loc == 3  # def, x = 1, return x


def test_debt_is_zero_at_threshold_and_positive_above():
    limit = THRESHOLDS["cyclomatic"]
    body = "\n".join(f"    if a == {i}:\n        return {i}" for i in range(limit - 1))
    at = units_of(f"def f(a):\n{body}\n    return 0\n")["f"]
    assert at.cyclomatic == limit
    assert at.debt() == 0.0

    body_over = "\n".join(f"    if a == {i}:\n        return {i}" for i in range(limit + 4))
    over = units_of(f"def f(a):\n{body_over}\n    return 0\n")["f"]
    assert over.cyclomatic > limit
    assert over.debt() > 0.0


def test_syntax_error_is_reported_not_raised():
    units, error = analyze_source("bad.py", "def f(\n")
    assert units == []
    assert error is not None and "syntax error" in error


def test_async_functions_are_measured():
    us = units_of(
        """
        async def f(a):
            async for x in a:
                if x:
                    return x
        """
    )
    assert us["f"].cyclomatic == 3
