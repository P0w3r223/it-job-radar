"""Ordered schema migrations for the SQLite system of record.

``CREATE TABLE IF NOT EXISTS`` can create a schema but cannot evolve one: against a
database that already has the table, it silently does nothing and the new column never
appears. Every schema change therefore lands here as a numbered step, applied in order
inside its own transaction, with ``PRAGMA user_version`` recording how far a database has
come.

Steps are callables rather than plain SQL because migrating data (not just structure)
sometimes needs logic — see ``_v3_snapshot_identity``, which invents a snapshot row for
each pre-migration date so old metrics keep a valid parent.

Note on transactions: ``executescript`` issues an implicit COMMIT before running, which
would break the per-step transaction, so statements are executed one at a time.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

Step = Callable[[sqlite3.Connection], None]

# --- v1: the schema as it existed before migrations were introduced ----------
_BASELINE = (
    """CREATE TABLE IF NOT EXISTS offers (
        offer_id TEXT PRIMARY KEY, title TEXT, company TEXT, offer_url TEXT,
        collected_date TEXT
    )""",
    "CREATE TABLE IF NOT EXISTS offer_seniority (offer_id TEXT, seniority TEXT)",
    "CREATE TABLE IF NOT EXISTS offer_work_modes (offer_id TEXT, work_mode TEXT)",
    "CREATE TABLE IF NOT EXISTS offer_locations (offer_id TEXT, city TEXT, region TEXT)",
    """CREATE TABLE IF NOT EXISTS offer_technologies (
        offer_id TEXT, technology TEXT, required INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS offer_salaries (
        offer_id TEXT, contract_type TEXT, kind TEXT, currency TEXT,
        salary_from REAL, salary_to REAL, time_unit TEXT, monthly_from REAL, monthly_to REAL
    )""",
    """CREATE TABLE IF NOT EXISTS snapshot_stats (
        date TEXT, metric TEXT, value REAL, PRIMARY KEY (date, metric)
    )""",
)

# --- v2: the population frame (ADR 0003) -------------------------------------
# One row per offer id ever listed in the sitemap. Presence is complete and free: an
# offer's disappearance is recorded implicitly, by `last_seen` no longer advancing.
_POPULATION_FRAME = (
    """CREATE TABLE IF NOT EXISTS sitemap_offers (
        offer_id TEXT PRIMARY KEY,
        offer_url TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        cohort TEXT NOT NULL,
        fetch_state TEXT NOT NULL,
        fetch_date TEXT,
        gaps INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_frame_pending ON sitemap_offers(fetch_state, last_seen)",
    "CREATE INDEX IF NOT EXISTS ix_frame_first_seen ON sitemap_offers(first_seen)",
)

# --- v3: snapshot identity ---------------------------------------------------
_SNAPSHOTS = """CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    observed_date TEXT NOT NULL,
    started_at TEXT NOT NULL,
    seed INTEGER,
    budget INTEGER,
    git_sha TEXT,
    note TEXT
)"""

_STATS_WITH_SNAPSHOT = """CREATE TABLE snapshot_stats_v3 (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(snapshot_id),
    date TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL,
    detail TEXT,
    PRIMARY KEY (snapshot_id, metric)
)"""


def _run(conn: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    for statement in statements:
        conn.execute(statement)


def _v1_baseline(conn: sqlite3.Connection) -> None:
    _run(conn, _BASELINE)


def _v2_population_frame(conn: sqlite3.Connection) -> None:
    _run(conn, _POPULATION_FRAME)


def _v3_snapshot_identity(conn: sqlite3.Connection) -> None:
    """Make a snapshot a run rather than a date.

    Keyed on ``(date, metric)``, two runs on one day overwrote each other — which is why
    the pre-migration database reported ``offer_count = 250`` while holding 314 offers.
    Existing rows are adopted by a synthetic snapshot per date so nothing is discarded.
    """
    conn.execute(_SNAPSHOTS)
    conn.execute(_STATS_WITH_SNAPSHOT)
    legacy_dates = [row[0] for row in conn.execute("SELECT DISTINCT date FROM snapshot_stats")]
    for date in legacy_dates:
        cursor = conn.execute(
            "INSERT INTO snapshots (kind, observed_date, started_at, note) VALUES (?, ?, ?, ?)",
            ("collect", date, date, "synthesised during migration v3 from snapshot_stats"),
        )
        conn.execute(
            "INSERT INTO snapshot_stats_v3 (snapshot_id, date, metric, value) "
            "SELECT ?, date, metric, value FROM snapshot_stats WHERE date = ?",
            (cursor.lastrowid, date),
        )
    conn.execute("DROP TABLE snapshot_stats")
    conn.execute("ALTER TABLE snapshot_stats_v3 RENAME TO snapshot_stats")


def _v4_role_family(conn: sqlite3.Connection) -> None:
    """Store the role family alongside the offer so aggregating SQL can group by it.

    Left NULL for existing rows; the pipeline classifies them on the next run, which keeps
    the classification rules in Python where they can be tested.
    """
    conn.execute("ALTER TABLE offers ADD COLUMN role_family TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_offers_role_family ON offers(role_family)")


def _v5_technology_provenance(conn: sqlite3.Connection) -> None:
    """Keep the technology name as the offer wrote it, so the dictionary can be re-applied.

    Role families re-derive from the stored title on every run, so improving a rule repairs
    offers classified before the fix. Technologies could not: only the normalized value was
    stored and the raw name was discarded, which left the alias feedback loop unable to
    close — a dictionary entry added today could never help an offer collected yesterday.

    Existing rows are seeded from the normalized value, which makes re-resolution a no-op
    wherever the old answer was already right: an unmatched name was stored as its own
    lowercased form, and a matched one as a canonical the dictionary maps to itself.

    What the seed is *not* is a record of what the offer wrote. A name resolved by the fuzzy
    matcher was stored as the canonical it hit, so for those rows the seed is the
    dictionary's own output — they count as matched by construction and cannot be
    re-litigated, because the string that would need a new alias is gone. Rows written after
    this migration carry the real name; pre-migration rows carry the best reconstruction of
    it, and coverage measured over them is optimistic by that much.
    """
    conn.execute("ALTER TABLE offer_technologies ADD COLUMN raw_name TEXT")
    conn.execute("UPDATE offer_technologies SET raw_name = technology WHERE raw_name IS NULL")


def _v6_one_row_per_technology(conn: sqlite3.Connection) -> None:
    """Move "an offer lists a technology once" from an assumption into the schema.

    Re-resolution can map two spellings onto one canonical name, which would leave an offer
    holding the same technology twice. That was first handled by deduplicating the whole
    table after every repair — a statement with no relationship to the rows being repaired,
    which reached duplicates in offers no dictionary edit had touched, and removed rows the
    data contract exists to report. A table-wide fix belongs in a migration, where it runs
    once and is versioned; a unique index then lets `UPDATE OR REPLACE` resolve exactly the
    collision the merge caused, and nothing else.

    `required` is part of the key on purpose: a technology can be listed as both a must-have
    and a nice-to-have, and those are two different statements about the same offer.
    """
    conn.execute(
        "DELETE FROM offer_technologies WHERE rowid NOT IN ("
        "  SELECT MIN(rowid) FROM offer_technologies"
        "  GROUP BY offer_id, technology, required)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_offer_technology "
        "ON offer_technologies(offer_id, technology, required)"
    )


MIGRATIONS: tuple[tuple[int, str, Step], ...] = (
    (1, "baseline schema", _v1_baseline),
    (2, "population frame", _v2_population_frame),
    (3, "snapshot identity", _v3_snapshot_identity),
    (4, "role family", _v4_role_family),
    (5, "technology provenance", _v5_technology_provenance),
    (6, "one row per technology", _v6_one_row_per_technology),
)

SCHEMA_VERSION = MIGRATIONS[-1][0]


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def apply(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration the database has not seen yet. Returns the names applied.

    Each step runs in its own transaction: a failing step leaves the database at the last
    version that fully succeeded, rather than half-migrated.
    """
    version = current_version(conn)
    applied: list[str] = []
    for target, name, step in MIGRATIONS:
        if target <= version:
            continue
        with conn:
            step(conn)
            # PRAGMA does not accept parameters; `target` is our own literal, not input.
            conn.execute(f"PRAGMA user_version = {int(target)}")
        applied.append(name)
    return applied
