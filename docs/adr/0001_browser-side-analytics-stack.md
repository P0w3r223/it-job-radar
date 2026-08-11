# ADR 0001 — Browser-side analytics stack (DuckDB-WASM + Parquet)

Date: 2026-08-11
Status: accepted
Author: P0w3r223 + Claude
Related to: `docs/ideas/0001_concept-catalogue.md`, `docs/adr/0002_published-artifact-policy.md`

---

## Context

The published site (`docs/index.html`) is a single static document holding three
matplotlib PNGs embedded as base64, produced by an f-string inside `report.py` and copied
into `docs/` by hand. It shows one snapshot, offers no way to ask a different question,
and — because `report.py` writes to the git-ignored `reports/site/` — nothing prevents
the published page from drifting away from the code that claims to generate it.

The dataset is small (314 offers today; the full current-offer base is 6466 URLs), public,
and immutable between snapshots. There is no per-user state and no write path from the
page. GitHub Pages is the hosting constraint: static files only, no server process.

The requirement driving this decision is that the page should let a reader *interrogate*
the data — filter by seniority, city or work mode and see the numbers change — while the
project must remain free to run and honest about what it computes.

## Decision

Ship the analytical dataset to the browser as **Parquet** and query it in the page with
**DuckDB-WASM**. Charts are rendered client-side with **Observable Plot**. The HTML shell
is generated at build time from a **Jinja2** template by a `site.build` module.

Every aggregation is defined once as a named `.sql` file under
`src/it_job_radar/analytics/queries/`. The same query text is executed by the Python
analytics layer (DuckDB over the exported Parquet), asserted in tests against the SQLite
system of record, embedded in the page, and shown to the reader behind a *Show SQL*
toggle next to each chart.

Supporting choices:

- **SQLite remains the system of record.** It handles the idempotent upsert path well.
  DuckDB is the analytical engine only, reading the exported Parquet.
- **The DuckDB-WASM bundle is vendored** into `docs/vendor/`, pinned by version — not
  loaded from a CDN.
- **The page degrades.** The build renders the headline numbers, KPI row and static
  fallback charts into the HTML. The WASM bundle (~3 MB) loads lazily, only when the
  reader engages with a filter or the query playground. Without JavaScript the page is
  still a complete, readable report.

## Alternatives considered

**Pre-aggregated JSON + Observable Plot.** Export a few dozen kB of ready aggregates and
render them client-side. Lighter and simpler, and the honest choice if interactivity were
limited to two or three axes. Rejected because the interesting questions in this dataset
are cross-cutting (technology x seniority x city x contract kind) and pre-aggregating
that product either explodes the payload or fixes the questions in advance — which is
exactly the limitation the redesign is meant to remove.

**Keep matplotlib PNGs, improve the template only.** Lowest effort, and it would still
fix the weakest part of the current page (its narrative). Rejected as the *only* change:
it leaves the site technologically indistinguishable from its current state, and the
reader still cannot ask a question we did not anticipate.

**A small backend API over the SQLite file.** Rejected: it introduces hosting, cost and
an availability dependency to serve data that fits comfortably in a file, and it would
break the GitHub Pages constraint.

**A JS framework (React/Svelte) for the page.** Rejected: one document with a handful of
charts and a filter bar does not need a component runtime; adding one signals reflex
rather than judgement.

## Consequences

**Positive.**
- Zero running cost and no infrastructure to keep alive; the page cannot go down
  independently of the repository.
- The reader can drill into dimensions the author did not pre-compute.
- One definition per metric, provable by the parity test (DuckDB-over-Parquet must equal
  SQLite for every published metric) — which simultaneously proves the export is faithful.
- The *Show SQL* toggle makes the gap between "what the chart claims" and "what was
  computed" inspectable rather than trusted.

**Negative / accepted costs.**
- ~3 MB of WASM vendored in the repository and downloaded by engaged readers. Mitigated
  by lazy loading and by the page being complete without it.
- Two SQL dialects exist in the codebase during the transition (SQLite for the write
  path, DuckDB for analytics). Mitigated by keeping SQLite queries confined to `db.py`.
- New runtime dependencies: `duckdb`, `pyarrow`, `jinja2`.
- Client-side rendering is harder to test than a PNG. Accepted: the parity test covers
  the numbers, and a browser smoke test is deferred to the backlog.

**Neutral.**
- The published artifact becomes a first-class deliverable, which forces the question of
  *what* may be published — answered separately in ADR 0002.
