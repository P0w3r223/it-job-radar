"""Tests for technology movement between runs (phase 7.4).

The figure's whole value is in what it refuses to draw. Coverage went from a tenth of the
market to all of it in four days, and a chart that plotted counts over that stretch would
have published our own sampling as a hiring trend. So the tests are about the refusals:
runs too partial to compare are dropped, a series too short is not turned into a movement,
a technology with only one endpoint has not moved, and the panel says which of those it is
rather than rendering an empty box.
"""

import pandas as pd
import pytest

from it_job_radar import config, db, export
from it_job_radar.analytics import engine, movement
from it_job_radar.site import build, charts

_SERIES = config.TECHNOLOGY_SERIES


def _run(conn, date, started_at, fetched, live, points, kind=None):
    """One recorded run: its coverage stats, and the dated metrics an export would write."""
    snapshot_id = db.start_snapshot(conn, kind or config.SNAPSHOT_COLLECT, date, started_at)
    db.write_snapshot_stat(conn, snapshot_id, date, "coverage_fetched", fetched)
    db.write_snapshot_stat(conn, snapshot_id, date, "frame_live", live)
    db.write_dimension_metrics(
        conn,
        snapshot_id,
        date,
        [(_SERIES, technology, value, n) for technology, value, n in points],
    )
    return snapshot_id


def _rows(*days) -> pd.DataFrame:
    """The shape ``technology_movement`` returns, without going through DuckDB."""
    return pd.DataFrame(
        [
            {
                "technology": technology,
                "observed_date": date,
                "vacancies": float(value),
                "analysed_vacancies": n,
                "share": value / n,
                "coverage": 1.0,
            }
            for date, entries in days
            for technology, value, n in entries
        ]
    )


# --- the comparison itself ----------------------------------------------------


def test_nothing_recorded_yet_is_not_an_error():
    comparison = movement.compare(pd.DataFrame())

    assert comparison.days == ()
    assert not comparison.drawable


def test_a_series_too_short_reports_its_days_and_refuses_the_movement():
    """Two comparable runs are two measurements, not a direction."""
    comparison = movement.compare(
        _rows(
            ("2026-08-13", [("python", 100, 1000)]),
            ("2026-08-14", [("python", 140, 1000)]),
        )
    )

    assert comparison.days == ("2026-08-13", "2026-08-14")
    assert comparison.moves == ()
    assert not comparison.drawable


def test_movement_is_measured_in_share_not_in_count():
    """The count can rise while the slice narrows — that is the case the figure is for."""
    comparison = movement.compare(
        _rows(
            ("2026-08-12", [("python", 100, 1000)]),
            ("2026-08-13", [("python", 120, 1500)]),
            ("2026-08-14", [("python", 150, 2000)]),
        ),
        min_days=3,
    )

    (move,) = comparison.moves
    assert move.first_vacancies == 100 and move.last_vacancies == 150
    assert move.delta == pytest.approx(0.075 - 0.1)  # the count grew, the share fell


def test_the_endpoints_are_the_first_and_last_day_not_the_last_two():
    comparison = movement.compare(
        _rows(
            ("2026-08-12", [("sql", 100, 1000)]),
            ("2026-08-13", [("sql", 500, 1000)]),
            ("2026-08-14", [("sql", 200, 1000)]),
        ),
        min_days=3,
    )

    (move,) = comparison.moves
    assert (move.first_share, move.last_share) == (0.1, 0.2)


def test_a_technology_with_only_one_endpoint_has_not_moved():
    """Entering the recorded top thirty is a fact about our recording depth, not hiring."""
    comparison = movement.compare(
        _rows(
            ("2026-08-12", [("sql", 100, 1000)]),
            ("2026-08-13", [("sql", 110, 1000), ("rust", 10, 1000)]),
            ("2026-08-14", [("sql", 120, 1000), ("rust", 40, 1000)]),
        ),
        min_days=3,
    )

    assert [move.technology for move in comparison.moves] == ["sql"]


