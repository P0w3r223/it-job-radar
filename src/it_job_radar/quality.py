"""Data quality: measured every run, stored dated, and published alongside the results.

Most analysis projects present findings and leave their trustworthiness implicit. Here the
trustworthiness is itself a product: how much of the market we hold, how much of it
discloses pay, how much of the technology vocabulary the alias dictionary actually
resolves, and whether any stratum is too thin to carry a claim.

Two halves:

- **Metrics** — descriptive numbers written to ``snapshot_stats``. They never fail a run;
  they are the instrument panel.
- **The contract** — rules the data must satisfy before anything is published. Each rule
  is written as the condition that is *wrong*, so a violation reports the offending table,
  rule and row count rather than a bare failure.

``alias_coverage`` closes a loop: it names the technology strings the dictionary missed,
ranked by frequency, which is exactly the list that should go into ``tech_aliases.yaml``.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

import yaml

from it_job_radar import config, normalize


class ContractError(RuntimeError):
    """Raised when the data violates the published contract."""


@dataclass(frozen=True)
class Metric:
    """One measured number, with optional context for the report."""

    value: float
    detail: str | None = None


@dataclass(frozen=True)
class AliasCoverage:
    """How much of the raw technology vocabulary the alias dictionary resolved."""

    total: int
    matched: int
    unmatched: Counter = field(default_factory=Counter)

    @property
    def rate(self) -> float:
        return self.matched / self.total if self.total else 1.0

    def top_unmatched(self, limit: int = 20) -> list[tuple[str, int]]:
        return self.unmatched.most_common(limit)


def alias_coverage(raw_offers: list[dict], alias_index: dict[str, str]) -> AliasCoverage:
    """Measure alias-dictionary coverage over the raw technology names of a run.

    A name counts as matched when the dictionary resolved it — exactly or fuzzily. An
    unmatched name still reaches the database (lowercased), so this is not an error rate;
    it is the share of the vocabulary we have actually curated.
    """
    total = matched = 0
    unmatched: Counter = Counter()
    for offer in raw_offers:
        for name in [*offer.get("tech_expected", []), *offer.get("tech_optional", [])]:
            key = (name or "").strip().lower()
            if not key:
                continue
            total += 1
            canonical = normalize.normalize_technology(name, alias_index)
            # canonical == key can only happen on the lowercase fallback: every canonical
            # form is itself indexed, so a real hit would have found key in the index.
            if key in alias_index or canonical != key:
                matched += 1
            else:
                unmatched[key] += 1
    return AliasCoverage(total=total, matched=matched, unmatched=unmatched)


def stored_alias_coverage(
    conn: sqlite3.Connection, alias_index: dict[str, str]
) -> AliasCoverage:
    """Alias coverage over the technology rows held, not just the last run's batch.

    Reads the name each offer actually used, which the database keeps precisely so this
    question can be asked again after the dictionary changes. Measuring only the offers of
    the most recent fetch would report a number that moves with the batch rather than with
    the curation, and could never show an edit taking effect.

    The unit is one row per resolved technology per offer per required flag — not every
    mention the offer made. An offer writing both ``React.js`` and ``ReactJS`` contributes
    one row, so the second spelling never reaches the miss report. Rows seeded by migration
    v5 from an already-resolved name count as matched by construction; coverage is
    optimistic by that much until they are re-collected.
    """
    names = [
        row[0]
        for row in conn.execute(
            "SELECT raw_name FROM offer_technologies WHERE raw_name IS NOT NULL"
        )
    ]
    return alias_coverage([{"tech_expected": names}], alias_index)


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> float:
    row = conn.execute(sql, params).fetchone()
    return float(row[0] or 0)


def snapshot_metrics(
    conn: sqlite3.Connection, observed_date: str, alias_index: dict[str, str] | None = None
) -> dict[str, Metric]:
    """Quality metrics derived from the stored data (not from a particular run).

    Alias coverage belongs here rather than beside a fetch: the repair that moves it runs on
    every ``observe``, so measuring it only during ``collect`` would date each curation gain
    to the next collection, or lose it entirely when collections are sparse. Being here also
    carries it into the manifest, which is the only place its definition is recorded.

    ``alias_index`` defaults to the dictionary on disk and is injectable so a test can
    measure against a known vocabulary.
    """
    aliases = alias_index if alias_index is not None else normalize.load_tech_aliases()
    offers = _scalar(conn, "SELECT COUNT(*) FROM offers")
    salary_rows = _scalar(conn, "SELECT COUNT(*) FROM offer_salaries")
    with_salary = _scalar(
        conn,
        "SELECT COUNT(DISTINCT offer_id) FROM offer_salaries WHERE monthly_from IS NOT NULL",
    )
    unknown_kind = _scalar(conn, "SELECT COUNT(*) FROM offer_salaries WHERE kind IS NULL")
    other_roles = _scalar(
        conn, "SELECT COUNT(*) FROM offers WHERE role_family = ?", (config.ROLE_FAMILY_OTHER,)
    )
    unclassified = _scalar(conn, "SELECT COUNT(*) FROM offers WHERE role_family IS NULL")

    thin = [
        (row[0], row[1])
        for row in conn.execute(
            "SELECT seniority, COUNT(DISTINCT offer_id) AS n FROM offer_seniority "
            "GROUP BY seniority HAVING n < ? ORDER BY n",
            (config.MIN_STRATUM_N,),
        )
    ]
    latest = conn.execute("SELECT MAX(collected_date) FROM offers").fetchone()[0]
    freshness = (date.fromisoformat(observed_date) - date.fromisoformat(latest)).days if latest else -1

    coverage = stored_alias_coverage(conn, aliases)
    unmatched = ", ".join(
        f"{name}x{count}" for name, count in coverage.top_unmatched(config.UNMATCHED_IN_DETAIL)
    )

    return {
        "salary_disclosure_rate": Metric(with_salary / offers if offers else 0.0),
        # Deliberately not `alias_coverage_rate`: that name carries a series measured over
        # one run's raw names, and continuing it under the same label would splice two
        # different measurements into one line on a future chart.
        "stored_alias_coverage_rate": Metric(coverage.rate, detail=unmatched or None),
        "salary_kind_unknown_share": Metric(unknown_kind / salary_rows if salary_rows else 0.0),
        "role_family_other_share": Metric(other_roles / offers if offers else 0.0),
        "role_family_unclassified": Metric(unclassified),
        "strata_below_min_n": Metric(
            len(thin),
            detail=", ".join(f"{level}={n}" for level, n in thin) or None,
        ),
        "freshness_days": Metric(freshness),
    }


# --- Contract ----------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    table: str
    rule: str
    rows: int

    def __str__(self) -> str:
        return f"{self.table}: {self.rule} ({self.rows} rows)"


def load_contract(path=config.CONTRACT_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _domain(name: str):
    """Resolve an ``allowed_from`` / ``max_from`` reference to a config constant."""
    value = getattr(config, name, None)
    if value is None:
        raise ContractError(f"contract references unknown config constant {name!r}")
    return value


def _column_checks(column: str, spec: dict) -> list[tuple[str, str, tuple]]:
    """Compile one column spec into ``(rule, violating SQL, params)`` triples."""
    checks: list[tuple[str, str, tuple]] = []
    nullable = spec.get("nullable", True)
    if not nullable:
        checks.append((f"{column} must not be null", f"{column} IS NULL", ()))
    if "allowed" in spec or "allowed_from" in spec:
        allowed = tuple(spec.get("allowed") or _domain(spec["allowed_from"]))
        placeholders = ", ".join("?" for _ in allowed)
        guard = f"{column} IS NOT NULL AND " if nullable else ""
        checks.append((
            f"{column} outside the allowed values",
            f"{guard}{column} NOT IN ({placeholders})",
            allowed,
        ))
    if "min" in spec:
        checks.append((
            f"{column} below the minimum",
            f"{column} IS NOT NULL AND {column} < ?",
            (spec["min"],),
        ))
    if "max" in spec or "max_from" in spec:
        maximum = spec["max"] if "max" in spec else _domain(spec["max_from"])
        checks.append((
            f"{column} above the maximum",
            f"{column} IS NOT NULL AND {column} > ?",
            (maximum,),
        ))
    return checks


def validate_contract(conn: sqlite3.Connection, contract: dict | None = None) -> list[Violation]:
    """Return every contract violation found, worst-populated first. Never raises."""
    contract = contract if contract is not None else load_contract()
    violations: list[Violation] = []
    for table, spec in (contract.get("tables") or {}).items():
        checks: list[tuple[str, str, tuple]] = []
        for column, column_spec in (spec.get("columns") or {}).items():
            checks.extend(_column_checks(column, column_spec))
        for rule in spec.get("rules") or []:
            checks.append((rule["name"], rule["violating"], ()))

        for name, violating, params in checks:
            # `violating` comes from our own contract file, never from user input.
            rows = _scalar(conn, f"SELECT COUNT(*) FROM {table} WHERE {violating}", params)
            if rows:
                violations.append(Violation(table=table, rule=name, rows=int(rows)))
    return sorted(violations, key=lambda v: v.rows, reverse=True)


def enforce_contract(conn: sqlite3.Connection, contract: dict | None = None) -> None:
    """Raise if the data violates the contract — the gate before anything is published."""
    violations = validate_contract(conn, contract)
    if violations:
        listed = "\n  ".join(str(v) for v in violations)
        raise ContractError(f"data contract violated:\n  {listed}")
