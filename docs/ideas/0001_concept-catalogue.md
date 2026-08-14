# Concept Catalogue — what this project should demonstrate

Date: 2026-08-11
Status: accepted
Author: P0w3r223
Related to: `docs/adr/0001_browser-side-analytics-stack.md`,
`docs/adr/0002_published-artifact-policy.md`,
`docs/plan/0001_implementation-walkthrough.md`

---

## Purpose

A catalogue of concepts for extending it-job-radar, and the reasoning that ranks them.
The implementation order lives in the walkthrough; this file records *why* each idea is
on (or off) the list, so a decision does not have to be re-derived later.

The target audience for the published site is a senior engineer reading it for five
minutes. The aim is not to impress with volume or complexity — it is that every choice
visible on the page looks deliberate.

## What actually impresses a senior reader

Ranked by how much signal each carries, based on what is scarce in portfolio projects:

1. **Honesty apparatus.** A number carrying its `n`, a suppressed thin stratum, a stated
   limitation. Scarce because it requires admitting the data is imperfect.
2. **No drift between what is claimed and what runs.** One definition of a metric, used
   by the pipeline, the tests, and the page — not three copies that silently diverge.
3. **A defensible architectural inversion.** Shipping the dataset and pushing compute to
   the client is a real trade-off with real consequences, not a framework choice.
4. **Ethics resolved in the design, not in a disclaimer.** The published artifact is
   deliberately non-substitutable for the source (see ADR 0002).
5. **Charts that answer a question.** A headline finding beats a grid of generic bars.

Explicitly *not* on this list: framework count, animation, dashboard density, LOC.

## Current state (baseline, 2026-08-11)

```
snapshot        314 offers, one collection date (2026-07-17)
strata          senior 165 · mid 153 · junior 19 · intern 5   -> junior is noise
salary          62 B2B PLN · 41 employment PLN · 340 rows with kind = NULL
trend           snapshot_stats holds 2 metrics for 1 date -> no time dimension
source          sitemap index -> 1 child file -> 6466 current offer URLs
sampling        deterministic stride from index 0: same ~300 slots every run
site            3 static PNGs in an f-string, copied by hand into docs/
```

Two facts drive most of the catalogue: **the site has no time dimension to show**, and
**the junior segment is presented with the same visual confidence as a segment 16x its
size**.

---

## Pillar 1 — The dataset is the artifact

**Concept.** The page ships a columnar dataset and runs real analytical SQL in the
reader's browser. No API, no server, no running cost, and the reader can drill into any
dimension we did not think to pre-aggregate.

**Why it carries signal.** It inverts the default assumption (backend computes, frontend
renders) for a defensible reason: the dataset is small, immutable between snapshots, and
public. It also makes the next concept possible.

**Cost.** Moderate — export layer, a vendored WASM bundle, a lazy-loading budget.
**Decision.** Accepted — ADR 0001. **Half reversed 2026-08-12:** the dataset *is* shipped
and is the artifact, but it is not queried in the reader's browser. The WASM bundle costed
as "moderate" here measures 21-37 MB against a 241 kB dataset, so the querying stayed in the
pipeline and the reader gets the file plus the exact SQL instead. The inversion this pillar
argues for survives; the runtime that would have expressed it did not. See the ADR 0001
amendment.

## Pillar 2 — One definition of every metric

**Concept.** Every aggregation lives once, as a named `.sql` file. The same query text
is executed by the Python analytics layer (DuckDB), asserted in tests, embedded in the
page, and shown to the reader behind a *Show SQL* toggle on each chart.

**Why it carries signal.** It removes the most common rot in analytics projects — the
notebook, the report, and the site slowly disagreeing about what "median salary" means.
Showing the query next to the chart is the cheapest possible proof that nothing was
massaged between the query and the picture.

**Consequence.** The analytical engine becomes DuckDB in both runtimes; SQLite stays the
system of record. A parity test asserts DuckDB-over-Parquet equals SQLite for each
metric, which also proves the export is faithful.

