"""SQLite persistence for normalized job offers.

Normalized (multi-table) schema so aggregating SQL is clean:
- ``offers`` — one row per offer (id, title, company, url, collection date);
- ``offer_technologies`` / ``offer_seniority`` / ``offer_work_modes`` /
  ``offer_locations`` — one row per value (offers are many-to-many with these);
- ``offer_salaries`` — one row per contract (with B2B/employment ``kind``);
- ``snapshot_stats`` — dated aggregate metrics, so daily runs build trends without
  duplicating every offer.

Re-writing an offer replaces its child rows, so re-running the collector is idempotent.
Queries are parameterized; timestamps/dates are ISO text.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from it_job_radar import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    offer_id TEXT PRIMARY KEY, title TEXT, company TEXT, offer_url TEXT, collected_date TEXT
);
CREATE TABLE IF NOT EXISTS offer_seniority (offer_id TEXT, seniority TEXT);
CREATE TABLE IF NOT EXISTS offer_work_modes (offer_id TEXT, work_mode TEXT);
CREATE TABLE IF NOT EXISTS offer_locations (offer_id TEXT, city TEXT, region TEXT);
CREATE TABLE IF NOT EXISTS offer_technologies (offer_id TEXT, technology TEXT, required INTEGER);
CREATE TABLE IF NOT EXISTS offer_salaries (
    offer_id TEXT, contract_type TEXT, kind TEXT, currency TEXT,
    salary_from REAL, salary_to REAL, time_unit TEXT, monthly_from REAL, monthly_to REAL
);
CREATE TABLE IF NOT EXISTS snapshot_stats (
    date TEXT, metric TEXT, value REAL, PRIMARY KEY (date, metric)
);
"""

_CHILD_TABLES = (
    "offer_seniority", "offer_work_modes", "offer_locations",
    "offer_technologies", "offer_salaries",
)


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Open a connection, creating the directory and schema if needed."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _replace_children(conn: sqlite3.Connection, offer: dict) -> None:
    oid = offer["offer_id"]
    for table in _CHILD_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE offer_id = ?", (oid,))

    conn.executemany(
        "INSERT INTO offer_seniority (offer_id, seniority) VALUES (?, ?)",
        [(oid, s) for s in offer.get("seniority", [])],
    )
    conn.executemany(
        "INSERT INTO offer_work_modes (offer_id, work_mode) VALUES (?, ?)",
        [(oid, m) for m in offer.get("work_modes", [])],
    )
    conn.executemany(
        "INSERT INTO offer_locations (offer_id, city, region) VALUES (?, ?, ?)",
        [(oid, c, None) for c in offer.get("cities", [])],
    )
    tech = offer.get("technologies", {})
    tech_rows = [(oid, t, 1) for t in tech.get("expected", [])] + \
                [(oid, t, 0) for t in tech.get("optional", [])]
    conn.executemany(
        "INSERT INTO offer_technologies (offer_id, technology, required) VALUES (?, ?, ?)",
        tech_rows,
    )
    conn.executemany(
        "INSERT INTO offer_salaries (offer_id, contract_type, kind, currency, salary_from, "
        "salary_to, time_unit, monthly_from, monthly_to) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (oid, s["contract_type"], s["kind"], s["currency"], s["salary_from"],
             s["salary_to"], s["time_unit"], s["monthly_from"], s["monthly_to"])
            for s in offer.get("salaries", [])
        ],
    )


def write_offers(conn: sqlite3.Connection, offers: list[dict], collected_date: str) -> int:
    """Upsert normalized offers (and replace their child rows). Returns count written."""
    for offer in offers:
        conn.execute(
            "INSERT OR REPLACE INTO offers (offer_id, title, company, offer_url, collected_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (offer["offer_id"], offer.get("title"), offer.get("company"),
             offer.get("offer_url"), collected_date),
        )
        _replace_children(conn, offer)
    conn.commit()
    return len(offers)


def write_snapshot_stat(conn: sqlite3.Connection, date: str, metric: str, value: float) -> None:
    """Upsert a dated aggregate metric (for trends)."""
    conn.execute(
        "INSERT OR REPLACE INTO snapshot_stats (date, metric, value) VALUES (?, ?, ?)",
        (date, metric, float(value)),
    )
    conn.commit()


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    """Read a whole table into a DataFrame (for analysis)."""
    return pd.read_sql_query(f"SELECT * FROM {table}", conn)
