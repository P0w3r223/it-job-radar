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
    db.write_snapshot_stat(conn, "2026-07-17", "offer_count", 12)
    stats = db.read_table(conn, "snapshot_stats")
    assert stats.loc[0, "metric"] == "offer_count"
    assert stats.loc[0, "value"] == 12
    conn.close()
