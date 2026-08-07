"""Running the factorial and collecting results."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import divergence, engine, metrics, strategy
from .data import Market
from .spec import ExecutionSpec, enumerate_specs

# Cost regimes in basis points. Zero is included as a control: every
# configuration must agree exactly there, which is what proves the divergence
# at higher levels comes from the cost model and nothing else.
DEFAULT_COST_LEVELS = (0.0, 5.0, 10.0, 25.0, 50.0)


@dataclass
class CostLevelRun:
    cost_bps: float
    specs: list[ExecutionSpec]
    results: list[engine.Result]
    metric_values: dict[str, np.ndarray] = field(default_factory=dict)

    def divergence_of(self, metric: str) -> divergence.Divergence:
        return divergence.Divergence(
            metric=metric,
            values=self.metric_values[metric],
            labels=[s.label() for s in self.specs],
        )

    @property
    def turnover(self) -> float:
        return float(np.mean([r.turnover for r in self.results]))


@dataclass
class Sweep:
    strategy_name: str
    runs: list[CostLevelRun]

    def by_cost(self, cost_bps: float) -> CostLevelRun:
        for run in self.runs:
            if run.cost_bps == cost_bps:
                return run
        raise KeyError(f"no run at {cost_bps} bps")

    def spreads(self, metric: str) -> dict[float, float]:
        return {r.cost_bps: r.divergence_of(metric).engine_spread for r in self.runs}

    def amplification(self, metric: str) -> dict[float, float]:
        return divergence.amplification(self.spreads(metric))

    @property
    def turnover(self) -> float:
        """Turnover is a property of the strategy, so report it once."""
        return float(np.mean([r.turnover for r in self.runs]))


def run_strategy(
    market: Market,
    strategy_name: str,
    cost_levels: tuple[float, ...] = DEFAULT_COST_LEVELS,
    capital: float = 1_000_000.0,
) -> Sweep:
    """Run one strategy through every implementation choice at every cost level."""
    signals = strategy.build(strategy_name, market)

    # Calibrated once per strategy, so every configuration in the sweep charges
    # the same average cost and the axes differ only in how they distribute it.
    reference = engine.calibrate_participation(market, signals, capital)

    runs: list[CostLevelRun] = []

    for cost_bps in cost_levels:
        specs = enumerate_specs(cost_bps)
        results = [
            engine.run(market, signals, spec, capital, reference_participation=reference)
            for spec in specs
        ]

        metric_values = {
            name: np.array([fn(r.equity) for r in results])
            for name, fn in metrics.METRICS.items()
        }
        runs.append(
            CostLevelRun(
                cost_bps=cost_bps,
                specs=specs,
                results=results,
                metric_values=metric_values,
            )
        )

    return Sweep(strategy_name=strategy_name, runs=runs)


def run_all(
    market: Market,
    strategy_names: list[str] | None = None,
    cost_levels: tuple[float, ...] = DEFAULT_COST_LEVELS,
) -> dict[str, Sweep]:
    names = strategy_names or list(strategy.REGISTRY)
    return {name: run_strategy(market, name, cost_levels) for name in names}
