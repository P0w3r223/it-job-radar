"""Tests for the analytical layer: named queries, parity with the old path, statistics.

The parity tests are the load-bearing ones. While both paths exist, the DuckDB engine
reading the exported Parquet must agree with `analyze.py` reading SQLite — that is what
proves the export is faithful *and* that moving the analysis to the browser does not
quietly change the numbers.
"""

import numpy as np
import pandas as pd
import pytest

from it_job_radar import analyze, config, db, export
from it_job_radar.analytics import engine, stats


def _offer(offer_id, seniority, technologies, monthly=None, work_mode="remote", family="backend"):
    salaries = []
    if monthly is not None:
        salaries = [{
            "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": monthly,
            "salary_to": monthly + 2000, "time_unit": "monthly", "monthly_from": monthly,
            "monthly_to": monthly + 2000,
        }]
    return {
        "offer_id": offer_id, "title": f"Engineer {offer_id}", "company": "ACME",
        "offer_url": f"https://x/{offer_id}", "role_family": family,
        "locations": [{"city": config.FOCUS_CITY, "region": "dolnośląskie"}],
        "seniority": [seniority], "work_modes": [work_mode],
        "technologies": {"expected": technologies, "optional": ["git"]},
        "salaries": salaries,
    }


@pytest.fixture
def dataset(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    offers = [
        _offer("a1", "senior", ["python", "sql"], 20000),
        _offer("a2", "senior", ["python"], 22000),
        _offer("a3", "mid", ["python", "java"], 14000),
        _offer("a4", "junior", ["sql"], None, work_mode="hybrid", family="support"),
    ]
    db.write_offers(conn, offers, "2026-08-11")
    out = tmp_path / "dataset"
    export.write_dataset(conn, out)
    connection = engine.connect(out)
    yield conn, connection
    connection.close()
    conn.close()


# --- Query catalogue ---------------------------------------------------------


def test_every_query_runs_against_the_dataset(dataset):
    """A query that no longer parses is a broken published metric."""
    _, connection = dataset
    for name in engine.available():
        engine.run(name, connection=connection)


def test_unknown_query_is_an_error_not_an_empty_result():
    with pytest.raises(engine.UnknownQuery):
        engine.query_text("does_not_exist")


def test_unknown_parameter_is_rejected(dataset):
    _, connection = dataset
    with pytest.raises(TypeError, match="nonsense"):
        engine.run("top_technologies", connection=connection, nonsense=1)


def test_query_text_is_verbatim_including_comments():
    """The site shows this text to the reader, so it must not be assembled or stripped."""
    sql = engine.query_text("top_technologies")
    assert sql.startswith("-- Most in-demand technologies.")
    assert "COUNT(DISTINCT t.offer_id)" in sql


# --- Parity with the pre-existing SQLite path --------------------------------


def test_top_technologies_matches_the_sqlite_path(dataset):
    conn, connection = dataset
    expected = analyze.top_technologies(conn, limit=10).sort_values("technology")
    actual = engine.run("top_technologies", connection=connection, limit=10).sort_values("technology")

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False
    )


def test_top_technologies_per_seniority_matches(dataset):
    conn, connection = dataset
    expected = analyze.top_technologies(conn, seniority="senior", limit=10).sort_values("technology")
    actual = engine.run(
        "top_technologies", connection=connection, seniority="senior", limit=10
    ).sort_values("technology")

    assert list(actual["technology"]) == list(expected["technology"])
    assert list(actual["offers"]) == list(expected["offers"])


def test_work_mode_distribution_matches(dataset):
    conn, connection = dataset
    expected = analyze.work_mode_distribution(conn).sort_values("work_mode")
    actual = engine.run("work_mode_distribution", connection=connection).sort_values("work_mode")

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False
    )


def test_salary_medians_match_the_sqlite_path(dataset):
    conn, connection = dataset
    expected = analyze.salary_by_seniority(conn).set_index("seniority")
    rows = engine.run("salary_rows", connection=connection)
    actual = stats.summarise_medians(rows, "seniority").set_index("seniority")

    for level in expected.index:
        assert actual.loc[level, "n"] == expected.loc[level, "offers"]
        assert actual.loc[level, "median_monthly_from"] == expected.loc[level, "median_from"]
        assert actual.loc[level, "median_monthly_to"] == expected.loc[level, "median_to"]


# --- Role filtering ----------------------------------------------------------


def test_role_filter_separates_support_from_engineering(dataset):
    """The distinction behind the site's headline finding."""
    _, connection = dataset
    split = engine.run("role_family_distribution", connection=connection, seniority="junior")
    assert dict(zip(split["role_family"], split["offers"])) == {"support": 1}


# --- Statistics --------------------------------------------------------------


def test_median_ci_brackets_a_known_median():
    values = np.concatenate([np.full(200, 10.0), np.full(200, 20.0)])
    low, high = stats.median_ci(values, resamples=500)
    assert low <= 15.0 <= high


def test_median_ci_of_empty_input_is_not_a_crash():
    low, high = stats.median_ci(pd.Series([], dtype=float))
    assert np.isnan(low) and np.isnan(high)


def test_median_ci_is_reproducible_by_default():
    values = np.arange(50, dtype=float)
    assert stats.median_ci(values) == stats.median_ci(values)


def test_thin_strata_are_flagged_but_kept(dataset):
    _, connection = dataset
    rows = engine.run("salary_rows", connection=connection)
    summary = stats.summarise_medians(rows, "seniority", min_n=2).set_index("seniority")

    assert summary.loc["senior", "n"] == 2 and not summary.loc["senior", "suppressed"]
    assert summary.loc["mid", "n"] == 1 and summary.loc["mid", "suppressed"]
    assert "mid" in summary.index  # flagged for the presentation layer, not dropped here


def test_summarise_medians_of_nothing_keeps_its_shape():
    empty = pd.DataFrame(columns=["seniority", "monthly_from", "monthly_to"])
    summary = stats.summarise_medians(empty, "seniority")
    assert {"n", "suppressed", "median_monthly_from"} <= set(summary.columns)
    assert summary.empty


def test_seniority_ordering_follows_the_configured_ladder():
    frame = pd.DataFrame({"seniority": ["senior", "junior", "mid", "unheard-of"]})
    assert list(stats.order_by_seniority(frame)["seniority"]) == [
        "junior", "mid", "senior", "unheard-of"
    ]
