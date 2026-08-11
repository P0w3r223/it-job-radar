"""Tests for the SQLite persistence layer (temp database)."""

from it_job_radar import db


def _offer(offer_id):
    return {
        "offer_id": offer_id, "title": "Backend", "company": "ACME", "offer_url": "u",
        "locations": [{"city": "Wrocław", "region": "dolnośląskie"}],
        "seniority": ["mid"], "work_modes": ["remote"],
        "technologies": {"expected": ["python"], "optional": ["docker"]},
        "salaries": [{
            "contract_type": "B2B", "kind": "b2b", "currency": "PLN",
            "salary_from": 100, "salary_to": 150, "time_unit": "godzinowo",
            "monthly_from": 16000, "monthly_to": 24000,
        }],
    }


def test_write_and_read_offers(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    assert db.write_offers(conn, [_offer("a1")], "2026-07-17") == 1

    offers = db.read_table(conn, "offers")
    assert len(offers) == 1
    assert offers.loc[0, "company"] == "ACME"
    assert set(db.read_table(conn, "offer_technologies")["technology"]) == {"python", "docker"}
    assert db.read_table(conn, "offer_salaries").loc[0, "kind"] == "b2b"
    conn.close()


def test_rewrite_offer_replaces_children(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [_offer("a1")], "2026-07-17")
    updated = _offer("a1")
    updated["technologies"] = {"expected": ["java"], "optional": []}
    db.write_offers(conn, [updated], "2026-07-18")

    tech = db.read_table(conn, "offer_technologies")
    assert set(tech["technology"]) == {"java"}  # old rows replaced, not appended
    assert len(db.read_table(conn, "offers")) == 1  # upsert, no duplicate
    conn.close()


def test_snapshot_stat_roundtrip(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    snapshot_id = db.start_snapshot(conn, "collect", "2026-07-17", "2026-07-17T10:00:00")
    db.write_snapshot_stat(conn, snapshot_id, "2026-07-17", "offer_count", 12)

    stats = db.read_table(conn, "snapshot_stats")
    assert stats.loc[0, "metric"] == "offer_count"
    assert stats.loc[0, "value"] == 12
    assert stats.loc[0, "snapshot_id"] == snapshot_id
    conn.close()


def test_two_runs_on_one_day_keep_separate_metrics(tmp_path):
    """A snapshot is a run, not a date — the second run must not overwrite the first."""
    conn = db.connect(tmp_path / "t.db")
    first = db.start_snapshot(conn, "collect", "2026-07-17", "2026-07-17T10:00:00")
    second = db.start_snapshot(conn, "collect", "2026-07-17", "2026-07-17T18:00:00")
    db.write_snapshot_stat(conn, first, "2026-07-17", "offer_count", 250)
    db.write_snapshot_stat(conn, second, "2026-07-17", "offer_count", 314)

    stats = db.read_table(conn, "snapshot_stats").sort_values("value")
    assert list(stats["value"]) == [250.0, 314.0]
    conn.close()
