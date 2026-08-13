"""Normalization: technologies, seniority, work mode, currency, salary.

Raw offers carry noisy labels (``ReactJS`` vs ``React.js``, ``regular`` for mid, ``zł``
for PLN, hourly B2B vs monthly gross). Aggregating without normalizing first turns
signal into noise, so every analysis runs on normalized values.

Pure functions — no network, no DB.
"""

from __future__ import annotations

from dataclasses import dataclass

import yaml
from rapidfuzz import fuzz, process

from it_job_radar import config

RoleRules = tuple[tuple[str, tuple[str, ...]], ...]  # ordered (family, patterns)


@dataclass(frozen=True)
class Normalization:
    """The reference data normalization needs, loaded once per run."""

    tech_aliases: dict[str, str]
    role_rules: RoleRules


@dataclass(frozen=True)
class Technology:
    """A technology as the offer wrote it (``raw``) and as we resolved it (``name``).

    Both are kept because the alias dictionary is edited over time. Storing only the
    resolved name would make every dictionary improvement apply to future offers alone,
    and leave yesterday's ``ci / cd`` split from today's ``ci/cd`` for good.
    """

    raw: str
    name: str

_HOURS_PER_MONTH = 160  # ~20 working days x 8h, to convert hourly B2B to monthly
_FUZZY_THRESHOLD = 88

_CURRENCY_MAP = {
    "zł": "PLN", "zl": "PLN", "pln": "PLN",
    "€": "EUR", "eur": "EUR",
    "$": "USD", "usd": "USD",
    "£": "GBP", "gbp": "GBP",
}


def load_tech_aliases(path=config.TECH_ALIASES_PATH) -> dict[str, str]:
    """Load the alias dictionary as a flat ``alias(lowercase) -> canonical`` index."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    index: dict[str, str] = {}
    for canonical, aliases in raw.items():
        index[canonical.lower()] = canonical
        for alias in aliases or []:
            index[str(alias).lower()] = canonical
    return index


def load_role_families(path=config.ROLE_FAMILIES_PATH) -> RoleRules:
    """Load the ordered role-family rules. Order is the rule: first match wins."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return tuple(
        (entry["family"], tuple(str(p).lower() for p in entry.get("patterns", [])))
        for entry in raw
    )


def load_normalization(
    aliases_path=config.TECH_ALIASES_PATH, roles_path=config.ROLE_FAMILIES_PATH
) -> Normalization:
    """Load every reference table normalization needs — one file read per run."""
    return Normalization(
        tech_aliases=load_tech_aliases(aliases_path),
        role_rules=load_role_families(roles_path),
    )


def classify_role_family(title: str | None, rules: RoleRules) -> str:
    """Map an offer title to a role family (pure). ``other`` when nothing matches.

    Substring matching on the lowercased title, first rule wins. Deliberately a rule table
    rather than a model: the question is what the title *says*, the rules are auditable,
    and a wrong answer is fixed by editing one line of YAML.
    """
    text = f" {(title or '').lower()} "
    for family, patterns in rules:
        if any(pattern in text for pattern in patterns):
            return family
    return config.ROLE_FAMILY_OTHER


def normalize_technology(name: str, alias_index: dict[str, str], threshold: int = _FUZZY_THRESHOLD) -> str:
    """Map a raw technology name to its canonical form (exact alias → fuzzy → lowercased)."""
    key = (name or "").strip().lower()
    if not key:
        return ""
    if key in alias_index:
        return alias_index[key]
    match = process.extractOne(key, alias_index.keys(), scorer=fuzz.ratio)
    if match and match[1] >= threshold:
        return alias_index[match[0]]
    return key  # unknown technology — keep it, lowercased


def normalize_technologies(names, alias_index: dict[str, str]) -> list[Technology]:
    """Resolve raw technology names, deduplicated by canonical form and ordered by it.

    Deduplication is on the resolved name, so two spellings of one technology produce one
    row for the offer — the first spelling seen is the one kept as provenance.
    """
    resolved: dict[str, Technology] = {}
    for raw in names:
        text = (raw or "").strip()
        if not text:
            continue
        canonical = normalize_technology(text, alias_index)
        if canonical and canonical not in resolved:
            resolved[canonical] = Technology(raw=text, name=canonical)
    return [resolved[name] for name in sorted(resolved)]


