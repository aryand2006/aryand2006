"""Implementation-risk metrics and per-axis attribution.

The four summary metrics follow the framing of Yin et al. (2026),
*Implementation Risk in Portfolio Backtesting: A Previously Unquantified Source
of Error* (arXiv:2603.20319), which established that identical strategies run
through different engines agree exactly at zero transaction cost and diverge
systematically once costs are switched on.

The exact formulas in that paper were not reachable when this was written, so
the operationalizations below are this project's own and are stated explicitly
rather than presented as the authors'. The attribution in the second half is not
from the paper at all: it is the part that turns "results diverge" into "results
diverge *because of this decision*", which is the actionable form.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .spec import AXES, ExecutionSpec


@dataclass(frozen=True)
class Divergence:
    """Spread of one metric across a full factorial of implementation choices."""

    metric: str
    values: np.ndarray
    labels: list[str]

    @property
    def engine_spread(self) -> float:
        """ES -- the full range. The honest headline: how wrong you can be."""
        return float(self.values.max() - self.values.min())

    @property
    def relative_spread(self) -> float:
        """ES scaled by the mean magnitude, so it compares across metrics."""
        scale = float(np.abs(self.values).mean())
        if scale <= 1e-15:
            return 0.0
        return self.engine_spread / scale

    def uncertainty_interval(self, lower: float = 5.0, upper: float = 95.0) -> tuple[float, float]:
        """IUI -- a robust interval, so one pathological config cannot define it."""
        return (
            float(np.percentile(self.values, lower)),
            float(np.percentile(self.values, upper)),
        )

    @property
    def best(self) -> tuple[str, float]:
        i = int(np.argmax(self.values))
        return self.labels[i], float(self.values[i])

    @property
    def worst(self) -> tuple[str, float]:
        i = int(np.argmin(self.values))
        return self.labels[i], float(self.values[i])

    def conclusion_sensitivity(self, threshold: float) -> float:
        """CSI -- how unstable a yes/no verdict is across implementations.

        0.0 means every configuration agrees on whether the metric clears the
        threshold. 1.0 means the configurations split evenly, so the decision is
        determined entirely by which library was used.
        """
        if self.values.size == 0:
            return 0.0
        above = float(np.mean(self.values > threshold))
        return float(2.0 * min(above, 1.0 - above))

    def summary(self, threshold: float | None = None) -> dict:
        lo, hi = self.uncertainty_interval()
        out = {
            "metric": self.metric,
            "n_configs": int(self.values.size),
            "mean": float(self.values.mean()),
            "median": float(np.median(self.values)),
            "min": float(self.values.min()),
            "max": float(self.values.max()),
            "engine_spread": self.engine_spread,
            "relative_spread": self.relative_spread,
            "iui_5_95": [lo, hi],
            "best_config": self.best[0],
            "worst_config": self.worst[0],
        }
        if threshold is not None:
            out["threshold"] = threshold
            out["conclusion_sensitivity"] = self.conclusion_sensitivity(threshold)
        return out


def amplification(spreads_by_cost: dict[float, float]) -> dict[float, float]:
    """DAF -- how divergence grows as the cost regime intensifies.

    Normalized against the smallest nonzero cost level, because at zero cost the
    spread is exactly zero by construction and a ratio against it is undefined.
    Reported as "divergence at this cost level is N times the divergence at the
    lightest one".
    """
    nonzero = sorted(c for c in spreads_by_cost if c > 0)
    if not nonzero:
        return {c: 0.0 for c in spreads_by_cost}

    base_cost = nonzero[0]
    base = spreads_by_cost[base_cost]
    if base <= 1e-15:
        return {c: 0.0 for c in spreads_by_cost}

    return {c: spreads_by_cost[c] / base for c in sorted(spreads_by_cost)}


def attribute(
    specs: list[ExecutionSpec], values: np.ndarray, axes: dict[str, tuple] | None = None
) -> dict[str, float]:
    """Share of the outcome variance explained by each implementation axis.

    A one-way main-effect decomposition. Because the design is a *full* factorial
    -- every option of every axis appears with every combination of the others --
    the axes are balanced and orthogonal, so these shares are directly
    comparable and their shortfall from 1.0 is the interaction between axes.

    Returns eta-squared per axis plus an "interaction" remainder.
    """
    axes = axes or AXES
    if values.size == 0:
        return {}

    grand_mean = float(values.mean())
    total_ss = float(np.sum((values - grand_mean) ** 2))
    if total_ss <= 1e-30:
        return {axis: 0.0 for axis in axes} | {"interaction": 0.0}

    shares: dict[str, float] = {}
    explained = 0.0

    for axis in axes:
        groups: dict[str, list[int]] = {}
        for i, spec in enumerate(specs):
            groups.setdefault(getattr(spec, axis), []).append(i)

        axis_ss = 0.0
        for indices in groups.values():
            group_mean = float(values[indices].mean())
            axis_ss += len(indices) * (group_mean - grand_mean) ** 2

        share = axis_ss / total_ss
        shares[axis] = share
        explained += share

    shares["interaction"] = max(0.0, 1.0 - explained)
    return shares


def condition_on(
    specs: list[ExecutionSpec],
    values: np.ndarray,
    axis: str,
    keep: tuple[str, ...],
) -> tuple[list[ExecutionSpec], np.ndarray]:
    """Restrict to specs whose `axis` is one of `keep`, preserving balance.

    Filtering a full factorial on a single axis leaves every other axis still
    fully crossed, so attribution on the subset remains exact. This is what
    separates a genuine modeling difference from a level difference: one axis
    can dominate simply because one of its options switches a cost off, and
    conditioning it away shows what is left.
    """
    indices = [i for i, s in enumerate(specs) if getattr(s, axis) in keep]
    return [specs[i] for i in indices], values[indices]


def axis_effect(
    specs: list[ExecutionSpec], values: np.ndarray, axis: str
) -> dict[str, float]:
    """Mean outcome for each option of one axis, for reading the direction."""
    groups: dict[str, list[int]] = {}
    for i, spec in enumerate(specs):
        groups.setdefault(getattr(spec, axis), []).append(i)
    return {
        option: float(values[indices].mean())
        for option, indices in sorted(groups.items())
    }
