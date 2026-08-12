"""Tests for the schema migration runner.

The point of these is the *upgrade* path: a database created before migrations existed
must gain the new structure without losing the rows it already had.
"""

import sqlite3

import pytest

from it_job_radar import db, migrations

# The schema exactly as it shipped before migrations were introduced.
_LEGACY_SCHEMA = """
CREATE TABLE offers (
    offer_id TEXT PRIMARY KEY, title TEXT, company TEXT, offer_url TEXT, collected_date TEXT
);
CREATE TABLE offer_seniority (offer_id TEXT, seniority TEXT);
CREATE TABLE offer_work_modes (offer_id TEXT, work_mode TEXT);
CREATE TABLE offer_locations (offer_id TEXT, city TEXT, region TEXT);
CREATE TABLE offer_technologies (offer_id TEXT, technology TEXT, required INTEGER);
CREATE TABLE offer_salaries (
    offer_id TEXT, contract_type TEXT, kind TEXT, currency TEXT,
    salary_from REAL, salary_to REAL, time_unit TEXT, monthly_from REAL, monthly_to REAL
);
CREATE TABLE snapshot_stats (date TEXT, metric TEXT, value REAL, PRIMARY KEY (date, metric));
"""


def _legacy_database(path):
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO offers (offer_id, title, collected_date) VALUES ('a1', 'Backend', '2026-07-17')"
    )
    conn.executemany(
        "INSERT INTO offer_technologies (offer_id, technology, required) VALUES (?, ?, ?)",
        [("a1", "ci / cd", 1), ("a1", "python", 1)],
    )
    conn.executemany(
        "INSERT INTO snapshot_stats (date, metric, value) VALUES (?, ?, ?)",
        [("2026-07-17", "offer_count", 250), ("2026-07-17", "offers_with_salary", 67)],
    )
    conn.commit()
    return conn


def test_fresh_database_is_fully_migrated(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    assert migrations.current_version(conn) == migrations.SCHEMA_VERSION

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"offers", "sitemap_offers", "snapshots", "snapshot_stats"} <= tables
    conn.close()


def test_applying_twice_is_a_noop(tmp_path):
    conn = db.connect(tmp_path / "fresh.db")
    assert migrations.apply(conn) == []  # connect() already ran them
    conn.close()


def test_legacy_database_gains_new_structure(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path).close()

    conn = db.connect(path)
    assert migrations.current_version(conn) == migrations.SCHEMA_VERSION
    columns = {row[1] for row in conn.execute("PRAGMA table_info(sitemap_offers)")}
    assert {"offer_id", "first_seen", "last_seen", "cohort", "fetch_state"} <= columns
    conn.close()


def test_legacy_metrics_are_adopted_not_dropped(tmp_path):
    path = tmp_path / "legacy.db"
    _legacy_database(path).close()

    conn = db.connect(path)
    stats = conn.execute(
        "SELECT snapshot_id, metric, value FROM snapshot_stats ORDER BY metric"
    ).fetchall()
    assert [(row[1], row[2]) for row in stats] == [
        ("offer_count", 250.0),
        ("offers_with_salary", 67.0),
    ]
    # both metrics hang off one synthesised snapshot for that date
    assert len({row[0] for row in stats}) == 1
    snapshot = conn.execute("SELECT kind, observed_date, note FROM snapshots").fetchone()
    assert snapshot[1] == "2026-07-17"
    assert "migration" in snapshot[2]
    # offers survived untouched
    assert conn.execute("SELECT title FROM offers").fetchone()[0] == "Backend"
    conn.close()


def test_duplicate_technology_rows_are_collapsed_once_and_then_forbidden(tmp_path):
    """The table-wide fix belongs here, where it runs once and is versioned.

    It used to run after every repair, which let it reach offers no dictionary edit had
    touched. The unique index makes the guarantee structural instead.
    """
    path = tmp_path / "legacy.db"
    legacy = _legacy_database(path)
    legacy.execute(
        "INSERT INTO offer_technologies (offer_id, technology, required) VALUES ('a1', 'python', 1)"
    )
    legacy.commit()
    legacy.close()

    conn = db.connect(path)
    rows = conn.execute(
        "SELECT technology, COUNT(*) FROM offer_technologies GROUP BY technology ORDER BY technology"
    ).fetchall()
    assert rows == [("ci / cd", 1), ("python", 1)]

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO offer_technologies (offer_id, technology, required) "
            "VALUES ('a1', 'python', 1)"
        )
    conn.close()


def test_stored_technologies_gain_a_provenance_seed(tmp_path):
    """Rows written before provenance existed must still be re-resolvable.

    The seed is the stored normalized value: for an unmatched name that *is* the raw
    string lowercased, so feeding it back through the dictionary is exactly the repair the
    alias feedback loop promises.
    """
    path = tmp_path / "legacy.db"
    _legacy_database(path).close()

    conn = db.connect(path)
    rows = conn.execute(
        "SELECT technology, raw_name FROM offer_technologies ORDER BY technology"
    ).fetchall()
    assert rows == [("ci / cd", "ci / cd"), ("python", "python")]
    conn.close()
