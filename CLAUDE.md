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
  config.py                # source, scraping etiquette, sampling, paths, normalization maps
  collect/theprotocol.py   # sitemap frame -> offer pages -> parsed offer dicts (I/O split from parse)
  migrations.py            # ordered schema migrations (PRAGMA user_version)
  db.py                    # SQLite: population frame + offer attributes + snapshots
  sampling.py              # fetch-queue construction (pure): inflow -> backlog -> audit
  normalize.py             # tech aliases, role families, seniority (PL), currency, B2B/UoP
  quality.py               # quality metrics + data contract (violating-predicate rules)
  export.py                # redacted Parquet dataset (ADR 0002)
  analytics/queries/*.sql  # ONE definition per published metric — edit metrics here
  analytics/engine.py      # runs the named queries in DuckDB over the dataset
  analytics/stats.py       # bootstrap intervals; suppression by count AND interval width
  analytics/history.py     # dated per-dimension metrics (7.1) — same queries, stored per run
  site/build.py            # Jinja2 + inline-SVG charts -> docs/ (no JavaScript, no PNGs)
  pipeline.py              # CLI: observe | collect | quality | export | site | verify
data/normalization/        # technology alias dictionary (YAML)
notebooks/                 # analysis notebook
tests/                     # pytest
docs/adr/                  # architecture decisions (stack, published artifact, sampling)
docs/plan/                 # implementation walkthrough
docs/research/             # data-source research + legal/ethics
```

## Rules (do not violate)

- **Respect the source.** Browser UA is required for data, but stay respectful: a bounded
  fetch budget capped by `MAX_FETCH_BUDGET` (never the whole base), throttle between
  requests, **no personal data** (drop the `applying` block), attribution in README.
- **Presence is free, attributes are not.** One sitemap request identifies every live
  offer, so presence is never sampled; offer pages are fetched at most once per offer.
  See `docs/adr/0003_sampling-design.md`.
- **Cohorts are not interchangeable.** Offers already listed at day 0 have an unknown
  entry date (left truncation) and must never be used for lifetime estimation.
- **B2B ≠ UoP.** Salary `kindCode` is `gross` (employment) or `netto (+ VAT)` (B2B);
  never average them together. Watch `time_unit` (`godzinowo` hourly vs monthly), and note
  that the source lets an employer file one unit under the other — a monthly equivalent
  outside `SALARY_SANITY_MIN..MAX` is withheld rather than published or reinterpreted.
- **Count vacancies, not adverts.** One role is published once per city, so ~36% of adverts
  repeat a job. Every counting query groups on `vacancy_id` (title + company, hashed on
  export); `city_vs_remote_rows` is the deliberate exception, because eighteen cities really
  are eighteen cities. Changing this changes what every published metric means — the series
  metrics were renamed rather than continued when it did.
- **Normalize before aggregating.** Unify technology aliases and seniority labels first,
  or trends are noise (`ReactJS` vs `React.js`). `load_tech_aliases` refuses to load a
  dictionary where one name is both a canonical and an alias, or where two canonicals claim
  the same alias — that failure had already happened once, silently.
- **A figure is marked by measured precision, not only by count.** `MIN_STRATUM_N` asks how
  many observations; `MAX_CI_WIDTH_SHARE` asks what they bought. Both, because a narrow
  interval on two rows is degeneracy.
- **Separate I/O from logic.** Parsing (`parse_offer`, `offer_id_from_url`) and queue
  construction (`sampling.build_queue`) are pure and unit-tested; network lives in
  `fetch_*`, database access in `db.py`.
- **Schema changes go through `migrations.py`.** `CREATE TABLE IF NOT EXISTS` cannot
  evolve a table that already exists.
- **Dated metrics are measured from the published dataset, never recomputed.**
  `analytics/history.py` runs the same named queries the page runs, which is why `export`
  writes the series table twice — a run cannot appear in the dataset it is measured from
  until it has been measured. Every point carries its `n`; the contract rejects one without.

## Conventions

- English for code, comments, README, commit messages. Conventional Commits.
- No hardcoded values — configurable things live in `config.py`.
- Interpreter: `.venv/Scripts/python.exe` (Python 3.12). On Windows run with
  `PYTHONIOENCODING=utf-8` for Polish characters.

## How to run

```bash
.venv/Scripts/python -m pip install -r requirements.txt
pytest

# record the population frame — one cheap request, presence only
.venv/Scripts/python -m it_job_radar.pipeline observe
# frame + a bounded queue of offers whose attributes we do not hold yet
.venv/Scripts/python -m it_job_radar.pipeline collect --budget 300 --seed 20260811
# quality metrics + data contract (exit 1 on violation) and the unmatched-alias list
.venv/Scripts/python -m it_job_radar.pipeline quality
# redacted Parquet dataset the analytics layer and the site query
.venv/Scripts/python -m it_job_radar.pipeline export
# render docs/index.html from that dataset — CI fails if the committed page differs
.venv/Scripts/python -m it_job_radar.pipeline site
# manifest vs the parquet beside it — the one drift the page diff cannot see
.venv/Scripts/python -m it_job_radar.pipeline verify
```

Editing `tech_aliases.yaml` or `role_families.yaml` repairs data already stored: both are
re-derived on every `observe`, from the offer's title and from the technology name the
offer used. Run `observe` after an edit rather than waiting for the next `collect`.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes_tool` or `query_graph_tool` instead of Grep
- **Understanding impact**: `get_impact_radius_tool` instead of manually tracing imports
- **Code review**: `detect_changes_tool` + `get_review_context_tool` instead of reading entire files
- **Finding relationships**: `query_graph_tool` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview_tool` + `list_communities_tool`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes_tool` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context_tool` | Need source snippets for review — token-efficient |
| `get_impact_radius_tool` | Understanding blast radius of a change |
| `get_affected_flows_tool` | Finding which execution paths are impacted |
| `query_graph_tool` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes_tool` | Finding functions/classes by name or keyword |
| `get_architecture_overview_tool` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. No hooks installed — run `code-review-graph update` after code changes.
2. Use `detect_changes_tool` for code review.
3. Use `get_affected_flows_tool` to understand impact.
4. Use `query_graph_tool` pattern="tests_for" to check coverage.
