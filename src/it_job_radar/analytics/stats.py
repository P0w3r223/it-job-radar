"""Statistics applied to query results: medians with intervals, and thin strata flagged.

A median published without its ``n`` invites the reader to trust 19 offers as much as 300,
and the current snapshot has six seniority strata below the reporting threshold. So every
summary produced here carries three things the bare number hides: how many rows it rests
on, how wide the uncertainty is, and whether the stratum is too thin to carry a claim at
all.

The interval is a percentile bootstrap — no distributional assumption, which matters
because salary ranges are skewed and small strata are exactly where a normal approximation
misleads. ``suppressed`` is advice for the presentation layer, not a filter: the row stays
in the result, because dropping thin strata silently is its own kind of dishonesty.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from it_job_radar import config


def median_ci(
    values: np.ndarray | pd.Series,
    resamples: int = config.BOOTSTRAP_RESAMPLES,
    confidence: float = config.BOOTSTRAP_CONFIDENCE,
    seed: int | None = 0,
) -> tuple[float, float]:
    """Percentile bootstrap interval for a median. ``(nan, nan)`` for an empty input.

    The seed is fixed by default so a published figure is reproducible; pass ``None`` for
    an independent draw.
    """
    data = np.asarray(pd.Series(values).dropna(), dtype=float)
    if data.size == 0:
        return (float("nan"), float("nan"))
    if data.size == 1:
        return (float(data[0]), float(data[0]))

    rng = np.random.default_rng(seed)
    draws = rng.choice(data, size=(resamples, data.size), replace=True)
    medians = np.median(draws, axis=1)
    tail = (1 - confidence) / 2
    low, high = np.quantile(medians, [tail, 1 - tail])
    return (float(low), float(high))


def summarise_medians(
    rows: pd.DataFrame,
    group: str,
    value_columns: tuple[str, ...] = ("monthly_from", "monthly_to"),
    min_n: int = config.MIN_STRATUM_N,
    seed: int | None = 0,
    max_ci_width: float = config.MAX_CI_WIDTH_SHARE,
) -> pd.DataFrame:
    """Median per group with ``n``, a bootstrap interval, and a suppression flag.

    Returns one row per group with ``median_<col>``, ``ci_low_<col>``, ``ci_high_<col>``
    for each value column, plus ``n`` and ``suppressed``.

    A figure is marked when *either* test fails, because each catches what the other
    misses. Counting alone marked the wrong strata: junior B2B passed `min_n` with 33 rows
    and an interval 43% as wide as its own median, while `head` was marked at n=2 despite an
    interval 7% wide — narrow because two points cannot disagree, which is degeneracy rather
    than precision. So the width test cannot replace the count either, and both stay.
    """
    if rows.empty:
        columns = [group, "n", "suppressed"] + [
            f"{prefix}_{column}"
            for column in value_columns
            for prefix in ("median", "ci_low", "ci_high")
        ]
        return pd.DataFrame(columns=columns)

    summaries = []
    for key, chunk in rows.groupby(group, dropna=False):
        summary = {group: key, "n": len(chunk)}
        for column in value_columns:
            values = chunk[column].dropna()
            low, high = median_ci(values, seed=seed)
            summary[f"median_{column}"] = float(values.median()) if len(values) else float("nan")
            summary[f"ci_low_{column}"] = low
            summary[f"ci_high_{column}"] = high
        summary["suppressed"] = len(chunk) < min_n or _too_wide(
            summary, value_columns, max_ci_width
        )
        summaries.append(summary)
    return pd.DataFrame(summaries)


def _too_wide(summary: dict, value_columns: tuple[str, ...], limit: float) -> bool:
    """Whether any published bound rests on an interval too wide to read as a figure.

    Relative to the median, so the test means the same thing at every salary level: a
    2000 PLN spread is precision at 20 000 and noise at 6000. A median of zero or NaN
    cannot be judged this way and is left to the count test.
    """
    for column in value_columns:
        median = summary.get(f"median_{column}")
        low, high = summary.get(f"ci_low_{column}"), summary.get(f"ci_high_{column}")
        if median is None or low is None or high is None:
            continue
        if not median or median != median:  # zero, or NaN (which compares unequal to itself)
            continue
        if (high - low) / median > limit:
            return True
    return False


def order_by_seniority(frame: pd.DataFrame, column: str = "seniority") -> pd.DataFrame:
    """Sort by the configured seniority ladder rather than alphabetically or by count."""
    rank = {level: index for index, level in enumerate(config.SENIORITY_ORDER)}
    return (
        frame.assign(_rank=frame[column].map(lambda level: rank.get(level, len(rank))))
        .sort_values(["_rank", column])
        .drop(columns="_rank")
        .reset_index(drop=True)
    )
