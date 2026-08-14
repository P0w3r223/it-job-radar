"""Tests for the salary premium per technology.

The figure exists because the obvious version of it is wrong: vacancies listing Kubernetes
pay more than the rest, and almost all of that is seniority. So the tests plant an effect
and check it comes back, plant a *confound* and check it does not, and hold the model to
its refusals — a technology too rare to model, an interval that spans zero, two
technologies that always appear together.
"""

import numpy as np
import pandas as pd
import pytest

from it_job_radar import config, db, export, normalize
from it_job_radar.analytics import engine, premium
from it_job_radar.site import charts


def _rows(records) -> pd.DataFrame:
    """The shape `salary_premium_rows` returns."""
    return pd.DataFrame(
        [
            {
                "vacancy": f"v{index}",
                "monthly_floor": floor,
                "seniority": seniority,
                "work_modes": "remote",
                "technologies": "|".join(technologies),
            }
            for index, (floor, seniority, technologies) in enumerate(records)
        ]
    )


def _market(rng, *, premiums, count=200, senior_lift=0.6):
    """A synthetic market with known coefficients, in log space."""
    records = []
    for index in range(count):
        senior = index % 2 == 0
        technologies = [name for name, _, holds in premiums if holds(index, senior)]
        effect = sum(value for name, value, holds in premiums if holds(index, senior))
        log_floor = 9.5 + (senior_lift if senior else 0.0) + effect + rng.normal(0, 0.05)
        records.append((float(np.exp(log_floor)), "senior" if senior else "junior", technologies))
    return _rows(records)


def test_a_planted_premium_comes_back(monkeypatch):
    rows = _market(
        np.random.default_rng(11),
        premiums=[("terraform", 0.2, lambda index, senior: index % 3 == 0)],
    )

    fit = premium.estimate(rows, min_n=30)

    (estimate,) = [item for item in fit.premiums if item.technology == "terraform"]
    assert estimate.percent == pytest.approx(22.1, abs=3.0)  # exp(0.2) - 1
    assert estimate.ci_low < estimate.percent < estimate.ci_high
    assert estimate.distinguishable


def test_a_technology_that_only_travels_with_seniority_shows_no_premium_of_its_own():
    """The whole reason the figure is a regression and not a median comparison."""
    rows = _market(
        np.random.default_rng(12),
        premiums=[("kubernetes", 0.0, lambda index, senior: senior and index % 3 != 0)],
    )

    fit = premium.estimate(rows, min_n=30)
    (estimate,) = [item for item in fit.premiums if item.technology == "kubernetes"]

    assert abs(estimate.percent) < 5
    assert not estimate.distinguishable  # the interval spans zero, and the page says so


def test_a_technology_below_the_floor_is_not_modelled_at_all():
    rows = _market(
        np.random.default_rng(13),
        premiums=[
            ("cobol", 0.3, lambda index, senior: index < 10),
            ("python", 0.1, lambda index, senior: index % 2 == 0),
        ],
    )

    fit = premium.estimate(rows, min_n=60)

    assert [item.technology for item in fit.premiums] == ["python"]


def test_two_technologies_that_always_appear_together_do_not_crash_the_fit():
    """A singular design matrix is a data property, not a bug — it must not be a traceback."""
    rows = _market(
        np.random.default_rng(14),
        premiums=[
            ("spring", 0.15, lambda index, senior: index % 2 == 0),
            ("hibernate", 0.0, lambda index, senior: index % 2 == 0),
        ],
    )

    fit = premium.estimate(rows, min_n=30)

    assert {item.technology for item in fit.premiums} == {"spring", "hibernate"}
    assert all(np.isfinite(item.percent) for item in fit.premiums)


def test_nothing_disclosed_is_not_an_error():
    fit = premium.estimate(pd.DataFrame())

    assert fit.premiums == ()
    assert not fit.drawable


