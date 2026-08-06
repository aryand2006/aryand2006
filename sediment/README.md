# sediment

**A deterministic structural-erosion gate for machine-authored code.**

Coding agents pass tests and still make a codebase worse. `sediment` measures the
structural debt a change *adds* — not the absolute state of the code it lands in —
and fails CI when a change erodes the codebase, with no model in the loop.

```
sediment  main..HEAD

  FAIL   erosion rate 4.31 / 1.5 allowed
  [########################]

  debt added 8.62   removed 0.0   net +8.62
  across 200 added lines

  units introduced carrying debt
    + 5.10  billing.py::apply_discounts:41
            cyclomatic 24/10, cognitive 38/15, max_nesting 7/4

  near-duplicates introduced
    91%  billing.py::apply_discounts
         billing.py::apply_promotions

  signals introduced
    +1.20  billing.py:88  error_masking
            broad except that only logs and continues
```

---

## Why this exists

The 2026 bottleneck in software is verification, not generation. Two findings
frame the problem:

- **SlopCodeBench** (2026) had agents repeatedly extend their own prior solutions
  under evolving specs. Agents reached initial correctness, then degraded:
  structural erosion rose in **80%** of trajectories and verbosity in **89.8%**,
  with agent code **2.2× more verbose** than human-maintained repositories. Tracked
  over time, human code stayed flat while agent code deteriorated with each
  iteration. Prompt engineering improved the starting point but *did not halt the
  rate of decay*.
- Pass-rate benchmarks **systematically undermeasure extension robustness** — the
  code passes, and gets worse anyway.

The tooling gap follows directly:

| Existing approach | What it does | Why it misses this |
|---|---|---|
| SonarQube, Codacy | Absolute quality thresholds | A legacy codebase fails on day one, so the gate gets switched off |
| `eslint-seatbelt`, coverage floors | Ratchets on **lint counts** and **coverage %** | Ratchets the wrong variable — neither tracks structural decay |
| CodeRabbit, LLM reviewers | Probabilistic review | Adds another stochastic layer to a pipeline with no deterministic gate |
| SlopCodeBench, GitClear | Measure erosion | A benchmark and an analytics product — neither blocks a merge |

Nobody ships a **deterministic, per-diff, ratcheted structural-erosion gate**.
That is this tool.

---

## The measurement

Erosion is scored on **code units** — functions, methods, module top level —
because erosion is a property of the thing a human reads in one sitting.

**Structural debt** per unit is the *fractional overage* past each threshold, so a
unit sitting at the threshold contributes exactly zero:

| Metric | Threshold | Weight |
|---|---|---|
| Cognitive complexity (nesting-weighted) | 15 | 1.5 |
| Cyclomatic complexity | 10 | 1.0 |
| Max nesting depth | 4 | 1.0 |
| Lines of code | 50 | 0.6 |
| Parameters | 5 | 0.4 |

**Signals** add categorical debt for habits that are markedly more common in
generated code, each individually defensible as a defect or comprehension cost:

| Signal | Weight |
|---|---|
| `error_masking` — exception caught and discarded | 1.2 |
| `stub_implementation` — placeholder body left behind | 1.0 |
| `mutable_default` — mutable default argument | 1.0 |
| `unreachable_code` — statements after an unconditional exit | 0.9 |
| `context_dropping_raise` — `raise` in `except` without `from` | 0.8 |
| `repeated_literal` — same literal repeated instead of named | 0.3 |
| `narrating_comment` — comment restates the line below it | 0.15 |

**Near-duplicates** are found by fingerprinting each function's *node-type stream*
with identifiers and literal values erased, then comparing k-gram shingle sets by
Jaccard similarity through an inverted index. Agents copy-paste and then rename;
text-based clone detection misses that entirely, and this does not.

### Why marginal, not absolute

The score that gates a change is the **erosion rate** — net debt added per 100
added lines:

```
erosion_rate = (debt_added - debt_removed) / (added_lines / 100)
```

