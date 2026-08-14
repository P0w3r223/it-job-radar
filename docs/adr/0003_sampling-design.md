# ADR 0003 — Sampling design: presence from the frame, attributes by census of inflow

Date: 2026-08-11
Status: accepted
Author: P0w3r223
Related to: `docs/plan/0001_implementation-walkthrough.md`, `docs/research/data-sources.md`,
`docs/adr/0002_published-artifact-policy.md`

---

## Context

The collector takes `DEFAULT_SAMPLE_SIZE` offers per run via `_spread_sample` — a fixed
stride from index 0 over the sitemap. Three measurements taken on 2026-08-11 reframe what
that costs and what is possible instead:

1. **The offer id is contained in the URL.** Every one of the 6466 sitemap URLs ends in
   `,oferta,<guid>`; the guid is unique across the file and equals `offer.id` from
   `__NEXT_DATA__` (verified on the first, middle and last URL of the sitemap). The
   identity of every live offer is therefore knowable **without fetching any offer page**.
2. **The sitemap index holds exactly one child file** listing 6466 current offers — one
   request yields the complete population frame.
3. **Offers are short-lived.** Of the 314 offers collected on 2026-07-17, **68 (21.7%)
   were still listed 25 days later**. Under a constant-hazard assumption that implies a
   median lifetime around 11 days and, by Little's law over a 6466-offer base, an inflow
   on the order of 400 new offers per day.

Two consequences follow. Presence is free and complete, so nothing about *which offers
exist* needs to be sampled. And offer attributes (title, technologies, salary, seniority)
are effectively immutable for the life of a posting, so fetching a known offer a second
time buys nothing.

The current design ignores both: it re-fetches the same ~300 stride positions every run,
learns nothing about the other 95% of the base, and discards presence information it
already had in hand.

## Decision

**Separate presence from attributes.**

*Presence* is recorded for the entire population, every run, from the sitemap alone
(one request). A `sitemap_offers` table is the population frame: `offer_id`, `url`,
`first_seen`, `last_seen`, `fetch_state`. An offer's disappearance is recorded implicitly
— `last_seen` stops advancing.

*Attributes* are fetched at most once per offer, from a priority queue rebuilt each run:

| Priority | Queue | Purpose |
|---|---|---|
| P1 | ids appearing in the frame for the first time today, never fetched | census of inflow |
| P2 | never-fetched ids still live (backlog), drawn uniformly with a recorded seed | drain the day-0 stock without bias |
| P3 | ~2% quota of already-fetched, still-live ids | audit the immutability assumption |

The run fetches `min(budget, len(queue))` pages, throttled as before. Anything the budget
does not reach stays in the backlog and is reconsidered next run — the queue is
self-healing, so an undersized budget delays coverage rather than losing it.

**The budget is set from measurement, not assumption.** Exact daily inflow is the
difference between two consecutive frames and costs one request per day. The first week
runs in observe-only mode (`pipeline observe`: fetch the frame, fetch no offer pages),
after which `DEFAULT_SAMPLE_SIZE` is set to the measured inflow plus backlog headroom.

**Two cohorts are kept distinct in analysis**, because they carry different evidential
weight:

- **Cohort A — the stock present at day 0.** Entry date unknown (**left truncation**).
  Valid for market composition; **invalid for lifetime estimation**.
- **Cohort B — offers first observed after day 0.** Entry observed, exit observed or
  right-censored. Valid for survival analysis (Kaplan-Meier).

Mixing them when estimating lifetime would be the same class of error as pooling B2B with
employment salaries, and is prevented in the query layer rather than by convention.

**Length bias is measured, not assumed away.** If the budget is persistently smaller than
the inflow, short-lived offers expire before they are ever fetched and the known set skews
toward long-lived postings — the inspection paradox. The primary defence is a budget at or
above the measured inflow, which drives the per-offer capture probability to ~1. A quality
metric, `inflow_capture_rate` (fetched new ids / new ids appearing), is computed each run
and published; when it drops below 1, Horvitz-Thompson weights derived from
`1 - (1 - p)^k` (k = runs the offer was live) become necessary, and the metric is the
signal to apply them.

## Alternatives considered

**Seeded uniform sampling over the whole frame each run.** Simple and unbiased for
composition. Rejected: it spends most of its budget re-fetching offers whose attributes
are already known, and it converges on coverage far more slowly than a queue that never
repeats work.

**Keep the stride, add a random offset per run.** A one-line change that would at least
rotate coverage. Rejected as insufficient: it still cannot distinguish known from unknown
offers, so the budget keeps colliding with already-fetched ids as coverage grows.

**Re-fetch every known live offer to detect edits.** Rejected: it would consume the entire
budget to answer a question the 2% audit quota answers statistically, and it scales with
the base rather than with the inflow.

**Per-sighting history table (`offer_seen`, one row per offer per run).** Rejected:
~6466 rows per run, ~2.4M per year, to store what two columns (`first_seen`, `last_seen`)
already express. Offers that vanish and return later are handled with a re-appearance
flag; that case is rare and does not justify the table.

## Consequences

**Positive.**
- Complete, unbiased presence data from day one — survival analysis becomes possible after
  roughly two weeks, far earlier than technology trends.
- The politeness constraint stops being only a limitation: one bounded, non-repeating
  fetch queue per day converges toward full coverage of everything published after day 0.
- The budget rests on a measured inflow rather than a guessed sample size.
- The main statistical threat (length bias) has a named metric attached to it.

**Negative / accepted costs.**
- Schema migration and a rewrite of the sampling path (`_spread_sample` is retired).
- "Attributes are immutable" is an assumption. It is *measured* by the P3 audit quota
  rather than asserted, but until several runs accumulate it remains unverified.
- The 25-day survival figure rests on 314 offers drawn by the old stride and on a
  constant-hazard assumption. It is used only to size an initial budget, never published
  as a finding; the real estimate comes from cohort B.
- Cohort A can never support lifetime analysis. This is inherent to starting observation
  mid-stream, not a defect to be fixed later.

**Neutral.**
- `data/job_offers.db` grows by one frame row per distinct offer ever seen (~1 MB per
  6.5k offers). At the observed inflow this is on the order of 15-20 MB per year — well
  within SQLite's comfort, and the file stays local per ADR 0002.
