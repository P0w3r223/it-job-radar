"""Fetch-queue construction — pure, no network and no database.

Presence is already known for the whole population from the sitemap frame, so the fetch
budget buys only one thing: attributes of offers we have never fetched. The queue is
rebuilt every run from three pools, in priority order (ADR 0003):

1. **inflow** — ids that appeared in the frame today. Fetching all of them makes the
   collection a *census* of new offers, which is what keeps the panel free of length bias:
   short-lived offers are captured before they expire.
2. **backlog** — live ids never fetched, drawn uniformly at random with a recorded seed.
   These drain the stock that was already open when observation started.
3. **audit** — a small quota of already-fetched live ids, re-fetched to test the
   assumption that a posting's attributes do not change while it is open. The assumption
   is load-bearing (it is why we never re-fetch), so it is measured rather than trusted.

Whatever the budget does not reach stays in the frame and is reconsidered next run, so an
undersized budget delays coverage instead of losing it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from it_job_radar import config

Entry = tuple[str, str]  # (offer_id, offer_url)


@dataclass(frozen=True)
class FetchQueue:
    """What one run will fetch, kept split so each pool can be reported separately."""

    inflow: list[Entry]
    backlog: list[Entry]
    audit: list[Entry]
    inflow_available: int

    @property
    def entries(self) -> list[Entry]:
        return [*self.inflow, *self.backlog, *self.audit]

    @property
    def inflow_capture_rate(self) -> float:
        """Share of today's new offers this run will actually fetch.

        Below 1.0 the panel starts skewing toward long-lived offers (the inspection
        paradox), because short-lived ones expire before their turn comes. This is the
        signal to raise the budget — or to weight the estimates.
        """
        if not self.inflow_available:
            return 1.0
        return len(self.inflow) / self.inflow_available

    def __len__(self) -> int:
        return len(self.entries)


def _take(pool: list[Entry], count: int, rng: random.Random) -> list[Entry]:
    """Draw ``count`` entries uniformly at random — never the first N.

    Sitemap order is the source's, not ours; taking a prefix would inherit whatever it
    encodes (publication date, employer batching) as a sampling bias.
    """
    if count <= 0:
        return []
    if count >= len(pool):
        return list(pool)
    return rng.sample(pool, count)


def build_queue(
    *,
    new_today: list[Entry],
    backlog: list[Entry],
    fetched_live: list[Entry],
    budget: int = config.DEFAULT_FETCH_BUDGET,
    seed: int | None = None,
    audit_share: float = config.AUDIT_QUOTA_SHARE,
) -> FetchQueue:
    """Build one run's fetch queue from the frame pools.

    ``seed`` makes a run reproducible; it is recorded on the snapshot row.
    """
    if budget <= 0:
        raise ValueError(f"budget must be positive, got {budget}")
    if budget > config.MAX_FETCH_BUDGET:
        # The bounded sample is an ethical guardrail (EU database sui generis right), not
        # a performance setting — so exceeding it is an error, not a warning.
        raise ValueError(
            f"budget {budget} exceeds MAX_FETCH_BUDGET={config.MAX_FETCH_BUDGET}; "
            "the collector never pulls the whole base in one run"
        )

    rng = random.Random(seed)
    audit_slots = min(round(budget * audit_share), len(fetched_live))
    fetch_slots = budget - audit_slots

    inflow = _take(new_today, min(fetch_slots, len(new_today)), rng)
    leftover = fetch_slots - len(inflow)
    return FetchQueue(
        inflow=inflow,
        backlog=_take(backlog, leftover, rng),
        audit=_take(fetched_live, audit_slots, rng),
        inflow_available=len(new_today),
    )
