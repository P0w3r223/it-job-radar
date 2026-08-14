# it-job-radar

**Most junior IT offers in Poland are not development jobs.**

Of the 368 *vacancies* open to juniors, 97 are IT support and service-desk work — the
largest single category, against 72 that are development of any kind. Making that claim
defensible is what this repository is: a sampling design that does not confuse "listed"
with "observed", a unit of analysis that does not confuse an advert with a job, a data
contract that fails the build before a bad number reaches the page, and every published
metric defined exactly once in SQL, shown to the reader verbatim.

**Live report: <https://p0w3r223.github.io/it-job-radar/>**

> Portfolio project A2 — data engineering. Numbers above are from the 2026-08-14 snapshot;
> [`docs/data/manifest.json`](docs/data/manifest.json) always carries the current ones.

## How the sample is built

Measuring the market does not mean fetching every offer — presence and attributes cost
different things ([ADR 0003](docs/adr/0003_sampling-design.md)):

- **Presence is free and complete.** One sitemap request identifies every live offer, so
  the population frame is a census on every run, never a sample.
- **Attributes are bounded.** Offer pages are fetched at most once per offer under a budget
  capped by `MAX_FETCH_BUDGET`. The queue is rebuilt each run: a census of everything new
  today, a seeded uniform draw from the backlog, then a ~2% audit quota that *measures* the
  "attributes do not change" assumption.
- **Cohorts are not interchangeable.** Offers listed on day 0 have an unknown entry date
  (left truncation) and cannot support lifetime estimation; the two cohorts are marked in
  the schema so the analysis layer cannot mix them.

Daily inflow has ranged from 210 to 451 new offers, so the budget is read off the `new`
count `observe` prints rather than fixed as a constant — capturing a whole day's inflow is
what keeps the panel from skewing toward long-lived postings.

### An advert is not a job

One employer publishes a single role once per city — 18 adverts for the same Cloud Data
Engineer. **39% of adverts repeat a job this way**, so counting adverts lets posting habits
stand in for demand, and the bias grows with the sample. Deduplicating moved `azure` from
third place in the technology ranking to seventh.

Every counting metric groups on a vacancy key (title + company, hashed into the published
dataset). The one exception is city-versus-remote: a role advertised in eighteen cities
really is offered in eighteen cities.

## Architecture

Every published metric is defined once, as a `.sql` file, and DuckDB executes it over a
redacted Parquet dataset committed to this repository. Page, notebook and tests run the
same files, so numbers cannot drift between them — and each query is printed beside the
chart it produced.

The dataset is a download, not a private input. Shipping DuckDB-WASM to filter it *in* the
page was the original plan, dropped once the bundle measured 21–37 MB against a 241 kB
dataset ([ADR 0001](docs/adr/0001_browser-side-analytics-stack.md)).

```
src/it_job_radar/
  config.py                # source, etiquette, sampling, thresholds, export policy
  collect/theprotocol.py   # sitemap frame -> offer pages -> parsed dicts (I/O split from parsing)
  migrations.py            # ordered schema migrations (PRAGMA user_version)
  db.py                    # SQLite system of record: frame, attributes, snapshots
  sampling.py              # fetch-queue construction (pure)
  normalize.py             # tech aliases, role families, seniority (PL), currency, B2B/UoP
  quality.py               # quality metrics + data contract
  export.py                # redacted Parquet dataset + manifest
  analytics/queries/*.sql  # ONE definition per published metric
  analytics/engine.py      # runs the named queries in DuckDB over the dataset
  analytics/stats.py       # bootstrap intervals, thin-stratum suppression
  analytics/history.py     # dated per-dimension metrics, measured with those same queries
  site/build.py            # Jinja2 + inline-SVG charts -> docs/
  pipeline.py              # CLI
docs/data/                 # the published artifact: Parquet + manifest.json
docs/adr/                  # why the non-obvious decisions were made
```

## The published dataset

`docs/data/` holds the artifact the page downloads (~250 kB): **derived analytical data,
deliberately not a substitute for the source**
([ADR 0002](docs/adr/0002_published-artifact-policy.md)) — no title, no company, no URL,
and `offer_id` replaced by a salted, non-reversible hash stable across snapshots.
`manifest.json` states provenance, row counts, quality metrics and what was redacted.