**Cost.** Low-moderate. **Decision.** Accepted.

## Pillar 3 — Data quality as a published product

**Concept.** Parse success rate, salary coverage, **alias-dictionary coverage** (share of
raw technology names that fell through to the lowercase fallback), stratum sizes, and
snapshot freshness are computed every run, stored dated, validated against a contract,
and published on the page.

**Why it carries signal.** Most portfolio projects present results; almost none present
the measured trustworthiness of those results. Alias coverage is a self-improving loop:
the report lists the top unmatched names, they go into the YAML, coverage rises, and the
improvement is visible in a time series.

**Cost.** Low. **Decision.** Accepted — highest value-to-effort ratio in the catalogue.

## Pillar 4 — A panel that accumulates, politely

**Concept.** Each run takes one bounded, seeded sample and prefers offer ids not seen
before; `first_seen` / `last_seen` are maintained per offer. Coverage of the base grows
across runs without ever increasing load on the source.

**Why it carries signal.** It converts an ethical constraint into an analytical asset:
"never take the whole base" stops being only a limitation and becomes the mechanism that
produces a longitudinal panel. It unlocks offer lifetime (how long a posting stays open,
by technology), market churn, and a coverage-over-time chart that visibly proves the
pipeline runs.

**Cost.** Moderate — schema migration, sampling rework.
**Decision.** Accepted.

## Pillar 5 — Honesty in the interface

**Concept.** Every figure carries its `n`. Strata below a configured threshold are
greyed and labelled, not silently plotted. Medians carry bootstrap confidence intervals.
Limitations are a section, not a footnote.

**Why it carries signal.** The junior chart currently on the live site rests on 19
offers and looks exactly as authoritative as the chart resting on 314. A senior reader
notices that within seconds; fixing it is the single largest credibility gain available.
The bootstrap intervals also connect this project to P2 `ab-lab`.

**Cost.** Low. **Decision.** Accepted.

## Pillar 6 — Reproducibility you can see

**Concept.** A published `manifest.json` carrying snapshot id, collection date, git SHA,
row counts and quality metrics; the page footer renders it. CI regenerates the site from
the committed data artifact and fails if the result differs from what is in `docs/` —
the drift between `reports/site/` and `docs/` becomes impossible rather than discouraged.

**Cost.** Low. **Decision.** Accepted.

---

## Backlog — considered, deferred

| Concept | Value | Why deferred |
|---|---|---|
| ~~Technology co-occurrence graph~~ | High visual payoff; one self-join | **Shipped 2026-08-14** as a lift ranking rather than a graph: the pair *counts* are just the demand chart drawn twice, so what is published is how far each pair sits from chance, floored at `MIN_PAIR_N` shared vacancies |
| Salary premium per technology (regression, controlling for seniority/city) | Strongest analytical claim available | Needs `n` per cell that the current panel cannot support |
| Offer survival curve (Kaplan-Meier on offer lifetime) | Ties data engineering to statistics | Requires several weeks of `first_seen`/`last_seen` |
| Role-family classifier (backend/frontend/devops/data/QA/support) | Fixes the misleading junior segment | Accepted, but as a rule table — an ML classifier here would be complexity for its own sake |
| Clean dataset export consumed by P4 `pl-jobs-lora` | Turns A2 into a source for the portfolio, as the index README already claims | Blocked on the export layer (Phase 4); trivial afterwards |
| Semantic search over titles (embeddings) | Fashionable | Adds a heavy dependency to answer a question rules already answer. Rejected for now |
| Multi-source collection (other boards) | Broader market picture | `docs/research/data-sources.md` rejected the alternatives on robots.txt grounds; revisit only if that changes |
| Live collection from CI | Removes the manual step | Would require bot evasion; deliberately rejected (README states this) |

## Rejected outright

- **A JS framework for the site.** The page is one document with a handful of charts;
  React or Svelte here would signal reflex rather than judgement.
- **A backend API.** There is nothing to serve that a static artifact cannot.
- **Publishing raw offer text.** See ADR 0002 — the artifact is redacted by design.
