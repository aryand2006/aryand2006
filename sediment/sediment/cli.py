"""Command line interface.

    sediment scan [path]              measure a tree as it stands
    sediment gate --base <ref>        score a change and set the exit code
    sediment ratchet --accept         record the current state as the floor
    sediment trajectory --since <ref> debt density across a commit series

Exit codes: 0 pass, 1 fail, 2 usage/environment error. A warn is exit 0 unless
--strict is given, so teams can adopt the gate in report-only mode first.
"""

from __future__ import annotations

import argparse
import json
import sys

from . import gitio
from .analyze import snapshot_at_path, snapshot_at_ref
from .report import (
    render_markdown,
    render_report,
    render_snapshot,
    render_trajectory,
)
from .score import (
    DEFAULT_MAX_EROSION_RATE,
    check_ratchet,
    compare,
    load_baseline,
    save_baseline,
)

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", default=".", help="repository root (default: .)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")


def cmd_scan(args: argparse.Namespace) -> int:
    if args.ref:
        if not gitio.is_repo(args.repo):
            print(f"not a git repository: {args.repo}", file=sys.stderr)
            return EXIT_ERROR
        snapshot = snapshot_at_ref(args.repo, args.ref)
    else:
        snapshot = snapshot_at_path(args.path or args.repo)

    if args.json:
        # summary() keeps `units` as a count; the per-unit detail goes under its
        # own key so a consumer never has to guess which shape it is getting.
        payload = snapshot.summary()
        payload["heaviest_units"] = [
            u.to_dict()
            for u in sorted(
                snapshot.units.values(), key=lambda u: u.debt(), reverse=True
            )
            if u.debt() > 0
        ]
        payload["findings"] = [f.to_dict() for f in snapshot.findings]
        payload["clones"] = [c.to_dict() for c in snapshot.clones]
        print(json.dumps(payload, indent=2))
    else:
        print(render_snapshot(snapshot, top=args.top))

    return EXIT_PASS


def cmd_gate(args: argparse.Namespace) -> int:
    repo = args.repo
    if not gitio.is_repo(repo):
        print(f"not a git repository: {repo}", file=sys.stderr)
        return EXIT_ERROR

    try:
        base = gitio.resolve(repo, args.base)
        head = gitio.resolve(repo, args.head)
        changes = gitio.changed_files(repo, base, head)
        added_loc = gitio.added_line_count(repo, base, head)
    except gitio.GitError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR

    if not changes:
        print("sediment: no Python files changed")
        return EXIT_PASS

    head_paths = [c.path for c in changes if c.status != "D"]
    base_paths = [c.old_path or c.path for c in changes if c.status != "A"]
    touched = set(head_paths)

    before = snapshot_at_ref(repo, base, paths=base_paths)
    after = snapshot_at_ref(repo, head, paths=head_paths)

    report = compare(
        before,
        after,
        touched_files=touched,
        added_loc=added_loc,
        base_label=args.base,
        head_label=args.head,
    )

    if not args.no_ratchet:
        baseline = load_baseline(repo)
        if baseline:
            report.ratchet_violations = check_ratchet(baseline, after, touched)

    if args.json:
        print(json.dumps(report.to_dict(args.max_rate), indent=2))
    elif args.markdown:
        print(render_markdown(report, args.max_rate))
    else:
        print(render_report(report, args.max_rate))

    verdict = report.verdict(args.max_rate)
    if verdict == "fail":
        return EXIT_FAIL
    if verdict == "warn" and args.strict:
        return EXIT_FAIL
    return EXIT_PASS


def cmd_ratchet(args: argparse.Namespace) -> int:
    repo = args.repo
    if not gitio.is_repo(repo):
        print(f"not a git repository: {repo}", file=sys.stderr)
        return EXIT_ERROR

    if not args.accept:
        baseline = load_baseline(repo)
        if not baseline:
            print("no baseline recorded; run `sediment ratchet --accept`")
            return EXIT_PASS
        print(f"baseline covers {len(baseline)} files")
        for path, debt in sorted(baseline.items(), key=lambda kv: -kv[1])[: args.top]:
            print(f"  {debt:8.2f}  {path}")
        return EXIT_PASS

    snapshot = snapshot_at_ref(repo, args.ref)
    path = save_baseline(repo, snapshot, args.ref)
    summary = snapshot.summary()
    print(
        f"baseline written to {path}\n"
        f"  {summary['files']} files, total debt {summary['total_debt']}, "
        f"density {summary['debt_density']} per 1k loc"
    )
    return EXIT_PASS


