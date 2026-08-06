<h1 align="center">Aryan Daga</h1>
<p align="center">
  CS @ Carnegie Mellon &nbsp;·&nbsp; Machine Learning &amp; Computational Finance
</p>

---

I work on **program analysis and verification** — the part of the stack that decides
whether code is actually correct, not just whether it runs.

In 2026 the constraint on software is no longer writing it. Models generate more code
than teams can confirm is right, and the tooling for confirming it hasn't kept up.
That gap is what I build for.

---

### Selected work

**[sediment](https://github.com/aryand2006/sediment)** — a deterministic structural-erosion
gate for machine-authored code.
Coding agents pass tests and still make a codebase worse; published benchmarks show
agent-authored code eroding in 80% of long-horizon trajectories while human code stays
flat. Existing tools either use absolute thresholds that legacy code fails on day one,
or add another LLM to review the first one. `sediment` scores the structural debt a change
*adds* — complexity, nesting, duplication, error-masking — attributes it to the diff, and
fails CI on erosion. Identifier-blind AST fingerprinting catches copy-paste that text
diffing misses. Zero dependencies, 43 tests, gates itself in its own CI.

**[ShadowStack](https://github.com/aryand2006/ShadowStack)** — a verified language
modernization engine. 25k LOC of Java built on Eclipse JDT with full type resolution:
call-graph and data-flow analysis, purity and mutation classification, baseline capture,
and a 7-layer verification pipeline that proves a refactor preserved behavior before a
human is asked to approve it. Pluggable adapters for Java, COBOL, and Python 2→3.

Both are the same idea from different ends: **don't trust a transformation you can't verify.**

---

### Also

Live trading systems and portfolio optimization · RAG pipelines and retrieval
verification · interfaces for high-cognitive-load workflows · a spreadsheet engine,
a browser, and a 3D renderer written to understand how they work rather than to ship them.

---

### Contact

[aryand@andrew.cmu.edu](mailto:aryand@andrew.cmu.edu) · [LinkedIn](https://linkedin.com/in/aryan-daga)

If you're building something ambitious or unconventional, reach out.
