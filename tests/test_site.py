"""Tests for the published page.

These check the promises the page makes rather than its wording: that the headline follows
the data instead of being hard-coded, that no figure ships without its sample size, that
thin strata stay visible but marked, and that the redaction holds all the way to the HTML.
"""

import re

import pytest
from markupsafe import escape

from it_job_radar import config, db, export, normalize
from it_job_radar.analytics import engine
from it_job_radar.site import build, charts


def _offer(offer_id, seniority, monthly=None, family="backend", title="Java Engineer"):
    salaries = []
    if monthly is not None:
        salaries = [{
            "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": monthly,
            "salary_to": monthly + 3000, "time_unit": "monthly", "monthly_from": monthly,
            "monthly_to": monthly + 3000,
        }]
    return {
        "offer_id": offer_id, "title": title, "company": "ACME Sp. z o.o.",
        "offer_url": f"https://theprotocol.it/x,oferta,{offer_id}", "role_family": family,
        "locations": [{"city": config.FOCUS_CITY, "region": "dolnośląskie"}],
        "seniority": [seniority], "work_modes": ["remote"],
        "technologies": {
            "expected": normalize.normalize_technologies(["python"], {}),
            "optional": [],
        },
        "salaries": salaries,
    }


@pytest.fixture
def site(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    offers = [_offer(f"s{i}", "senior", 20000 + i * 100) for i in range(35)]
    offers += [
        _offer("j1", "junior", 8000, family="support", title="Informatyk"),
        _offer("j2", "junior", None, family="support", title="Helpdesk Specialist"),
        _offer("j3", "junior", None, family="backend"),
    ]
    db.write_offers(conn, offers, "2026-08-11")
    db.record_frame(conn, [(o["offer_id"], f"u{o['offer_id']}") for o in offers], "2026-08-11")
    db.start_snapshot(conn, "collect", "2026-08-11", "2026-08-11T10:00:00")
    db.reconcile_fetch_state(conn)
    dataset = tmp_path / "data"
    export.publish(conn, dataset, git_sha="abc1234")
    yield conn, dataset
    conn.close()


def test_headline_follows_the_data(site):
    _, dataset = site
    page = build.gather(dataset)
    assert "not development jobs" in page["headline"]["claim"]
    assert page["headline"]["n"] == 3


def test_headline_changes_when_the_data_does(tmp_path):
    """The claim is derived, so it cannot outlive the finding that justified it."""
    conn = db.connect(tmp_path / "t.db")
    offers = [_offer(f"j{i}", "junior", None, family="backend") for i in range(4)]
    db.write_offers(conn, offers, "2026-08-11")
    db.record_frame(conn, [(o["offer_id"], "u") for o in offers], "2026-08-11")
    db.start_snapshot(conn, "collect", "2026-08-11", "2026-08-11T10:00:00")
    dataset = tmp_path / "data"
    export.publish(conn, dataset)

    page = build.gather(dataset)
    assert "not development" not in page["headline"]["claim"]
    assert "backend" in page["headline"]["claim"]
    conn.close()


def _junior_page(tmp_path, families):
    """Publish a snapshot of junior offers with the given role families, then gather it."""
    conn = db.connect(tmp_path / "t.db")
    offers = [
        _offer(f"j{i}", "junior", None, family=family, title=f"Rola {i}")
        for i, family in enumerate(families)
    ]
    db.write_offers(conn, offers, "2026-08-11")
    db.record_frame(conn, [(o["offer_id"], "u") for o in offers], "2026-08-11")
    db.start_snapshot(conn, "collect", "2026-08-11", "2026-08-11T10:00:00")
    dataset = tmp_path / "data"
    export.publish(conn, dataset)
    try:
        return build.gather(dataset)["headline"]
    finally:
        conn.close()


def test_the_unmatched_residue_never_carries_the_headline(tmp_path):
    """"other" is a gap in our rule table, not a kind of work the market offers.

    It ties with support here and sorts first alphabetically, which is exactly how the
    published page once led with "The largest junior category is other".
    """
    headline = _junior_page(tmp_path, ["other", "other", "support", "support"])
    assert "other" not in headline["claim"]
    assert "not development jobs" in headline["claim"]
    assert headline["n"] == 4  # the residue stays in the denominator
    assert "2 of 4" in headline["detail"]
    assert "the largest single category" in headline["detail"]


def test_the_claim_weakens_when_the_residue_is_the_larger_bucket(tmp_path):
    headline = _junior_page(tmp_path, ["other"] * 3 + ["support"])
    assert "not development jobs" in headline["claim"]
    assert "the largest classified category" in headline["detail"]


def test_the_majority_claim_is_checked_as_a_majority(tmp_path):
    """Ranking first is not the same proposition as "most", and the h1 says "most".

    Role families are fine-grained, so development can pass half the segment while every
    single development family stays below support. Here support leads with 4 of 11 and the
    development families sum to 6 — the neutral wording has to take over.
    """
    families = ["support"] * 4 + ["backend"] * 2 + ["frontend"] * 2 + ["mobile"] + ["ml"] + ["qa"]
    headline = _junior_page(tmp_path, families)
    assert "not development jobs" not in headline["claim"]
    assert "support" in headline["claim"]


def test_the_majority_claim_survives_a_development_minority(tmp_path):
    families = ["support"] * 4 + ["backend"] * 2 + ["qa"] * 3
    headline = _junior_page(tmp_path, families)
    assert "not development jobs" in headline["claim"]
    assert "Development accounts for 2" in headline["detail"]


def test_a_snapshot_the_rule_table_cannot_place_says_so(tmp_path):
    headline = _junior_page(tmp_path, [None, "other"])
    assert "No junior offer" in headline["claim"]
    assert "other" not in headline["claim"]
    assert headline["n"] == 2


def test_a_withheld_salary_is_not_reported_as_an_undisclosed_one(site):
    """The refusal reached the manifest but stopped there, so the page said the opposite.

    A figure we withdrew as a unit error is not a salary the employer declined to publish,
    and a reader looking at the disclosure percentage alone cannot tell the two apart.
    """
    assert build._disclosure_note(0) == "the rest publish no figure at all"
    assert "withheld" in build._disclosure_note(13)

    _, dataset = site
    page = build.gather(dataset)
    labels = [kpi.note for kpi in page["kpis"]]
    assert any("no figure at all" in note for note in labels)  # nothing withheld in this fixture
    assert "salary_monthly_withheld" in page["manifest"]["quality"]


def test_every_chart_states_its_sample_size(site):
    _, dataset = site
    page = build.gather(dataset)
    for name, markup in page["charts"].items():
        markup = str(markup)
        has_counts = 'class="bar-value"' in markup
        says_nothing_to_show = 'class="empty"' in markup
        assert has_counts or says_nothing_to_show, f"{name} publishes values without counts"
    build._assert_figures_carry_n(page)  # the build-time gate itself


def test_a_figure_without_a_count_fails_the_build():
    with pytest.raises(build.IncompleteFigure):
        build._assert_figures_carry_n({"charts": {"bogus": "<svg></svg>"}})


def test_thin_strata_are_marked_not_dropped(site):
    _, dataset = site
    page = build.gather(dataset)
    html = build.render(dataset)

    assert "junior" in page["thin_strata"]  # n=3, under the threshold
    assert "senior" not in page["thin_strata"]  # n=35, above it
    assert "junior" in html  # still shown
    assert "muted" in page["charts"]["salary_b2b"]  # but visibly qualified


def test_redaction_survives_all_the_way_into_the_page(site):
    _, dataset = site
    html = build.render(dataset)
    assert "ACME" not in html
    assert "oferta," not in html


def test_page_is_complete_without_javascript(site):
    _, dataset = site
    html = build.render(dataset)
    assert "<script" not in html
    assert html.count("<svg") >= 5  # charts are rendered server-side, not drawn later


def test_page_publishes_the_query_behind_every_metric(site):
    _, dataset = site
    html = build.render(dataset)
    assert "top_technologies.sql" in html
    # Escaped, because the template escapes it: comparing against the file itself is the
    # promise ("the page shows the query"), and the escaping is how it keeps it safely.
    assert str(escape(engine.query_text("top_technologies"))) in html


def test_page_carries_provenance_and_social_metadata(site):
    _, dataset = site
    html = build.render(dataset)
    assert "abc1234" in html
    assert 'property="og:title"' in html
    assert "<time datetime=" in html
    assert "prefers-color-scheme: dark" in html


def test_build_writes_next_to_the_dataset(site, tmp_path):
    _, dataset = site
    written = build.build(tmp_path / "out", dataset)
    assert written.is_file() and written.name == "index.html"


def test_build_without_a_manifest_says_what_to_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="pipeline export"):
        build.gather(tmp_path / "nothing")