def test_the_largest_effects_are_kept_and_shown_from_top_to_bottom():
    rows = _market(
        np.random.default_rng(15),
        premiums=[
            ("a", 0.3, lambda index, senior: index % 2 == 0),
            ("b", -0.3, lambda index, senior: index % 3 == 0),
            ("c", 0.01, lambda index, senior: index % 5 == 0),
        ],
    )

    fit = premium.estimate(rows, min_n=30, limit=2)

    assert [item.technology for item in fit.premiums] == ["a", "b"]  # sorted by estimate
    assert fit.premiums[0].percent > fit.premiums[1].percent


# --- the query the model is fed ------------------------------------------------


def _offer(offer_id, technologies, monthly, kind="b2b", title=None, company="ACME"):
    title = title or f"Engineer {offer_id}"
    return {
        "offer_id": offer_id,
        "title": title,
        "company": company,
        "vacancy_key": normalize.vacancy_key(title, company),
        "offer_url": f"https://x/{offer_id}",
        "role_family": "backend",
        "locations": [{"city": config.FOCUS_CITY, "region": "dolnośląskie"}],
        "seniority": ["mid"],
        "work_modes": ["remote"],
        "technologies": {
            "expected": normalize.normalize_technologies(technologies, {}),
            "optional": [],
        },
        "salaries": [{
            "contract_type": "B2B", "kind": kind, "currency": "PLN",
            "salary_from": monthly, "salary_to": monthly + 3000, "time_unit": "monthly",
            "monthly_from": monthly, "monthly_to": monthly + 3000,
        }],
    }


@pytest.fixture
def dataset(tmp_path):
    conn = db.connect(tmp_path / "premium.db")
    offers = [
        _offer("a1", ["python"], 20000, title="Data Engineer"),
        _offer("a2", ["python"], 20000, title="Data Engineer"),  # same job, another city
        _offer("b1", ["java"], 18000, kind="employment", company="Beta"),
    ]
    db.write_offers(conn, offers, "2026-08-14")
    db.record_frame(conn, [(o["offer_id"], o["offer_url"]) for o in offers], "2026-08-14")
    out = tmp_path / "dataset"
    export.write_dataset(conn, out)
    yield conn, out
    conn.close()


def test_one_job_advertised_twice_is_one_observation(dataset):
    _, out = dataset
    rows = engine.run("salary_premium_rows", dataset_dir=out, kind="b2b")

    assert len(rows) == 1
    assert rows["technologies"].iloc[0] == "python"


def test_the_two_contract_kinds_are_never_pooled(dataset):
    _, out = dataset

    b2b = engine.run("salary_premium_rows", dataset_dir=out, kind="b2b")
    employment = engine.run("salary_premium_rows", dataset_dir=out, kind="employment")

    assert float(b2b["monthly_floor"].iloc[0]) == 20000
    assert float(employment["monthly_floor"].iloc[0]) == 18000


# --- how it is drawn -----------------------------------------------------------


def test_the_interval_is_drawn_and_printed_beside_every_estimate():
    svg = charts.forest_chart(
        [charts.Estimate(label="gcp", value=13.4, low=7.9, high=19.2, n=84)],
        "Estimated pay premium",
        waiting="nothing to model",
    )

    assert "+13.4% (+7.9 to +19.2, n=84)" in svg
    assert 'class="ci"' in svg
    assert 'class="bar-value"' in svg  # the build guard's rule


def test_an_estimate_that_spans_zero_is_marked_rather_than_dropped():
    svg = charts.forest_chart(
        [charts.Estimate(label="docker", value=2.6, low=-3.0, high=8.6, n=106, muted=True)],
        "Estimated pay premium",
        waiting="",
    )

    assert 'class="range-dot muted"' in svg
    assert "no measured gap" in svg


def test_nothing_modellable_says_so_instead_of_drawing_an_empty_axis():
    assert "too few" in charts.forest_chart(
        [], "Estimated pay premium", waiting="too few disclosing vacancies"
    )
