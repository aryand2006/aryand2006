import ast
import textwrap

from sediment.duplication import find_clones, shingles_for
from sediment.metrics import analyze_source


def build_units(source: str, path: str = "t.py"):
    source = textwrap.dedent(source)
    units, error = analyze_source(path, source)
    assert error is None, error
    tree = ast.parse(source)
    nodes = {
        (n.lineno, n.name): n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for unit in units:
        node = nodes.get((unit.lineno, unit.qualname.split(".")[-1]))
        if node is not None:
            unit.shingles = shingles_for(node)
    return units


RENAMED_PAIR = """
    def process_orders(orders):
        results = []
        for order in orders:
            if order.total > 100:
                results.append(order.id)
            elif order.total > 50:
                results.append(order.ref)
            else:
                continue
        return results

    def handle_invoices(invoices):
        collected = []
        for invoice in invoices:
            if invoice.amount > 100:
                collected.append(invoice.key)
            elif invoice.amount > 50:
                collected.append(invoice.tag)
            else:
                continue
        return collected
"""


def test_renamed_copy_paste_is_detected():
    units = build_units(RENAMED_PAIR)
    pairs = find_clones(units)
    assert len(pairs) == 1
    assert pairs[0].similarity >= 0.8
    assert {pairs[0].left, pairs[0].right} == {
        "t.py::process_orders",
        "t.py::handle_invoices",
    }


def test_structurally_different_functions_are_not_clones():
    units = build_units(
        """
        def alpha(values):
            total = 0
            for v in values:
                total += v
            return total

        def beta(mapping):
            if not mapping:
                raise ValueError("empty")
            keys = sorted(mapping)
            while keys:
                key = keys.pop()
                del mapping[key]
            return mapping
        """
    )
    assert find_clones(units) == []


def test_literal_values_do_not_defeat_fingerprinting():
    units = build_units(
        """
        def a(xs):
            out = []
            for x in xs:
                if x > 10:
                    out.append(x * 2)
                else:
                    out.append(x + 3)
            return out

        def b(ys):
            acc = []
            for y in ys:
                if y > 9999:
                    acc.append(y * 7)
                else:
                    acc.append(y + 41)
            return acc
        """
    )
    pairs = find_clones(units)
    assert len(pairs) == 1


def test_tiny_functions_are_not_compared():
    units = build_units(
        """
        def a():
            return 1

        def b():
            return 2
        """
    )
    assert find_clones(units) == []


def test_operator_difference_lowers_similarity():
    """Same shape but different arithmetic is a real behavioural difference."""
    same = build_units(RENAMED_PAIR)
    assert find_clones(same, threshold=0.99) != []

    units = build_units(
        """
        def a(xs):
            out = []
            for x in xs:
                if x:
                    out.append(x * 2 + 1)
            return out

        def b(xs):
            out = []
            for x in xs:
                if x:
                    out.append(x / 2 - 1)
            return out
        """
    )
    assert find_clones(units, threshold=0.99) == []
