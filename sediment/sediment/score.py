"""Erosion attribution and the ratchet.

The central idea: judge a change by the debt it *adds*, not by the absolute
state of the code it lands in. Absolute thresholds are why quality gates get
switched off -- point one at a decade-old codebase and everything fails on day
one, so the team disables it and learns nothing. A marginal measure works on
any codebase from the first commit, because the question it asks is only ever
"is this change making it worse".
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .analyze import Snapshot
from .duplication import ClonePair
from .metrics import Unit
from .slop import Finding

BASELINE_PATH = os.path.join(".sediment", "baseline.json")

# Debt added per 100 changed lines, above which a change is called eroding.
# Calibrated so a change that adds one function sitting moderately over a
# single threshold passes, while one that adds several does not.
DEFAULT_MAX_EROSION_RATE = 1.5

# A near-duplicate pair introduced by the change is worth this much debt.
CLONE_DEBT = 1.0


@dataclass
class UnitDelta:
    key: str
    before: float
    after: float

    @property
    def delta(self) -> float:
        return round(self.after - self.before, 4)


@dataclass
class ErosionReport:
    base: str
    head: str

    added_units: list[Unit] = field(default_factory=list)
    worsened: list[UnitDelta] = field(default_factory=list)
    improved: list[UnitDelta] = field(default_factory=list)
    removed_debt_units: list[str] = field(default_factory=list)

    new_findings: list[Finding] = field(default_factory=list)
    fixed_findings: list[Finding] = field(default_factory=list)
    new_clones: list[ClonePair] = field(default_factory=list)

    added_loc: int = 0
    ratchet_violations: dict[str, tuple[float, float]] = field(default_factory=dict)

    @property
    def debt_added(self) -> float:
        structural = sum(u.debt() for u in self.added_units)
        structural += sum(d.delta for d in self.worsened)
        slop = sum(f.weight for f in self.new_findings)
        clones = CLONE_DEBT * len(self.new_clones)
        return round(structural + slop + clones, 4)

    @property
    def debt_removed(self) -> float:
        structural = sum(-d.delta for d in self.improved)
        slop = sum(f.weight for f in self.fixed_findings)
        return round(structural + slop, 4)

    @property
    def net_erosion(self) -> float:
        return round(self.debt_added - self.debt_removed, 4)

    @property
    def erosion_rate(self) -> float:
        """Net debt added per 100 lines added.

        Normalizing by change size is what makes the number comparable across a
        one-line fix and a thousand-line feature. Small changes are measured
        against a floor so a 3-line change that adds a 40-branch function is
        not flattered by its own size.
        """
        denominator = max(self.added_loc, 20) / 100
        return round(self.net_erosion / denominator, 4)

    def verdict(self, max_rate: float = DEFAULT_MAX_EROSION_RATE) -> str:
        if self.ratchet_violations:
            return "fail"
        if self.erosion_rate > max_rate:
            return "fail"
        if self.net_erosion > 0:
            return "warn"
        return "pass"

    def to_dict(self, max_rate: float = DEFAULT_MAX_EROSION_RATE) -> dict:
        return {
            "base": self.base,
            "head": self.head,
            "verdict": self.verdict(max_rate),
            "added_loc": self.added_loc,
            "debt_added": self.debt_added,
            "debt_removed": self.debt_removed,
            "net_erosion": self.net_erosion,
            "erosion_rate": self.erosion_rate,
            "max_erosion_rate": max_rate,
            "added_units": [u.to_dict() for u in self.added_units],
            "worsened": [
                {"unit": d.key, "before": d.before, "after": d.after, "delta": d.delta}
                for d in self.worsened
            ],
            "improved": [
                {"unit": d.key, "before": d.before, "after": d.after, "delta": d.delta}
                for d in self.improved
            ],
            "new_findings": [f.to_dict() for f in self.new_findings],
            "fixed_findings": [f.to_dict() for f in self.fixed_findings],
            "new_clones": [c.to_dict() for c in self.new_clones],
            "ratchet_violations": {
                path: {"baseline": base, "current": current}
                for path, (base, current) in self.ratchet_violations.items()
            },
        }


def _finding_id(f: Finding) -> tuple[str, str, str]:
    # Line numbers shift for reasons unrelated to the finding, so identity is
    # (file, kind, detail) -- stable under unrelated edits above it.
    return (f.path, f.kind, f.detail)


def _clone_id(c: ClonePair) -> tuple[str, str]:
    return tuple(sorted((c.left, c.right)))  # type: ignore[return-value]


def compare(
    before: Snapshot,
    after: Snapshot,
    touched_files: set[str],
    added_loc: int,
    base_label: str = "base",
    head_label: str = "head",
) -> ErosionReport:
    """Attribute the difference between two snapshots to the change itself.

    Only units and findings in files the change touched are considered, so
    unrelated drift elsewhere in the repo never lands on this change's bill.
    """
    report = ErosionReport(base=base_label, head=head_label, added_loc=added_loc)

    def in_scope(path: str) -> bool:
        return not touched_files or path in touched_files

    before_units = {k: u for k, u in before.units.items() if in_scope(u.path)}
    after_units = {k: u for k, u in after.units.items() if in_scope(u.path)}

    for key, unit in after_units.items():
        prior = before_units.get(key)
        if prior is None:
            if unit.debt() > 0:
                report.added_units.append(unit)
        else:
            delta = UnitDelta(key, prior.debt(), unit.debt())
            if delta.delta > 0:
                report.worsened.append(delta)
            elif delta.delta < 0:
                report.improved.append(delta)

    for key, unit in before_units.items():
        if key not in after_units and unit.debt() > 0:
            report.removed_debt_units.append(key)
            report.improved.append(UnitDelta(key, unit.debt(), 0.0))

    before_findings = {
        _finding_id(f): f for f in before.findings if in_scope(f.path)
    }
    after_findings = {_finding_id(f): f for f in after.findings if in_scope(f.path)}

    report.new_findings = [f for k, f in after_findings.items() if k not in before_findings]
    report.fixed_findings = [f for k, f in before_findings.items() if k not in after_findings]

    before_clones = {_clone_id(c) for c in before.clones}
    report.new_clones = [
        c
        for c in after.clones
        if _clone_id(c) not in before_clones
        and (in_scope(c.left.split("::")[0]) or in_scope(c.right.split("::")[0]))
    ]

    report.added_units.sort(key=lambda u: u.debt(), reverse=True)
    report.worsened.sort(key=lambda d: d.delta, reverse=True)
    report.improved.sort(key=lambda d: d.delta)
    report.new_findings.sort(key=lambda f: f.weight, reverse=True)

    return report


# -- ratchet ---------------------------------------------------------------


def load_baseline(repo: str) -> dict[str, float]:
    path = os.path.join(repo, BASELINE_PATH)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: float(v) for k, v in data.get("files", {}).items()}
    except (OSError, ValueError):
        return {}


def save_baseline(repo: str, snapshot: Snapshot, ref: str) -> str:
    path = os.path.join(repo, BASELINE_PATH)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "version": 1,
        "ref": ref,
        "summary": snapshot.summary(),
        "files": snapshot.debt_by_file(),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def check_ratchet(
    baseline: dict[str, float],
    after: Snapshot,
    touched_files: set[str],
    tolerance: float = 0.0,
) -> dict[str, tuple[float, float]]:
    """Files whose debt rose above their recorded baseline.

    Files absent from the baseline are new and cannot violate it; they are
    governed by the erosion rate instead.
    """
    violations: dict[str, tuple[float, float]] = {}
    current = after.debt_by_file()

    for path in sorted(touched_files):
        if path not in baseline:
            continue
        recorded = baseline[path]
        now = current.get(path, 0.0)
        if now > recorded + tolerance:
            violations[path] = (recorded, round(now, 4))

    return violations
