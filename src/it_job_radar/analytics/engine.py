"""Run the named queries against the exported dataset with DuckDB.

The queries live in ``queries/*.sql`` and are read verbatim — never assembled from
fragments — because the same text is what the site shows the reader under "Show SQL".
A query the reader cannot see is a query nobody can check.

The dataset is a directory of Parquet files registered as views under their table names,
so the SQL reads like ordinary table SQL and stays portable between this engine and
DuckDB-WASM in the browser.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd

from it_job_radar import config

QUERY_DIR = Path(__file__).parent / "queries"
_PARAM_RE = re.compile(r"\$([a-z_]+)")

# Defaults per parameter name. Names mean the same thing in every query, so one table is
# clearer than repeating defaults per file — and it keeps them out of the SQL, which has to
# stay readable to someone inspecting it in the browser.
_PARAM_DEFAULTS = {
    "seniority": None,
    "role_family": None,
    "required_only": True,
    "limit": 15,
    "kind": config.CONTRACT_B2B,
    "currency": "PLN",
    "city": config.FOCUS_CITY,
    "work_mode": config.WORK_MODE_REMOTE,
    "series": config.TECHNOLOGY_SERIES,
    "min_coverage": config.MIN_COMPARABLE_COVERAGE,
}


class UnknownQuery(KeyError):
    """Raised when a query name has no matching .sql file."""


def available() -> tuple[str, ...]:
    """Names of every defined query, which is also the catalogue the site publishes."""
    return tuple(sorted(path.stem for path in QUERY_DIR.glob("*.sql")))


@lru_cache(maxsize=None)
def query_text(name: str) -> str:
    """The verbatim SQL for a named query — comments included, since they are the docs."""
    path = QUERY_DIR / f"{name}.sql"
    if not path.is_file():
        raise UnknownQuery(f"no query named {name!r}; available: {', '.join(available())}")
    return path.read_text(encoding="utf-8")


def _parameters(sql: str, overrides: dict) -> dict:
    """Resolve the placeholders a query actually uses, defaults filled in."""
    names = set(_PARAM_RE.findall(sql))
    unknown = set(overrides) - names
    if unknown:
        raise TypeError(f"query does not take {', '.join(sorted(unknown))}")
    missing = names - set(_PARAM_DEFAULTS)
    if missing:
        raise UnknownQuery(f"no default declared for {', '.join(sorted(missing))}")
    return {name: overrides.get(name, _PARAM_DEFAULTS[name]) for name in names}


def connect(dataset_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open an in-memory DuckDB with the dataset's Parquet files registered as views."""
    dataset_dir = Path(dataset_dir or config.DATASET_DIR)
    connection = duckdb.connect()
    for table in config.DATASET_TABLES:
        parquet = dataset_dir / f"{table}.parquet"
        if parquet.is_file():
            # DDL cannot take a prepared parameter, so the path is inlined. It comes from
            # our own filesystem, never from input; quotes are escaped regardless.
            literal = str(parquet).replace("'", "''")
            connection.execute(
                f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{literal}')"
            )
    return connection


def run(
    name: str,
    dataset_dir: Path | None = None,
    connection: duckdb.DuckDBPyConnection | None = None,
    **overrides,
) -> pd.DataFrame:
    """Execute a named query and return its result.

    Pass ``connection`` to run several queries against one open dataset; otherwise a
    connection is opened and closed here.
    """
    sql = query_text(name)
    params = _parameters(sql, overrides)
    own_connection = connection is None
    connection = connection or connect(dataset_dir)
    try:
        return connection.execute(sql, params).df()
    finally:
        if own_connection:
            connection.close()