def test_rebuilding_the_same_dataset_gives_the_same_bytes(site, tmp_path):
    """What the CI drift guard rests on: the page is a function of the dataset alone.

    A build that embedded the wall clock would differ on every run, and the guard would
    then be unable to tell a stale page from a fresh one.
    """
    _, dataset = site
    first = build.build(tmp_path / "once", dataset_dir=dataset)
    second = build.build(tmp_path / "again", dataset_dir=dataset)
    # bytes, not text: read_text hides the line-ending difference this also has to rule out
    assert second.read_bytes() == first.read_bytes()
    assert b"\r\n" not in first.read_bytes()  # CI rebuilds on Linux and diffs the result


@pytest.mark.skipif(
    not (config.DATASET_DIR / config.MANIFEST_NAME).is_file(),
    reason="no published dataset in this checkout",
)
def test_committed_page_matches_the_committed_dataset(tmp_path):
    """The same check CI runs, available before the push rather than after it.

    Without it, drift is only ever discovered on the runner, where the developer cannot
    see which of their local numbers moved.
    """
    rebuilt = build.build(tmp_path / "rebuilt", dataset_dir=config.DATASET_DIR)
    published = config.PUBLISH_DIR / "index.html"
    assert rebuilt.read_bytes() == published.read_bytes(), (
        "docs/index.html is stale — run `python -m it_job_radar.pipeline site`"
    )


