import numpy as np
import pytest

from parallax import data, engine, metrics, strategy
from parallax.spec import AXES, ExecutionSpec, enumerate_specs, spec_count


@pytest.fixture(scope="module")
def market():
    return data.generate(n_days=400, n_assets=12, seed=7)


def test_zero_cost_makes_every_implementation_agree_on_cost(market):
    """The control from the source paper: no cost, no cost-driven divergence.

    Fill timing and rounding still change the portfolio itself, so equity curves
    are not identical -- but every configuration must pay exactly zero.
    """
    signals = strategy.build("momentum", market)
    for spec in enumerate_specs(cost_bps=0.0):
        result = engine.run(market, signals, spec)
        assert result.total_cost == 0.0


def test_zero_cost_identical_curves_when_only_cost_axes_vary(market):
    """Holding the portfolio-shaping axes fixed, cost axes must not matter at 0bp."""
    signals = strategy.build("momentum", market)
    base = ExecutionSpec(cost_bps=0.0, fill_timing="next_open", rounding="fractional",
                         min_trade="none", cash_yield="none")
    reference = engine.run(market, signals, base)

    for cost_basis in AXES["cost_basis"]:
        for slippage in AXES["slippage"]:
            variant = ExecutionSpec(
                cost_bps=0.0,
                fill_timing="next_open",
                rounding="fractional",
                min_trade="none",
                cash_yield="none",
                cost_basis=cost_basis,
                slippage=slippage,
            )
            result = engine.run(market, signals, variant)
            assert np.allclose(result.equity, reference.equity, rtol=0, atol=1e-9)


def test_cost_models_share_a_budget_but_not_a_distribution(market):
    """Both commission models charge a comparable total, distributed differently."""
    signals = strategy.build("momentum", market)
    flat = engine.run(market, signals, ExecutionSpec(cost_bps=20.0, cost_basis="notional",
                                                     slippage="none"))
    spread = engine.run(market, signals, ExecutionSpec(cost_bps=20.0, cost_basis="half_spread",
                                                       slippage="none"))
    assert flat.total_cost > 0 and spread.total_cost > 0
    # Same order of magnitude by construction...
    assert 0.5 < spread.total_cost / flat.total_cost < 2.0
    # ...but genuinely different, or the axis would be measuring nothing.
    assert not np.allclose(flat.equity, spread.equity)


def test_higher_cost_never_increases_equity(market):
    signals = strategy.build("momentum_fast", market)
    spec_kwargs = dict(fill_timing="next_open", cost_basis="notional", slippage="fixed_bps")
    curves = [
        engine.run(market, signals, ExecutionSpec(cost_bps=c, **spec_kwargs)).equity[-1]
        for c in (0.0, 10.0, 50.0)
    ]
    assert curves[0] >= curves[1] >= curves[2]


def test_buy_and_hold_has_almost_no_implementation_risk(market):
    """One trade at the start means nothing downstream can disagree much."""
    signals = strategy.build("buy_and_hold", market)
    finals = [
        engine.run(market, signals, spec).equity[-1]
        for spec in enumerate_specs(cost_bps=25.0)
    ]
    spread = (max(finals) - min(finals)) / np.mean(finals)
    assert spread < 0.02


def test_daily_rebalancing_has_large_implementation_risk(market):
    """Rebalancing every day compounds every implementation difference."""
    signals = strategy.build("momentum_daily", market)
    finals = [
        engine.run(market, signals, spec).equity[-1]
        for spec in enumerate_specs(cost_bps=25.0)
    ]
    spread = (max(finals) - min(finals)) / np.mean(finals)
    assert spread > 0.05


def test_no_lookahead_when_filling_at_next_bar(market):
    """A signal must never fill before the bar that generated it."""
    signals = strategy.build("momentum", market)
    schedule = engine._fill_schedule(signals, market, "next_open")
    assert schedule
    for fill_day, signal_day, _ in schedule:
        assert fill_day > signal_day


def test_rebalance_past_the_end_of_sample_is_dropped(market):
    """A signal on the final bar cannot fill at the next one, so it is skipped."""
    signals = strategy.build("momentum_daily", market)
    same_bar = engine._fill_schedule(signals, market, "signal_close")
    next_bar = engine._fill_schedule(signals, market, "next_open")
    assert len(next_bar) == len(same_bar) - 1


def test_whole_share_rounding_never_exceeds_fractional_position(market):
    signals = strategy.build("equal_weight", market)
    frac = engine.run(market, signals, ExecutionSpec(cost_bps=0.0, rounding="fractional"))
    whole = engine.run(market, signals, ExecutionSpec(cost_bps=0.0, rounding="whole_shares"))
    # Truncation can only leave cash uninvested, so it cannot be more invested.
    assert whole.equity[-1] <= frac.equity[-1] * 1.001


def test_min_trade_threshold_reduces_turnover(market):
    signals = strategy.build("equal_weight", market)
    without = engine.run(market, signals, ExecutionSpec(cost_bps=10.0, min_trade="none"))
    with_min = engine.run(market, signals, ExecutionSpec(cost_bps=10.0, min_trade="10bps"))
    assert with_min.turnover <= without.turnover


def test_cash_yield_helps_only_when_cash_is_idle(market):
    signals = strategy.build("buy_and_hold", market)
    off = engine.run(market, signals, ExecutionSpec(cost_bps=0.0, cash_yield="none"))
    on = engine.run(market, signals, ExecutionSpec(cost_bps=0.0, cash_yield="riskfree"))
    assert on.equity[-1] >= off.equity[-1]


def test_invalid_spec_is_rejected(market):
    signals = strategy.build("momentum", market)
    with pytest.raises(ValueError, match="fill_timing"):
        engine.run(market, signals, ExecutionSpec(fill_timing="teleport"))


def test_factorial_is_complete_and_balanced():
    specs = enumerate_specs(cost_bps=10.0)
    assert len(specs) == spec_count()
    for axis, options in AXES.items():
        counts = {o: 0 for o in options}
        for spec in specs:
            counts[getattr(spec, axis)] += 1
        assert len(set(counts.values())) == 1, f"{axis} is unbalanced"


def test_equity_is_finite_for_every_implementation(market):
    for name in strategy.REGISTRY:
        signals = strategy.build(name, market)
        for spec in enumerate_specs(cost_bps=50.0):
            result = engine.run(market, signals, spec)
            assert np.all(np.isfinite(result.equity)), f"{name} / {spec.label()}"


def test_metrics_handle_a_flat_curve():
    flat = np.full(100, 1000.0)
    assert metrics.sharpe(flat) == 0.0
    assert metrics.max_drawdown(flat) == 0.0
    assert metrics.total_return(flat) == 0.0
