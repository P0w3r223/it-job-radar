"""What moved between two comparable runs — and when nothing may be said yet.

The dated series records a technology's vacancy count per run. Turning that into a claim
about the market takes three refusals, and this module is where they live:

* **Counts are not comparable, shares are.** Every early count rose because the sample did.
  A share still needs a comparable denominator, which is what ``technology_movement.sql``
  filters for; here it is taken as given.
* **Two points are not a trend.** Below ``MIN_SERIES_POINTS`` comparable days the movement
  is not computed at all, and the caller is told how many days it has — the same rule the
  coverage chart draws by, for the same reason.
* **A technology absent from the first run has not moved.** It entered the *recorded* top
  thirty, which is a fact about our recording depth, not about hiring. Movement is measured
  only where both endpoints exist.

Pure: a DataFrame in, a value object out. Nothing here reads the dataset or the clock.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from it_job_radar import config


@dataclass(frozen=True)
class Move:
    """One technology's share on the first and last comparable day."""

    technology: str
    first_share: float
    last_share: float
    first_vacancies: int
    last_vacancies: int
    n_first: int
    n_last: int

    @property
    def delta(self) -> float:
        """Change in share, in share units — positive means a wider slice of the market."""
        return self.last_share - self.first_share


@dataclass(frozen=True)
class Comparison:
    """Every measurable move, plus what the comparison rests on.

    ``days`` is the comparable days found, in order. It is reported even when the
    comparison is refused: "two of the three runs needed" is the answer, and a reader given
    an empty panel with no count cannot tell a young series from a broken one.
    """

    days: tuple[str, ...]
    moves: tuple[Move, ...]

    @property
    def drawable(self) -> bool:
        return bool(self.moves)

    @property
    def first_day(self) -> str | None:
        return self.days[0] if self.days else None

    @property
    def last_day(self) -> str | None:
        return self.days[-1] if self.days else None


def compare(
    rows: pd.DataFrame,
    min_days: int = config.MIN_SERIES_POINTS,
    limit: int = config.MOVEMENT_LIMIT,
) -> Comparison:
    """Movement between the first and last comparable day, largest absolute change first.

    ``rows`` is the result of ``technology_movement``: one row per technology per
    comparable day, carrying that day's share and the vacancies behind it.
    """
    if rows.empty:
        return Comparison(days=(), moves=())

    days = tuple(sorted(str(day) for day in rows["observed_date"].unique()))
    if len(days) < min_days:
        return Comparison(days=days, moves=())

    first = rows[rows["observed_date"].astype(str) == days[0]].set_index("technology")
    last = rows[rows["observed_date"].astype(str) == days[-1]].set_index("technology")
    moves = [
        Move(
            technology=str(technology),
            first_share=float(first.at[technology, "share"]),
            last_share=float(last.at[technology, "share"]),
            first_vacancies=int(first.at[technology, "vacancies"]),
            last_vacancies=int(last.at[technology, "vacancies"]),
            n_first=int(first.at[technology, "analysed_vacancies"]),
            n_last=int(last.at[technology, "analysed_vacancies"]),
        )
        # Both endpoints, and in the order the first run ranked them, so that ties in the
        # sort below resolve the same way on every build — the page is committed, and a
        # rebuild that reshuffles equal bars would report drift that did not happen.
        for technology in first.index
        if technology in last.index
    ]
    moves.sort(key=lambda move: (-abs(move.delta), move.technology))
    return Comparison(days=days, moves=tuple(moves[:limit]))
