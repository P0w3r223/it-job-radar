# Implementation Walkthrough — it-job-radar v2

Date: 2026-08-11
Status: draft
Author: P0w3r223 + Claude
Related to: `docs/ideas/0001_concept-catalogue.md`, `docs/adr/0001_browser-side-analytics-stack.md`,
`docs/adr/0002_published-artifact-policy.md`

---

## How to read this document

A living plan. Phases are ordered by dependency, not by importance — each one leaves the
repository in a working, committable state, and the site keeps rendering throughout.
Every step states its **goal**, the **files** it touches, and its **done when** condition,
so work can stop at any step boundary and resume later.

Phases 0-6 constitute v2. Phase 7 unlocks only after several snapshots exist; the backlog
in the concept catalogue feeds phases beyond that.

## Progress

| Phase | State |
|---|---|
| 0 — Foundations | **done** (0.1 deps; `analytics/` and `site/` packages are created with their contents in phases 3 and 5, not as empty scaffolding) |
| 1 — Data foundation | **done** |
| 2 — Quality layer | **done** |
| 3 — Analytics layer | **done** |
| 4 — Export | **done** — redaction and the Parquet writer landed early, with phase 3, because the engine needed something to query |
| 5 — Site | 5.1, 5.2 and 5.5 **done** (server-rendered page, inline-SVG charts, honesty gate); 5.3, 5.4 (DuckDB-WASM layer) and 5.6 (retire `analyze.py`) remain |
| 6 — Publication | 6.4 **done** (README rebuilt finding-first, About metadata and topics updated, ADR pointers added to the research doc); 6.1-6.3 and 6.5 remain |
| 7 — Trends and survival | blocked on repeated observations |

Two deliberate deviations, recorded so they are not mistaken for oversights:

- **No `data_quality` table.** Migration v3 gave `snapshot_stats` a `detail` column, which
  covers everything the separate table was for. A second near-identical table would only
  add a join.
- **Role classification re-runs over every offer**, not only unclassified ones. A
  classification that ran once would freeze early mistakes in place; re-deriving makes the
  rule table live — edit the YAML, and the next run repairs the labels.
- **Salary metrics are defined as row queries, not aggregates.** `salary_rows.sql` returns
  the filtered rows and the aggregation happens in `analytics/stats.py`. The filter is the
  part that must be defined once; keeping a second aggregated query would duplicate that
  `WHERE` clause, and returning rows is what allows a bootstrap interval and an honest `n`.
- **Charts are inline SVG generated at build time, not matplotlib PNGs.** The plan said
  "static fallback charts"; SVG turned out to be the better default rather than a fallback
  — it inherits the reader's colour scheme (so dark mode is not a second rendering), stays
  sharp at any size, and its labels are real text for screen readers. It also cut the page
  from 82 kB of base64 to 31 kB.
- **Technology mentions keep their raw name (migration v5, added 2026-08-12).** Phase 2.3
  promised that alias coverage would "rise measurably after the list is applied", and the
  first real report showed it could not: only the normalized value was stored, so a
  dictionary edit could improve future collections and nothing else. The schema now keeps
  the name the offer used, and re-resolution runs on every observation exactly as role
  classification does. Measured effect on the stored data: coverage 0.368 → 0.625, with
  102 mentions re-resolved and 8 duplicate rows merged.
- **Alias coverage is measured from the database, not from the last fetch.** It used to be
  computed over the raw offers of one run, which made it a property of that batch and
  impossible to recompute after a dictionary edit. It now reads the stored raw names, so
  `pipeline quality` answers with the current dictionary.
- **Parity is asserted against `analyze.py`, not between two dialects.** SQLite has no
  `MEDIAN`, so identical query text cannot run on both engines. The stronger check is the
  one in place: the exported Parquet must equal the redacted source table for table, and
  the DuckDB metrics must equal what the existing SQLite path produces.

## Target architecture

