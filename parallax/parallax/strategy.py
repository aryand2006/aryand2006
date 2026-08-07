"""Strategies, expressed as target weights on rebalance days.

A strategy here is deliberately *only* a signal: it says what the portfolio
should look like and when it should be reshaped, and says nothing about how the
trades get done. Everything about how is an implementation choice, and lives in
the spec. Keeping that line clean is what lets the same strategy run unchanged
through every configuration.

The set spans a turnover range on purpose, because the central hypothesis is
that implementation risk is a function of turnover.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .data import Market


@dataclass(frozen=True)
class Signals:
    targets: np.ndarray    # (T, N) desired weights, valid where rebalance is True
    rebalance: np.ndarray  # (T,) bool
    name: str


def _empty(market: Market, name: str) -> tuple[np.ndarray, np.ndarray]:
    return (
        np.zeros((market.n_days, market.n_assets)),
        np.zeros(market.n_days, dtype=bool),
    )


def buy_and_hold(market: Market) -> Signals:
    """Equal weight once, then never trade again. The turnover floor."""
    targets, rebalance = _empty(market, "buy_and_hold")
    targets[0] = 1.0 / market.n_assets
    rebalance[0] = True
    return Signals(targets, rebalance, "buy_and_hold")


def equal_weight(market: Market, every: int = 21) -> Signals:
    """Rebalance back to equal weight monthly. Turnover comes only from drift."""
    targets, rebalance = _empty(market, "equal_weight")
    targets[:] = 1.0 / market.n_assets
    rebalance[::every] = True
    return Signals(targets, rebalance, f"equal_weight_{every}d")


def _cross_sectional(
    market: Market,
    score: np.ndarray,
    every: int,
    top_k: int,
    name: str,
    long_short: bool = False,
) -> Signals:
    targets, rebalance = _empty(market, name)
    n = market.n_assets
    top_k = min(top_k, n // 2 if long_short else n)

    for t in range(0, market.n_days, every):
        row = score[t]
        if not np.isfinite(row).any():
            continue
        order = np.argsort(np.where(np.isfinite(row), row, -np.inf))
        longs = order[-top_k:]
        weights = np.zeros(n)
        if long_short:
            shorts = order[:top_k]
            weights[longs] = 0.5 / top_k
            weights[shorts] = -0.5 / top_k
        else:
            weights[longs] = 1.0 / top_k
        targets[t] = weights
        rebalance[t] = True

    return Signals(targets, rebalance, name)


def momentum(market: Market, lookback: int = 60, every: int = 21, top_k: int = 8) -> Signals:
    """Buy the trailing winners. Moderate turnover.

    The score at t uses closes up to and including t, and the engine never fills
    before t, so there is no lookahead regardless of the fill-timing choice.
    """
    close = market.close
    score = np.full_like(close, np.nan)
    score[lookback:] = close[lookback:] / close[:-lookback] - 1.0
    return _cross_sectional(market, score, every, top_k, f"momentum_{lookback}d", False)


def momentum_fast(market: Market, lookback: int = 20, every: int = 5, top_k: int = 8) -> Signals:
    """The same idea on a shorter clock, long and short. High turnover.

    Deliberately the *same* signal family as `momentum` rather than its inverse.
    An anti-momentum strategy in a momentum-driven market loses for reasons that
    have nothing to do with execution, which would confound the measurement --
    what this experiment needs from a strategy is turnover, not a different sign.
    """
    close = market.close
    score = np.full_like(close, np.nan)
    score[lookback:] = close[lookback:] / close[:-lookback] - 1.0
    return _cross_sectional(market, score, every, top_k, f"momentum_fast_{every}d", True)


def momentum_daily(market: Market, lookback: int = 10, top_k: int = 8) -> Signals:
    """Reshaped every single day. The turnover ceiling."""
    close = market.close
    score = np.full_like(close, np.nan)
    score[lookback:] = close[lookback:] / close[:-lookback] - 1.0
    return _cross_sectional(market, score, 1, top_k, "momentum_daily", True)


REGISTRY: dict[str, Callable[[Market], Signals]] = {
    "buy_and_hold": buy_and_hold,
    "equal_weight": equal_weight,
    "momentum": momentum,
    "momentum_fast": momentum_fast,
    "momentum_daily": momentum_daily,
}


def build(name: str, market: Market) -> Signals:
    if name not in REGISTRY:
        raise KeyError(f"unknown strategy {name!r}; have {sorted(REGISTRY)}")
    return REGISTRY[name](market)
