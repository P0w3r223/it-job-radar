"""SQLite persistence for the collected market data — the system of record.

Two things live here, and they answer different questions (ADR 0003):

- **The population frame** (``sitemap_offers``) — one row per offer id ever listed in the
  sitemap, with ``first_seen`` / ``last_seen``. It is complete: one sitemap request
  observes every live offer, so presence never has to be sampled. Disappearance is
  implicit — ``last_seen`` simply stops advancing.
- **Offer attributes** (``offers`` and its child tables) — fetched at most once per offer,
  because a posting's attributes do not change while it is open. Normalized across
  several tables so aggregating SQL stays clean.

``snapshots`` identifies a run (a snapshot is a run, not a date), and ``snapshot_stats``
hangs dated metrics off it.

Re-writing an offer replaces its child rows, so re-running the collector is idempotent.
Queries are parameterized; timestamps/dates are ISO text. Schema changes go through
``migrations.py``, never through edits here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from it_job_radar import config, migrations

_CHILD_TABLES = (
    "offer_seniority", "offer_work_modes", "offer_locations",
    "offer_technologies", "offer_salaries",
)


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    """Open a connection, creating the directory and applying pending migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    migrations.apply(conn)
    return conn


# --- Snapshots ---------------------------------------------------------------


def start_snapshot(
    conn: sqlite3.Connection,
    kind: str,
    observed_date: str,
    started_at: str,
    seed: int | None = None,
    budget: int | None = None,
    git_sha: str | None = None,
) -> int:
    """Open a run and return its id. Every metric written later hangs off this row."""
    cursor = conn.execute(
        "INSERT INTO snapshots (kind, observed_date, started_at, seed, budget, git_sha) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (kind, observed_date, started_at, seed, budget, git_sha),
    )
    conn.commit()
    return int(cursor.lastrowid)


def write_snapshot_stat(
    conn: sqlite3.Connection,
    snapshot_id: int,
    date: str,
    metric: str,
    value: float,
    detail: str | None = None,
) -> None:
    """Upsert one metric for one run. ``detail`` carries context (e.g. unmatched names)."""
    conn.execute(
        "INSERT OR REPLACE INTO snapshot_stats (snapshot_id, date, metric, value, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (snapshot_id, date, metric, float(value), detail),
    )
    conn.commit()


# --- Population frame --------------------------------------------------------


@dataclass(frozen=True)
class FrameDelta:
    """What one sitemap observation changed."""

    live: int  # offers listed in this observation
    new: int  # ids never seen before
    disappeared: int  # listed in the previous observation, absent now
    returned: int  # listed again after being absent for at least one observation


@dataclass(frozen=True)
class FrameState:
    """The frame split into the pools the fetch queue draws from, as ``(id, url)``."""

    new_today: list[tuple[str, str]]
    backlog: list[tuple[str, str]]
    fetched_live: list[tuple[str, str]]


def last_frame_date(conn: sqlite3.Connection) -> str | None:
    """Date of the most recent sitemap observation, or None if the frame is empty.

    Derived from the frame itself rather than tracked separately — the newest
    ``last_seen`` *is* the previous observation.
    """
    row = conn.execute("SELECT MAX(last_seen) FROM sitemap_offers").fetchone()
    return row[0] if row and row[0] else None


def record_frame(
    conn: sqlite3.Connection, entries: list[tuple[str, str]], observed_date: str
) -> FrameDelta:
    """Record one full sitemap observation and report what changed.

    ``entries`` is every ``(offer_id, offer_url)`` currently listed. Ids already known
    advance ``last_seen``; unknown ids are inserted. The first observation ever recorded
    is the *stock* cohort — those offers were already open when we started watching, so
    their entry date is unknown (left truncation) and they can never support lifetime
    estimation. Everything appearing later is the *flow* cohort.
    """
    previous_date = last_frame_date(conn)
    is_first_observation = previous_date is None
    cohort = config.COHORT_STOCK if is_first_observation else config.COHORT_FLOW

    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS frame_batch (offer_id TEXT PRIMARY KEY, offer_url TEXT)"
    )
    conn.execute("DELETE FROM frame_batch")
    conn.executemany("INSERT OR REPLACE INTO frame_batch VALUES (?, ?)", entries)

    live = conn.execute("SELECT COUNT(*) FROM frame_batch").fetchone()[0]
    new = conn.execute(
        "SELECT COUNT(*) FROM frame_batch b "
        "LEFT JOIN sitemap_offers s ON s.offer_id = b.offer_id WHERE s.offer_id IS NULL"
    ).fetchone()[0]
    disappeared = returned = 0
    if not is_first_observation:
        disappeared = conn.execute(
            "SELECT COUNT(*) FROM sitemap_offers WHERE last_seen = ? "
            "AND offer_id NOT IN (SELECT offer_id FROM frame_batch)",
            (previous_date,),
        ).fetchone()[0]
        returned = conn.execute(
            "SELECT COUNT(*) FROM sitemap_offers WHERE last_seen < ? "
            "AND offer_id IN (SELECT offer_id FROM frame_batch)",
            (previous_date,),
        ).fetchone()[0]

    conn.execute(
        "UPDATE sitemap_offers SET "
        "  last_seen = :today, "
        "  offer_url = (SELECT b.offer_url FROM frame_batch b WHERE b.offer_id = sitemap_offers.offer_id), "
        "  gaps = gaps + (CASE WHEN last_seen < :previous THEN 1 ELSE 0 END) "
        "WHERE offer_id IN (SELECT offer_id FROM frame_batch)",
        {"today": observed_date, "previous": previous_date or observed_date},
    )
    conn.execute(
        "INSERT INTO sitemap_offers "
        "  (offer_id, offer_url, first_seen, last_seen, cohort, fetch_state) "
        "SELECT b.offer_id, b.offer_url, ?, ?, ?, ? FROM frame_batch b "
        "LEFT JOIN sitemap_offers s ON s.offer_id = b.offer_id WHERE s.offer_id IS NULL",
        (observed_date, observed_date, cohort, config.FETCH_PENDING),
    )
    conn.commit()
    return FrameDelta(live=live, new=new, disappeared=disappeared, returned=returned)


