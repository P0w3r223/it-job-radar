"""Dated per-dimension metrics: the series every trend on the site will be drawn from.

``snapshot_stats`` records what one run measured about itself — how large the frame is, how
much of it we hold, how curated the dictionary is. None of that can answer "did Python's
share move" or "did senior B2B medians drift", because those numbers carry a dimension and
a sample size, and a table of scalars has room for neither.

The values here are measured with the **same named queries the page runs**, over the
Parquet dataset that was just published. Recomputing them against SQLite would be quicker
and would create a second definition of "top technologies" in a second dialect — precisely
the drift ``analytics/queries`` exists to prevent. A number in this table and the same
number on the page therefore cannot disagree; if they ever do, one of them is a bug rather
than a difference of method.

Every point carries ``n``, and what ``n`` means is a per-metric decision rather than a
convention: for a count it is the population the count is a fraction of, for a median it is
how many salaries stand behind it. Getting that wrong would publish a share against the
wrong denominator, so each metric states which one it uses instead of leaving it implied.

Metric names carry the population they were measured over, and change when it does. The
`*_offers` series stopped on 2026-08-13 and `*_vacancies` began beside it: counting moved
from adverts to jobs, and continuing one line through that change would splice two different
measurements into a trend nobody measured. Same reason `alias_coverage_rate` became
`stored_alias_coverage_rate`.

The series begins at the first export that runs this code. Past runs cannot be backfilled:
the dataset holds the current state of the market, not a record of every earlier view of
it, so a point not measured on the day is a point lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from it_job_radar import config
from it_job_radar.analytics import engine, stats

# What a metric's `n` counts.
DATASET = "dataset"  # every offer whose attributes we hold — the value is a share of it
GROUP = "group"  # the rows this query returned — the value is a share of its own total

# Both bounds of a salary range are kept. Publishing only the floor would show a market
# moving whenever the ceiling moved alone, and the two do move apart.
_SALARY_BOUNDS = ("from", "to")


@dataclass(frozen=True)
class Count:
    """One counting metric: a named query, the column that varies, and its denominator."""

    metric: str
    query: str
    dimension: str
    denominator: str
    filters: dict = field(default_factory=dict)


COUNTS = (
    # A technology's denominator is every analysed offer, not the sum over technologies:
    # one offer lists several, so that sum counts offers repeatedly and would make each
    # share smaller the wider the ranking gets.
    Count(
        config.TECHNOLOGY_SERIES, "top_technologies", "technology", DATASET,
        {"limit": config.HISTORY_TECHNOLOGY_LIMIT},
    ),
    Count("role_family_vacancies", "role_family_distribution", "role_family", DATASET),
    # The page's headline claim, tracked as a series so it can be watched changing rather
    # than only asserted about the current snapshot. Role families partition the offers
    # they describe, so here the query's own total is the right denominator.
    Count(
        f"{config.HEADLINE_SENIORITY}_role_family_vacancies",
        "role_family_distribution", "role_family", GROUP,
        {"seniority": config.HEADLINE_SENIORITY},
    ),
    Count("stratum_vacancies", "stratum_sizes", "seniority", DATASET),
    Count("work_mode_vacancies", "work_mode_distribution", "work_mode", DATASET),
)


def _count_rows(spec: Count, connection, offer_count: int) -> list[tuple]:
    frame = engine.run(spec.query, connection=connection, **spec.filters)
    if frame.empty:
        return []
    n = offer_count if spec.denominator == DATASET else int(frame["offers"].sum())
    if n <= 0:
        return []
    return [
        (spec.metric, str(row[spec.dimension]), float(row["offers"]), n)
        for _, row in frame.iterrows()
    ]


def _vacancy_count(connection) -> int:
    """Distinct live jobs — the denominator every share is taken of.

    Live, because the numerators are: a share of an archive against a market denominator
    would shrink every published figure as offers left the frame.
    """
    frame = connection.execute(
        "SELECT COUNT(DISTINCT COALESCE(o.vacancy_id, o.offer_id)) FROM offers o JOIN sitemap_offers f ON f.offer_id = o.offer_id AND f.last_seen = (SELECT MAX(last_seen) FROM sitemap_offers)"
    ).fetchdf()
    return int(frame.iloc[0, 0])


def _median_rows(connection) -> list[tuple]:
    """Median salary per seniority, per contract kind — B2B and employment never pooled.

    Routed through ``stats.summarise_medians`` rather than a plain ``median()`` so the
    stored point is the same number the page prints, computed by the same code. The
    bootstrap interval it also produces is deliberately not stored: a trend line is drawn
    through the point estimate, and keeping the interval would double the rows to carry a
    figure recomputed for the current snapshot anyway.
    """
    rows: list[tuple] = []
    for kind in config.CONTRACT_KINDS:
        summary = stats.summarise_medians(
            engine.run("salary_rows", connection=connection, kind=kind), "seniority"
        )
        for _, row in summary.iterrows():
            n = int(row["n"])
            if n <= 0:
                continue
            for bound in _SALARY_BOUNDS:
                value = row[f"median_monthly_{bound}"]
                if pd.isna(value):
                    continue  # a stratum can disclose a floor and no ceiling
                rows.append(
                    (f"vacancy_salary_median_{bound}_{kind}", str(row["seniority"]), float(value), n)
                )
    return rows


def measure(dataset_dir=None, connection=None) -> list[tuple]:
    """Every dated metric for the published dataset, as ``(metric, dimension, value, n)``.

    The denominator for dataset-wide metrics is the number of *vacancies*, counted here
    from the same dataset the numerators come from. It used to be the advert count handed
    in by the publisher; once the numerators became vacancy counts, that would have divided
    jobs by adverts and quietly shrunk every published share by a third.

    Pass ``connection`` to reuse an open dataset; otherwise one is opened and closed here.
    Rows come back ordered, so what reaches the database — and the Parquet beside it — does
    not depend on the order the queries happened to run in.
    """
    own_connection = connection is None
    connection = connection or engine.connect(dataset_dir)
    try:
        vacancy_count = _vacancy_count(connection)
        rows = [row for spec in COUNTS for row in _count_rows(spec, connection, vacancy_count)]
        rows.extend(_median_rows(connection))
    finally:
        if own_connection:
            connection.close()
    return sorted(rows, key=lambda row: (row[0], row[1]))