def cmd_trajectory(args: argparse.Namespace) -> int:
    repo = args.repo
    if not gitio.is_repo(repo):
        print(f"not a git repository: {repo}", file=sys.stderr)
        return EXIT_ERROR

    try:
        commits = gitio.commit_list(repo, args.since, args.head, limit=args.limit)
    except gitio.GitError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR

    if not commits:
        print(f"no commits in {args.since}..{args.head}", file=sys.stderr)
        return EXIT_ERROR

    # Sampling keeps long histories tractable; each point is a full tree measure.
    step = max(1, len(commits) // args.samples) if args.samples else 1
    sampled = commits[::step]
    if sampled[-1] != commits[-1]:
        sampled.append(commits[-1])

    points = []
    for i, sha in enumerate(sampled, 1):
        if not args.json:
            print(f"\rmeasuring {i}/{len(sampled)}", end="", file=sys.stderr)
        snapshot = snapshot_at_ref(repo, sha, detect_clones=not args.fast)
        meta = gitio.commit_meta(repo, sha)
        points.append(
            {
                "sha": sha,
                "date": meta["date"],
                "subject": meta["subject"],
                **snapshot.summary(),
            }
        )
    if not args.json:
        print("\r" + " " * 30 + "\r", end="", file=sys.stderr)

    if args.json:
        print(json.dumps({"points": points}, indent=2))
    else:
        print(render_trajectory(points))

    return EXIT_PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sediment",
        description="Deterministic structural-erosion gate for machine-authored code.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="measure a tree as it stands")
    _add_common(scan)
    scan.add_argument("path", nargs="?", help="directory to scan (default: --repo)")
    scan.add_argument("--ref", help="measure this git ref instead of the working tree")
    scan.add_argument("--top", type=int, default=10, help="heaviest units to list")
    scan.set_defaults(func=cmd_scan)

    gate = sub.add_parser("gate", help="score a change and set the exit code")
    _add_common(gate)
    gate.add_argument("--base", required=True, help="ref the change is measured against")
    gate.add_argument("--head", default="HEAD", help="ref being judged (default: HEAD)")
    gate.add_argument(
        "--max-rate",
        type=float,
        default=DEFAULT_MAX_EROSION_RATE,
        help=f"debt per 100 added lines allowed (default: {DEFAULT_MAX_EROSION_RATE})",
    )
    gate.add_argument("--strict", action="store_true", help="treat a warn as a failure")
    gate.add_argument("--no-ratchet", action="store_true", help="ignore the baseline")
    gate.add_argument("--markdown", action="store_true", help="emit a PR-ready comment")
    gate.set_defaults(func=cmd_gate)

    ratchet = sub.add_parser("ratchet", help="record or show the debt floor")
    _add_common(ratchet)
    ratchet.add_argument("--accept", action="store_true", help="record current state")
    ratchet.add_argument("--ref", default="HEAD", help="ref to record (default: HEAD)")
    ratchet.add_argument("--top", type=int, default=15)
    ratchet.set_defaults(func=cmd_ratchet)

    traj = sub.add_parser("trajectory", help="debt density across a commit series")
    _add_common(traj)
    traj.add_argument("--since", required=True, help="starting ref (exclusive)")
    traj.add_argument("--head", default="HEAD")
    traj.add_argument("--limit", type=int, default=0, help="cap commits considered")
    traj.add_argument("--samples", type=int, default=40, help="points to measure")
    traj.add_argument("--fast", action="store_true", help="skip clone detection")
    traj.set_defaults(func=cmd_trajectory)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return EXIT_ERROR
    except gitio.GitError as exc:
        print(f"git error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