```
src/it_job_radar/
  config.py                    # + sitemap index, sampling, thresholds, export policy
  collect/theprotocol.py       # + index discovery, seeded coverage-aware sampling
  db.py                        # SYSTEM OF RECORD (SQLite): upserts, migrations
  migrations.py                # NEW  schema_version + ordered migration steps
  normalize.py                 # + role families, alias-miss reporting
  quality.py                   # NEW  data-quality metrics -> data_quality table
  export.py                    # NEW  SQLite -> redacted Parquet + manifest.json
  analytics/
    queries/*.sql              # NEW  single source of truth for every metric
    engine.py                  # NEW  DuckDB runner over the exported Parquet
  analyze.py                   # thin facade -> analytics.engine (notebook compatibility)
  site/
    build.py                   # NEW  Jinja2 render -> docs/
    templates/index.html.j2    # NEW
    assets/{app.js,styles.css} # NEW
  pipeline.py                  # CLI: collect | export | site build | quality report

data/
  job_offers.db                # local, git-ignored, unredacted
  normalization/tech_aliases.yaml
  normalization/role_families.yaml   # NEW
  contract.yaml                # NEW  published-artifact contract

docs/                          # published site (build output, committed)
  index.html
  data/{offers,technologies,salaries,snapshots}.parquet
  data/manifest.json
  vendor/duckdb-wasm/          # pinned bundle
```

Dependency additions: `duckdb`, `pyarrow`, `jinja2`. Removed from the runtime path once
Phase 5 lands: `seaborn` (unused), and `matplotlib` moves to the `dev` extra — it stays
for the notebook, but the site no longer renders PNGs.

---

## Phase 0 — Foundations

No user-visible change. Makes the later phases safe to apply.

**0.1 Dependencies and layout**
Goal: declare the new stack and create empty package scaffolding.
Files: `pyproject.toml`, `src/it_job_radar/analytics/__init__.py`, `site/__init__.py`.
Done when: `pip install -e .[dev]` succeeds and `pytest` is still green.

**0.2 Schema migrations**
Goal: a `schema_version` table and an ordered list of migration callables applied on
`db.connect()`. Today the schema is created by `executescript` with `IF NOT EXISTS`,
which silently cannot evolve a table that already exists — every later phase in this plan
needs an `ALTER TABLE`.
Files: `migrations.py`, `db.py`.
Sketch: `MIGRATIONS: list[tuple[int, str, Callable]]`; `connect()` reads
`PRAGMA user_version`, applies pending steps in a transaction, sets the new version.
Done when: a test opens a database created by the *old* schema, connects, and finds the
new columns present with `user_version` advanced; a second connect is a no-op.

**0.3 Config surface**
Goal: every threshold this plan introduces lands in `config.py`, per project rules —
sitemap index URL, sample seed policy, `MIN_STRATUM_N` (suppression threshold), export
paths, redaction column lists, size budget.
Done when: no literal thresholds appear outside `config.py`.

---

## Phase 1 — Data foundation

**1.1 Sitemap index discovery**
Goal: stop hardcoding the child sitemap. `robots.txt` publishes
`.../CurrentOffers/sitemap_index.xml`, which today lists exactly one child
(`SiteMapJobOffers1.xml`, 6466 URLs) — but the count and names are the source's business,
not ours.
Files: `config.py` (index URL replaces `TP_SITEMAP_URL`), `collect/theprotocol.py`
(`fetch_sitemap_index()` -> child URLs; `fetch_sitemap_urls()` unions them).
Done when: a unit test with a fixture index containing two children returns the union;
a live smoke run reports 6466 URLs from one child.

**1.2 Population frame and the observer** (see ADR 0003)
Goal: record presence for the *entire* base every run from the sitemap alone, and stop
treating "which offers exist" as something that needs sampling. The offer id is contained
in the URL (`...,oferta,<guid>`, verified), so one request identifies all 6466 live
offers.
Files: `migrations.py` (`sitemap_offers(offer_id, url, first_seen, last_seen,
fetch_state, reappeared)`), `db.py` (`record_frame`), `collect/theprotocol.py`
(`offer_id_from_url`), `pipeline.py` (`observe` command).
Sketch: upsert every sitemap id — new ids get `first_seen = last_seen = today`, known ids
advance `last_seen`. Disappearance is implicit (`last_seen` stops advancing). An id that
returns after a gap sets `reappeared`.
Done when: `pipeline observe` costs one request, writes one frame row per live offer, and
a second run on the same frame changes only `last_seen`.

**1.3 Priority fetch queue** (see ADR 0003)
Goal: retire `_spread_sample` — a fixed stride from index 0 that re-fetches the same ~300
positions every run — and spend the fetch budget only on offers whose attributes are
unknown.
Files: `collect/theprotocol.py`, `pipeline.py` (`--seed`, `--budget`), `config.py`.
Sketch: rebuild the queue each run — **P1** ids new to the frame today and never fetched
(census of inflow); **P2** never-fetched ids still live, drawn uniformly with a recorded
seed (drains the day-0 stock without bias); **P3** a ~2% audit quota of already-fetched
live ids, which *measures* the "attributes are immutable" assumption instead of asserting
it. Fetch `min(budget, len(queue))`; the remainder carries over to the next run.
Done when: no offer is fetched twice outside the audit quota, two runs with different
seeds draw disjoint P2 sets, and coverage (`fetched / frame`) strictly increases.

