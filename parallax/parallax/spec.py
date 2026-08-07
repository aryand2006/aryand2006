"""The axes along which backtest engines legitimately disagree.

None of these choices is wrong. Each is defensible, each is made by at least one
widely-used backtesting library, and each is usually undocumented. Together they
define the space of results a single strategy can produce on a single dataset --
which is the thing this project measures.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, asdict, fields
from typing import Iterator

# Each axis maps to the options a reasonable engine might implement.
AXES: dict[str, tuple] = {
    # When a signal computed from bar t actually gets filled. Vectorized engines
    # commonly fill at the close of the signal bar; event-driven engines usually
    # cannot, and fill at the next bar.
    "fill_timing": ("signal_close", "next_open", "next_close"),

    # How commission is charged. Proportional-to-notional is the common default;
    # charging a half-spread crossing is the more microstructurally honest model
    # and gives a different answer whenever the spread is not constant.
    "cost_basis": ("notional", "half_spread"),

    # Price concession on top of commission.
    "slippage": ("none", "fixed_bps", "sqrt_participation"),

    # Whether the engine can hold fractional shares. Whole-share rounding turns a
    # continuous weight target into a discrete one, which matters most for small
    # accounts and high-priced assets.
    "rounding": ("fractional", "whole_shares"),

    # Whether tiny rebalances are executed or suppressed. Engines that suppress
    # them report lower turnover and higher returns for identical signals.
    "min_trade": ("none", "10bps"),

    # Whether idle cash earns the risk-free rate.
    "cash_yield": ("none", "riskfree"),
}


@dataclass(frozen=True)
class ExecutionSpec:
    """One fully-specified set of implementation choices."""

    fill_timing: str = "next_open"
    cost_basis: str = "notional"
    slippage: str = "fixed_bps"
    rounding: str = "fractional"
    min_trade: str = "none"
    cash_yield: str = "none"

    # Cost intensity in basis points, held fixed across a comparison so that
    # divergence is attributable to the choices above rather than to the level.
    cost_bps: float = 10.0

    def label(self) -> str:
        return "|".join(
            f"{f.name}={getattr(self, f.name)}"
            for f in fields(self)
            if f.name != "cost_bps"
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> None:
        for axis, options in AXES.items():
            value = getattr(self, axis)
            if value not in options:
                raise ValueError(
                    f"{axis}={value!r} is not one of {options}"
                )


def enumerate_specs(cost_bps: float, axes: dict[str, tuple] | None = None) -> list[ExecutionSpec]:
    """Every combination of implementation choices at one cost level.

    This is the population the divergence metrics are computed over. It is a full
    factorial rather than a sample so that per-axis attribution is exact: every
    option of every axis appears with every combination of the others.
    """
    axes = axes or AXES
    names = list(axes)
    specs = []
    for combo in itertools.product(*(axes[n] for n in names)):
        specs.append(ExecutionSpec(cost_bps=cost_bps, **dict(zip(names, combo))))
    return specs


def spec_count(axes: dict[str, tuple] | None = None) -> int:
    axes = axes or AXES
    total = 1
    for options in axes.values():
        total *= len(options)
    return total


def iter_axis_values(specs: list[ExecutionSpec], axis: str) -> Iterator[tuple[str, list[int]]]:
    """Yield (option, indices of specs using it) for one axis."""
    groups: dict[str, list[int]] = {}
    for i, spec in enumerate(specs):
        groups.setdefault(getattr(spec, axis), []).append(i)
    yield from groups.items()