def frame_state(conn: sqlite3.Connection, observed_date: str) -> FrameState:
    """Split the currently-live frame into the pools the fetch queue draws from.

    ``new_today`` is *inflow*: offers that appeared while we were watching. It is keyed on
    the cohort, not on ``first_seen`` — on the very first observation every offer is "seen
    for the first time" while none of them are new arrivals, and treating the whole
    day-zero stock as inflow would make the capture-rate metric meaningless.

    A failed fetch stays eligible — it returns to the backlog rather than being written off
    after one bad response.
    """

    def rows(where: str, params: tuple) -> list[tuple[str, str]]:
        return [
            (r[0], r[1])
            for r in conn.execute(
                f"SELECT offer_id, offer_url FROM sitemap_offers WHERE {where}", params
            )
        ]

    live_and_unfetched = "last_seen = ? AND fetch_state != ?"
    is_inflow = "cohort = ? AND first_seen = ?"
    return FrameState(
        new_today=rows(
            f"{live_and_unfetched} AND {is_inflow}",
            (observed_date, config.FETCH_DONE, config.COHORT_FLOW, observed_date),
        ),
        backlog=rows(
            f"{live_and_unfetched} AND NOT ({is_inflow})",
            (observed_date, config.FETCH_DONE, config.COHORT_FLOW, observed_date),
        ),
        fetched_live=rows(
            "last_seen = ? AND fetch_state = ?", (observed_date, config.FETCH_DONE)
        ),
    )


def reconcile_fetch_state(conn: sqlite3.Connection) -> int:
    """Mark frame rows as fetched wherever we already hold the offer's attributes.

    Attributes can pre-date the frame — the first 314 offers were collected before the
    frame existed — and a frame that does not know this would queue them for a pointless
    re-fetch. Idempotent, so it is safe to run on every observation.
    """
    cursor = conn.execute(
        "UPDATE sitemap_offers SET "
        "  fetch_state = ?, "
        "  fetch_date = COALESCE(fetch_date, ("
        "    SELECT o.collected_date FROM offers o WHERE o.offer_id = sitemap_offers.offer_id)) "
        "WHERE fetch_state != ? AND offer_id IN (SELECT offer_id FROM offers)",
        (config.FETCH_DONE, config.FETCH_DONE),
    )
    conn.commit()
    return cursor.rowcount


def coverage(conn: sqlite3.Connection, observed_date: str) -> tuple[int, int]:
    """``(offers whose attributes we hold, offers currently listed)`` — coverage of the base."""
    fetched = conn.execute(
        "SELECT COUNT(*) FROM sitemap_offers WHERE fetch_state = ?", (config.FETCH_DONE,)
    ).fetchone()[0]
    live = conn.execute(
        "SELECT COUNT(*) FROM sitemap_offers WHERE last_seen = ?", (observed_date,)
    ).fetchone()[0]
    return int(fetched), int(live)


def mark_fetched(
    conn: sqlite3.Connection, results: list[tuple[str, str]], fetch_date: str
) -> None:
    """Record the outcome of fetch attempts as ``(offer_id, fetch_state)`` pairs."""
    conn.executemany(
        "UPDATE sitemap_offers SET fetch_state = ?, fetch_date = ? WHERE offer_id = ?",
        [(state, fetch_date, offer_id) for offer_id, state in results],
    )
    conn.commit()


