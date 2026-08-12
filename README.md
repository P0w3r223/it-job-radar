# it-job-radar

**Most junior IT offers in Poland are not development jobs.**

Of the 47 offers open to juniors in the current sample, 14 are IT support and
administration — the largest single category, ahead of every engineering discipline.
That is the finding this repository exists to make defensible: a sampling design that
does not confuse "listed" with "observed", a data contract that fails the build before a
bad number reaches the page, and every published metric defined exactly once, in SQL,
which the site shows the reader verbatim.

**Live report: <https://p0w3r223.github.io/it-job-radar/>**

> Portfolio project A2 — data engineering. Numbers above are from the 2026-08-12 snapshot;
> [`docs/data/manifest.json`](docs/data/manifest.json) always carries the current ones.

## How the sample is built

The expensive assumption in job-market scraping is that measuring the market means
fetching offers. It does not — presence and attributes cost different things, so this
project separates them ([ADR 0003](docs/adr/0003_sampling-design.md)):

- **Presence is free and complete.** One sitemap request identifies every live offer, and
  the offer id is contained in the URL. So the population frame is a census, recorded on
  every run — never a sample. `observe` costs a handful of requests.
- **Attributes are bounded.** Offer pages are fetched at most once per offer, under a
  budget capped by `MAX_FETCH_BUDGET` — never the whole base. The queue is rebuilt each
  run: a census of everything new today, then a seeded uniform draw from the backlog,
  then a ~2% audit quota that *measures* the "attributes do not change" assumption instead
  of asserting it.
- **Cohorts are not interchangeable.** Offers already listed on day 0 have an unknown
  entry date (left truncation) and can never support lifetime estimation; offers first
  seen later can. The two are marked in the schema so the analysis layer cannot mix them
  by accident.

Because presence is a census, the panel is honest from day one: on 2026-08-12 the frame
grew by 210 new offers and lost 73, against 6603 listed — an inflow the fetch budget
covers in full (`inflow_capture_rate = 1.0`), which is what keeps the panel from skewing
toward long-lived postings.

## Architecture

Every published metric is defined exactly once, as a `.sql` file, and DuckDB executes it
over a redacted Parquet dataset that is committed to this repository. The page, the
notebook and the tests all run those same files, so a number in one cannot drift from a
number in another — and the query behind every chart is printed next to it, verbatim,
rather than described.

The dataset is a download, not a private input: a reader who wants a question the page
does not answer can run the same queries against the same file. Shipping DuckDB-WASM to do
that filtering *in* the page was the original plan and was dropped once the bundle was
measured at 21–37 MB against a 241 kB dataset —
[ADR 0001](docs/adr/0001_browser-side-analytics-stack.md) records the numbers and the
reversal.

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

`docs/data/` holds the artifact the page downloads (~250 kB). It is **derived analytical
data, deliberately not a substitute for the source**
([ADR 0002](docs/adr/0002_published-artifact-policy.md)): no title, no company, no offer
URL, and `offer_id` replaced by a salted hash that is stable across snapshots and not
reversible. `manifest.json` states the provenance (git SHA, snapshot, schema version),
row counts, quality metrics, and what was redacted.

So the dataset answers *market* questions — which technologies appear, what the salary
ranges look like per seniority and contract kind, how the market splits by work mode —
and deliberately cannot answer *listing* questions: who is hiring, and where to apply.

`snapshot_dimension_metrics` is the same answers, dated: one row per run per metric per
dimension — a technology's offer count, a seniority's median — each carrying the `n` it
rests on. It is measured on every export with the same named queries the page runs, so a
point in the series and a number on the page cannot disagree by method. The series starts
at the first export that recorded it: a run that has passed cannot be measured again.

## Trusting the numbers

- **A data contract** (`data/contract.yaml`) states required columns, value domains and
  sanity bounds as the conditions that are *wrong*. `pipeline quality` exits non-zero on a
  violation, and nothing is exported from data that fails it. Value domains reference
  `config.py` so the contract and the code cannot drift.
- **Every figure carries its `n`.** The site build fails if a chart would publish values
  without counts. Strata below `MIN_STRATUM_N` are labelled and greyed rather than
  silently plotted — today that is `head` (4), `intern` (11) and `lead` (24).
- **Medians carry a bootstrap interval.** This immediately earned its keep: the median B2B
  rate for `expert` once rested on n=4 with an interval from 140 to 28560 PLN — a number
  the page must not print as if it were solid.
- **B2B is never averaged with employment.** Salary `kindCode` is `gross` (employment) or
  `netto (+ VAT)` (B2B), and `time_unit` distinguishes hourly from monthly.
- **The alias dictionary reports its own misses, and the fix reaches old data.**
  `pipeline quality` prints the technology names it failed to resolve, ranked by how often
  they cost us, ready to paste into `data/normalization/tech_aliases.yaml`. Every mention
  keeps the name the offer used, so the next observation re-resolves what is already
  stored — an alias added today repairs an offer collected months ago instead of only
  improving the next collection.

## Pipeline

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
pytest

# presence census — one cheap request, the whole population frame
.venv/Scripts/python -m it_job_radar.pipeline observe
# frame + a bounded queue of offers whose attributes are not known yet
.venv/Scripts/python -m it_job_radar.pipeline collect --budget 300 --seed 20260812
# quality metrics + data contract (exit 1 on violation), and the unmatched-alias list
.venv/Scripts/python -m it_job_radar.pipeline quality
# the redacted Parquet dataset the site queries
.venv/Scripts/python -m it_job_radar.pipeline export
# render docs/index.html from that dataset
.venv/Scripts/python -m it_job_radar.pipeline site
# check the published manifest still describes the data beside it (CI runs this too)
.venv/Scripts/python -m it_job_radar.pipeline verify
```

## Limitations

Stated here rather than discovered by the reader:

- **Coverage is partial.** Attributes are known for 387 of 6603 listed offers (5.9%).
  Presence is complete; everything else is a sample, and the page says so beside the
  figures that depend on it.
- **Thin strata exist and are shown as thin.** Three seniority levels sit below the
  suppression threshold. They are labelled, not deleted — a suppressed stratum that
  vanishes silently is worse than one the reader can see is small.
- **Salary is disclosed on a minority of offers** (~28%), and most disclosed rows do not
  state whether the amount is B2B or employment. Both shares are published as metrics.
- **Collection is not scheduled.** theprotocol serves stripped pages to datacenter IPs
  (GitHub Actions), so collection runs locally and the site is published from a committed
  snapshot; CI keeps the suite green as the living proof. Escalating bot-evasion to scrape
  from CI would be the wrong trade-off for a portfolio project — a documented limitation
  rather than a hidden failure.
- **Trends need time.** Survival analysis unlocks on the flow cohort after roughly two
  weeks of observation; technology trends need several collection runs on distinct days.

## Data source & ethics

Primary source **theprotocol.it** (Grupa Pracuj): `robots.txt` permits the offer pages and
publishes an offers sitemap. The project stays respectful — a bounded fetch budget (never
the whole base; EU database *sui generis* right), throttling between requests, **no
personal data** (the `applying` block is dropped at parse time), and attribution.
[`docs/research/data-sources.md`](docs/research/data-sources.md) carries the full
reasoning, including why No Fluff Jobs and justjoin.it were rejected (`robots.txt`
disallows `/api/`).

## License

MIT. Job data © theprotocol.it (Grupa Pracuj) — collected respectfully for educational,
non-commercial use.
