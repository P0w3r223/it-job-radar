"""Tests for the aggregation queries (on a seeded temp database)."""

from it_job_radar import analyze, db


def _offer(oid, tech, seniority, city=None, work_mode=None, mfrom=None, mto=None, kind="b2b"):
    return {
        "offer_id": oid, "title": "T", "company": "C", "offer_url": "u",
        "cities": [city] if city else [], "regions": [],
        "seniority": [seniority], "work_modes": [work_mode] if work_mode else [],
        "technologies": {"expected": [tech], "optional": []},
        "salaries": (
            [{"contract_type": "B2B", "kind": kind, "currency": "PLN",
              "salary_from": None, "salary_to": None, "time_unit": "miesięcznie",
              "monthly_from": mfrom, "monthly_to": mto}]
            if mfrom else []
        ),
    }


def _seed(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [
        _offer("a", "python", "junior", city="Wrocław", mfrom=10000, mto=15000),
        _offer("b", "java", "senior", work_mode="remote", mfrom=20000, mto=25000),
        _offer("c", "python", "senior", work_mode="remote", mfrom=22000, mto=28000),
    ], "2026-07-17")
    return conn


def test_top_technologies_counts_distinct_offers(tmp_path):
    conn = _seed(tmp_path)
    counts = dict(zip(*analyze.top_technologies(conn)[["technology", "offers"]].values.T))
    assert counts["python"] == 2
    assert counts["java"] == 1
    conn.close()


def test_top_technologies_filtered_by_seniority(tmp_path):
    conn = _seed(tmp_path)
    junior = analyze.top_technologies(conn, seniority="junior")
    assert set(junior["technology"]) == {"python"}
    conn.close()


def test_salary_by_seniority_medians(tmp_path):
    conn = _seed(tmp_path)
    table = analyze.salary_by_seniority(conn, kind="b2b").set_index("seniority")
    assert table.loc["junior", "median_from"] == 10000
    assert table.loc["senior", "median_from"] == 21000  # median of 20000, 22000
    conn.close()


def test_wroclaw_vs_remote_counts(tmp_path):
    conn = _seed(tmp_path)
    compare = analyze.wroclaw_vs_remote(conn, kind="b2b").set_index("group")
    assert compare.loc["Wrocław", "offers"] == 1
    assert compare.loc["remote", "offers"] == 2
    conn.close()
