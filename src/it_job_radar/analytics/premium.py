"""What a technology is associated with in pay, once seniority and work mode are held level.

The naive version of this figure — median salary of vacancies listing Kubernetes against
the rest — measures seniority. Kubernetes appears in senior infrastructure roles, and the
gap it shows is mostly the gap between senior and junior. So the estimate here comes from
one regression of the log salary floor on seniority, work mode and a technology indicator
per technology, and each coefficient is read as "with the others held level".

Three properties this file is responsible for:

* **Log scale, reported as a percentage.** Salaries are multiplicative — a technology is
  worth "12% more", not "2 000 PLN more, whether the job pays 8 000 or 40 000".
* **An interval on every estimate, from robust standard errors.** Salary variance is not
  constant across seniority, and the textbook standard error assumes it is; HC1 does not.
  An interval that spans zero is reported as spanning zero rather than dropped, because a
  technology that turns out *not* to pay is a finding the page can make.
* **A floor on the sample per technology.** Below ``MIN_PREMIUM_N`` vacancies a coefficient
  is an anecdote with a confidence interval drawn around it.

What it cannot claim: causation. Nobody is paid more *because* the advert lists Terraform;
the technology travels with the kind of work, the size of the employer and the parts of the
market this sample can see. The page says so beside the figure.

Pure: a DataFrame in, value objects out. No dataset access, no clock, no plotting.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd

from it_job_radar import config

_SEPARATOR = "|"


@dataclass(frozen=True)
class Premium:
    """One technology's estimated association with pay, in percent."""

    technology: str
    percent: float
    ci_low: float
    ci_high: float
    n: int

    @property
    def distinguishable(self) -> bool:
        """False when the interval spans zero — the honest reading is "no measured gap"."""
        return self.ci_low > 0 or self.ci_high < 0


@dataclass(frozen=True)
class Fit:
    """The estimates and what they were measured on."""

    premiums: tuple[Premium, ...]
    vacancies: int
    controls: tuple[str, ...]

    @property
    def drawable(self) -> bool:
        return bool(self.premiums)


def _multi_hot(values: pd.Series, columns: list[str]) -> np.ndarray:
    """Indicator columns from pipe-joined lists — a vacancy can carry several of each."""
    sets = [set(_split(value)) for value in values]
    return np.array(
        [[1.0 if column in row else 0.0 for column in columns] for row in sets], dtype=float
    )


def _split(value) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    return [item for item in value.split(_SEPARATOR) if item]


def _counts(values: pd.Series) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        for item in set(_split(value)):
            counts[item] = counts.get(item, 0) + 1
    return counts


def _controls(values: pd.Series, min_n: int) -> list[str]:
    """Levels to model, minus the most common one — which becomes the reference.

    Keeping every level beside an intercept would make the design matrix singular whenever
    the levels partition the rows, and the reference has to be *some* level; the largest
    one is the least surprising thing to compare against.
    """
    counts = {name: count for name, count in _counts(values).items() if count >= min_n}
    if len(counts) < 2:
        return []
    reference = max(counts.items(), key=lambda item: (item[1], item[0]))[0]
    return sorted(name for name in counts if name != reference)


def _robust_errors(design: np.ndarray, residuals: np.ndarray, inverse: np.ndarray) -> np.ndarray:
    """HC1 standard errors: the sandwich, with the small-sample correction."""
    rows, columns = design.shape
    meat = design.T @ (design * (residuals**2)[:, None])
    covariance = inverse @ meat @ inverse * (rows / max(rows - columns, 1))
    return np.sqrt(np.clip(np.diag(covariance), 0.0, None))


def estimate(
    rows: pd.DataFrame,
    min_n: int = config.MIN_PREMIUM_N,
    limit: int = config.PREMIUM_LIMIT,
    confidence: float = config.BOOTSTRAP_CONFIDENCE,
    min_control_n: int = config.MIN_STRATUM_N,
) -> Fit:
    """Fit the model and return the technologies with the largest estimated premium."""
    if rows.empty:
        return Fit(premiums=(), vacancies=0, controls=())

    usable = rows[rows["monthly_floor"] > 0]
    technology_counts = {
        name: count for name, count in _counts(usable["technologies"]).items() if count >= min_n
    }
    if usable.empty or not technology_counts:
        return Fit(premiums=(), vacancies=int(len(usable)), controls=())

    technologies = sorted(technology_counts)
    seniorities = _controls(usable["seniority"], min_control_n)
    work_modes = _controls(usable["work_modes"], min_control_n)

    blocks = [
        np.ones((len(usable), 1)),
        _multi_hot(usable["seniority"], seniorities),
        _multi_hot(usable["work_modes"], work_modes),
        _multi_hot(usable["technologies"], technologies),
    ]
    design = np.hstack([block for block in blocks if block.size])
    outcome = np.log(usable["monthly_floor"].to_numpy(dtype=float))

    coefficients, *_ = np.linalg.lstsq(design, outcome, rcond=None)
    # pinv rather than inv: with a hundred indicators over a thousand rows, two technologies
    # that always appear together make the matrix singular, and a crash is not a finding.
    inverse = np.linalg.pinv(design.T @ design)
    errors = _robust_errors(design, outcome - design @ coefficients, inverse)

    offset = design.shape[1] - len(technologies)
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    premiums = [
        Premium(
            technology=technology,
            percent=(float(np.exp(coefficients[offset + index])) - 1) * 100,
            ci_low=(float(np.exp(coefficients[offset + index] - z * errors[offset + index])) - 1)
            * 100,
            ci_high=(float(np.exp(coefficients[offset + index] + z * errors[offset + index])) - 1)
            * 100,
            n=technology_counts[technology],
        )
        for index, technology in enumerate(technologies)
    ]
    # Largest effects, either direction, then read top to bottom as a forest plot.
    premiums.sort(key=lambda premium: (-abs(premium.percent), premium.technology))
    return Fit(
        premiums=tuple(sorted(premiums[:limit], key=lambda premium: -premium.percent)),
        vacancies=int(len(usable)),
        controls=tuple(seniorities + work_modes),
    )
