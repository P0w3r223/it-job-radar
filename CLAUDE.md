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
