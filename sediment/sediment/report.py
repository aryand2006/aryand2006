"""Rendering. Terminal output for humans, markdown for pull requests."""

from __future__ import annotations

import os
import sys

from .analyze import Snapshot
from .score import ErosionReport
from .slop import SIGNAL_DESCRIPTIONS

_VERDICT_STYLE = {
    "pass": ("\033[32m", "PASS"),
    "warn": ("\033[33m", "WARN"),
    "fail": ("\033[31m", "FAIL"),
}


def _color_enabled(stream=sys.stdout) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return hasattr(stream, "isatty") and stream.isatty()


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}\033[0m" if enabled else text


def _bar(value: float, limit: float, width: int = 24) -> str:
    if limit <= 0:
        return ""
    filled = min(width, max(0, round(value / limit * width)))
    return "#" * filled + "." * (width - filled)


def render_snapshot(snapshot: Snapshot, top: int = 10) -> str:
    s = snapshot.summary()
    lines = [
        f"sediment  {s['label']}",
        "",
        f"  files {s['files']}   units {s['units']}   loc {s['loc']}",
        f"  structural debt {s['structural_debt']}   slop debt {s['slop_debt']}",
        f"  total debt {s['total_debt']}   density {s['debt_density']} per 1k loc",
        f"  near-duplicate pairs {s['clone_pairs']}",
    ]

    worst = sorted(snapshot.units.values(), key=lambda u: u.debt(), reverse=True)
    worst = [u for u in worst if u.debt() > 0][:top]
    if worst:
        lines += ["", f"  heaviest units"]
        for unit in worst:
            over = ", ".join(
                f"{name} {value}/{threshold}"
                for name, (value, threshold) in unit.exceeded().items()
            )
            lines.append(f"    {unit.debt():6.2f}  {unit.key}")
            lines.append(f"            {over}")

    if snapshot.findings:
        counts: dict[str, int] = {}
        for f in snapshot.findings:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        lines += ["", "  signals"]
        for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {count:5d}  {kind} -- {SIGNAL_DESCRIPTIONS.get(kind, '')}")

    if snapshot.errors:
        lines += ["", f"  unparseable files: {len(snapshot.errors)}"]

    return "\n".join(lines)


def render_report(report: ErosionReport, max_rate: float, color: bool | None = None) -> str:
    if color is None:
        color = _color_enabled()

    verdict = report.verdict(max_rate)
    code, label = _VERDICT_STYLE[verdict]

    lines = [
        f"sediment  {report.base}..{report.head}",
        "",
        f"  {_paint(label, code, color)}   "
        f"erosion rate {report.erosion_rate} / {max_rate} allowed",
        f"  [{_bar(report.erosion_rate, max_rate)}]",
        "",
        f"  debt added {report.debt_added}   removed {report.debt_removed}   "
        f"net {report.net_erosion:+}",
        f"  across {report.added_loc} added lines",
    ]

    if report.ratchet_violations:
        lines += ["", "  ratchet violations"]
        for path, (base, current) in report.ratchet_violations.items():
            lines.append(f"    {path}: {base} -> {current}")

    if report.added_units:
        lines += ["", "  units introduced carrying debt"]
        for unit in report.added_units[:8]:
            over = ", ".join(
                f"{name} {value}/{threshold}"
                for name, (value, threshold) in unit.exceeded().items()
            )
            lines.append(f"    +{unit.debt():5.2f}  {unit.key}:{unit.lineno}")
            lines.append(f"            {over}")

    if report.worsened:
        lines += ["", "  units that got worse"]
        for delta in report.worsened[:8]:
            lines.append(f"    +{delta.delta:5.2f}  {delta.key}  ({delta.before} -> {delta.after})")

    if report.new_clones:
        lines += ["", "  near-duplicates introduced"]
        for clone in report.new_clones[:6]:
            lines.append(f"    {clone.similarity:.0%}  {clone.left}")
            lines.append(f"          {clone.right}")

    if report.new_findings:
        lines += ["", "  signals introduced"]
        for finding in report.new_findings[:12]:
            lines.append(
                f"    +{finding.weight:4.2f}  {finding.path}:{finding.lineno}  "
                f"{finding.kind}"
            )
            lines.append(f"            {finding.detail}")

    if report.improved:
        total = sum(-d.delta for d in report.improved)
        lines += ["", f"  {len(report.improved)} units improved (-{total:.2f} debt)"]

    if verdict == "pass" and not report.added_units and not report.new_findings:
        lines += ["", "  no structural debt attributable to this change"]

    return "\n".join(lines)


def render_markdown(report: ErosionReport, max_rate: float) -> str:
    verdict = report.verdict(max_rate)
    badge = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}[verdict]

    lines = [
        f"### sediment — {badge}",
        "",
        f"Erosion rate **{report.erosion_rate}** against a limit of {max_rate} "
        f"(net {report.net_erosion:+} debt over {report.added_loc} added lines).",
        "",
    ]

    if report.ratchet_violations:
        lines += ["**Ratchet violations**", "", "| File | Baseline | Now |", "|---|---|---|"]
        for path, (base, current) in report.ratchet_violations.items():
            lines.append(f"| `{path}` | {base} | {current} |")
        lines.append("")

    if report.added_units or report.worsened:
        lines += ["| Unit | Debt | Over threshold |", "|---|---|---|"]
        for unit in report.added_units[:10]:
            over = ", ".join(
                f"{name} {value}/{threshold}"
                for name, (value, threshold) in unit.exceeded().items()
            )
            lines.append(f"| `{unit.key}` | +{unit.debt():.2f} | {over} |")
        for delta in report.worsened[:10]:
            lines.append(f"| `{delta.key}` | +{delta.delta:.2f} | {delta.before} → {delta.after} |")
        lines.append("")

    if report.new_findings:
        lines += ["| Signal | Location | Detail |", "|---|---|---|"]
        for finding in report.new_findings[:15]:
            lines.append(
                f"| {finding.kind} | `{finding.path}:{finding.lineno}` | {finding.detail} |"
            )
        lines.append("")

    if report.new_clones:
        lines += ["**Near-duplicates introduced**", ""]
        for clone in report.new_clones[:8]:
            lines.append(f"- {clone.similarity:.0%} — `{clone.left}` ≈ `{clone.right}`")
        lines.append("")

    return "\n".join(lines)


