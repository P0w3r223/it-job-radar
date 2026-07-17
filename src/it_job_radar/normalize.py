"""Normalization: technologies, seniority, work mode, currency, salary.

Raw offers carry noisy labels (``ReactJS`` vs ``React.js``, ``regular`` for mid, ``zł``
for PLN, hourly B2B vs monthly gross). Aggregating without normalizing first turns
signal into noise, so every analysis runs on normalized values.

Pure functions — no network, no DB.
"""

from __future__ import annotations

import yaml
from rapidfuzz import fuzz, process

from it_job_radar import config

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
    return {
        "contract_type": contract.get("type"),
        "kind": _classify_kind(contract.get("kind")),
        "currency": normalize_currency(contract.get("currency")),
        "salary_from": salary_from,
        "salary_to": salary_to,
        "time_unit": unit or None,
        "monthly_from": salary_from * multiplier if (salary_from and multiplier) else None,
        "monthly_to": salary_to * multiplier if (salary_to and multiplier) else None,
    }


def normalize_offer(offer: dict, alias_index: dict[str, str]) -> dict:
    """Return a normalized copy of a parsed offer (technologies, seniority, salaries)."""
    return {
        "offer_id": offer.get("offer_id"),
        "title": offer.get("title"),
        "company": offer.get("company"),
        "cities": offer.get("cities", []),
        "regions": offer.get("regions", []),
        "seniority": [s for s in (normalize_seniority(v) for v in offer.get("seniority", [])) if s],
        "work_modes": [m for m in (normalize_work_mode(v) for v in offer.get("work_modes", [])) if m],
        "technologies": {
            "expected": sorted({normalize_technology(t, alias_index) for t in offer.get("tech_expected", []) if t}),
            "optional": sorted({normalize_technology(t, alias_index) for t in offer.get("tech_optional", []) if t}),
        },
        "salaries": [normalize_salary(c) for c in offer.get("contracts", [])],
    }