def normalize_seniority(value: str | None) -> str | None:
    """Map a seniority label to a canonical level (Polish ``regular`` → mid)."""
    if not value:
        return None
    return config.SENIORITY_MAP.get(value.strip().lower(), value.strip().lower())


def normalize_work_mode(code: str | None) -> str | None:
    """Map a work-mode code to remote/hybrid/office/mobile."""
    if not code:
        return None
    return config.WORK_MODE_MAP.get(code.strip().lower(), code.strip().lower())


def normalize_currency(code: str | None) -> str | None:
    """Map a currency symbol/code to an ISO code (``zł`` → PLN)."""
    if not code:
        return None
    return _CURRENCY_MAP.get(code.strip().lower(), code.strip().upper())


def _classify_kind(kind_code: str | None) -> str | None:
    """B2B (net + VAT) vs employment (gross) — kept apart, never averaged together."""
    if not kind_code:
        return None
    k = kind_code.lower()
    if "net" in k or "vat" in k:
        return config.CONTRACT_B2B
    if "gross" in k or "brutto" in k:
        return config.CONTRACT_EMPLOYMENT
    return None


def _beyond_sanity(monthly: float | None) -> bool:
    """Whether a monthly equivalent is outside anything a job advert can plausibly mean."""
    return monthly is not None and monthly > config.SALARY_SANITY_MAX


def normalize_salary(contract: dict) -> dict:
    """Normalize one contract's salary: ISO currency, kind, and a monthly-equivalent range.

    Hourly rates (B2B) are scaled to a monthly figure; currencies are NOT converted
    (rates change) — analysis compares within a currency, PLN being the bulk.
    """
    unit = (contract.get("time_unit") or "").lower()
    if "godz" in unit or "hour" in unit:
        multiplier = _HOURS_PER_MONTH
    elif "mies" in unit or "month" in unit:
        multiplier = 1
    else:
        multiplier = None

    salary_from = contract.get("salary_from")
    salary_to = contract.get("salary_to")
    monthly_from = salary_from * multiplier if (salary_from and multiplier) else None
    monthly_to = salary_to * multiplier if (salary_to and multiplier) else None
    # A unit the employer cannot have meant. theprotocol's form takes the amount and the
    # unit as separate fields, so nothing stops a monthly figure being filed as hourly:
    # one offer in the 2026-08-13 sample published 14 500 PLN "godzinowo", which converts
    # to 2.3 M a month and would move a bootstrap interval on its own. We do not guess what
    # was meant — the amount and the unit stay exactly as published, and only the figure we
    # derived is withheld, because it is ours and we know it is false.
    # `quality.salary_monthly_withheld` counts these, so the refusal is visible.
    if _beyond_sanity(monthly_from) or _beyond_sanity(monthly_to):
        monthly_from = monthly_to = None
    return {
        "contract_type": contract.get("type"),
        "kind": _classify_kind(contract.get("kind")),
        "currency": normalize_currency(contract.get("currency")),
        "salary_from": salary_from,
        "salary_to": salary_to,
        "time_unit": unit or None,
        "monthly_from": monthly_from,
        "monthly_to": monthly_to,
    }


def normalize_offer(offer: dict, normalization: Normalization) -> dict:
    """Return a normalized copy of a parsed offer (technologies, seniority, salaries)."""
    alias_index = normalization.tech_aliases
    return {
        "role_family": classify_role_family(offer.get("title"), normalization.role_rules),
        "offer_id": offer.get("offer_id"),
        "title": offer.get("title"),
        "company": offer.get("company"),
        # Carried through explicitly: this dict is rebuilt field by field, and omitting
        # the URL here is what silently stored NULL for every offer collected before
        # 2026-08-11 (see docs/plan/0001_implementation-walkthrough.md, step 1.6).
        "offer_url": offer.get("offer_url"),
        "locations": offer.get("locations", []),
        "seniority": [s for s in (normalize_seniority(v) for v in offer.get("seniority", [])) if s],
        "work_modes": [m for m in (normalize_work_mode(v) for v in offer.get("work_modes", [])) if m],
        "technologies": {
            "expected": normalize_technologies(offer.get("tech_expected", []), alias_index),
            "optional": normalize_technologies(offer.get("tech_optional", []), alias_index),
        },
        "salaries": [normalize_salary(c) for c in offer.get("contracts", [])],
    }
