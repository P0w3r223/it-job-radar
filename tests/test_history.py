"""Tests for the dated series (phase 7.1).

Three things have to hold or a trend drawn from this table is worse than no trend at all:
every point carries the population it rests on, a point means the same thing as the number
the page prints, and exporting twice does not turn one observation into two.
"""

import pandas as pd
import pytest

from it_job_radar import config, db, export, normalize, quality
from it_job_radar.analytics import engine, history, stats


def _offer(offer_id, seniority="senior", technologies=("java",), salary=None, title="Backend Engineer"):
    return {
        "offer_id": offer_id, "title": title, "company": "ACME",
        "offer_url": f"https://theprotocol.it/x,oferta,{offer_id}",
        "role_family": "software", "locations": [{"city": "Wrocław", "region": "dolnośląskie"}],
        "seniority": [seniority], "work_modes": ["remote"],
        "technologies": {
            "expected": normalize.normalize_technologies(list(technologies), {}),
            "optional": [],
        },
        "salaries": [{
            "contract_type": "B2B", "kind": config.CONTRACT_B2B, "currency": "PLN",
            "salary_from": salary, "salary_to": salary, "time_unit": "monthly",
            "monthly_from": salary, "monthly_to": salary + 2000,
        }] if salary else [],
    }


@pytest.fixture
def published(tmp_path):
    """A database with one recorded run, published to a dataset directory."""
    conn = db.connect(tmp_path / "t.db")
    db.start_snapshot(conn, config.SNAPSHOT_COLLECT, "2026-08-12", "2026-08-12T10:00:00")
    offers = [
        _offer("a1", "senior", ("java", "docker"), salary=20000),
        _offer("a2", "senior", ("java",), salary=24000),
        _offer("a3", config.HEADLINE_SENIORITY, ("java",), salary=8000),
        _offer("a4", config.HEADLINE_SENIORITY, ("python",)),
    ]
    db.write_offers(conn, offers, "2026-08-12")
    db.record_frame(conn, [(o["offer_id"], o["offer_url"]) for o in offers], "2026-08-12")
    db.reconcile_fetch_state(conn)
    out = tmp_path / "dataset"
    export.publish(conn, out, git_sha="abc1234")
    yield conn, out
    conn.close()


def _series(out) -> pd.DataFrame:
    return pd.read_parquet(out / f"{export.SERIES_TABLE}.parquet")


def test_every_point_carries_the_population_it_rests_on(published):
    _, out = published
    series = _series(out)

    assert not series.empty
    assert series["n"].notna().all()
    assert (series["n"] > 0).all()


def test_the_run_appears_in_the_dataset_it_produced(published):
    """The two-phase write exists for this: a series nobody can read is not a series."""
    conn, out = published
    snapshot_id = db.latest_snapshot(conn)[0]
    series = _series(out)

    assert set(series["snapshot_id"]) == {snapshot_id}
    assert set(series["date"]) == {"2026-08-12"}


def test_counts_and_medians_are_both_recorded(published):
    _, out = published
    metrics = set(_series(out)["metric"])

    assert "technology_offers" in metrics
    assert "stratum_offers" in metrics
    assert "work_mode_offers" in metrics
    assert f"{config.HEADLINE_SENIORITY}_role_family_offers" in metrics
    assert f"salary_median_from_{config.CONTRACT_B2B}" in metrics


def test_a_technology_is_a_share_of_the_offers_that_could_have_listed_it(published):
    """Not of the sum over technologies: one offer lists several, so that sum is not a base."""
    _, out = published
    series = _series(out)
    java = series[(series["metric"] == "technology_offers") & (series["dimension"] == "java")]

    assert float(java["value"].iloc[0]) == 3  # a1, a2, a3
    assert int(java["n"].iloc[0]) == 4  # every analysed offer, not 3 + 1 + 1


def test_the_headline_segment_is_a_share_of_itself(published):
    """Role families partition the offers they describe, so the query's own total is right."""
    _, out = published
    series = _series(out)
    metric = f"{config.HEADLINE_SENIORITY}_role_family_offers"
    junior = series[series["metric"] == metric]

    assert int(junior["value"].sum()) == 2  # a3 and a4
    assert set(junior["n"]) == {2}


def test_a_stored_median_is_the_number_the_page_prints(published):
    """One definition per metric: the series and the page must not diverge by method."""
    _, out = published
    connection = engine.connect(out)
    try:
        rows = engine.run("salary_rows", connection=connection, kind=config.CONTRACT_B2B)
    finally:
        connection.close()
    summary = stats.summarise_medians(rows, "seniority")
    expected = summary.loc[summary["seniority"] == "senior", "median_monthly_from"].iloc[0]

    series = _series(out)
    stored = series[
        (series["metric"] == f"salary_median_from_{config.CONTRACT_B2B}")
        & (series["dimension"] == "senior")
    ]
    assert float(stored["value"].iloc[0]) == pytest.approx(float(expected))
    assert int(stored["n"].iloc[0]) == 2


def test_publishing_the_same_run_twice_does_not_double_its_points(published):
    """A rerun replaces a run's points; it never gives one observation two of anything."""
    conn, out = published
    before = _series(out)

    export.publish(conn, out, git_sha="abc1234")
    after = _series(out)

    assert len(after) == len(before)
    assert not after.duplicated(subset=["snapshot_id", "metric", "dimension"]).any()


def test_a_second_run_extends_the_series_rather_than_replacing_it(published, tmp_path):
    conn, out = published
    db.start_snapshot(conn, config.SNAPSHOT_OBSERVE, "2026-08-13", "2026-08-13T10:00:00")
    export.publish(conn, out)

    series = _series(out)
    assert set(series["date"]) == {"2026-08-12", "2026-08-13"}
    assert series["snapshot_id"].nunique() == 2


def test_the_series_reaches_the_manifest_and_the_contract(published):
    conn, out = published
    manifest = export.publish(conn, out)

    assert manifest["rows"][export.SERIES_TABLE] == len(_series(out))
    # nothing recorded here may violate the contract the export gate enforces
    assert quality.validate_contract(conn) == []


def test_measuring_a_dataset_with_no_offers_yields_no_points(tmp_path):
    """An empty denominator is not a zero share — it is a number that cannot be published."""
    conn = db.connect(tmp_path / "empty.db")
    out = tmp_path / "dataset"
    export.write_dataset(conn, out)

    assert history.measure(0, dataset_dir=out) == []
    conn.close()


def test_a_run_with_no_snapshot_records_nothing(tmp_path):
    """Publishing a bare database is legitimate; a point without provenance is not."""
    conn = db.connect(tmp_path / "bare.db")
    db.write_offers(conn, [_offer("a1", salary=20000)], "2026-08-12")
    out = tmp_path / "dataset"

    manifest = export.publish(conn, out)

    assert manifest["rows"][export.SERIES_TABLE] == 0
    assert _series(out).empty
    conn.close()
