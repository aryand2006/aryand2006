"""Near-duplicate detection over AST shape.

Agents copy-paste and then rename. Text-based clone detection misses that
entirely, and so does anything keyed on identifiers. So the fingerprint here is
built from the *node-type stream* of a function with all names and literal
values erased -- two functions that differ only in what things are called
produce byte-identical fingerprints.

The similarity measure is Jaccard over k-gram shingle sets, compared through an
inverted index so the cost is proportional to actual shingle collisions rather
than to the square of the unit count.
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from .metrics import Unit

# Length of the node-type k-gram. Long enough that trivial shapes (a bare
# `return x`) do not collide; short enough to catch a copied 10-line helper.
SHINGLE_K = 8

# Jaccard similarity at or above which two units are called near-duplicates.
CLONE_THRESHOLD = 0.80

# Units smaller than this produce too few shingles to judge honestly.
MIN_UNIT_LOC = 6


def _node_token(node: ast.AST) -> str:
    """A name- and value-blind token for one AST node.

    Operators are kept because `+` vs `-` is a real behavioural difference, but
    identifiers, attribute names, constants and argument names are all erased.
    """
    name = type(node).__name__
    if isinstance(node, ast.BinOp):
        return f"BinOp:{type(node.op).__name__}"
    if isinstance(node, ast.UnaryOp):
        return f"UnaryOp:{type(node.op).__name__}"
    if isinstance(node, ast.BoolOp):
        return f"BoolOp:{type(node.op).__name__}"
    if isinstance(node, ast.Compare):
        ops = ",".join(type(o).__name__ for o in node.ops)
        return f"Compare:{ops}"
    if isinstance(node, ast.Constant):
        # Keep the type, drop the value: 1 and 9999 are the same shape.
        return f"Const:{type(node.value).__name__}"
    return name


def _token_stream(node: ast.AST) -> list[str]:
    """Depth-first node-type stream for a unit, excluding nested unit bodies."""
    tokens: list[str] = []

    def walk(current: ast.AST, is_root: bool) -> None:
        if not is_root and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            # Nested units are fingerprinted separately.
            return
        tokens.append(_node_token(current))
        for child in ast.iter_child_nodes(current):
            walk(child, False)

    walk(node, True)
    return tokens


def _hash_shingle(tokens: tuple[str, ...]) -> int:
    digest = hashlib.blake2b("\x1f".join(tokens).encode(), digest_size=8)
    return int.from_bytes(digest.digest(), "big")


def shingles_for(node: ast.AST) -> frozenset[int]:
    """Hashed k-gram shingle set describing one unit's shape."""
    tokens = _token_stream(node)
    if len(tokens) < SHINGLE_K:
        return frozenset()
    return frozenset(
        _hash_shingle(tuple(tokens[i : i + SHINGLE_K]))
        for i in range(len(tokens) - SHINGLE_K + 1)
    )


@dataclass(frozen=True)
class ClonePair:
    left: str
    right: str
    similarity: float

    def to_dict(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "similarity": round(self.similarity, 3),
        }


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    if not intersection:
        return 0.0
    return intersection / len(a | b)


def find_clones(
    units: list[Unit], threshold: float = CLONE_THRESHOLD
) -> list[ClonePair]:
    """All near-duplicate unit pairs, strongest first.

    Uses an inverted shingle index to avoid the all-pairs comparison: only units
    that share at least one shingle are ever scored against each other.
    """
    candidates = [
        u for u in units if u.shingles and u.loc >= MIN_UNIT_LOC
    ]

    index: dict[int, list[int]] = defaultdict(list)
    for i, unit in enumerate(candidates):
        for shingle in unit.shingles:
            index[shingle].append(i)

    # Count shared shingles per pair, so each pair is scored at most once.
    shared: dict[tuple[int, int], int] = defaultdict(int)
    for bucket in index.values():
        # A shingle appearing in a huge number of units is boilerplate, not a
        # clone signal, and would otherwise cost O(n^2) on its own.
        if len(bucket) > 40:
            continue
        for a_idx in range(len(bucket)):
            for b_idx in range(a_idx + 1, len(bucket)):
                shared[(bucket[a_idx], bucket[b_idx])] += 1

    pairs: list[ClonePair] = []
    for (i, j), overlap in shared.items():
        left, right = candidates[i], candidates[j]
        union = len(left.shingles) + len(right.shingles) - overlap
        if union <= 0:
            continue
        similarity = overlap / union
        if similarity >= threshold:
            pairs.append(ClonePair(left.key, right.key, similarity))

    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def duplicated_units(pairs: list[ClonePair]) -> set[str]:
    """Every unit key participating in at least one near-duplicate pair."""
    keys: set[str] = set()
    for pair in pairs:
        keys.add(pair.left)
        keys.add(pair.right)
    return keys
