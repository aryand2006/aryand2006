"""Snapshot construction: turn a tree of Python files into measured state."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field

from . import gitio
from .duplication import ClonePair, find_clones, shingles_for
from .metrics import Unit, analyze_source
from .slop import Finding, analyze_slop

# Directories that are never the author's own work.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "build", "dist", ".eggs", "site-packages", ".sediment",
}


def _is_skipped(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts)


@dataclass
class Snapshot:
    """Measured state of a tree at one point in time."""

    label: str
    units: dict[str, Unit] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    clones: list[ClonePair] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    file_count: int = 0

    @property
    def total_loc(self) -> int:
        return sum(u.loc for u in self.units.values())

    @property
    def structural_debt(self) -> float:
        return round(sum(u.debt() for u in self.units.values()), 4)

    @property
    def slop_debt(self) -> float:
        return round(sum(f.weight for f in self.findings), 4)

    @property
    def total_debt(self) -> float:
        return round(self.structural_debt + self.slop_debt, 4)

    @property
    def debt_density(self) -> float:
        """Debt per 1000 lines -- the size-independent health number."""
        if not self.total_loc:
            return 0.0
        return round(self.total_debt / self.total_loc * 1000, 4)

    def debt_by_file(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for unit in self.units.values():
            totals[unit.path] = totals.get(unit.path, 0.0) + unit.debt()
        for finding in self.findings:
            totals[finding.path] = totals.get(finding.path, 0.0) + finding.weight
        return {k: round(v, 4) for k, v in totals.items()}

    def summary(self) -> dict:
        return {
            "label": self.label,
            "files": self.file_count,
            "units": len(self.units),
            "loc": self.total_loc,
            "structural_debt": self.structural_debt,
            "slop_debt": self.slop_debt,
            "total_debt": self.total_debt,
            "debt_density": self.debt_density,
            "clone_pairs": len(self.clones),
        }


def _measure(sources: dict[str, str], label: str, detect_clones: bool = True) -> Snapshot:
    snapshot = Snapshot(label=label, file_count=len(sources))

    for path, source in sources.items():
        units, error = analyze_source(path, source)
        if error:
            snapshot.errors.append(error)
            continue

        # Attach shape fingerprints for clone detection.
        try:
            tree = ast.parse(source)
            nodes = {
                (n.lineno, n.name): n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
        except SyntaxError:
            nodes = {}

        for unit in units:
            node = nodes.get((unit.lineno, unit.qualname.split(".")[-1]))
            if node is not None:
                unit.shingles = shingles_for(node)
            snapshot.units[unit.key] = unit

        snapshot.findings.extend(analyze_slop(path, source))

    if detect_clones:
        snapshot.clones = find_clones(list(snapshot.units.values()))

    return snapshot


def snapshot_at_ref(
    repo: str, ref: str, paths: list[str] | None = None, detect_clones: bool = True
) -> Snapshot:
    """Measure a tree as it existed at a git ref."""
    if paths is None:
        paths = [p for p in gitio.list_python_files(repo, ref) if not _is_skipped(p)]
    else:
        paths = [p for p in paths if not _is_skipped(p)]

    sources = gitio.read_blobs(repo, ref, paths)
    return _measure(sources, label=ref, detect_clones=detect_clones)


def snapshot_at_path(root: str, detect_clones: bool = True) -> Snapshot:
    """Measure a directory on disk, ignoring git entirely."""
    sources: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if _is_skipped(rel):
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    sources[rel] = fh.read()
            except OSError:
                continue

    return _measure(sources, label=root, detect_clones=detect_clones)
