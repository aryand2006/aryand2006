# What to build next — audit, research, and decision

Written 2026-08-06. This is the reasoning behind [`sediment/`](sediment/), kept in
the open so the choice can be argued with.

---

## 1. Audit of 26 repositories

Every public repository was cloned and measured rather than read from its README,
because READMEs and codebases disagree.

**What the portfolio actually contains:**

| Cluster | Repos | Verdict |
|---|---|---|
| Hackathon full-stack + AI wrapper | Savewise, dinect, streakbreaker, Offset, JalSampark, KrishiDNA, Claude-Builder-Hackathon | 6 variations on one skill. Next.js + TypeScript + an LLM call. Well-executed, but interchangeable with thousands of others. |
| Serious systems | **ShadowStack** (25.5k LOC Java) | The outlier, and by a distance. |
| Coursework | idl-hw4 (CMU 11-785) | Real, but coursework reads as coursework. |
| Private | Trading (26 MB), deep-research-agent-ey | Not visible, so not doing any work for the profile. |
| Early / small | NOVA-Browser, PaintByAryan, TicTacToe-Multiverse, CastQuest, SpreadsheetByAryan, etc. | Fine. Noise at this point. |

**ShadowStack is the finding.** It is not README inflation — the code is there:
`CallGraphBuilder`, `DataFlowAnalyzer`, `PurityClassifier`, `MutationAnalyzer`,
`BaselineCapture`, `ASTStructuralComparator`, `BytecodeDescriptorComparator`,
Eclipse JDT with full type resolution, and a 7-layer verification pipeline across
Java, COBOL and Python adapters. Compiler-grade static analysis is a rare skill at
any level and very rare in an undergraduate portfolio.

**Two structural problems, independent of code quality:**

1. **Signal is buried.** The rarest thing here sits at position 2 of 26, next to
   25 repos that dilute it. A reader spending 10 seconds sees hackathon apps.
2. **No development history.** Repos carry 2–7 commits each — bulk dumps, not
   worked history. That reads as code that arrived rather than code that was
   built, and it forfeits the most credible evidence of engineering judgment.

---

## 2. Landscape research

The question was not "what is a good project" but "what is currently unsolved
where this specific person has an unfair advantage."

**The 2026 bottleneck is verification, not generation.** AI-authored code is a
large share of committed code; the constraint has moved to confirming it is
correct, and that constraint is human-limited. When generation scales past
verification, teams optimize for closing items rather than reducing risk.

**The specific measured phenomenon** (SlopCodeBench, 2026): agents repeatedly
extending their own prior solutions reach initial correctness and then degrade —
structural erosion rises in **80%** of trajectories, verbosity in **89.8%**, and
agent code is **2.2× more verbose** than human-maintained repositories. Human code
tracked over the same period stays flat. Prompt engineering improves the starting
quality and **does not change the rate of decay**. The authors' conclusion: pass-rate
benchmarks *systematically undermeasure extension robustness*.

**What exists, and what it misses:**

- **SonarQube / Codacy** — absolute thresholds. Point one at a decade-old codebase
  and everything fails on day one, so the team disables it.
- **`eslint-seatbelt` (Notion), coverage floors** — genuine ratchets, but on lint-rule
  counts and coverage percentage. Right mechanism, wrong variable.
- **CodeRabbit / LLM reviewers** — probabilistic. As one 2026 write-up put it,
  deploying AI at the review stage adds another probabilistic layer to a pipeline
  that already lacks a deterministic quality gate.
- **SlopCodeBench / GitClear** — measure erosion precisely, but one is a benchmark
  and the other an analytics product. Neither blocks a merge.

**The gap:** a deterministic, per-diff, ratcheted structural-erosion gate. The
phenomenon is published and quantified; the control system for it does not exist.

---

## 3. Decision

**Build `sediment` — the erosion gate.**

Why this and not something else:

- **It uses the rare skill.** Erosion measurement *is* static analysis: complexity,
  nesting, call structure, clone detection, baseline capture. ShadowStack already
  proves capability with exactly this machinery. This is the second data point
  that turns one impressive repo into a demonstrated specialty.
- **It is an instrument, not another agent.** Everyone in 2026 is building agents.
  Almost nobody is building the thing that measures whether agent output is
  degrading a codebase. The scarcity is on the measurement side.
- **It is falsifiable.** The tool produces numbers on real repositories that a
  reader can reproduce and disagree with. That is a materially different claim
  from "I built an app."