Only units in files the change touched are considered, so unrelated drift
elsewhere never lands on this change's bill. Normalizing by change size makes a
one-line fix and a thousand-line feature comparable, with a floor so a 3-line
change that adds a 40-branch function is not flattered by its own size.

This is the design decision that makes the gate adoptable: it works on any
codebase from the first commit, because the only question it asks is *"is this
change making it worse."*

---

## Install

```bash
pip install sediment      # no runtime dependencies, by design
```

## Use

```bash
# Measure a tree as it stands
sediment scan src/

# Gate a change; exit 1 if it erodes
sediment gate --base main --head HEAD

# Record the current state as a floor nothing may cross
sediment ratchet --accept

# Debt density across a commit series
sediment trajectory --since v1.0.0
```

Wire it into CI with [`ci/github-action.yml`](ci/github-action.yml) — it posts a
markdown report on the PR and updates it in place. Adopt in report-only mode
first; `--strict` promotes warnings to failures once a baseline is settled.

### The ratchet

`sediment ratchet --accept` records per-file debt. From then on, a change may not
push a touched file above its recorded floor. Files absent from the baseline are
new and cannot violate it — they are governed by the erosion rate instead. This
is what lets a team adopt the gate on a codebase that is already in bad shape:
today's mess becomes the ceiling, and it can only come down.

---

## Measured on real code

Every number below is `sediment scan` output on real repositories, not an
estimate. Density is total debt per 1,000 lines.

| Repository | Files | LOC | Units | Structural | Signals | **Density** | Clones |
|---|---|---|---|---|---|---|---|
| sediment (this tool) | 9 | 1198 | 86 | 11.1 | 2.4 | **11.3** | 0 |
| ShadowStack (Python packages) | 6 | 1010 | 47 | 3.2 | 9.3 | **12.4** | 1 |
| SpreadsheetByAryan | 38 | 6887 | 420 | 87.1 | 58.8 | **21.2** | 2 |
| CastQuest | 2 | 197 | 14 | 1.3 | 4.7 | **30.4** | 0 |
| Offset (HackMIT, 36h build) | 19 | 2070 | 68 | 115.2 | 41.0 | **75.5** | 0 |

The spread is the point: a deliberately-built tool and a hackathon build differ
by **6.7×** on the same scale, and the ranking matches how the code actually
reads. The single heaviest unit found anywhere was `Offset`'s
`estimate_carbon_strict` — cyclomatic 96, **cognitive 292**, nesting depth 10,
219 lines — one function carrying 39.8 debt, a quarter of that repository's total.

`sediment` gates itself in its own CI.

---

## Scope and limits

Stated plainly, because a measurement tool that oversells itself is worthless:

- **Python only.** The analysis is built on the `ast` module. The unit/metric/
  signal split is language-agnostic and the adapter seam is the obvious next
  extension, but today it reads Python and nothing else.
- **Thresholds are conventional, not derived.** They come from common static-analysis
  practice, not from a fitted study. Weights are calibrated so one severe signal
  is comparable to one badly over-complex function. They are configurable because
  they are opinions.
- **Erosion is not correctness.** A change can be structurally clean and wrong, or
  eroding and necessary. This gate measures one axis and does not pretend to
  measure the other.
- **Renames read as delete-plus-add.** Unit identity is `path::qualname`, so a
  renamed function shows as debt removed and debt added. Net erosion is right;
  the attribution is noisier.
- **`narrating_comment` is a texture signal**, deliberately weighted at 0.15. It
  fires only when a comment's content words — after stripping stopwords,
  mechanical verbs, and filler nouns — are already spelled out in the line below.

## Development

```bash
pip install -e ".[dev]"
pytest            # 43 tests, no network, no fixtures beyond throwaway git repos
```

The end-to-end tests build real git repositories in a temp directory and gate
real commits, so the git plumbing is covered rather than mocked.

## License

MIT
