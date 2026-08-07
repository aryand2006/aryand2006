"""Command line interface.

    parallax axes                  show the implementation space
    parallax run --strategy X      sweep one strategy across implementations
    parallax compare               implementation risk across the turnover range
"""

from __future__ import annotations

import argparse
import json
import sys

from . import data, report, strategy, sweep
from .divergence import attribute

EXIT_OK, EXIT_ERROR = 0, 2


def _market(args: argparse.Namespace) -> data.Market:
    return data.generate(
        n_days=args.days,
        n_assets=args.assets,
        seed=args.seed,
    )


def cmd_axes(args: argparse.Namespace) -> int:
    print(report.render_axes())
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    if args.strategy not in strategy.REGISTRY:
        print(
            f"unknown strategy {args.strategy!r}; have {sorted(strategy.REGISTRY)}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    market = _market(args)
    result = sweep.run_strategy(market, args.strategy, cost_levels=tuple(args.costs))

    if args.json:
        worst = max(
            result.runs, key=lambda r: r.divergence_of(args.metric).engine_spread
        )
        d = worst.divergence_of(args.metric)
        payload = {
            "strategy": result.strategy_name,
            "metric": args.metric,
            "turnover": result.turnover,
            "seed": args.seed,
            "by_cost": [
                run.divergence_of(args.metric).summary(args.threshold)
                | {"cost_bps": run.cost_bps}
                for run in result.runs
            ],
            "amplification": {str(k): v for k, v in result.amplification(args.metric).items()},
            "attribution": attribute(worst.specs, d.values),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(report.render_sweep(result, args.metric, args.threshold))

    return EXIT_OK


def cmd_compare(args: argparse.Namespace) -> int:
    market = _market(args)
    sweeps = sweep.run_all(market, cost_levels=(args.cost,))

    if args.json:
        payload = {
            name: {
                "turnover": s.turnover,
                **s.by_cost(args.cost).divergence_of(args.metric).summary(args.threshold),
            }
            for name, s in sweeps.items()
        }
        print(json.dumps(payload, indent=2))
    else:
        print(report.render_comparison(sweeps, args.metric, args.cost))

    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parallax",
        description="Measure how much a backtest result depends on implementation choices.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--days", type=int, default=1260, help="trading days (default: 5y)")
        p.add_argument("--assets", type=int, default=30)
        p.add_argument("--seed", type=int, default=20260806)
        p.add_argument("--metric", default="sharpe")
        p.add_argument("--json", action="store_true")

    axes = sub.add_parser("axes", help="show the implementation space")
    axes.set_defaults(func=cmd_axes)

    run = sub.add_parser("run", help="sweep one strategy across implementations")
    common(run)
    run.add_argument("--strategy", default="momentum")
    run.add_argument(
        "--costs",
        type=float,
        nargs="+",
        default=list(sweep.DEFAULT_COST_LEVELS),
        help="cost regimes in bps; include 0 as a control",
    )
    run.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="report conclusion sensitivity against this value",
    )
    run.set_defaults(func=cmd_run)

    compare = sub.add_parser("compare", help="implementation risk across strategies")
    common(compare)
    compare.add_argument("--cost", type=float, default=25.0)
    compare.add_argument("--threshold", type=float, default=None)
    compare.set_defaults(func=cmd_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