def test_the_largest_movers_come_first_and_the_rest_are_dropped():
    days = [
        (
            date,
            [("sql", 100 + shift, 1000), ("java", 100, 1000), ("go", 100 - shift // 2, 1000)],
        )
        for date, shift in (("2026-08-12", 0), ("2026-08-13", 20), ("2026-08-14", 40))
    ]
    comparison = movement.compare(_rows(*days), min_days=3, limit=2)

    assert [move.technology for move in comparison.moves] == ["sql", "go"]
    assert comparison.moves[0].delta > 0 > comparison.moves[1].delta


# --- the query that decides which runs may be compared -------------------------


@pytest.fixture
def dataset(tmp_path):
    """Three days, one of which saw too little of the market to be comparable."""
    conn = db.connect(tmp_path / "movement.db")
    _run(conn, "2026-08-12", "2026-08-12T10:00:00", 600, 6000, [("python", 60, 600)])
    _run(conn, "2026-08-13", "2026-08-13T10:00:00", 5900, 6000, [("python", 500, 5000)])
    _run(conn, "2026-08-14", "2026-08-14T10:00:00", 5950, 6000, [("python", 560, 5000)])
    out = tmp_path / "dataset"
    export.publish(conn, out)
    yield conn, out
    conn.close()


def test_a_run_that_saw_a_tenth_of_the_market_is_not_compared_with_one_that_saw_all_of_it(dataset):
    _, out = dataset
    frame = engine.run("technology_movement", dataset_dir=out)

    assert sorted(frame["observed_date"].unique()) == ["2026-08-13", "2026-08-14"]


def test_a_run_with_no_recorded_coverage_cannot_establish_comparability(tmp_path):
    conn = db.connect(tmp_path / "uncovered.db")
    snapshot_id = db.start_snapshot(conn, config.SNAPSHOT_COLLECT, "2026-08-14", "2026-08-14T10:00:00")
    db.write_dimension_metrics(conn, snapshot_id, "2026-08-14", [(_SERIES, "python", 10, 100)])
    out = tmp_path / "dataset"
    export.publish(conn, out)

    assert engine.run("technology_movement", dataset_dir=out).empty
    conn.close()


def test_a_day_of_many_runs_contributes_one_point(tmp_path):
    """Seven collects in an afternoon are one day of market, not seven days of movement."""
    conn = db.connect(tmp_path / "busy.db")
    _run(conn, "2026-08-13", "2026-08-13T10:00:00", 5000, 6000, [("python", 400, 5000)])
    _run(conn, "2026-08-13", "2026-08-13T16:00:00", 5900, 6000, [("python", 500, 5000)])
    out = tmp_path / "dataset"
    export.publish(conn, out)

    frame = engine.run("technology_movement", dataset_dir=out)
    assert len(frame) == 1
    assert float(frame["vacancies"].iloc[0]) == 500  # the day's last comparable run
    conn.close()


def test_the_query_reads_the_series_the_history_writer_records(dataset):
    """One name, from config: a series read under a name nobody writes is a silent blank."""
    _, out = dataset
    metrics = engine.connect(out).execute(
        "SELECT DISTINCT metric FROM snapshot_dimension_metrics"
    ).df()

    assert _SERIES in set(metrics["metric"])
    assert not engine.run("technology_movement", dataset_dir=out).empty


# --- what the panel says in each state -----------------------------------------


def test_the_panel_says_what_it_is_waiting_for_rather_than_showing_an_empty_box(dataset):
    _, out = dataset
    page = build.gather(out)

    assert page["movement_days"] == 2
    assert "2 comparable runs of the 3 needed" in str(page["charts"]["movement"])


def test_every_bar_carries_the_counts_behind_its_percentage():
    svg = charts.movement_chart(
        [charts.Change(label="python", delta=0.012, note="500 → 560")],
        "How each technology's share moved",
        waiting="not yet",
        footer="2026-08-13 → 2026-08-14",
    )

    assert "+1.2 pp · 500 → 560" in svg
    assert 'class="bar-value"' in svg  # the build guard's rule


def test_a_fall_and_a_rise_are_told_apart_by_more_than_colour():
    falling = charts.movement_chart(
        [charts.Change(label="php", delta=-0.02, note="90 → 40")], "t", waiting="", footer=""
    )

    assert "-2.0 pp" in falling
    assert 'class="bar down"' in falling
