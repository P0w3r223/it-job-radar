"""Tests for the CLI orchestration layer.

Only the parts that carry a promise: the day's page accounting, which is the ethical
guardrail the per-run budget alone could not hold.
"""

import pytest

from it_job_radar import config, db, normalize, pipeline, quality


def test_a_run_cannot_walk_past_the_days_page_limit(tmp_path, monkeypatch):
    """MAX_FETCH_BUDGET bounds an invocation; a ceiling that resets is not a limit.

    Seven runs on 2026-08-13, each inside the per-run ceiling, fetched 6037 pages against a
    6530-offer base — the whole base in a day, which the documentation promises never
    happens. The accounting is therefore per day, read from the runs already recorded.
    """
    conn = db.connect(tmp_path / "t.db")
    snapshot = db.start_snapshot(conn, "collect", "2026-08-13", "2026-08-13T10:00:00")
    db.write_snapshot_stat(conn, snapshot, "2026-08-13", "fetch_attempted", 1800)
    monkeypatch.setattr(config, "MAX_DAILY_FETCH", 2000)

    assert pipeline._budget_left_today(conn, "2026-08-13", 1000) == 200  # trimmed, not refused
    assert pipeline._budget_left_today(conn, "2026-08-12", 1000) == 1000  # another day is clean

    db.write_snapshot_stat(conn, snapshot, "2026-08-13", "fetch_attempted", 2000)
    with pytest.raises(pipeline.DailyBudgetSpent):
        pipeline._budget_left_today(conn, "2026-08-13", 100)
    conn.close()


def _raw_offer(offer_id, title="Cloud Data Engineer", company="Sii"):
    return {
        "offer_id": offer_id, "title": title, "company": company,
        "offer_url": f"https://theprotocol.it/x,oferta,{offer_id}",
        "locations": [{"city": "Wrocław", "region": "dolnośląskie"}],
        "seniority": ["senior"], "work_modes": ["remote"],
        "tech_expected": ["python"], "tech_optional": [], "contracts": [],
    }


def test_offers_stored_before_the_key_existed_are_grouped_on_the_next_frame_run(tmp_path):
    """The repair loop the whole vacancy unit rests on, which nothing exercised.

    Made a no-op, every advert falls back to its own id and every published "vacancy"
    figure silently becomes an advert figure again — the bias the unit exists to remove,
    back without a single red test.
    """
    conn = db.connect(tmp_path / "t.db")
    context = normalize.load_normalization()
    offers = [normalize.normalize_offer(_raw_offer(f"a{i}"), context) for i in range(2)]
    db.write_offers(conn, offers, "2026-08-13")
    conn.execute("UPDATE offers SET vacancy_key = NULL")  # as rows written before v10 look
    conn.commit()

    changed = pipeline._group_vacancies(conn)
    assert changed == 2
    keys = {row[0] for row in conn.execute("SELECT vacancy_key FROM offers")}
    assert keys == {"cloud data engineer|sii"}  # one job, two adverts

    assert pipeline._group_vacancies(conn) == 0  # re-deriving an unchanged rule writes nothing
    conn.close()


def test_nothing_is_published_from_data_that_fails_the_contract(tmp_path):
    """The gate between a bad row and the public page. Removing it left the suite green."""
    conn = db.connect(tmp_path / "t.db")
    context = normalize.load_normalization()
    db.write_offers(conn, [normalize.normalize_offer(_raw_offer("a1"), context)], "2026-08-13")
    db.record_frame(conn, [("a1", "u1")], "2026-08-13")
    db.start_snapshot(conn, "collect", "2026-08-13", "2026-08-13T10:00:00")
    conn.execute(
        "INSERT INTO offer_salaries (offer_id, kind, currency, monthly_from, monthly_to) "
        "VALUES ('a1', 'b2b', 'PLN', 900000, 950000)"  # beyond SALARY_SANITY_MAX
    )
    conn.commit()

    out = tmp_path / "dataset"
    with pytest.raises(quality.ContractError):
        pipeline.export_dataset(out, conn=conn)
    assert not (out / config.MANIFEST_NAME).exists()
    conn.close()