So it answers *market* questions — technologies, salary ranges per seniority and contract
kind, work-mode split — and cannot answer *listing* questions: who is hiring, where to
apply.

`snapshot_dimension_metrics` is the same answers, dated: one row per run per metric per
dimension, each carrying its `n`, measured on every export with the queries the page runs.
A passed run cannot be measured again, so the series starts at the first export.

## Trusting the numbers

- **A data contract** (`data/contract.yaml`) states required columns, value domains and
  sanity bounds as the conditions that are *wrong*. `pipeline quality` exits non-zero on a
  violation, and nothing is exported from data that fails it.
- **Every figure carries its `n`**, and the site build fails if a chart would publish
  values without counts. One stratum, `head` (28), sits below `MIN_STRATUM_N` and is
  greyed rather than silently plotted.
- **Precision is measured, not assumed.** A median is also greyed when its bootstrap
  interval exceeds `MAX_CI_WIDTH_SHARE` of itself — which caught a junior B2B figure that
  passed the count test at n=52. Both tests are kept: a narrow interval on two rows is
  degeneracy, not precision.
- **B2B is never averaged with employment.** `kindCode` separates gross employment from
  `netto (+ VAT)`, and `time_unit` hourly from monthly.
- **A derived number known to be false is withheld.** Amount and unit are separate source
  fields, so both errors occur: 14 500 PLN filed as an hourly rate, and hourly rates filed
  as monthly at 14–180 PLN. What the employer wrote stays as written; only *our* monthly
  equivalent is withdrawn, and the page counts the withholdings.
- **The alias dictionary reports its own misses, and the fix reaches old data.** Every
  mention keeps the raw name the offer used, so the next observation re-resolves what is
  already stored — an alias added today repairs an offer collected months ago.

## Pipeline

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
pytest

# presence census — one cheap request, the whole population frame
.venv/Scripts/python -m it_job_radar.pipeline observe
# bounded queue of offers whose attributes are not known yet
# (--budget above the `new` count observe printed, or the inflow census is partial)
.venv/Scripts/python -m it_job_radar.pipeline collect --budget 400 --seed 20260814
# quality metrics + data contract (exit 1 on violation), and the unmatched-alias list
.venv/Scripts/python -m it_job_radar.pipeline quality
# the redacted Parquet dataset the site queries, then the page built from it
.venv/Scripts/python -m it_job_radar.pipeline export
.venv/Scripts/python -m it_job_radar.pipeline site
# check the published manifest still describes the data beside it (CI runs this too)
.venv/Scripts/python -m it_job_radar.pipeline verify
```

## Limitations

- **Coverage.** Attributes are known for 6570 of 6571 listed adverts (100%), which is
  4007 distinct vacancies. Presence is complete; attributes remain a bounded sample by
  design, and the page says so beside the figures that depend on it.
- **Thin and imprecise figures are labelled, not deleted** — one seniority level below the
  count threshold, several medians greyed for interval width.
- **Salary is disclosed on ~28% of offers**, and most disclosed rows do not state B2B or
  employment. Both shares are published as metrics.
- **Collection is not scheduled.** theprotocol serves stripped pages to datacenter IPs, so
  collection runs locally and the site is published from a committed snapshot; CI keeps the
  suite green. Escalating bot-evasion to scrape from CI would be the wrong trade-off.
- **Trends need time.** Survival analysis unlocks on the flow cohort after roughly two
  weeks of observation; technology trends need several runs on distinct days.

## Data source & ethics

Primary source **theprotocol.it** (Grupa Pracuj): `robots.txt` permits the offer pages and
publishes an offers sitemap. The project stays respectful — a bounded fetch budget (never
the whole base; EU database *sui generis* right), throttling between requests, **no
personal data** (the `applying` block is dropped at parse time), and attribution.
[`docs/research/data-sources.md`](docs/research/data-sources.md) carries the full
reasoning, including why No Fluff Jobs and justjoin.it were rejected.

## License

MIT. Job data © theprotocol.it (Grupa Pracuj) — collected respectfully for educational,
non-commercial use.
