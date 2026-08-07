# parallax

**A backtest result is not a number. It's a distribution over implementation choices.**

The same strategy, on the same data, at the same cost level, reports a different
Sharpe depending on decisions no paper states and most libraries don't document:
when a signal fills, how commission is charged, whether shares are whole.
`parallax` measures the size of that dependence and attributes it to the decisions
responsible.

```
parallax  momentum_daily   metric=sharpe
  turnover 535.7x   144 implementations per cost level

  cost      mean        min         max        spread     rel    DAF    CSI
  -------------------------------------------------------------------------
    0.0bp      3.249       2.867       3.761       0.894  27.5%    --     0.00
    5.0bp      2.225       1.704       2.971       1.267  56.9%   1.00x   0.00
   10.0bp      1.225       0.542       2.181       1.639   134%*  1.29x   0.67
   25.0bp     -1.647      -2.913      -0.180       2.733   166%*  2.16x   0.00
   50.0bp     -6.039      -8.441      -3.987       4.453  73.7%   3.51x   0.00
  * spread exceeds the mean: the sign itself is implementation-dependent

  'sharpe > 1.0' is decided by implementation at:
     10.0bp   [0.542, 2.181]   CSI 0.67
```

At 10 basis points this strategy has a Sharpe of 0.54 or 2.18 — a rejected idea
or a funded one — and which one you see is decided by your choice of library.

---

## Why