**1.3a Cohort marking**
Goal: the analysis layer must not be able to mix the two cohorts by accident — offers
present at day 0 are left-truncated (entry date unknown) and cannot support lifetime
estimation, while offers first observed later can.
Files: `migrations.py` (`cohort` column on `sitemap_offers`), `analytics/queries/*.sql`.
Done when: the lifetime query filters to cohort B by construction, and a test asserts a
cohort-A offer never appears in a survival result.

**1.4 Snapshot identity**
Goal: a snapshot is a run, not a date. Today re-running on one day overwrites
`snapshot_stats` — which is why the stored `offer_count` reads 250 while `offers` holds
314.
Files: `migrations.py` (`snapshots(snapshot_id, started_at, seed, sample_size, git_sha)`;
`snapshot_stats` gains `snapshot_id`), `db.py`, `pipeline.py`.
Done when: two runs on one day produce two snapshot rows, and `offer_count` reflects the
database total rather than the run's sample size.

**1.5 Normalization gaps**
Goal: close the two known holes — `head` appears in the data but is missing from
`SENIORITY_MAP` and `SENIORITY_ORDER` (it sorts to rank 99); role families do not exist,
which is why "top technologies for juniors" currently reports a helpdesk profile
(`active directory`, `windows server`, `microsoft office`) off 19 offers.
Files: `config.py`, `data/normalization/role_families.yaml`, `normalize.py`.
Sketch: an ordered rule table matching normalized title text to
`backend|frontend|fullstack|devops|data|qa|analyst|support|security|management|other`;
first match wins; `other` is a legitimate outcome and is reported, not hidden.
Done when: unit tests cover the Polish and English title forms present in the snapshot,
and the share classified `other` is published as a quality metric (1.5 feeds 2.1).

**1.6 Restore `offer_url`**
Goal: fix a silent data loss found on 2026-08-11 — `normalize_offer` rebuilds the offer
dict field by field and omits `offer_url`, so `db.write_offers` has always stored `None`.
All 314 rows in the current database have a NULL URL.
Files: `normalize.py`, `tests/test_normalize.py`, one backfill step in `migrations.py`.
Sketch: copy the key through; backfill from `sitemap_offers` for offers still listed (68
of the 314 were still live on 2026-08-11). The rest stay NULL — the URL of a delisted
offer is not recoverable, and inventing one would be worse than a null.
Done when: a regression test asserts a normalized offer keeps its URL, and the backfill
reports how many rows it could and could not repair.

---

## Phase 2 — Quality layer

**2.1 Metrics**
Goal: compute, per snapshot, the numbers that say how much the results can be trusted.
Files: `quality.py`, `migrations.py` (`data_quality(snapshot_id, metric, value, detail)`).
Metrics: pages fetched / parsed / skipped; share of offers with a usable salary; share of
salary rows with `kind IS NULL` (340 of 443 today); **alias coverage** — share of raw
technology names resolved by the dictionary rather than the lowercase fallback, plus the
top-N unmatched names stored in `detail`; role-family `other` share; `n` per seniority,
city and contract stratum; snapshot freshness in days.
Note: `collect_offers` currently prints its skip count and discards it — return it.
Done when: a run writes one `data_quality` row per metric, and a test on a synthetic
snapshot asserts each computed value.

**2.2 Data contract**
Goal: a declarative contract for the published artifact — required columns, types,
nullability, allowed value sets (seniority, work mode, contract kind, currency), and
sanity bounds (`monthly_from <= monthly_to`, salaries within a plausible range).
Files: `data/contract.yaml`, `quality.py` (`validate_contract`).
Sketch: hand-rolled validation over the export frames — a schema-validation dependency
would be more machinery than the rule set justifies. Revisit if the contract grows.
Done when: violating the contract raises with the offending column, rule and row count;
a test asserts each rule fires.

**2.3 Alias feedback loop**
Goal: make the dictionary improve itself. `pipeline quality report` prints the top
unmatched technology names, ranked by frequency, ready to paste into
`tech_aliases.yaml`.
Done when: running it against the current snapshot produces a non-empty, plausible list,
and alias coverage rises measurably after the list is applied.

