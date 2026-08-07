"""Rendering."""

from __future__ import annotations

from . import divergence
from .spec import AXES
from .sweep import Sweep


def _fmt(value: float, metric: str) -> str:
    if metric in ("total_return", "cagr", "volatility", "max_drawdown"):
        return f"{value * 100:+.2f}%"
    return f"{value:.3f}"


def render_sweep(sweep: Sweep, metric: str = "sharpe", threshold: float | None = None) -> str:
    header = "  cost      mean        min         max        spread     rel    DAF"
    if threshold is not None:
        header += "    CSI"

    lines = [
        f"parallax  {sweep.strategy_name}   metric={metric}",
        f"  turnover {sweep.turnover:.1f}x   "
        f"{len(sweep.runs[0].specs)} implementations per cost level",
        "",
        header,
        "  " + "-" * (len(header) - 2),
    ]

    amp = sweep.amplification(metric)
    flagged = False
    for run in sweep.runs:
        d = run.divergence_of(metric)
        daf = amp.get(run.cost_bps, 0.0)
        daf_text = "  --  " if run.cost_bps == 0 else f"{daf:5.2f}x"

        # Relative spread is normalized by the mean, so it is not meaningful once
        # the mean is smaller than the spread -- at that point the *sign* of the
        # result is implementation-dependent, which the marker calls out rather
        # than dressing up as a percentage.
        rel = d.relative_spread
        if rel > 1.0:
            rel_text = f"{rel:5.0%}*"
            flagged = True
        else:
            rel_text = f"{rel:5.1%} "

        row = (
            f"  {run.cost_bps:5.1f}bp  "
            f"{_fmt(float(d.values.mean()), metric):>9}  "
            f"{_fmt(float(d.values.min()), metric):>10}  "
            f"{_fmt(float(d.values.max()), metric):>10}  "
            f"{_fmt(d.engine_spread, metric):>10}  "
            f"{rel_text} {daf_text}"
        )
        if threshold is not None:
            row += f"  {d.conclusion_sensitivity(threshold):5.2f}"
        lines.append(row)

    if flagged:
        lines.append("  * spread exceeds the mean: the sign itself is implementation-dependent")

    if threshold is not None:
        flips = [
            run for run in sweep.runs
            if run.divergence_of(metric).conclusion_sensitivity(threshold) > 0
        ]
        if flips:
            lines += ["", f"  '{metric} > {threshold}' is decided by implementation at:"]
            for run in flips:
                d = run.divergence_of(metric)
                lines.append(
                    f"    {run.cost_bps:5.1f}bp   "
                    f"[{_fmt(float(d.values.min()), metric)}, "
                    f"{_fmt(float(d.values.max()), metric)}]   "
                    f"CSI {d.conclusion_sensitivity(threshold):.2f}"
                )
        else:
            lines += ["", f"  '{metric} > {threshold}': every implementation agrees at every cost level"]

    worst = max(sweep.runs, key=lambda r: r.divergence_of(metric).engine_spread)
    d = worst.divergence_of(metric)
    lo, hi = d.uncertainty_interval()

    lines += [
        "",
        f"  at {worst.cost_bps:.0f}bp the same strategy on the same data reports",
        f"  {metric} anywhere in [{_fmt(float(d.values.min()), metric)}, "
        f"{_fmt(float(d.values.max()), metric)}]   (5-95%: "
        f"[{_fmt(lo, metric)}, {_fmt(hi, metric)}])",
    ]

    shares = divergence.attribute(worst.specs, d.values)
    ranked = sorted(
        ((k, v) for k, v in shares.items() if k != "interaction"),
        key=lambda kv: kv[1],
        reverse=True,
    )

    lines += ["", f"  what drives the spread at {worst.cost_bps:.0f}bp"]
    for axis, share in ranked:
        bar = "#" * int(round(share * 40))
        lines.append(f"    {share:6.1%}  {axis:<18} {bar}")
    lines.append(f"    {shares['interaction']:6.1%}  {'interaction':<18}")

    if ranked and ranked[0][1] > 0:
        top_axis = ranked[0][0]
        effects = divergence.axis_effect(worst.specs, d.values, top_axis)
        lines += ["", f"  {top_axis} in detail"]
        for option, mean in sorted(effects.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"    {_fmt(mean, metric):>10}   {option}")

    # Whether an engine models slippage at all is a difference in how much cost
    # is charged, not in how it is modelled, and it is large enough to hide
    # everything else. Conditioning on it being modelled shows the rest.
    modelled = tuple(o for o in AXES["slippage"] if o != "none")
    sub_specs, sub_values = divergence.condition_on(
        worst.specs, d.values, "slippage", modelled
    )
    if len(sub_specs) > 1:
        sub_shares = divergence.attribute(sub_specs, sub_values)
        sub_ranked = sorted(
            ((k, v) for k, v in sub_shares.items() if k not in ("interaction", "slippage")),
            key=lambda kv: kv[1],
            reverse=True,
        )
        sub_spread = float(sub_values.max() - sub_values.min())
        lines += [
            "",
            f"  among the {len(sub_specs)} implementations that model slippage at all",
            f"  (spread narrows to {_fmt(sub_spread, metric)})",
        ]
        for axis, share in sub_ranked:
            bar = "#" * int(round(share * 40))
            lines.append(f"    {share:6.1%}  {axis:<18} {bar}")
        lines.append(f"    {sub_shares['slippage']:6.1%}  {'slippage (shape)':<18}")

    return "\n".join(lines)


def render_comparison(sweeps: dict[str, Sweep], metric: str, cost_bps: float) -> str:
    """Cross-strategy view: does implementation risk scale with turnover?"""
    lines = [
        f"parallax  implementation risk vs turnover   metric={metric}  cost={cost_bps:.0f}bp",
        "",
        "  strategy            turnover      mean       spread    rel spread",
        "  " + "-" * 62,
    ]

    rows = []
    for name, sweep in sweeps.items():
        run = sweep.by_cost(cost_bps)
        d = run.divergence_of(metric)
        rows.append((sweep.turnover, name, float(d.values.mean()), d.engine_spread, d.relative_spread))

    for turnover, name, mean, spread, rel in sorted(rows):
        lines.append(
            f"  {name:<18}  {turnover:8.1f}x  {_fmt(mean, metric):>9}  "
            f"{_fmt(spread, metric):>10}  {rel:9.1%}"
        )

    return "\n".join(lines)


def render_axes() -> str:
    lines = ["parallax  implementation axes", ""]
    total = 1
    for axis, options in AXES.items():
        total *= len(options)
        lines.append(f"  {axis:<16} {', '.join(options)}")
    lines += ["", f"  {total} distinct implementations"]
    return "\n".join(lines)
