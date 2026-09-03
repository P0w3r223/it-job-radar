"""Tests for technologies asked together.

The pair chart's whole claim is that it is *not* the demand chart drawn twice. So what is
tested is the arithmetic that makes it a different question — counting per vacancy rather
than per advert, keeping each unordered pair once, and dropping the thin pairs where lift
is largest and least real.
"""

import pytest

from it_job_radar import config, db, export, normalize
from it_job_radar.analytics import engine
from it_job_radar.site import build, charts


def _offer(offer_id, technologies, title=None, company="ACME"):
    title = title or f"Engineer {offer_id}"
    return {
        "offer_id": offer_id,
        "title": title,
        "company": company,
        # What makes two adverts one job. Derived here as the pipeline derives it, so the
        # per-city copies in these fixtures collapse the way the real ones do.
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
        "salaries": [],
    }


def _publish(conn, offers, out, date="2026-08-14"):
    """Store the adverts, put them in the frame every published query filters on, export."""
    db.write_offers(conn, offers, date)
    db.record_frame(conn, [(o["offer_id"], o["offer_url"]) for o in offers], date)
    db.start_snapshot(conn, config.SNAPSHOT_COLLECT, date, f"{date}T10:00:00")
    db.reconcile_fetch_state(conn)
    export.publish(conn, out)


@pytest.fixture
def workspace(tmp_path):
    conn = db.connect(tmp_path / "pairs.db")
    yield conn, tmp_path / "dataset"
    conn.close()


def test_a_pair_is_counted_once_per_vacancy_not_once_per_city(workspace):
    """One role published in three cities is one job asking for the pair."""
    conn, out = workspace
    _publish(
        conn,
        [_offer(f"o{i}", ["python", "sql"], title="Data Engineer") for i in range(3)],
        out,
    )

    frame = engine.run("technology_pairs", dataset_dir=out, min_pair_n=1)
    assert len(frame) == 1
    assert int(frame["vacancies"].iloc[0]) == 1


def test_each_unordered_pair_appears_once_and_never_with_itself(workspace):
    conn, out = workspace
    _publish(conn, [_offer("a", ["python", "sql", "aws"])], out)

    frame = engine.run("technology_pairs", dataset_dir=out, min_pair_n=1)
    pairs = {(row["technology_a"], row["technology_b"]) for _, row in frame.iterrows()}

    assert pairs == {("aws", "python"), ("aws", "sql"), ("python", "sql")}
    assert all(a < b for a, b in pairs)


def test_lift_is_one_when_two_technologies_are_independent(workspace):
    """Four vacancies: python and sql in half each, sharing exactly one — that is chance."""
    conn, out = workspace
    _publish(
        conn,
        [
            _offer("a", ["python", "sql"], company="A"),
            _offer("b", ["python", "go"], company="B"),
            _offer("c", ["sql", "go"], company="C"),
            _offer("d", ["go"], company="D"),
        ],
        out,
    )

    frame = engine.run("technology_pairs", dataset_dir=out, min_pair_n=1)
    lift = {(row["technology_a"], row["technology_b"]): row["lift"] for _, row in frame.iterrows()}

    assert lift[("python", "sql")] == pytest.approx(1.0)  # 1/4 shared against 2/4 × 2/4
    assert lift[("go", "python")] == pytest.approx(2 / 3)  # together less often than chance


def test_a_thin_pair_is_dropped_rather_than_published_as_the_strongest_finding(workspace):
    """Two technologies appearing only together score the highest lift on the page."""
    conn, out = workspace
    _publish(
        conn,
        [_offer("a", ["cobol", "jcl"], company="A"), _offer("b", ["cobol", "jcl"], company="B")]
        + [_offer(f"c{i}", ["python", "sql"], company=f"C{i}") for i in range(10)],
        out,
    )

    frame = engine.run("technology_pairs", dataset_dir=out, min_pair_n=3)
    pairs = {(row["technology_a"], row["technology_b"]) for _, row in frame.iterrows()}

    assert ("cobol", "jcl") not in pairs
    assert ("python", "sql") in pairs


def test_the_strongest_pair_is_not_the_most_frequent_one(workspace):
    """Twice as many vacancies ask for python and sql, and they still rank second.

    That is the whole point of the panel: frequency is the chart above, and repeating it
    under a second title would publish one finding as two.
    """
    conn, out = workspace
    _publish(
        conn,
        [_offer(f"p{i}", ["grafana", "prometheus"], company=f"O{i}") for i in range(4)]
        + [_offer(f"c{i}", ["python", "sql"], company=f"D{i}") for i in range(8)],
        out,
    )

    frame = engine.run("technology_pairs", dataset_dir=out, min_pair_n=4)
    ranked = [(row["technology_a"], row["technology_b"]) for _, row in frame.iterrows()]

    assert ranked == [("grafana", "prometheus"), ("python", "sql")]


def test_the_bar_states_a_lift_rather_than_rounding_it_into_a_count():
    """A lift of 4.6 printed as "5" is a different number."""
    svg = charts.bar_chart(
        [charts.Bar(label="grafana + prometheus", value=4.6, value_text="4.6×", note="n=40")],
        "Asked together",
        unit="lift",
    )

    assert "4.6× n=40" in svg


def test_the_panel_reaches_the_page_with_the_population_its_lift_was_measured_over(workspace):
    conn, out = workspace
    vacancies = config.MIN_PAIR_N
    offers = [_offer(f"o{i}", ["python", "sql"], company=f"C{i}") for i in range(vacancies)]
    _publish(conn, offers, out)

    page = build.gather(out)

    assert page["min_pair_n"] == config.MIN_PAIR_N
    assert page["pair_base"] == vacancies
    assert "python + sql" in str(page["charts"]["pairs"])


def test_nothing_shared_often_enough_says_so_instead_of_drawing_an_empty_axis(workspace):
    conn, out = workspace
    _publish(conn, [_offer("a", ["python", "sql"])], out)

    page = build.gather(out)  # one vacancy, far under MIN_PAIR_N

    assert page["pair_base"] == 0
    assert 'class="empty"' in str(page["charts"]["pairs"])
