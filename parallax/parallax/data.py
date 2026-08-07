"""Market data: a controlled synthetic generator, and a loader for real files.

The synthetic generator exists because a controlled data-generating process is
the right instrument for this question. Implementation risk is a property of the
*interaction* between a strategy's turnover and an engine's cost model, and
isolating that interaction needs the ability to vary volatility, spread, and
liquidity independently -- which a single historical sample cannot do.

Every series is a deterministic function of the seed, so any result here is
reproducible exactly by anyone, with no data vendor in the loop.

`load_csv` takes real OHLCV when you have it; nothing downstream knows or cares
which source it came from.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 252


@dataclass
class Market:
    """Aligned price, spread and volume panels for a set of assets."""

    dates: np.ndarray          # (T,) integer day index
    symbols: list[str]
    open_: np.ndarray          # (T, N)
    close: np.ndarray          # (T, N)
    spread_bps: np.ndarray     # (T, N) quoted half-spread in bps
    dollar_volume: np.ndarray  # (T, N)
    riskfree_daily: float = 0.0

    @property
    def n_days(self) -> int:
        return self.close.shape[0]

    @property
    def n_assets(self) -> int:
        return self.close.shape[1]

    def returns(self) -> np.ndarray:
        """Close-to-close simple returns, first row zero."""
        out = np.zeros_like(self.close)
        out[1:] = self.close[1:] / self.close[:-1] - 1.0
        return out


def generate(
    n_days: int = 1260,
    n_assets: int = 30,
    seed: int = 20260806,
    annual_vol: float = 0.28,
    annual_drift: float = 0.10,
    alpha_scale: float = 0.0022,
    reversal_scale: float = 0.15,
    market_beta_spread: float = 0.6,
    base_spread_bps: float = 4.0,
    tail_df: float = 4.0,
) -> Market:
    """A synthetic multi-asset market with the features that drive cost models.

    Three properties are deliberately reproduced because each one changes what a
    cost model does:

    * **Volatility clustering** (GARCH-like), so spread and impact are not
      constant through time and a spread-crossing cost model separates from a
      flat-bps one.
    * **Fat tails** (Student-t innovations), so the extreme days that dominate
      turnover are actually present.
    * **A common market factor**, so cross-sectional strategies produce the
      correlated, concentrated rebalances that make fill timing matter.
    """
    rng = np.random.default_rng(seed)

    daily_vol = annual_vol / np.sqrt(TRADING_DAYS)

    # Volatility clustering: a GARCH(1,1)-style recursion on the market factor.
    omega, alpha, beta = 0.05, 0.10, 0.85
    market_var = np.empty(n_days)
    market_shock = np.empty(n_days)
    var = 1.0
    for t in range(n_days):
        innovation = rng.standard_t(tail_df) / np.sqrt(tail_df / (tail_df - 2))
        shock = np.sqrt(var) * innovation
        market_var[t] = var
        market_shock[t] = shock
        var = omega + alpha * shock**2 + beta * var

    betas = 1.0 + market_beta_spread * (rng.random(n_assets) - 0.5) * 2
    idio_scale = rng.uniform(0.6, 1.5, n_assets)

    idio = rng.standard_t(tail_df, size=(n_days, n_assets))
    idio /= np.sqrt(tail_df / (tail_df - 2))
    idio *= idio_scale

    # A slow-moving latent expected return per asset. Without it the market is
    # unpredictable by construction, every strategy loses money net of costs,
    # and the interesting question -- whether an implementation choice flips a
    # go/no-go verdict -- can never arise. Persistence is high enough that a
    # trailing-return signal partially recovers it, and the scale is set so a
    # perfect-foresight version earns a plausible rather than absurd Sharpe.
    alpha_persistence = 0.98
    alpha = np.empty((n_days, n_assets))
    state = rng.normal(0.0, 1.0, n_assets)
    for t in range(n_days):
        state = alpha_persistence * state + np.sqrt(1 - alpha_persistence**2) * rng.normal(
            0.0, 1.0, n_assets
        )
        alpha[t] = state
    expected = alpha_scale * alpha

    # An equity risk premium. Without one the whole panel is a driftless random
    # walk, every long-only strategy is a coin flip, and a single unlucky seed
    # makes buy-and-hold lose money over five years -- which is not the market
    # any of these engines were built to simulate.
    drift = annual_drift / TRADING_DAYS

    # Transient price pressure: a displacement in the *level* of log price that
    # decays over a few days, which is what a liquidity provider gets paid to
    # absorb. Its contribution to returns is the day-over-day change, so returns
    # inherit short-horizon negative autocorrelation without the panel becoming
    # a one-day bounce that a daily strategy can harvest perfectly.
    pressure_decay = 0.7
    pressure = np.empty((n_days, n_assets))
    level = np.zeros(n_assets)
    for t in range(n_days):
        level = pressure_decay * level + rng.standard_normal(n_assets)
        pressure[t] = level

    transient = np.zeros((n_days, n_assets))
    transient[1:] = reversal_scale * daily_vol * (pressure[1:] - pressure[:-1])

    total = (
        drift
        + expected
        + transient
        + daily_vol * (market_shock[:, None] * betas[None, :] + idio) / np.sqrt(2.0)
    )

    close = 100.0 * np.exp(np.cumsum(total, axis=0))
    close *= rng.uniform(0.4, 3.0, n_assets)  # varied price levels

    # Opens gap from the prior close by a fraction of the day's move, which is
    # what makes next_open and next_close genuinely different fills.
    gap = rng.normal(0.0, 0.3, size=(n_days, n_assets)) * daily_vol
    open_ = np.empty_like(close)
    open_[0] = close[0] * (1.0 + gap[0])
    open_[1:] = close[:-1] * (1.0 + gap[1:])

    # Spread widens with realized volatility -- the mechanism that separates a
    # half-spread cost model from a flat-bps one.
    realized = np.sqrt(np.maximum(market_var, 1e-8))
    vol_factor = realized / realized.mean()
    spread_bps = base_spread_bps * vol_factor[:, None] * rng.uniform(0.5, 2.0, n_assets)[None, :]
    spread_bps = np.clip(spread_bps, 0.5, 100.0)

    # Dollar volume is lognormal, mean-reverting, and inversely related to spread.
    liquidity = rng.lognormal(mean=16.0, sigma=1.0, size=n_assets)
    volume_noise = rng.lognormal(0.0, 0.35, size=(n_days, n_assets))
    dollar_volume = liquidity[None, :] * volume_noise / vol_factor[:, None]

    return Market(
        dates=np.arange(n_days),
        symbols=[f"A{i:02d}" for i in range(n_assets)],
        open_=open_,
        close=close,
        spread_bps=spread_bps,
        dollar_volume=dollar_volume,
        riskfree_daily=0.02 / TRADING_DAYS,
    )


def load_csv(paths: dict[str, str], spread_bps: float = 4.0) -> Market:
    """Load real OHLCV from per-symbol CSVs.

    Expects a header containing at least `date`, `open`, `close`, and optionally
    `volume`. Rows are intersected across symbols on date so the panel is
    aligned. Where a file carries no spread, a flat quoted spread is assumed and
    that assumption is recorded rather than hidden -- it is itself one of the
    implementation choices this project is about.
    """
    per_symbol: dict[str, dict[str, tuple[float, float, float]]] = {}

    for symbol, path in paths.items():
        rows: dict[str, tuple[float, float, float]] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldmap = {k.lower().strip(): k for k in (reader.fieldnames or [])}
            for required in ("date", "open", "close"):
                if required not in fieldmap:
                    raise ValueError(f"{path}: missing required column {required!r}")
            for row in reader:
                date = row[fieldmap["date"]].strip()
                try:
                    o = float(row[fieldmap["open"]])
                    c = float(row[fieldmap["close"]])
                except (TypeError, ValueError):
                    continue
                v = 0.0
                if "volume" in fieldmap:
                    try:
                        v = float(row[fieldmap["volume"]]) * c
                    except (TypeError, ValueError):
                        v = 0.0
                rows[date] = (o, c, v)
        per_symbol[symbol] = rows

    symbols = sorted(per_symbol)
    if not symbols:
        raise ValueError("no symbols supplied")

    common = set.intersection(*(set(per_symbol[s]) for s in symbols))
    if not common:
        raise ValueError("symbols share no common dates")
    ordered = sorted(common)

    n_days, n_assets = len(ordered), len(symbols)
    open_ = np.empty((n_days, n_assets))
    close = np.empty((n_days, n_assets))
    volume = np.empty((n_days, n_assets))

    for j, symbol in enumerate(symbols):
        rows = per_symbol[symbol]
        for i, date in enumerate(ordered):
            o, c, v = rows[date]
            open_[i, j], close[i, j], volume[i, j] = o, c, v

    # Fall back to a nominal turnover figure where volume is absent, so
    # participation-based slippage still has a denominator.
    volume[volume <= 0] = np.median(volume[volume > 0]) if (volume > 0).any() else 1e9

    return Market(
        dates=np.arange(n_days),
        symbols=symbols,
        open_=open_,
        close=close,
        spread_bps=np.full((n_days, n_assets), spread_bps),
        dollar_volume=volume,
        riskfree_daily=0.0,
    )