---

## Phase 3 — Analytics layer

**3.1 Named queries**
Goal: every published metric defined exactly once, as SQL, in a file.
Files: `analytics/queries/*.sql` — `top_technologies`, `salary_by_seniority`,
`salary_by_contract_kind`, `work_mode_distribution`, `city_vs_remote`,
`stratum_sizes`, `offer_lifetime`, `quality_summary`.
Sketch: DuckDB dialect, reading Parquet by path, with named parameters (`$seniority`,
`$limit`, `$required_only`). Header comment per file stating what the metric means and
what it deliberately excludes.
Done when: each file runs standalone against the exported artifact.

**3.2 Engine**
Goal: `analytics.engine.run(name, **params) -> pd.DataFrame`, loading the query text once
and executing it in DuckDB.
Files: `analytics/engine.py`; `analyze.py` becomes a thin facade delegating to it, so the
notebook keeps working.
Done when: existing `tests/test_analyze.py` passes against the facade unchanged.

**3.3 Parity test**
Goal: the load-bearing test of this whole design — for each published metric, the
DuckDB-over-Parquet result must equal the SQLite result computed from the system of
record. It proves the export is faithful *and* that the browser sees the same numbers the
pipeline does.
Files: `tests/test_parity.py`.
Done when: parity holds for every named query on a fixture database, and deliberately
corrupting the export makes the test fail.

**3.4 Uncertainty**
Goal: medians published with a bootstrap confidence interval, and any stratum below
`MIN_STRATUM_N` flagged rather than silently plotted.
Files: `analytics/engine.py` (or a small `analytics/stats.py`).
Done when: `salary_by_seniority` returns `median_from`, `ci_low`, `ci_high`, `n`,
`suppressed`; a test on a known distribution asserts the interval covers the truth at the
expected rate.

---

## Phase 4 — Export

**4.1 Redacted Parquet export**
Goal: `export.py` writes `offers`, `technologies`, `salaries`, `snapshots` as Parquet
under `docs/data/`, applying ADR 0002 — no `title`, no `company`, no `offer_url`, and
`offer_id` replaced by a stable salted hash.
Done when: a test asserts the excluded columns are absent from every written file and
that the same offer hashes identically across two snapshots.

**4.2 Manifest**
Goal: `manifest.json` carrying snapshot id, collection date, git SHA, row counts per
table, the quality metrics from Phase 2, the schema version, and the attribution string.
Done when: the file validates against its own contract and the site footer renders it.

**4.3 Budgets**
Goal: the export fails if the artifact exceeds `MAX_ARTIFACT_BYTES` — a static site
should not accumulate a database by accident.
Done when: the budget is asserted in a test with a synthetic oversized frame.

---

## Phase 5 — Site

**5.1 Template extraction**
Goal: move the HTML out of the f-string in `report.py` into
`site/templates/index.html.j2`; `site/build.py` gathers data and renders. This is the
same I/O-from-logic split the collector already follows.
Done when: `pipeline site build --out docs/` reproduces the current page's content from
the template, and `report.py` is deleted or reduced to a deprecation shim.

**5.2 Narrative and honesty**
Goal: the page leads with a finding, not with "Overview" — the sibling portfolio sites
(`ab-lab`, `mlops-car-price`) all do, and this one does not.
Content order: headline finding -> KPI row (offers, share with disclosed salary, remote
share, median mid B2B) -> in-demand technologies -> salaries as a **range/dumbbell chart
with B2B and employment side by side** (both exist in the data; only B2B is shown today)
-> junior reality check with its `n` stated -> work modes -> data quality -> methodology
and limitations -> footer with manifest provenance.
Rules applied throughout: every figure carries `n`; strata under `MIN_STRATUM_N` are
greyed and labelled; the overlapping-bars salary chart is replaced (it currently reads as
a stacked bar and invites misreading).
Done when: no chart on the page lacks an `n`, and the junior section states its sample
size in the visible copy.

**5.3 Interactive layer**
Goal: lazy-load the vendored DuckDB-WASM bundle on first interaction; filter bar over
seniority, city, work mode and contract kind; charts re-render from live query results
via Observable Plot.
Files: `site/assets/app.js`, `docs/vendor/duckdb-wasm/`.
Done when: filtering to `seniority = 'junior'` reproduces the numbers the Python engine
computes for the same filter, and the page's first paint does not download the bundle.

