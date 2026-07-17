"""Aggregations over the offer database: tech trends, salary medians, Wrocław vs remote.

SQL does the joining/grouping; medians are computed in pandas (SQLite has no MEDIAN).
Salaries are always filtered by currency + kind, because B2B (net) and employment
(gross) must never be pooled.
"""

from __future__ import annotations

import pandas as pd

from it_job_radar import config


def top_technologies(
    conn, seniority: str | None = None, limit: int = 15, required_only: bool = True
) -> pd.DataFrame:
    """Most frequent technologies (optionally per seniority).

    ``required_only`` (default) counts only must-have technologies (``required = 1``);
    set False to include nice-to-haves. Counting both together over-weights optional
    skills, which distorts "what the market demands".
    """
    conditions: list[str] = []
    params: list = []
    if required_only:
        conditions.append("ot.required = 1")  # constant, not user input
    join = ""
    if seniority:
        join = "JOIN offer_seniority os ON ot.offer_id = os.offer_id"
        conditions.append("os.seniority = ?")
        params.append(seniority)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    query = (
        f"SELECT ot.technology AS technology, COUNT(DISTINCT ot.offer_id) AS offers "
        f"FROM offer_technologies ot {join} {where} "
        f"GROUP BY ot.technology ORDER BY offers DESC LIMIT ?"
    )
    return pd.read_sql_query(query, conn, params=tuple(params))


def _order_by_seniority(df: pd.DataFrame, column: str = "seniority") -> pd.DataFrame:
    rank = {s: i for i, s in enumerate(config.SENIORITY_ORDER)}
    return (
        df.assign(_rank=df[column].map(lambda s: rank.get(s, 99)))
        .sort_values("_rank")
        .drop(columns="_rank")
        .reset_index(drop=True)
    )


def salary_by_seniority(
    conn, kind: str = config.CONTRACT_B2B, currency: str = "PLN"
) -> pd.DataFrame:
    """Median monthly salary range per seniority for one contract kind + currency."""
    query = (
        "SELECT os.seniority AS seniority, sal.monthly_from AS mfrom, sal.monthly_to AS mto "
        "FROM offer_salaries sal JOIN offer_seniority os ON sal.offer_id = os.offer_id "
        "WHERE sal.currency = ? AND sal.kind = ? AND sal.monthly_from IS NOT NULL"
    )
    df = pd.read_sql_query(query, conn, params=(currency, kind))
    if df.empty:
        return df
    agg = df.groupby("seniority").agg(
        offers=("mfrom", "size"),
        median_from=("mfrom", "median"),
        median_to=("mto", "median"),
    ).reset_index()
    return _order_by_seniority(agg)


def wroclaw_vs_remote(
    conn, kind: str = config.CONTRACT_B2B, currency: str = "PLN"
) -> pd.DataFrame:
    """Compare offer counts and median salary: Wrocław offers vs remote offers."""
    wro_q = (
        "SELECT sal.monthly_from AS mfrom, sal.monthly_to AS mto "
        "FROM offer_salaries sal JOIN offer_locations ol ON sal.offer_id = ol.offer_id "
        "WHERE ol.city = ? AND sal.currency = ? AND sal.kind = ? AND sal.monthly_from IS NOT NULL"
    )
    rem_q = (
        "SELECT sal.monthly_from AS mfrom, sal.monthly_to AS mto "
        "FROM offer_salaries sal JOIN offer_work_modes wm ON sal.offer_id = wm.offer_id "
        "WHERE wm.work_mode = 'remote' AND sal.currency = ? AND sal.kind = ? "
        "AND sal.monthly_from IS NOT NULL"
    )
    wro = pd.read_sql_query(wro_q, conn, params=(config.FOCUS_CITY, currency, kind))
    rem = pd.read_sql_query(rem_q, conn, params=(currency, kind))
    return pd.DataFrame(
        {
            "group": [config.FOCUS_CITY, "remote"],
            "offers": [len(wro), len(rem)],
            "median_from": [wro["mfrom"].median() if len(wro) else None,
                            rem["mfrom"].median() if len(rem) else None],
            "median_to": [wro["mto"].median() if len(wro) else None,
                          rem["mto"].median() if len(rem) else None],
        }
    )


def work_mode_distribution(conn) -> pd.DataFrame:
    """Offer counts per work mode (remote/hybrid/office)."""
    query = (
        "SELECT work_mode, COUNT(DISTINCT offer_id) AS offers "
        "FROM offer_work_modes GROUP BY work_mode ORDER BY offers DESC"
    )
    return pd.read_sql_query(query, conn)
