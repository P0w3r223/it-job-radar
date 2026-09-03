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


class AliasConflict(ValueError):
    """Raised when the dictionary would silently put one technology in two buckets."""


def load_tech_aliases(path=config.TECH_ALIASES_PATH) -> dict[str, str]:
    """Load the alias dictionary as a flat ``alias(lowercase) -> canonical`` index.

    The flattening is what makes validation necessary: two entries claiming the same name
    used to resolve by file order, silently. That happened — ``microsoft 365`` was both a
    canonical of its own and an alias of ``microsoft office``, so ``m365`` and ``ms office``
    landed in different buckets depending on which spelling an advert used. That is the
    ``ReactJS`` / ``React.js`` failure this dictionary exists to prevent, committed by the
    dictionary itself. At ~200 canonicals and a pass added every few hundred offers, the
    only durable fix is refusing to load a file that contains one.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    canonicals = {str(name).lower() for name in raw}
    index: dict[str, str] = {}
    for canonical, aliases in raw.items():
        index[canonical.lower()] = canonical
        for alias in aliases or []:
            alias = str(alias).lower()
            if alias in canonicals:
                raise AliasConflict(
                    f"{alias!r} is an alias of {canonical!r} and a canonical name of its own"
                )
            claimed = index.get(alias)
            if claimed is not None and claimed != canonical:
                raise AliasConflict(
                    f"{alias!r} is claimed by both {claimed!r} and {canonical!r}"
                )
            index[alias] = canonical
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


def vacancy_key(title: str | None, company: str | None) -> str | None:
    """The identity of the *job*, as opposed to the identity of the advert.

    One employer publishes a single role as one advert per city — 18 of them for the same
    Cloud Data Engineer, each with its own offer id, the same title, the same technologies
    and the same salary. Counted per advert, that employer casts eighteen votes in every
    demand ranking, and the bias grows with the sample rather than washing out.

    The key is deliberately literal: lowercased title and company with whitespace collapsed,
    nothing else. Stripping the gender markers this market appends ("(k/m)", "(f/m/x)")
    would merge adverts an employer chose to phrase differently, and any cleverer key would
    start merging genuinely separate openings — an error nobody could see afterwards. This
    one only ever merges adverts that are character-for-character the same job.
    """
    if not title or not company:
        return None  # nothing to group on; the advert stands alone
    return f"{' '.join(title.lower().split())}|{' '.join(company.lower().split())}"


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


def normalize_technology(
    name: str, alias_index: dict[str, str], threshold: int = _FUZZY_THRESHOLD
) -> str:
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


def _outside_sanity(monthly: float | None) -> bool:
    """Whether a monthly equivalent is outside anything a job advert can plausibly mean.

    Both bounds catch one mistake from its two sides: the source takes the amount and the
    unit as separate fields, so a monthly figure filed as hourly overshoots the ceiling and
    an hourly rate filed as monthly falls under the floor.
    """
    if monthly is None:
        return False
    return monthly > config.SALARY_SANITY_MAX or monthly < config.SALARY_SANITY_MIN


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
    # unit as separate fields, so nothing stops one being filed under the other: the
    # 2026-08-13 sample held 14 500 PLN "godzinowo" (2.3 M a month once converted) and, in
    # the other direction, eleven rows at 14-180 PLN "miesięcznie" — hourly rates that were
    # dragging five published medians down. We do not guess what was meant — the amount and
    # the unit stay exactly as published, and only the figure we derived is withheld,
    # because it is ours and we know it is false.
    # `quality.salary_monthly_withheld` counts these, so the refusal is visible.
    if _outside_sanity(monthly_from) or _outside_sanity(monthly_to):
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
        # Derived on the way in as well as re-derived on every observation. Without it here,
        # offers from a fresh collect would reach `export` with no key at all and be counted
        # one vote each until the next `observe` happened to repair them.
        "vacancy_key": vacancy_key(offer.get("title"), offer.get("company")),
        "offer_id": offer.get("offer_id"),
        "title": offer.get("title"),
        "company": offer.get("company"),
        # Carried through explicitly: this dict is rebuilt field by field, and omitting
        # the URL here is what silently stored NULL for every offer collected before
        # 2026-08-11 (see docs/plan/0001_implementation-walkthrough.md, step 1.6).
        "offer_url": offer.get("offer_url"),
        "locations": offer.get("locations", []),
        "seniority": [s for s in (normalize_seniority(v) for v in offer.get("seniority", [])) if s],
        "work_modes": [
            m for m in (normalize_work_mode(v) for v in offer.get("work_modes", [])) if m
        ],
        "technologies": {
            "expected": normalize_technologies(offer.get("tech_expected", []), alias_index),
            "optional": normalize_technologies(offer.get("tech_optional", []), alias_index),
        },
        "salaries": [normalize_salary(c) for c in offer.get("contracts", [])],
    }
