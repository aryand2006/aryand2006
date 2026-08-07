"""Performance metrics computed from an equity curve.

Deliberately plain definitions. The point of this project is that the *spread*
in these numbers across implementations is large; using an exotic estimator
would just add a second explanation for the spread.
"""

from __future__ import annotations

import numpy as np

TRADING_DAYS = 252


def total_return(equity: np.ndarray) -> float:
    if equity[0] == 0:
        return 0.0
    return float(equity[-1] / equity[0] - 1.0)


def cagr(equity: np.ndarray, periods_per_year: int = TRADING_DAYS) -> float:
    years = len(equity) / periods_per_year
    if years <= 0 or equity[0] <= 0 or equity[-1] <= 0:
        return 0.0
    return float((equity[-1] / equity[0]) ** (1.0 / years) - 1.0)


def volatility(equity: np.ndarray, periods_per_year: int = TRADING_DAYS) -> float:
    r = _returns(equity)
    if r.size < 2:
        return 0.0
    return float(np.std(r, ddof=1) * np.sqrt(periods_per_year))


def sharpe(equity: np.ndarray, periods_per_year: int = TRADING_DAYS) -> float:
    """Annualized Sharpe at a zero risk-free rate.

    Returns 0.0 for a flat curve rather than a divide-by-zero, since a strategy
    that never moves has no risk-adjusted return to report.
    """
    r = _returns(equity)
    if r.size < 2:
        return 0.0
    sd = np.std(r, ddof=1)
    if sd <= 1e-15:
        return 0.0
    return float(np.mean(r) / sd * np.sqrt(periods_per_year))


def max_drawdown(equity: np.ndarray) -> float:
    """Largest peak-to-trough decline, as a positive fraction."""
    peak = np.maximum.accumulate(equity)
    safe = np.where(peak > 0, peak, 1.0)
    drawdown = equity / safe - 1.0
    return float(-drawdown.min())


def _returns(equity: np.ndarray) -> np.ndarray:
    if equity.size < 2:
        return np.zeros(0)
    prior = np.where(equity[:-1] == 0, 1.0, equity[:-1])
    return equity[1:] / prior - 1.0


METRICS = {
    "sharpe": sharpe,
    "total_return": total_return,
    "cagr": cagr,
    "volatility": volatility,
    "max_drawdown": max_drawdown,
}


def evaluate(equity: np.ndarray) -> dict[str, float]:
    return {name: fn(equity) for name, fn in METRICS.items()}
