"""The reference engine.

One simulator, parameterized by an ExecutionSpec. This is the design decision
the whole project rests on: comparing five third-party libraries confounds the
cost model with everything else they differ on -- data alignment, corporate
actions, rounding of the accounting itself. Running one auditable engine across
the space of implementation choices isolates the variable, so divergence can be
*attributed* rather than merely observed.

Cost models are normalized to a common mean so that `cost_bps` sets the level
and the spec sets only the shape. Two consequences, both deliberate:

* At `cost_bps = 0` every configuration produces bit-identical equity curves.
  That reproduces the control from the source paper and is asserted in the tests.
* Any divergence at nonzero cost is attributable to *how* the cost is
  distributed across time and assets, never to how much of it there is.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import Market
from .spec import ExecutionSpec
from .strategy import Signals

# Fallback participation level at which the square-root impact model returns its
# reference cost, used only when calibration is unavailable. In normal use this
# is replaced by a per-run calibration -- see `calibrate_participation`.
REFERENCE_PARTICIPATION = 1e-3

# Slippage is charged at half the commission level, so the two components stay
# comparable as cost_bps is swept.
SLIPPAGE_FRACTION = 0.5


@dataclass
class Result:
    equity: np.ndarray       # (T,) mark-to-market equity at each close
    turnover: float          # total traded notional / mean equity
    total_cost: float        # all commission and slippage paid
    n_trades: int
    spec: ExecutionSpec
    strategy: str

    def returns(self) -> np.ndarray:
        out = np.zeros_like(self.equity)
        out[1:] = self.equity[1:] / self.equity[:-1] - 1.0
        return out


def _fill_schedule(
    signals: Signals, market: Market, timing: str
) -> list[tuple[int, int, np.ndarray]]:
    """(fill_day, signal_day, fill_price) for each rebalance, in order.

    Rebalances whose fill day would fall past the end of the sample are dropped
    rather than silently filled at the last bar, which would be a lookahead.
    """
    schedule = []
    last = market.n_days - 1

    for signal_day in np.flatnonzero(signals.rebalance):
        signal_day = int(signal_day)
        if timing == "signal_close":
            fill_day, price = signal_day, market.close[signal_day]
        elif timing == "next_open":
            fill_day = signal_day + 1
            if fill_day > last:
                continue
            price = market.open_[fill_day]
        elif timing == "next_close":
            fill_day = signal_day + 1
            if fill_day > last:
                continue
            price = market.close[fill_day]
        else:
            raise ValueError(f"unknown fill_timing {timing!r}")
        schedule.append((fill_day, signal_day, price))

    return schedule


def _commission_rate(
    spec: ExecutionSpec, market: Market, fill_day: int
) -> np.ndarray:
    """Per-asset commission rate as a fraction of traded notional.

    Both models are scaled to the same sample-average rate, so switching between
    them changes the distribution of cost across assets and days without
    changing the total budget.
    """
    level = spec.cost_bps / 1e4
    if level == 0.0:
        return np.zeros(market.n_assets)

    if spec.cost_basis == "notional":
        return np.full(market.n_assets, level)

    if spec.cost_basis == "half_spread":
        half = market.spread_bps[fill_day] / 2.0
        mean_half = market.spread_bps.mean() / 2.0
        if mean_half <= 0:
            return np.full(market.n_assets, level)
        return level * half / mean_half

    raise ValueError(f"unknown cost_basis {spec.cost_basis!r}")


def _slippage_rate(
    spec: ExecutionSpec,
    market: Market,
    fill_day: int,
    traded_notional: np.ndarray,
    reference_participation: float = REFERENCE_PARTICIPATION,
) -> np.ndarray:
    """Per-asset slippage rate as a fraction of traded notional."""
    level = spec.cost_bps / 1e4 * SLIPPAGE_FRACTION
    if level == 0.0 or spec.slippage == "none":
        return np.zeros(market.n_assets)

    if spec.slippage == "fixed_bps":
        return np.full(market.n_assets, level)

    if spec.slippage == "sqrt_participation":
        volume = np.maximum(market.dollar_volume[fill_day], 1.0)
        participation = traded_notional / volume
        return level * np.sqrt(participation / reference_participation)

    raise ValueError(f"unknown slippage {spec.slippage!r}")


def calibrate_participation(
    market: Market, signals: Signals, capital: float = 1_000_000.0
) -> float:
    """Notional-weighted mean participation for this strategy on this data.

    Used as the reference point for the square-root impact model so that it
    charges the *same average* as the flat model, leaving only the shape of the
    cost -- concentrated on large trades in thin names -- to differ. Without
    this, switching slippage models silently changes the cost budget, and the
    attribution reports a level difference dressed up as a modeling difference.

    Calibration runs the strategy once at zero cost. Trade sizes depend on costs
    only through their effect on equity, which is second order, so a costless
    pass is an accurate schedule to calibrate against.
    """
    probe = ExecutionSpec(cost_bps=0.0, slippage="none")
    schedule = _fill_schedule(signals, market, probe.fill_timing)
    by_day = {f: (s, p) for f, s, p in schedule}

    shares = np.zeros(market.n_assets)
    cash = float(capital)
    weighted_sum = 0.0
    total_notional = 0.0

    for t in range(market.n_days):
        if t in by_day:
            signal_day, price = by_day[t]
            price = np.maximum(price, 1e-8)
            equity_now = cash + float(shares @ price)
            desired = signals.targets[signal_day] * equity_now / price
            delta = desired - shares
            traded = np.abs(delta) * price

            volume = np.maximum(market.dollar_volume[t], 1.0)
            participation = traded / volume
            weighted_sum += float((participation * traded).sum())
            total_notional += float(traded.sum())

            cash -= float(delta @ price)
            shares = desired

    if total_notional <= 0:
        return REFERENCE_PARTICIPATION
    return max(weighted_sum / total_notional, 1e-9)


def run(
    market: Market,
    signals: Signals,
    spec: ExecutionSpec,
    capital: float = 1_000_000.0,
    reference_participation: float | None = None,
) -> Result:
    """Simulate one strategy under one set of implementation choices.

    `reference_participation` calibrates the square-root impact model to charge
    the same average as the flat one; pass the value from
    `calibrate_participation` so the slippage axis measures shape rather than
    level. Callers that omit it get the nominal constant, which is fine for a
    single run but not for a comparison.
    """
    spec.validate()
    if reference_participation is None:
        reference_participation = REFERENCE_PARTICIPATION

    n_assets = market.n_assets
    shares = np.zeros(n_assets)
    cash = float(capital)

    equity = np.empty(market.n_days)
    total_cost = 0.0
    total_traded = 0.0
    n_trades = 0

    schedule = _fill_schedule(signals, market, spec.fill_timing)
    by_day: dict[int, tuple[int, np.ndarray]] = {
        fill_day: (signal_day, price) for fill_day, signal_day, price in schedule
    }

    min_trade_frac = 10e-4 if spec.min_trade == "10bps" else 0.0

    for t in range(market.n_days):
        if t in by_day:
            signal_day, price = by_day[t]
            price = np.maximum(price, 1e-8)

            # Equity available at the moment of the fill.
            equity_now = cash + float(shares @ price)
            desired_notional = signals.targets[signal_day] * equity_now
            desired_shares = desired_notional / price

            if spec.rounding == "whole_shares":
                desired_shares = np.trunc(desired_shares)

            delta = desired_shares - shares

            if min_trade_frac > 0.0:
                too_small = np.abs(delta) * price < min_trade_frac * equity_now
                delta = np.where(too_small, 0.0, delta)

            traded_notional = np.abs(delta) * price

            commission = _commission_rate(spec, market, t) * traded_notional
            slippage = (
                _slippage_rate(spec, market, t, traded_notional, reference_participation)
                * traded_notional
            )
            costs = float(commission.sum() + slippage.sum())

            cash -= float(delta @ price) + costs
            shares = shares + delta

            total_cost += costs
            total_traded += float(traded_notional.sum())
            n_trades += int(np.count_nonzero(delta))

        if spec.cash_yield == "riskfree" and cash > 0.0:
            cash *= 1.0 + market.riskfree_daily

        equity[t] = cash + float(shares @ market.close[t])

    mean_equity = float(np.mean(equity)) or 1.0
    return Result(
        equity=equity,
        turnover=total_traded / mean_equity,
        total_cost=total_cost,
        n_trades=n_trades,
        spec=spec,
        strategy=signals.name,
    )
