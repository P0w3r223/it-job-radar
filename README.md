# it-job-radar

**Pipeline collecting Polish IT job offers — technology trends and salary ranges.**

> Portfolio project A2. Demonstrates responsible data collection (respecting
> `robots.txt` / ToS), database schema design, aggregating SQL, data normalization, and
> daily automation — analysing the market a candidate actually applies to.

## What it does

1. **Collect** — gathers a bounded, spread sample of IT offers from
   [theprotocol.it](https://theprotocol.it) (data from each page's `__NEXT_DATA__`),
   respectfully: throttled, no personal data, attribution.
2. **Store** — writes normalized offers into a local SQLite database with dated snapshots.
3. **Normalize** — unifies technologies (`ReactJS`/`React.js` → `react`), seniority
   (Polish quirk: `regular` = mid), currencies, and keeps **B2B (net) separate from
   employment (gross)**.
4. **Analyze** — top technologies (incl. for juniors), salary medians per seniority/tech,
   Wrocław vs. remote.
5. **Publish** — a scheduled job snapshots daily (trends over time) and deploys a mini
   report site to GitHub Pages.

## Data source & ethics

Primary source **theprotocol.it** (Grupa Pracuj): `robots.txt` permits the offer pages
and publishes an offers sitemap. This project stays respectful: a bounded sample (never
the whole base — EU database *sui generis* right), throttling, **no personal data**
(recruiter details dropped), and attribution. See
[`docs/research/data-sources.md`](docs/research/data-sources.md) for the full reasoning,
including why No Fluff Jobs / justjoin.it were rejected (`robots.txt` disallows `/api/`).

## Project structure

```
src/it_job_radar/
  config.py                # source, scraping etiquette, paths, normalization maps
  collect/theprotocol.py   # sitemap -> offers -> parsed dicts (I/O split from parsing)
data/normalization/        # technology alias dictionary
notebooks/                 # analysis notebook
tests/                     # pytest
docs/research/             # data-source research + legal/ethics
```

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
pytest
```

## License

MIT. Job data © theprotocol.it (Grupa Pracuj) — collected respectfully for educational,
non-commercial use.