**5.4 Show SQL / playground**
Goal: each chart exposes the exact query behind it; an editable panel lets the reader run
their own against the same artifact.
Done when: the query text shown is read from the same `.sql` files Phase 3 executes — not
a copy pasted into the template.

**5.6 Retire the deprecated path**
Goal: `analyze.py` exists only because `notebooks/01_analysis.ipynb` still imports it.
Move the notebook onto `analytics.engine` + `analytics.stats`, then delete `analyze.py`
together with the parity tests that were guarding the transition.
Files: `notebooks/01_analysis.ipynb`, `src/it_job_radar/analyze.py`,
`tests/test_analytics.py` (parity section), `pyproject.toml`, `config.py`.
Also then possible: drop `seaborn` (unused), move `matplotlib` to the `dev` extra, and
remove `config.FIGURES_DIR` with the stale PNGs in `reports/figures/`.
Done when: nothing imports `analyze`, and the runtime dependency list contains only what
the pipeline and the site actually use.

**5.5 Craft pass**
Goal: progressive enhancement verified (full report readable with JS disabled), dark
mode, self-hosted font replacing the Google Fonts CDN link, Open Graph and Twitter meta
so the link previews when pasted into an application, favicon, `<time datetime>`,
keyboard-navigable filters, visible focus states, chart alt text.
Done when: the page passes a manual a11y pass and renders correctly with JS off.

---

## Phase 6 — Publication

**6.1 CLI**
Goal: `pipeline collect | export | site build | quality report` as the only supported
path to a published page.
Done when: the manual copy from `reports/site/` to `docs/` no longer exists anywhere,
including in the README.

**6.2 Drift guard in CI**
Goal: CI rebuilds the site from the committed data artifact and fails if the result
differs from what is in `docs/`. The current arrangement — generated output in a
git-ignored directory, published output copied by hand — can silently ship a stale page.
Files: `.github/workflows/ci.yml`.
Done when: committing an edited `docs/index.html` without rebuilding fails CI.

**6.3 Pages deploy**
Goal: publish `docs/` via the Pages action rather than branch settings, so the deployment
is visible and versioned. Collection stays local (README's documented limitation:
theprotocol serves stripped pages to datacenter IPs).
Done when: a push to `main` publishes and the run appears in Actions.

**6.4 Repository landing page**
Goal: the first screen a senior reader sees on GitHub matches what the code now does. The
README still describes a stride sample, a `collect` command that no longer exists, and a
site built from matplotlib PNGs.
Content: the headline finding first (junior IT in Poland is mostly not development);
the browser-side architecture with a link to ADR 0001; the presence/attributes split and
the two cohorts with a link to ADR 0003; the redaction policy with a link to ADR 0002; the
current CLI (`observe | collect | quality | export | site build`); what the published
dataset contains and what it deliberately cannot answer; the honest limitations
(coverage share, thin strata, no scheduled collection).
Also: repository **About** metadata — description and topics (`duckdb`, `parquet`,
`data-engineering`, `web-scraping`, `sqlite`, `python`), and the Pages link. These are the
three lines shown next to the file list and are usually the first thing read.
`docs/research/data-sources.md` gains a pointer to ADR 0002 and ADR 0003.
Done when: nothing in the README describes a code path that no longer exists, and every
non-obvious decision links to the ADR that argues it.

**6.5 Portfolio index (`current_projects`)**
Goal: the portfolio index reflects the rebuilt project. `current_projects` has no Pages
site of its own — it is a README-only index whose projects are **git submodules**, so this
is two separate acts and the second is easy to forget.
Steps: (a) rewrite the A2 row and the "Live now" entry — the current text says "data
engineering — collecting IT job offers, schema design, aggregating SQL, normalization,
respectful scraping", which now undersells it; the distinguishing claims are browser-side
analytics over a published Parquet artifact, a measured data-quality layer with a
contract, and a sampling design that separates presence from attributes; (b) **bump the
submodule pointer** for `it-job-radar` so the index actually references the new commit,
following the repository's existing `chore/bump-*` branch convention.
Done when: the A2 entry describes the rebuilt project, the submodule points at the new
commit, and the live-site link resolves to the rebuilt page.

---

## Phase 7 — Trends and survival (unlocks with accumulated runs)

Under ADR 0003 presence is complete from day one, so **7.3 unlocks first** — roughly two
weeks of observation, not the several months a sampled panel would need. Technology trends
still require several collection runs across distinct days.