Yin et al. (2026), [*Implementation Risk in Portfolio Backtesting: A Previously
Unquantified Source of Error*](https://arxiv.org/abs/2603.20319), ran 15 strategies
through 5 independent engines over 180 S&P 500 constituents at four cost levels.
Their control result is the striking one: **at zero transaction cost every engine
agrees exactly**, and divergence appears only once costs are switched on — so the
disagreement is attributable to cost-model implementation and nothing else.

That paper measures the problem. No tool exists to measure it on *your* strategy,
which is what this is.

### The design decision

Comparing five third-party libraries confounds the cost model with everything
else they differ on — data alignment, corporate actions, the accounting itself.
So `parallax` runs **one auditable engine across the space of implementation
choices** instead. That isolates the variable, which means divergence can be
*attributed* rather than merely observed.

Six axes, each a real choice made differently by real libraries:

| Axis | Options |
|---|---|
| `fill_timing` | signal close · next open · next close |
| `cost_basis` | flat notional · half-spread crossing |
| `slippage` | none · fixed bps · square-root participation |
| `rounding` | fractional · whole shares |
| `min_trade` | none · suppress below 10bps |
| `cash_yield` | none · risk-free on idle cash |

That is **144 distinct implementations**, run as a full factorial so every option
of every axis appears with every combination of the others. The design is
balanced, so per-axis attribution is exact and the shortfall from 100% is the
interaction between axes.

### Keeping the comparison fair

Both commission models and both non-zero slippage models are **normalized to the
same sample-average cost**, with the square-root impact model calibrated per run
against the strategy's own realized participation. Without that, switching cost
models silently changes the cost *budget*, and the attribution reports a level
difference dressed up as a modeling difference — which is exactly the bug this
tool found in its own first draft, when `slippage` appeared to explain 98% of the
spread because one option simply charged 3.7× more than another.

## Metrics

- **ES** — engine spread, the full range across implementations.
- **IUI** — implementation uncertainty interval, the 5–95% band, so one
  pathological configuration cannot define the result.
- **DAF** — divergence amplification factor: how spread grows with cost
  intensity, normalized against the lightest non-zero regime.
- **CSI** — conclusion sensitivity: `0.0` when every implementation agrees on a
  yes/no verdict, `1.0` when they split evenly and the decision is made entirely
  by your choice of library.

The exact formulas in the source paper were not reachable when this was written,
so these operationalizations are this project's own and are stated as such. The
per-axis attribution is not from the paper at all — it's the part that turns
"results diverge" into "results diverge *because of this decision*".

---

## Measured

Synthetic panel, 30 assets, 1260 trading days, seed `20260806`, 25bp cost.
Every number reproducible with `parallax compare --cost 25`.

| Strategy | Turnover | Mean Sharpe | Min | Max | Spread | Relative |
|---|---|---|---|---|---|---|
| `buy_and_hold` | 1x | +0.237 | +0.233 | +0.240 | 0.007 | 2.9% |
| `equal_weight` | 5x | -0.282 | -0.290 | -0.275 | 0.015 | 5.4% |
| `momentum` | 41x | +1.114 | +1.065 | +1.170 | 0.106 | 9.5% |
| `momentum_fast` | 160x | +3.333 | +2.821 | +4.004 | 1.182 | 35.5% |
| `momentum_daily` | 536x | -1.647 | -2.913 | -0.180 | 2.733 | 165.9% |

**Implementation risk scales monotonically with turnover**, across two orders of
magnitude of it. A buy-and-hold backtest is worth trusting to three decimal
places. A daily-rebalanced one is barely worth trusting on its sign.

Two findings beyond that:

**Zero cost is not zero divergence.** The source paper's control holds for cost
models — at 0bp every configuration here pays exactly zero, and configurations
differing *only* in cost axes produce bit-identical equity curves, which the test
suite asserts. But the spread at 0bp is still **0.894 Sharpe points**, because
fill timing and share rounding change *which shares you hold*, not just what you
pay for them. Implementation risk has a portfolio-construction component that
switching costs off does not remove.

**The cost model's shape matters more than its level.** Conditioning on
implementations that model slippage at all — holding the average cost identical —
the choice between flat-bps and square-root impact still explains **95.5%** of the
remaining variance and moves Sharpe by ~3 points at high turnover. Whether you
charge cost proportionally or concentrate it on large trades in thin names is a
bigger decision than how much you charge.

---

## Install

```bash
pip install parallax-backtest      # numpy is the only dependency
```

## Use

```bash
parallax axes                                    # the implementation space
parallax run --strategy momentum --threshold 1.0 # sweep one strategy
parallax compare --cost 25                       # risk across the turnover range
parallax run --strategy momentum --json          # machine-readable
```

On your own strategy and data:

```python
from parallax import data, sweep

market = data.load_csv({"AAPL": "aapl.csv", "MSFT": "msft.csv"})
result = sweep.run_strategy(market, "momentum")
print(result.by_cost(25.0).divergence_of("sharpe").summary(threshold=1.0))
```

## Scope and limits

Stated plainly, because a measurement tool that oversells itself is worthless:

- **The headline results are on synthetic data.** This was built in an
  environment with no market data access, so the experiment is a controlled one:
  a deterministic generator with volatility clustering, fat tails, a common
  market factor, an equity risk premium, and transient price pressure. That is a
  legitimate instrument for this question — it isolates the turnover/cost
  interaction in a way one historical sample cannot — but it is **not** a claim
  about any real market. `load_csv` takes real OHLCV and everything downstream is
  identical; reproducing the table above on real data is a one-line change and is
  the first thing worth doing next.
- **One engine, not five.** This measures the space of implementation choices,
  not the specific behaviour of backtrader, vectorbt, or zipline. Those libraries
  differ on more than the axes modelled here. Adapters that map a real engine
  onto a point in this space are the natural extension.
- **The axes are not exhaustive.** Corporate actions, borrow costs, partial
  fills, and intraday queue position are all real sources of divergence and none
  are modelled.
- **Relative spread is unstable near zero.** When a mean crosses zero the ratio
  explodes; the report marks those rows rather than presenting them as clean
  percentages.
- **Thresholds and weights are conventions, not fitted values**, as are the
  synthetic generator's parameters, which were chosen to produce plausible
  pre-cost Sharpes rather than estimated from data.

## Development

```bash
pip install -e ".[dev]"
pytest      # 31 tests
```

The suite asserts the paper's control directly: every configuration pays exactly
zero at zero cost, and configurations differing only in cost axes produce
identical curves. It also tests the central hypothesis end to end — that
implementation risk rises with turnover — and that attribution recovers a known
planted effect exactly.

## License

MIT