# --- Chart rendering ---------------------------------------------------------


def test_bar_chart_escapes_labels():
    svg = charts.bar_chart([charts.Bar(label="c++ & <script>", value=1)], "t")
    assert "<script>" not in svg
    assert "&amp;" in svg


def test_empty_chart_says_so_instead_of_rendering_nothing():
    assert "No data" in charts.bar_chart([], "t")
    assert "No disclosed salaries" in charts.range_chart([], "t")


def test_range_chart_survives_a_missing_interval():
    """A single-row stratum has no usable interval; it must still render."""
    svg = charts.range_chart(
        [charts.Range("junior", 8000, 11000, float("nan"), float("nan"), 1, muted=True)], "t"
    )
    assert "n=1" in svg and "nan" not in svg.lower()


def test_every_table_scrolls_inside_its_own_box(site):
    """A table is never narrower than its columns need, so `width: 100%` cannot rescue one
    whose contents will not wrap — it takes the page sideways instead.

    This page does not overflow at a 375px viewport today; the wrapper is preventive, and it is
    here because the figures come from a snapshot. A longer label or a wider number is a change
    to the data, not to the layout, and nothing else would notice. Three sibling projects had
    exactly this defect measured on them, all three with `overflow-x` already present on their
    charts and none of it on their tables.
    """
    _, dataset = site
    html = build.render(dataset)

    assert html.count("<table") == html.count('<div class="table-wrap">'), (
        "a table is published outside a scroll container"
    )
    assert re.search(r"\.table-wrap\s*\{[^}]*overflow-x:\s*auto", html), (
        "the wrapper is inert without the rule that makes it scroll"
    )
