<h1 align="center">Aryan Daga</h1>
<p align="center">
  CS @ Carnegie Mellon &nbsp;·&nbsp; Machine Learning &amp; Computational Finance
</p>

---

I work on **program analysis and verification** — the part of the stack that decides
whether a result is actually correct — a backtest, a refactor, or a consensus protocol — not just whether it looks right.

In 2026 the constraint is no longer producing an answer. Models generate more code
than teams can confirm is sound, and backtests report more Sharpes than anyone can
falsify. The tooling for confirming either hasn't kept up. That gap is what I build for.

---

### Selected work

**[aperture](https://github.com/aryand2006/aperture)** — a metrics pipeline that proves planted-anomaly recall.
Ingest → tumbling aggregates → spike/drop/flatline/gap detectors. A deterministic simulator plants
ground-truth anomalies and fails on missed detections or clean-baseline false positives. Meta-shaped
observability work: the path under the dashboards, verified rather than demoed.

**[concord](https://github.com/aryand2006/concord)** — a Raft key-value store verified by
deterministic simulation.
Sans-IO Raft core, seeded fault injection (partitions, crashes, loss, reordering), continuous
election/state-machine safety checks, and a Wing&Gong linearizability checker. Same seed ⇒
bit-identical trace hash; a failing seed is a reproducing bug report. Built for the systems
interview question nobody can fake: *what happens when the network lies?*

**[scroll](https://github.com/aryand2006/scroll)** — a partitioned commit log that proves delivery under faults.
Consumer groups, durable partitions, at-least-once + per-partition order checks, seeded crash/drop campaigns.
Amazon-shaped systems work: the log abstraction SQS/Kinesis/Kafka sit on — verified, not assumed.

**[stratum](https://github.com/aryand2006/stratum)** — an LSM-tree storage engine that proves crash recovery.
WAL with CRC framing, memtable, SSTables, L0→L1 compaction, and a VFS that discards unsynced bytes on crash.
Seeded campaigns check durability, tombstones, and read-your-writes after reopen. Apple-shaped bottom-of-stack work.

**[affidavit](https://github.com/aryand2006/affidavit)** — a research-governance gate that
swears whether a strategy result survives falsification.
One command runs selection reconstitution, degrees-of-freedom accounting, cost tilt,
placebo nulls, track-record tests, and a black-box lookahead probe, then writes a
hash-chained JSON artifact. A result is **sworn** only when every applicable check
passes. Checks whose inputs are absent are skipped, never guessed — a gate that
guesses is a gate that gets overridden.

**[sediment](https://github.com/aryand2006/sediment)** — a deterministic structural-erosion
gate for machine-authored code.
Coding agents pass tests and still make a codebase worse; published benchmarks show
agent-authored code eroding in 80% of long-horizon trajectories while human code stays
flat. Existing tools either use absolute thresholds that legacy code fails on day one,
or add another LLM to review the first one. `sediment` scores the structural debt a change
*adds* — complexity, nesting, duplication, error-masking — attributes it to the diff, and
fails CI on erosion. Identifier-blind AST fingerprinting catches copy-paste that text
diffing misses. Zero dependencies, 43 tests, gates itself in its own CI.

**[parallax](https://github.com/aryand2006/parallax)** — measuring how much a backtest
result depends on implementation rather than on the strategy.
A 2026 paper showed that identical strategies run through different backtesting engines
agree exactly at zero transaction cost and diverge once costs are switched on. `parallax`
runs one auditable engine across 144 combinations of the execution decisions libraries
make differently — fill timing, cost basis, slippage model, share rounding — and attributes
the resulting spread to the decision responsible. Implementation risk scales monotonically
with turnover, from 2.9% of the result at buy-and-hold to 166% at daily rebalancing; at
10bp a daily strategy reports a Sharpe of either 0.54 or 2.18, which is the difference
between a rejected idea and a funded one.

**[assay](https://github.com/aryand2006/assay)** — testing whether a backtest result
survives the search that found it.
The statistics of selection bias are well established; the check nobody runs is the blunt
one — you tested N strategies and kept K, so what would running all N have returned?
Auditing a live system with it found a deployment candidate whose three cointegration
pairs had been kept from six tested: the reported 10.7%/yr becomes **1.7%/yr** once the
three losers are put back, against a 6.5% risk-free rate. Also implements deflated Sharpe,
minimum track record length, and probability of backtest overfitting via combinatorially
symmetric cross-validation.

**[clairvoyant](https://github.com/aryand2006/clairvoyant)** — detecting strategies
that can see the future.
Runs a decision function twice at the same date, once with the full dataset and once with
everything after it hidden; code that only uses information available at the time cannot
tell the difference. Measures how far forward a leak reaches by binary search on the visible
future window, which separates an off-by-one in a `shift()` from a statistic computed over
the whole sample — different bugs, different fixes. Black box, so it works against code you
didn't write.

**[ShadowStack](https://github.com/aryand2006/ShadowStack)** — a verified language
modernization engine. 25k LOC of Java built on Eclipse JDT with full type resolution:
call-graph and data-flow analysis, purity and mutation classification, baseline capture,
and a 7-layer verification pipeline that proves a refactor preserved behavior before a
human is asked to approve it. Pluggable adapters for Java, COBOL, and Python 2→3.

One thread runs through all of it: **don't trust a result you can't verify** — whether the
thing producing it is a compiler, an agent, a backtest, or the search that chose it.

---

### Research

**[Spread tilt governs cost-model sensitivity in portfolio backtests](https://github.com/aryand2006/spread-tilt)**
— working paper. A backtest's sensitivity to the choice of transaction-cost model turns out
not to be a property of the universe being traded but of the strategy's relationship to it,
predicted by one statistic computable before any backtest runs. The intuitive prediction is
backwards: widening a universe's liquidity range makes the commission-model choice matter
*less*. Measured on 48 Indian equities over 1,241 trading days, with every synthetic result
regenerable from seed.

---

### Also

Live trading systems and portfolio optimization · RAG pipelines and retrieval
verification · interfaces for high-cognitive-load workflows · a spreadsheet engine,
a browser, and a 3D renderer written to understand how they work rather than to ship them.

---

### Contact

[aryand@andrew.cmu.edu](mailto:aryand@andrew.cmu.edu) · [LinkedIn](https://linkedin.com/in/aryan-daga)

If you're building something ambitious or unconventional, reach out.
