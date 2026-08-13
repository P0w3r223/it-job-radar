"""Tests for the analytical layer: named queries, parity with the old path, statistics.

Every published metric is defined once, as SQL, and executed here exactly as the site
executes it. The parity tests that guarded the migration away from the old SQLite path are
gone with that path; what remains is the check that each query still parses and answers,
because a query that no longer runs is a broken published metric.
"""

import numpy as np
import pandas as pd
import pytest

from it_job_radar import config, db, export, normalize
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
        "technologies": {
            "expected": normalize.normalize_technologies(technologies, {}),
            "optional": normalize.normalize_technologies(["git"], {}),
        },
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
    # The frame is what makes an offer live, and every published query filters on it
    # (ADR 0004). A fixture without one models a state the pipeline never produces and
    # would have every query answer with nothing.
    db.record_frame(conn, [(o["offer_id"], o["offer_url"]) for o in offers], "2026-08-11")
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


def test_query_text_is_the_file_itself():
    """The site shows this text to the reader, so it must not be assembled or stripped.

    Compared against the file rather than against remembered snippets: an assertion on
    comment wording broke when a comment was reworded and passed when a metric changed,
    which is backwards. The counting semantics are pinned behaviourally instead.
    """
    queries = config.PROJECT_ROOT / "src/it_job_radar/analytics/queries"
    for name in engine.available():
        assert engine.query_text(name) == (queries / f"{name}.sql").read_text(encoding="utf-8")


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


def _three_city_dataset(tmp_path):
    """One role advertised in three cities, plus a second role — four adverts, two jobs."""
    context = normalize.Normalization(tech_aliases={}, role_rules=(("backend", ("engineer",)),))

    def raw(offer_id, title, city):
        return {
            "offer_id": offer_id, "title": title, "company": "Sii",
            "offer_url": f"u{offer_id}", "locations": [{"city": city, "region": "r"}],
            "seniority": ["senior"], "work_modes": ["remote"],
            "tech_expected": ["python"], "tech_optional": [],
            "contracts": [{
                "type": "B2B", "kind": "netto (+ VAT)", "currency": "zł",
                "salary_from": 20000, "salary_to": 25000, "time_unit": "miesięcznie",
            }],
        }

    conn = db.connect(tmp_path / "t.db")
    offers = [
        normalize.normalize_offer(raw(f"a{i}", "Cloud Data Engineer", city), context)
        for i, city in enumerate(["Wrocław", "Kraków", "Gdańsk"])
    ]
    offers.append(normalize.normalize_offer(raw("b1", "Kotlin Engineer", "Kraków"), context))
    db.write_offers(conn, offers, "2026-08-13")
    db.record_frame(conn, [(o["offer_id"], "u") for o in offers], "2026-08-13")
    db.start_snapshot(conn, "collect", "2026-08-13", "2026-08-13T10:00:00")
    out = tmp_path / "dataset"
    export.write_dataset(conn, out)
    return conn, out


def test_one_role_advertised_in_many_cities_counts_once(tmp_path):
    """Demand is a property of the job, not of how widely its employer advertises.

    Measured on real data when this changed: 4354 adverts were 2856 vacancies, and the
    published ranking moved azure from third place to seventh.
    """
    conn, out = _three_city_dataset(tmp_path)
    connection = engine.connect(out)
    try:
        technologies = engine.run("top_technologies", connection=connection)
        strata = engine.run("stratum_sizes", connection=connection)
        roles = engine.run("role_family_distribution", connection=connection)
        work_modes = engine.run("work_mode_distribution", connection=connection)
        salaries = engine.run("salary_rows", connection=connection, kind="b2b")
    finally:
        connection.close()
    conn.close()

    # Four adverts, two jobs: the three-city posting is one, the Kotlin role the other.
    assert int(technologies.loc[technologies["technology"] == "python", "offers"].iloc[0]) == 2
    assert int(strata.loc[strata["seniority"] == "senior", "offers"].iloc[0]) == 2
    # Every counting query, not only the two that happened to have a test: reverting any of
    # these to advert counting used to fail nothing but the committed-page byte diff, which
    # is re-baselined by the same commit that changes the metric.
    assert int(roles["offers"].sum()) == 2
    assert int(work_modes.loc[work_modes["work_mode"] == "remote", "offers"].iloc[0]) == 2
    assert len(salaries) == 2  # one row per vacancy, not per advert


def test_the_city_comparison_keeps_counting_adverts(tmp_path):
    """The one deliberate exception, pinned so it stays deliberate.

    A role advertised in three cities is offered in three cities, so the city arm counts
    adverts. The remote arm is the opposite case — all three copies are the same remote
    job — and counting adverts there inflated it by 28% on real data.
    """
    conn, out = _three_city_dataset(tmp_path)
    connection = engine.connect(out)
    try:
        rows = engine.run("city_vs_remote_rows", connection=connection, city="Wrocław")
    finally:
        connection.close()
    conn.close()

    counts = rows.groupby("group_name").size()
    assert int(counts.get("city", 0)) == 1   # only one advert names Wrocław
    assert int(counts.get("remote", 0)) == 2  # four remote adverts, two jobs


def test_a_delisted_offer_leaves_the_published_figures(tmp_path):
    """ADR 0004: the page is a snapshot of the market, not an archive of what we collected.

    Without the frame join the analysed set only ever grows — two days in, 309 of 6839
    analysed offers were already off the market, and the coverage KPI reached 101%.
    """
    conn = db.connect(tmp_path / "t.db")
    offers = [
        _offer("still", "senior", ["python"], 20000),
        _offer("gone", "senior", ["rust"], 21000),
    ]
    db.write_offers(conn, offers, "2026-08-12")
    db.record_frame(conn, [("still", "u1"), ("gone", "u2")], "2026-08-12")
    db.record_frame(conn, [("still", "u1")], "2026-08-13")  # 'gone' is no longer listed
    db.start_snapshot(conn, "collect", "2026-08-13", "2026-08-13T10:00:00")
    out = tmp_path / "dataset"
    export.write_dataset(conn, out)

    connection = engine.connect(out)
    try:
        technologies = set(engine.run("top_technologies", connection=connection)["technology"])
        salaries = engine.run("salary_rows", connection=connection, kind="b2b")
    finally:
        connection.close()
    conn.close()

    assert "python" in technologies
    assert "rust" not in technologies  # the delisted offer stops counting
    assert len(salaries) == 1
