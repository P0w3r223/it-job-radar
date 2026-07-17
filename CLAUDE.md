# CLAUDE.md — it-job-radar

Guidance for Claude Code (and any contributor) working in this repository.

## What this project is

A pipeline that collects Polish IT job offers, normalizes them, stores them in SQLite,
and analyses technology trends and salary ranges. Portfolio project A2 — proves data
engineering: responsible collection, schema design, normalization, aggregating SQL, and
daily automation.

## Architecture

```
src/it_job_radar/
  config.py                # source, scraping etiquette, paths, normalization maps
  collect/theprotocol.py   # sitemap -> offer pages -> parsed offer dicts (I/O split from parse)
  db.py                    # SQLite: offers + technologies + dated snapshots
  normalize.py             # tech aliases, seniority (PL), currency, B2B/UoP handling
  analyze.py               # aggregations (top tech, salary medians, Wrocław vs remote)
data/normalization/        # technology alias dictionary (YAML)
notebooks/                 # analysis notebook
tests/                     # pytest
docs/research/             # data-source research + legal/ethics
```

## Rules (do not violate)

- **Respect the source.** Browser UA is required for data, but stay respectful: bounded
  spread sample (never the whole base), throttle between requests, **no personal data**
  (drop the `applying` block), attribution in README.
- **B2B ≠ UoP.** Salary `kindCode` is `gross` (employment) or `netto (+ VAT)` (B2B);
  never average them together. Watch `time_unit` (`godzinowo` hourly vs monthly).
- **Normalize before aggregating.** Unify technology aliases and seniority labels first,
  or trends are noise (`ReactJS` vs `React.js`).
- **Separate I/O from logic.** Parsing (`parse_offer`) is pure and unit-tested; network
  lives in `fetch_*` / `collect_offers`.

## Conventions

- English for code, comments, README, commit messages. Conventional Commits.
- No hardcoded values — configurable things live in `config.py`.
- Interpreter: `.venv/Scripts/python.exe` (Python 3.12). On Windows run with
  `PYTHONIOENCODING=utf-8` for Polish characters.

## How to run

```bash
.venv/Scripts/python -m pip install -r requirements.txt
pytest
```
