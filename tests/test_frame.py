"""Tests for the population frame — presence recorded from the sitemap alone (ADR 0003).

The frame is what makes presence free and complete, so these tests pin down the parts the
survival analysis will later depend on: cohort assignment, implicit disappearance, and
the pools the fetch queue draws from.
"""

from it_job_radar import config, db


def _entries(ids):
    return [(i, f"https://theprotocol.it/szczegoly/praca/rola,oferta,{i}") for i in ids]


def test_first_observation_is_the_stock_cohort(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    delta = db.record_frame(conn, _entries(["a", "b", "c"]), "2026-08-11")

    assert (delta.live, delta.new, delta.disappeared, delta.returned) == (3, 3, 0, 0)
    frame = db.read_table(conn, "sitemap_offers")
    # entry dates unknown -> left truncated -> unusable for lifetime estimation
    assert set(frame["cohort"]) == {config.COHORT_STOCK}
    assert set(frame["fetch_state"]) == {config.FETCH_PENDING}
    conn.close()


def test_later_arrivals_are_the_flow_cohort(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["a"]), "2026-08-11")
    delta = db.record_frame(conn, _entries(["a", "b"]), "2026-08-12")

    assert (delta.live, delta.new) == (2, 1)
    cohorts = dict(conn.execute("SELECT offer_id, cohort FROM sitemap_offers"))
    assert cohorts == {"a": config.COHORT_STOCK, "b": config.COHORT_FLOW}
    conn.close()


def test_disappearance_is_implicit(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["a", "b"]), "2026-08-11")
    delta = db.record_frame(conn, _entries(["a"]), "2026-08-12")

    assert delta.disappeared == 1
    seen = dict(conn.execute("SELECT offer_id, last_seen FROM sitemap_offers"))
    assert seen == {"a": "2026-08-12", "b": "2026-08-11"}  # b simply stopped advancing
    conn.close()


def test_reappearance_is_counted_as_a_gap(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["a", "b"]), "2026-08-11")
    db.record_frame(conn, _entries(["a"]), "2026-08-12")
    delta = db.record_frame(conn, _entries(["a", "b"]), "2026-08-13")

    assert delta.returned == 1
    assert delta.new == 0  # a returning offer is not a new one
    gaps = dict(conn.execute("SELECT offer_id, gaps FROM sitemap_offers"))
    assert gaps == {"a": 0, "b": 1}
    conn.close()


def test_last_frame_date_reads_the_previous_observation(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    assert db.last_frame_date(conn) is None
    db.record_frame(conn, _entries(["a"]), "2026-08-11")
    assert db.last_frame_date(conn) == "2026-08-11"
    conn.close()


def test_frame_state_splits_the_fetch_pools(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["old", "gone", "stale"]), "2026-08-11")
    db.mark_fetched(conn, [("old", config.FETCH_DONE)], "2026-08-11")
    db.record_frame(conn, _entries(["old", "new", "stale"]), "2026-08-12")

    state = db.frame_state(conn, "2026-08-12")
    assert [i for i, _ in state.new_today] == ["new"]
    assert [i for i, _ in state.backlog] == ["stale"]  # live, listed before, never fetched
    assert [i for i, _ in state.fetched_live] == ["old"]  # audit pool
    # "gone" is in none of them: it is no longer live
    conn.close()


def test_day_zero_stock_is_backlog_not_inflow(tmp_path):
    """On the first observation nothing is a new *arrival* — everything was already open.

    Counting the day-zero stock as inflow would drive inflow_capture_rate to ~0 and raise
    a length-bias alarm that means nothing.
    """
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["a", "b"]), "2026-08-11")

    state = db.frame_state(conn, "2026-08-11")
    assert state.new_today == []
    assert sorted(i for i, _ in state.backlog) == ["a", "b"]
    conn.close()


def test_failed_fetches_stay_eligible(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["a"]), "2026-08-11")
    db.record_frame(conn, _entries(["a", "b"]), "2026-08-12")
    db.mark_fetched(conn, [("b", config.FETCH_FAILED)], "2026-08-12")

    state = db.frame_state(conn, "2026-08-12")
    assert [i for i, _ in state.new_today] == ["b"]  # retried, not written off
    assert state.fetched_live == []
    conn.close()


def test_coverage_counts_known_attributes_against_the_live_base(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.record_frame(conn, _entries(["a", "b", "c"]), "2026-08-11")
    db.mark_fetched(conn, [("a", config.FETCH_DONE)], "2026-08-11")

    assert db.coverage(conn, "2026-08-11") == (1, 3)
    conn.close()


def test_reconcile_marks_offers_collected_before_the_frame_existed(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO offers (offer_id, title, collected_date) "
        "VALUES ('known', 'Backend', '2026-07-17')"
    )
    conn.commit()
    db.record_frame(conn, _entries(["known", "unknown"]), "2026-08-11")

    assert db.reconcile_fetch_state(conn) == 1
    assert db.coverage(conn, "2026-08-11") == (1, 2)
    state = db.frame_state(conn, "2026-08-11")
    assert [i for i, _ in state.backlog] == ["unknown"]  # no pointless re-fetch of "known"
    row = conn.execute(
        "SELECT fetch_state, fetch_date FROM sitemap_offers WHERE offer_id = 'known'"
    ).fetchone()
    assert row == (config.FETCH_DONE, "2026-07-17")
    assert db.reconcile_fetch_state(conn) == 0  # idempotent
    conn.close()


def test_backfill_repairs_urls_only_for_offers_still_listed(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    conn.executemany(
        "INSERT INTO offers (offer_id, title, offer_url, collected_date) VALUES (?, ?, NULL, ?)",
        [("live", "Backend", "2026-07-17"), ("delisted", "Frontend", "2026-07-17")],
    )
    conn.commit()
    db.record_frame(conn, _entries(["live"]), "2026-08-11")

    repaired, missing = db.backfill_offer_urls(conn)
    assert (repaired, missing) == (1, 1)
    urls = dict(conn.execute("SELECT offer_id, offer_url FROM offers"))
    assert urls["live"].endswith(",oferta,live")
    assert urls["delisted"] is None  # not recoverable — a null beats a guess
    conn.close()
