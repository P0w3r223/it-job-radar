"""Analytical layer: named SQL over the exported dataset, plus the statistics on top.

Every published metric is defined once, as a file in ``queries/``. The same text is run by
the pipeline, asserted by the tests, and shown to the reader next to the chart it produced
(ADR 0001) — so the notebook, the report and the site cannot slowly disagree about what
"median salary" means.

DuckDB is the analytical engine over the exported Parquet and SQLite remains the system of
record for the write path. Both run here, at build time: ADR 0001's browser-side half was
dropped once its bundle measured 21-37 MB, so every figure the page shows was computed
before the page was published.
"""
