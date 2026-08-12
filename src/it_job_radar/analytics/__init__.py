"""Analytical layer: named SQL over the exported dataset, plus the statistics on top.

Every published metric is defined once, as a file in ``queries/``. The same text is run by
the pipeline, asserted by the tests, and shown to the reader next to the chart it produced
(ADR 0001) — so the notebook, the report and the site cannot slowly disagree about what
"median salary" means.

DuckDB is the analytical engine on both sides: here over Parquet on disk, and in the
browser over the same file. SQLite remains the system of record for the write path.
"""