- **7.1** Per-dimension dated metrics (top technologies, medians per seniority) written
  every run, so trends are computable at all — today `snapshot_stats` holds two numbers.
- **7.2** Coverage-over-time chart: unique offers ever seen vs. the current base size —
  the visible proof that bounded, polite sampling accumulates.
- **7.3** Survival analysis on cohort B (Kaplan-Meier over `first_seen`/`last_seen`, with
  right censoring for offers still live): median days a posting stays open, by technology
  and seniority. Cohort A is excluded by construction (left truncation — see ADR 0003).
- **7.4** Technology movement between snapshots, with an explicit note that short series
  are noise — no trend line drawn under a minimum series length.

## Verification strategy

| Layer | How it is verified |
|---|---|
| Parsing, normalization, role families | Unit tests on fixtures (already the project's pattern) |
| Schema migrations | Old-schema database migrated in a test; re-run is a no-op |
| Quality metrics, contract | Synthetic snapshots with known defects |
| Analytics | Parity test: DuckDB-over-Parquet == SQLite, per metric |
| Export redaction | Asserted absence of excluded columns; hash stability |
| Site content | Build-time assertions (every chart has `n`); manual a11y and JS-off pass |
| Publication | CI drift guard: rebuild must equal committed `docs/` |

Deferred: a Playwright smoke test asserting the browser numbers match the Python engine.
Worth adding once the interactive layer stabilises; not worth its setup cost before then.

## Remaining work, in the order I would do it

State at the end of the 2026-08-11 session: phases 0-4 complete, phase 5 complete except
its interactive layer, 129 tests green, eleven commits on
`feat/v2-browser-side-analytics` (branched from `main`, not merged).

**1. ~~Repository landing page (6.4).~~ Done 2026-08-12.** README rebuilt finding-first,
About description and topics updated (`duckdb`, `parquet`, `duckdb-wasm`, `data-quality`),
ADR pointers added to `docs/research/data-sources.md`.

**2. Publication guards (6.2, 6.3).** CI runs only `pytest` today. Add the drift guard —
rebuild `docs/` from the committed dataset, fail on any difference — and move the Pages
deploy into an action. Until this exists, a stale page can still be published silently.

**3. Retire the deprecated path (5.6).** Move the notebook onto the analytics engine, then
delete `analyze.py`, `seaborn`, the `matplotlib` runtime dependency, `config.FIGURES_DIR`
and the stale PNGs.

**4. Interactive layer (5.3, 5.4).** Valuable but not urgent: the page is complete without
it, and it is the one step that puts ~3 MB of vendored WASM into the repository. Decide
open question 3 before starting.

**5. Portfolio index (6.5).** Must be last: the submodule pointer should reference the
merged commit, so this follows the branch landing on `main`.

**6. Phase 7**, once repeated observations exist.

Then the concept-catalogue backlog: technology co-occurrence, salary premium by technology
(regression controlling for seniority and city), and the dataset export that P4
`pl-jobs-lora` consumes.

**Not a task, but a decision.** Coverage is 5.9% (387 of 6603 listed offers) after the
2026-08-12 collect. The junior finding now rests on 47 offers rather than 19, which moved
it from a direction to a measurement; further `collect` runs tighten it further.

## Open questions

1. ~~Is the offer id derivable from the sitemap URL?~~ **Resolved 2026-08-11: yes** —
   every URL ends in `,oferta,<guid>` and the guid equals `offer.id` from `__NEXT_DATA__`
   (verified on three URLs spread across the sitemap). Coverage-aware sampling needs no
   extra requests. See ADR 0003.
2. Fetch budget: the ~400 new offers/day estimate came from a constant-hazard fit to a
   single 25-day survival observation. **First measurement, 2026-08-12:** frame
   differencing gives 210 new and 73 gone against 6603 listed — a daily hazard near 1.1%,
   well under what that fit implied, and an inflow the 300 budget covers in full
   (`inflow_capture_rate = 1.0`). One interval is not a rate; confirm over ~5 days before
   fixing `DEFAULT_FETCH_BUDGET`.
3. Vendored WASM bundle size in practice — if it materially bloats the repository,
   reconsider a pinned CDN with the privacy trade-off documented.
4. ~~`MIN_STRATUM_N` value~~ **Resolved 2026-08-12 by data, not by argument:** the
   collect took junior from 19 to 47, above the conventional 30, so the threshold stays
   where it is and the headline segment is no longer marked thin. Three levels remain
   below it (`head` 4, `intern` 6, `lead` 18) and stay visible-but-marked.