def backfill_offer_urls(conn: sqlite3.Connection) -> tuple[int, int]:
    """Repair offer URLs lost before the ``normalize_offer`` fix, from the frame.

    Returns ``(repaired, still_missing)``. An offer that has since been delisted cannot be
    repaired — its URL is not recoverable, and a null is more honest than a guess.
    """
    cursor = conn.execute(
        "UPDATE offers SET offer_url = ("
        "  SELECT s.offer_url FROM sitemap_offers s WHERE s.offer_id = offers.offer_id"
        ") WHERE offer_url IS NULL "
        "AND offer_id IN (SELECT offer_id FROM sitemap_offers)"
    )
    repaired = cursor.rowcount
    missing = conn.execute("SELECT COUNT(*) FROM offers WHERE offer_url IS NULL").fetchone()[0]
    conn.commit()
    return int(repaired), int(missing)


# --- Offer attributes --------------------------------------------------------


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
        [(oid, loc.get("city"), loc.get("region")) for loc in offer.get("locations", [])],
    )
    tech = offer.get("technologies", {})
    tech_rows = [(oid, t.name, 1, t.raw) for t in tech.get("expected", [])] + \
                [(oid, t.name, 0, t.raw) for t in tech.get("optional", [])]
    conn.executemany(
        "INSERT INTO offer_technologies (offer_id, technology, required, raw_name) "
        "VALUES (?, ?, ?, ?)",
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
            "INSERT OR REPLACE INTO offers "
            "  (offer_id, title, company, offer_url, collected_date, role_family) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (offer["offer_id"], offer.get("title"), offer.get("company"),
             offer.get("offer_url"), collected_date, offer.get("role_family")),
        )
        _replace_children(conn, offer)
    conn.commit()
    return len(offers)


def latest_metric(conn: sqlite3.Connection, metric: str) -> tuple[float, str | None] | None:
    """Most recently recorded ``(value, detail)`` for a metric, or None if never written."""
    row = conn.execute(
        "SELECT value, detail FROM snapshot_stats WHERE metric = ? "
        "ORDER BY snapshot_id DESC LIMIT 1",
        (metric,),
    ).fetchone()
    return (float(row[0]), row[1]) if row else None


def offer_titles(conn: sqlite3.Connection) -> list[tuple[str, str | None, str | None]]:
    """``(offer_id, title, current role_family)`` for every stored offer.

    Everything is returned, not just the unclassified: the rule table is edited over time,
    and a classification that only ever ran once would freeze old mistakes in place.
    """
    return [
        (row[0], row[1], row[2])
        for row in conn.execute("SELECT offer_id, title, role_family FROM offers")
    ]


def set_role_families(conn: sqlite3.Connection, rows: list[tuple[str, str]]) -> int:
    """Apply ``(offer_id, role_family)`` classifications. Returns the count updated."""
    conn.executemany(
        "UPDATE offers SET role_family = ? WHERE offer_id = ?",
        [(family, offer_id) for offer_id, family in rows],
    )
    conn.commit()
    return len(rows)


def technology_names(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """``(rowid, raw_name, current technology)`` for every stored technology row.

    The raw name is what the offer wrote; re-resolving it through the current dictionary is
    what lets an alias added today repair an offer collected months ago.
    """
    return [
        (int(row[0]), row[1], row[2])
        for row in conn.execute(
            "SELECT rowid, raw_name, technology FROM offer_technologies WHERE raw_name IS NOT NULL"
        )
    ]


def set_technologies(conn: sqlite3.Connection, rows: list[tuple[int, str]]) -> tuple[int, int]:
    """Apply ``(rowid, technology)`` re-resolutions. Returns ``(updated, merged)``.

    Merging two spellings into one canonical name can leave an offer holding the same
    technology twice, which the unique index from migration v6 forbids. ``UPDATE OR
    REPLACE`` resolves that by dropping the row the merge made redundant — the index scopes
    the removal to the collision itself, so the repair cannot reach a row no dictionary edit
    touched.

    A merge is one-way: the losing spelling's provenance goes with its row, so the count is
    returned rather than left silent.
    """
    before = _technology_rows(conn)
    with conn:
        conn.executemany(
            "UPDATE OR REPLACE offer_technologies SET technology = ? WHERE rowid = ?",
            [(technology, rowid) for rowid, technology in rows],
        )
    return len(rows), before - _technology_rows(conn)


def _technology_rows(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM offer_technologies").fetchone()[0])


_READABLE_TABLES = frozenset({
    "offers", "offer_seniority", "offer_work_modes", "offer_locations",
    "offer_technologies", "offer_salaries", "snapshot_stats", "snapshots",
    "sitemap_offers",
})


def read_table(conn: sqlite3.Connection, table: str) -> pd.DataFrame:
    """Read a whole table into a DataFrame. The table name is whitelisted (not user input,
    but this keeps the one f-string query in the module provably injection-safe)."""
    if table not in _READABLE_TABLES:
        raise ValueError(f"unknown table: {table!r}")
    return pd.read_sql_query(f"SELECT * FROM {table}", conn)