- **It is small enough to be finished and good.** One clear thesis, zero
  dependencies, a real test suite — rather than a large half-built platform.

**Alternative considered and rejected: a quantitative-finance / ML project.**
It fits the stated concentration, but the public evidence would be weak — a
private `Trading` repo already exists, public quant projects are abundant and
usually read as naive, and it would not use the rare skill. Verification is the
stronger public bet. This does not touch the finance track; it complements it.

**Rejected: polishing the six hackathon apps.** Returns are near zero. The problem
is not that they are unpolished, it is that there are six of them.

---

## 4. Plan

| Step | Status |
|---|---|
| Metric extraction — cyclomatic, cognitive, nesting, LOC, params, per unit | done |
| Agent-specific signal detectors — 7 deterministic patterns | done |
| Identifier-blind AST clone detection via shingle Jaccard + inverted index | done |
| Git plumbing — historical trees via `cat-file --batch`, no working-tree writes | done |
| Marginal erosion scoring with change-scoped attribution | done |
| Ratchet — per-file debt floor, new files exempt | done |
| Trajectory — debt density across a commit series | done |
| CLI, terminal + markdown + JSON reporting | done |
| Test suite — 43 tests, end-to-end against real git repos | done |
| Validation on real repositories | done |
| CI integration — GitHub Action, pre-commit hook | done |

**Next, in order of value:**

1. **Extract to its own repository.** It currently lives in the profile repo
   because that was the only writable target. The extraction is prepared and
   verified — see [Migration](#6-migration) below — but creating the repository
   needs a credential this session did not have.
2. **A second language adapter.** The unit/metric/signal split is already
   language-agnostic; TypeScript is the obvious second target and the one most
   agent code is written in.
3. **Calibrate the thresholds.** They are conventional, not derived. Running the
   trajectory command across a corpus of human-maintained and agent-maintained
   repositories would turn them from opinions into fitted values — and would
   independently replicate or refute the SlopCodeBench result.
4. **Publish it.** PyPI, and a short write-up of the replication in step 3.

---

## 5. Profile changes

- Rewrote the profile README around evidence rather than adjectives, leading with
  the verification/static-analysis specialty.
- Named the two projects that carry real weight (ShadowStack, sediment) instead of
  listing everything equally.

Recommended, not done here (it needs repo-level access this session did not have):
**archive or unpin the long tail.** Twelve of the 26 repositories actively dilute
the signal. Archiving is reversible and costs nothing.

---

## 6. Migration — done

`sediment` now lives at **[github.com/aryand2006/sediment](https://github.com/aryand2006/sediment)**
with its development history intact.

`git subtree split --prefix=sediment` rewrote the six commits so paths lose the
`sediment/` prefix: the package sits at `sediment/`, tests at `tests/`, and the
workflow at `.github/workflows/sediment.yml`, where GitHub actually runs it. No
squashing — the commits that built it are still individually readable, which was
half the point.

Verified against the real remote after pushing: clean clone, six commits, 45
tests passing.

The copy was then removed from this repository so there is one source of truth.

---

## Sources

- [SlopCodeBench: Benchmarking How Coding Agents Degrade Over Long-Horizon Iterative Tasks](https://www.alphaxiv.org/resources/2603.24755v1)
- [Position: Coding Benchmarks Are Misaligned with Agentic Software Engineering](https://arxiv.org/abs/2606.17799)
- [Intent Formalization: A Grand Challenge for Reliable Coding in the Age of AI Agents](https://arxiv.org/abs/2603.17150)
- [AI-generated code, AI-generated findings, and the verification bottleneck — SRLabs](https://srlabs.de/blog/ai-verification-bottleneck)
- [Raising the Bar: Quality Gates for AI-Generated Code](https://www.frankneff.com/blog/2026-02-19-quality-gates-against-ai-slop/)
- [Introducing quality ratchets — LeadDev](https://leaddev.com/building-better-software/introducing-quality-ratchets-tool-managing-complex-systems)
- [Custom ESLint ratcheting — Notion](https://www.notion.com/blog/how-we-evolved-our-code-notions-ratcheting-system-using-custom-eslint-rules)
- [The Maintainability Gap: 2026 AI Code Quality Research — GitClear](https://www.gitclear.com/the_ai_code_quality_maintainability_gap)
- [Intent Drift in AI Code — Tricentis](https://www.tricentis.com/blog/intent-drift-ai-code-fix-regression-blind-spots)
- [EquiBench: Benchmarking LLMs' Reasoning about Program Semantics](https://arxiv.org/abs/2502.12466)
