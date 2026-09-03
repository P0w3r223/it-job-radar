"""Tests for coverage over time (phase 7.2).

The figure exists to support one claim — that a bounded, polite collector accumulates by
coming back — so what is tested is the honesty of the drawing: that the series is bound to
the metrics the pipeline actually writes, that a series too short to interpolate is not
given a line, and that the scale choice is stated rather than hidden.
"""

import json

import pytest

from it_job_radar import config, db, export, pipeline
from it_job_radar.analytics import engine
from it_job_radar.site import build, charts


def _run(conn, kind, date, started_at, fetched, live):
    """Record a run exactly the way the pipeline does, then report its metrics."""
    snapshot_id = db.start_snapshot(conn, kind, date, started_at)
    delta = db.FrameDelta(live=live, new=0, disappeared=0, returned=0)
    db.write_snapshot_stat(conn, snapshot_id, date, "coverage_fetched", fetched)
    db.write_snapshot_stat(conn, snapshot_id, date, "frame_live", delta.live)
    return snapshot_id


@pytest.fixture
def dataset(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    _run(conn, config.SNAPSHOT_OBSERVE, "2026-08-11", "2026-08-11T10:00:00", 0, 6466)
    _run(conn, config.SNAPSHOT_COLLECT, "2026-08-11", "2026-08-11T10:30:00", 93, 6466)
    _run(conn, config.SNAPSHOT_COLLECT, "2026-08-12", "2026-08-12T10:00:00", 387, 6603)
    out = tmp_path / "dataset"
    export.publish(conn, out)
    yield conn, out
    conn.close()


def test_the_query_reads_the_metric_names_the_pipeline_writes(tmp_path):
    """Bound by behaviour, not by matching strings: the pipeline records, the query reads.

    The metric names are literals in both places — parameterising them would hide from the
    reader which numbers the figure is made of, and the page shows this SQL verbatim.
    """
    conn = db.connect(tmp_path / "bound.db")
    snapshot_id = db.start_snapshot(
        conn, config.SNAPSHOT_COLLECT, "2026-08-12", "2026-08-12T10:00:00"
    )
    pipeline._record_frame_metrics(
        conn, snapshot_id, "2026-08-12", db.FrameDelta(live=6603, new=10, disappeared=2, returned=0)
    )
    out = tmp_path / "dataset"
    export.publish(conn, out)

    frame = engine.run("coverage_over_time", dataset_dir=out)
    assert len(frame) == 1
    assert float(frame["offers_listed"].iloc[0]) == 6603
    conn.close()


def test_runs_come_back_in_run_order(dataset):
    """The only order under which an accumulation is monotonic."""
    _, out = dataset
    frame = engine.run("coverage_over_time", dataset_dir=out)

    assert list(frame["snapshot_id"]) == sorted(frame["snapshot_id"])
    assert list(frame["offers_analysed"]) == [0.0, 93.0, 387.0]


def test_a_run_missing_its_base_is_left_out_rather_than_drawn(tmp_path):
    conn = db.connect(tmp_path / "partial.db")
    snapshot_id = db.start_snapshot(
        conn, config.SNAPSHOT_OBSERVE, "2026-08-12", "2026-08-12T10:00:00"
    )
    db.write_snapshot_stat(conn, snapshot_id, "2026-08-12", "coverage_fetched", 100)
    out = tmp_path / "dataset"
    export.publish(conn, out)

    assert engine.run("coverage_over_time", dataset_dir=out).empty
    conn.close()


def _points(count):
    return [charts.Point(label="2026-08-12", value=float(i), fetched=True) for i in range(count)]


def test_a_series_too_short_to_interpolate_gets_no_line():
    """Two points and a line between them is a claim about an interval nobody observed."""
    svg = charts.accumulation_chart(
        _points(2), "Coverage", reference=100, reference_label="100 listed"
    )
    assert "polyline" not in svg
    assert "too short for a line" in svg
    assert svg.count("<circle") == 2


def test_a_long_enough_series_is_connected():
    svg = charts.accumulation_chart(
        _points(config.MIN_SERIES_POINTS), "Coverage", reference=100, reference_label="100 listed"
    )
    assert "polyline" in svg
    assert "too short for a line" not in svg


def test_the_chart_states_the_ceiling_it_is_not_drawn_against(dataset):
    """The scale is the accumulation's own, so the market size has to be said in words."""
    _, out = dataset
    svg = str(build.gather(out)["charts"]["coverage"])

    assert "of 6 603 listed" in svg
    assert "387 (5.9%)" in svg  # the share is the honest reading of the rescaled line


def test_each_date_is_ticked_once_however_many_runs_it_held(dataset):
    """Several runs share a day; repeating the date under each reads as several days."""
    _, out = dataset
    svg = str(build.gather(out)["charts"]["coverage"])

    assert svg.count(">2026-08-11<") == 1
    assert svg.count(">2026-08-12<") == 1


def test_the_figure_reaches_the_page_with_its_counts(dataset):
    _, out = dataset
    page = build.gather(out)

    assert page["runs_recorded"] == 3
    assert 'class="bar-value"' in str(page["charts"]["coverage"])  # the build guard's rule


def test_no_recorded_runs_says_so_instead_of_drawing_an_empty_axis():
    assert "No recorded runs" in charts.accumulation_chart(
        [], "Coverage", reference=100, reference_label="100 listed"
    )


def test_the_committed_series_ends_where_the_committed_manifest_says_it_should():
    """Two independent paths to today's coverage: the chart's last point and the manifest.

    They are measured differently — one from the metrics recorded per run, one from the
    frame at export time — so a disagreement means the published artifact is internally
    inconsistent, which the page diff cannot see because both numbers would move together
    only if the export was complete.
    """
    manifest = json.loads(
        (config.DATASET_DIR / config.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    frame = engine.run("coverage_over_time", dataset_dir=config.DATASET_DIR)

    assert float(frame["offers_analysed"].iloc[-1]) == manifest["coverage"]["attributes_known"]
    assert float(frame["offers_listed"].iloc[-1]) == manifest["coverage"]["offers_listed"]
