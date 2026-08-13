"""Tests for the CLI orchestration layer.

Only the parts that carry a promise: the day's page accounting, which is the ethical
guardrail the per-run budget alone could not hold.
"""

import pytest

from it_job_radar import config, db, pipeline


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