def render_trajectory(points: list[dict]) -> str:
    """Debt density over a commit series, as a terminal sparkline chart."""
    if not points:
        return "no commits in range"

    densities = [p["debt_density"] for p in points]
    lo, hi = min(densities), max(densities)
    height = 12
    width = len(points)

    # A perfectly flat series has no range to scale against. Give it a nominal
    # band so the line renders through the middle instead of collapsing onto
    # the axis, which reads as "zero" rather than "unchanged".
    flat = hi - lo < 1e-9
    if flat:
        pad = max(abs(hi) * 0.1, 1.0)
        lo, hi = hi - pad, hi + pad
    span = hi - lo

    grid = [[" "] * width for _ in range(height)]
    for x, value in enumerate(densities):
        y = height - 1 - int(round((value - lo) / span * (height - 1)))
        grid[max(0, min(height - 1, y))][x] = "*"

    lines = [
        "sediment trajectory   debt density per 1k loc",
        "",
    ]
    for row_index, row in enumerate(grid):
        value = hi - (hi - lo) * row_index / (height - 1)
        lines.append(f"  {value:8.2f} | {''.join(row)}")
    lines.append(f"  {'':8} +{'-' * width}")
    lines.append(f"  {'':8}  {points[0]['sha'][:7]} -> {points[-1]['sha'][:7]}  ({width} commits)")

    first, last = densities[0], densities[-1]
    change = last - first
    direction = "eroding" if change > 0 else "improving" if change < 0 else "flat"
    pct = (change / first * 100) if first else 0.0
    lines += [
        "",
        f"  start {first:.2f}   end {last:.2f}   change {change:+.2f} ({pct:+.1f}%)  -- {direction}",
    ]

    rising = sum(
        1 for a, b in zip(densities, densities[1:]) if b > a
    )
    steps = len(densities) - 1
    if steps:
        lines.append(f"  density rose in {rising}/{steps} commits ({rising / steps:.0%})")

    return "\n".join(lines)
