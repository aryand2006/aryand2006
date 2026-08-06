"""Structural metric extraction from Python source.

Every metric here is deterministic and derived from the AST, never from a model.
That is the point: the gate has to give the same answer twice, or it is not a gate.

Units of measurement are *code units* -- functions, methods, and module top level --
because erosion is a property of the thing a human has to read in one sitting.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, asdict
from typing import Iterator


# Thresholds are the point at which a unit starts costing a reader real effort.
# They are deliberately forgiving: the gate scores *overage*, so a unit sitting
# at the threshold contributes exactly zero debt.
THRESHOLDS = {
    "cyclomatic": 10,
    "cognitive": 15,
    "max_nesting": 4,
    "loc": 50,
    "params": 5,
}

# Relative weights when folding per-metric overage into one debt number.
# Cognitive complexity dominates because it is the metric that best tracks
# "how hard is this to hold in your head", which is what erodes.
WEIGHTS = {
    "cyclomatic": 1.0,
    "cognitive": 1.5,
    "max_nesting": 1.0,
    "loc": 0.6,
    "params": 0.4,
}

_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass
class Unit:
    """One measurable code unit."""

    qualname: str
    path: str
    lineno: int
    end_lineno: int
    kind: str  # "function" | "method" | "module"

    cyclomatic: int = 1
    cognitive: int = 0
    max_nesting: int = 0
    loc: int = 0
    params: int = 0
    returns: int = 0

    # Fingerprints of this unit's shape, used for near-duplicate detection.
    shingles: frozenset[int] = field(default=frozenset(), repr=False, compare=False)

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qualname}"

    def debt(self) -> float:
        """Normalized structural debt for this unit.

        Each metric contributes its *fractional overage* past the threshold, so
        a function at 20 cyclomatic against a threshold of 10 contributes 1.0
        before weighting. A unit under every threshold contributes exactly 0.0.
        """
        total = 0.0
        for name, threshold in THRESHOLDS.items():
            value = getattr(self, name)
            if value > threshold:
                total += WEIGHTS[name] * (value - threshold) / threshold
        return round(total, 4)

    def exceeded(self) -> dict[str, tuple[int, int]]:
        """Metrics over threshold, as {metric: (value, threshold)}."""
        return {
            name: (getattr(self, name), threshold)
            for name, threshold in THRESHOLDS.items()
            if getattr(self, name) > threshold
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("shingles", None)
        d["debt"] = self.debt()
        return d


def _decision_points(node: ast.AST) -> int:
    """McCabe cyclomatic complexity contribution of a single node."""
    if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.For, ast.AsyncFor)):
        return 1
    if isinstance(node, ast.ExceptHandler):
        return 1
    if isinstance(node, ast.Assert):
        return 1
    if isinstance(node, ast.BoolOp):
        # `a and b and c` is two decisions, not one.
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.match_case):
        return 1
    return 0


class _UnitWalker(ast.NodeVisitor):
    """Walks one code unit's body, stopping at nested function boundaries.

    Nested functions are measured as their own units rather than folded into the
    parent, so a parent does not inherit debt for code it merely encloses.
    """

    def __init__(self, root: ast.AST):
        self.root = root
        self.cyclomatic = 1
        self.cognitive = 0
        self.max_nesting = 0
        self.returns = 0
        self._nesting = 0

    # Constructs that both cost cognitive load and deepen nesting for children.
    _NESTING = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Match,
    )
    # Constructs that add cognitive load scaled by how deep they already are.
    _COGNITIVE_NESTED = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.Match)

    def visit(self, node: ast.AST):
        if node is not self.root and isinstance(node, _FUNC_NODES + (ast.ClassDef,)):
            # Boundary of another unit: do not descend.
            return

        if node is not self.root:
            self.cyclomatic += _decision_points(node)

            if isinstance(node, self._COGNITIVE_NESTED):
                # Base cost of 1, plus 1 for every level of nesting it sits in.
                self.cognitive += 1 + self._nesting
            elif isinstance(node, ast.BoolOp):
                # Mixed boolean sequences cost 1 regardless of depth.
                self.cognitive += 1
            elif isinstance(node, (ast.Break, ast.Continue)):
                self.cognitive += 1

            if isinstance(node, ast.Return):
                self.returns += 1

        deepens = node is not self.root and isinstance(node, self._NESTING)
        if deepens:
            self._nesting += 1
            self.max_nesting = max(self.max_nesting, self._nesting)

        # `else` on an if is a branch a reader must track, but ast models it as a
        # nested If in the orelse list, so elif chains would otherwise be free.
        if isinstance(node, ast.If) and node.orelse:
            is_elif = len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If)
            if not is_elif:
                self.cognitive += 1

        for child in ast.iter_child_nodes(node):
            self.visit(child)

        if deepens:
            self._nesting -= 1


def _count_loc(source_lines: list[str], start: int, end: int) -> int:
    """Source lines in [start, end], excluding blanks and comment-only lines."""
    count = 0
    for raw in source_lines[start - 1 : end]:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


def _param_count(node: ast.AST) -> int:
    if not isinstance(node, _FUNC_NODES):
        return 0
    a = node.args
    total = len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)
    if a.vararg:
        total += 1
    if a.kwarg:
        total += 1
    # `self` / `cls` are not choices the author made.
    if a.args and a.args[0].arg in ("self", "cls"):
        total -= 1
    return total


def _iter_units(tree: ast.Module) -> Iterator[tuple[ast.AST, str, str]]:
    """Yield (node, qualname, kind) for every measurable unit in a module."""

    def walk(node: ast.AST, prefix: str, in_class: bool):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _FUNC_NODES):
                qualname = f"{prefix}{child.name}"
                yield child, qualname, "method" if in_class else "function"
                yield from walk(child, f"{qualname}.", False)
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.", True)

    yield from walk(tree, "", False)


def analyze_source(path: str, source: str) -> tuple[list[Unit], str | None]:
    """Extract every unit from one file.

    Returns (units, error). A syntax error yields ([], message) rather than
    raising -- a gate that crashes on one bad file is a gate nobody turns on.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [], f"{path}: syntax error at line {exc.lineno}: {exc.msg}"

    lines = source.splitlines()
    units: list[Unit] = []

    for node, qualname, kind in _iter_units(tree):
        walker = _UnitWalker(node)
        walker.visit(node)
        start = node.lineno
        end = getattr(node, "end_lineno", None) or start
        units.append(
            Unit(
                qualname=qualname,
                path=path,
                lineno=start,
                end_lineno=end,
                kind=kind,
                cyclomatic=walker.cyclomatic,
                cognitive=walker.cognitive,
                max_nesting=walker.max_nesting,
                loc=_count_loc(lines, start, end),
                params=_param_count(node),
                returns=walker.returns,
            )
        )

    return units, None
