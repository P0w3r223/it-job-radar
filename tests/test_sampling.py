"""Tests for fetch-queue construction (pure, no network, no database).

These encode the guarantees ADR 0003 relies on: the inflow is prioritised so the panel
does not skew toward long-lived offers, the backlog draw is uniform and reproducible, and
the bounded budget is an error to exceed rather than a suggestion.
"""

import pytest

from it_job_radar import config, sampling


def _pool(prefix, count):
    return [(f"{prefix}{i}", f"https://x/{prefix}{i}") for i in range(count)]


def test_inflow_is_fetched_before_backlog():
    queue = sampling.build_queue(
        new_today=_pool("new", 10), backlog=_pool("old", 100), fetched_live=[],
        budget=20, seed=1,
    )
    assert len(queue.inflow) == 10  # every new offer, none left to expire unseen
    assert len(queue.backlog) == 10  # the rest of the budget drains the stock
    assert queue.inflow_capture_rate == 1.0


def test_capture_rate_reports_an_undersized_budget():
    queue = sampling.build_queue(
        new_today=_pool("new", 100), backlog=_pool("old", 100), fetched_live=[],
        budget=25, seed=1,
    )
    assert len(queue.inflow) == 25
    assert queue.backlog == []  # inflow comes first; nothing left for the stock
    assert queue.inflow_capture_rate == 0.25  # the signal that weighting is needed


def test_audit_quota_is_carved_out_of_the_budget():
    queue = sampling.build_queue(
        new_today=[], backlog=_pool("old", 500), fetched_live=_pool("done", 500),
        budget=100, seed=1, audit_share=0.02,
    )
    assert len(queue.audit) == 2
    assert len(queue.backlog) == 98
    assert len(queue) == 100


def test_audit_quota_is_capped_by_what_has_been_fetched():
    queue = sampling.build_queue(
        new_today=[], backlog=_pool("old", 50), fetched_live=_pool("done", 1),
        budget=100, seed=1,
    )
    assert len(queue.audit) == 1  # cannot audit more than we hold


def test_backlog_draw_is_seeded_and_reproducible():
    kwargs = dict(new_today=[], backlog=_pool("old", 500), fetched_live=[], budget=50)
    first = sampling.build_queue(**kwargs, seed=42).backlog
    again = sampling.build_queue(**kwargs, seed=42).backlog
    different = sampling.build_queue(**kwargs, seed=43).backlog

    assert first == again  # a recorded seed reproduces the run
    assert first != different  # a different seed covers different offers


def test_backlog_draw_is_not_a_prefix_of_sitemap_order():
    """Sitemap order is the source's; taking a prefix would inherit whatever it encodes."""
    backlog = _pool("old", 500)
    drawn = sampling.build_queue(
        new_today=[], backlog=backlog, fetched_live=[], budget=50, seed=7
    ).backlog
    assert drawn != backlog[:50]
    assert set(drawn) <= set(backlog)
    assert len(set(drawn)) == 50  # no duplicates


def test_queue_never_exceeds_the_budget():
    queue = sampling.build_queue(
        new_today=_pool("new", 400), backlog=_pool("old", 400),
        fetched_live=_pool("done", 400), budget=300, seed=1,
    )
    assert len(queue) == 300


def test_smaller_pools_than_budget_are_not_padded():
    queue = sampling.build_queue(
        new_today=_pool("new", 3), backlog=_pool("old", 2), fetched_live=[],
        budget=300, seed=1,
    )
    assert len(queue) == 5


@pytest.mark.parametrize("budget", [0, -1])
def test_nonpositive_budget_is_rejected(budget):
    with pytest.raises(ValueError):
        sampling.build_queue(new_today=[], backlog=[], fetched_live=[], budget=budget)


def test_budget_above_the_ethical_ceiling_is_rejected():
    # the bounded sample is a guardrail, not a tuning knob — never the whole base
    with pytest.raises(ValueError, match="MAX_FETCH_BUDGET"):
        sampling.build_queue(
            new_today=[], backlog=[], fetched_live=[],
            budget=config.MAX_FETCH_BUDGET + 1,
        )
