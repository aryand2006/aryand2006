import numpy as np
import pytest

from parallax import data, strategy, sweep
from parallax.divergence import Divergence, amplification, attribute, axis_effect
from parallax.spec import ExecutionSpec, enumerate_specs


def make_divergence(values, metric="sharpe"):
    values = np.asarray(values, dtype=float)
    return Divergence(metric, values, [f"c{i}" for i in range(values.size)])


def test_engine_spread_is_the_range():
    d = make_divergence([1.0, 1.5, 2.0])
    assert d.engine_spread == pytest.approx(1.0)


def test_relative_spread_normalizes_by_magnitude():
    small = make_divergence([0.1, 0.2])
    large = make_divergence([10.1, 10.2])
    assert small.engine_spread == pytest.approx(large.engine_spread)
    assert small.relative_spread > large.relative_spread


def test_identical_values_have_no_spread():
    d = make_divergence([1.25] * 8)
    assert d.engine_spread == 0.0
    assert d.relative_spread == 0.0
    assert d.conclusion_sensitivity(1.0) == 0.0


def test_conclusion_sensitivity_is_zero_when_all_agree():
    d = make_divergence([1.4, 1.5, 1.6])
    assert d.conclusion_sensitivity(1.0) == 0.0   # all above
    assert d.conclusion_sensitivity(2.0) == 0.0   # all below


def test_conclusion_sensitivity_is_one_on_an_even_split():
    d = make_divergence([0.5, 0.6, 1.4, 1.5])
    assert d.conclusion_sensitivity(1.0) == pytest.approx(1.0)


def test_uncertainty_interval_excludes_outliers():
    values = [1.0] * 98 + [-50.0, 50.0]
    d = make_divergence(values)
    lo, hi = d.uncertainty_interval()
    assert -50.0 < lo <= 1.0 <= hi < 50.0


def test_amplification_is_relative_to_lightest_nonzero_cost():
    amp = amplification({0.0: 0.0, 10.0: 0.2, 50.0: 1.0})
    assert amp[10.0] == pytest.approx(1.0)
    assert amp[50.0] == pytest.approx(5.0)


def test_amplification_survives_a_zero_baseline():
    amp = amplification({0.0: 0.0, 10.0: 0.0, 50.0: 0.0})
    assert all(v == 0.0 for v in amp.values())


def test_attribution_finds_the_axis_that_drives_the_outcome():
    """Construct values that depend only on fill_timing; attribution must say so."""
    specs = enumerate_specs(cost_bps=10.0)
    offsets = {"signal_close": 3.0, "next_open": 0.0, "next_close": -3.0}
    values = np.array([offsets[s.fill_timing] for s in specs])

    shares = attribute(specs, values)
    assert shares["fill_timing"] == pytest.approx(1.0)
    for axis in ("cost_basis", "slippage", "rounding", "min_trade", "cash_yield"):
        assert shares[axis] == pytest.approx(0.0, abs=1e-9)
    assert shares["interaction"] == pytest.approx(0.0, abs=1e-9)


def test_attribution_splits_between_two_contributing_axes():
    specs = enumerate_specs(cost_bps=10.0)
    fill = {"signal_close": 1.0, "next_open": 0.0, "next_close": -1.0}
    rounding = {"fractional": 1.0, "whole_shares": -1.0}
    values = np.array([fill[s.fill_timing] + rounding[s.rounding] for s in specs])

    shares = attribute(specs, values)
    assert shares["fill_timing"] > 0.1
    assert shares["rounding"] > 0.1
    assert shares["fill_timing"] + shares["rounding"] == pytest.approx(1.0, abs=1e-9)


def test_attribution_of_constant_values_is_all_zero():
    specs = enumerate_specs(cost_bps=10.0)
    shares = attribute(specs, np.full(len(specs), 2.5))
    assert all(v == 0.0 for v in shares.values())


def test_axis_effect_reports_direction():
    specs = enumerate_specs(cost_bps=10.0)
    offsets = {"signal_close": 3.0, "next_open": 0.0, "next_close": -3.0}
    values = np.array([offsets[s.fill_timing] for s in specs])

    effects = axis_effect(specs, values, "fill_timing")
    assert effects["signal_close"] > effects["next_open"] > effects["next_close"]


def test_condition_on_keeps_the_design_balanced():
    """Filtering one axis must leave every other axis fully crossed."""
    from parallax.divergence import condition_on
    from parallax.spec import AXES

    specs = enumerate_specs(cost_bps=10.0)
    values = np.arange(len(specs), dtype=float)
    kept, kept_values = condition_on(specs, values, "slippage", ("fixed_bps", "sqrt_participation"))

    assert len(kept) == len(kept_values)
    assert {s.slippage for s in kept} == {"fixed_bps", "sqrt_participation"}
    for axis, options in AXES.items():
        if axis == "slippage":
            continue
        counts = {o: sum(1 for s in kept if getattr(s, axis) == o) for o in options}
        assert len(set(counts.values())) == 1, f"{axis} unbalanced after conditioning"


def test_conditioning_removes_the_axis_that_only_set_a_level():
    """An axis whose effect is one option being zero should vanish once dropped."""
    from parallax.divergence import condition_on

    specs = enumerate_specs(cost_bps=10.0)
    # slippage="none" is worth +10; the other two are identical.
    values = np.array([10.0 if s.slippage == "none" else 0.0 for s in specs])

    assert attribute(specs, values)["slippage"] == pytest.approx(1.0)

    kept, kept_values = condition_on(specs, values, "slippage", ("fixed_bps", "sqrt_participation"))
    assert float(kept_values.max() - kept_values.min()) == pytest.approx(0.0)


def test_sweep_reports_zero_spread_at_zero_cost_for_cost_axes():
    """End to end: the control holds through the whole sweep pipeline."""
    market = data.generate(n_days=300, n_assets=10, seed=11)
    result = sweep.run_strategy(market, "momentum", cost_levels=(0.0, 25.0))

    zero = result.by_cost(0.0)
    assert all(r.total_cost == 0.0 for r in zero.results)

    # And divergence grows once costs are on.
    assert (
        result.by_cost(25.0).divergence_of("sharpe").engine_spread > 0.0
    )


def test_implementation_risk_increases_with_turnover():
    """The central hypothesis, tested end to end."""
    market = data.generate(n_days=500, n_assets=12, seed=13)
    low = sweep.run_strategy(market, "buy_and_hold", cost_levels=(25.0,))
    high = sweep.run_strategy(market, "momentum_daily", cost_levels=(25.0,))

    assert high.turnover > low.turnover
    low_spread = low.by_cost(25.0).divergence_of("total_return").engine_spread
    high_spread = high.by_cost(25.0).divergence_of("total_return").engine_spread
    assert high_spread > low_spread
