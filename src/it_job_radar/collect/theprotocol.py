"""theprotocol.it collector: sitemap -> offer pages -> parsed offer dicts.

Network I/O (``fetch_*``, ``collect_offers``) is separated from parsing
(``parse_offer``, pure) so parsing is unit-testable without the network.

Etiquette (see docs/research/data-sources.md): a browser User-Agent (the site serves a
stripped page otherwise), throttling between requests, a **bounded, spread sample**
rather than the whole base, and **no personal data** — only offer attributes are kept.

Offer data lives in the page's ``__NEXT_DATA__`` JSON under
``props.pageProps.offer``; salary carries ``kindCode`` = ``gross`` (employment) or
``netto (+ VAT)`` (B2B), which must never be averaged together.
"""

from __future__ import annotations

import json
import re
import time

import requests

from it_job_radar import config

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL
)
_OFFER_LOC_RE = re.compile(r"<loc>(https://theprotocol\.it/szczegoly/[^<]+)</loc>")


class TheProtocolError(RuntimeError):
    """Raised on unrecoverable collector errors."""


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})
    return session


def fetch_sitemap_urls(session: requests.Session | None = None) -> list[str]:
    """Return all current offer URLs from the published sitemap."""
    session = session or _session()
    resp = session.get(config.TP_SITEMAP_URL, timeout=config.REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return _OFFER_LOC_RE.findall(resp.text)


def fetch_offer_html(url: str, session: requests.Session | None = None) -> str:
    """Fetch a single offer page's HTML."""
    session = session or _session()
    resp = session.get(url, timeout=config.REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    return resp.text


def _extract_next_data(html: str) -> dict | None:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _parse_contract(contract: dict) -> dict:
    salary = contract.get("salary")
    salary = salary if isinstance(salary, dict) else {}
    time_unit = salary.get("timeUnit") or {}
    return {
        "type": contract.get("name"),
        "salary_from": salary.get("from"),
        "salary_to": salary.get("to"),
        "currency": salary.get("currencyCode"),
        "kind": salary.get("kindCode"),  # "gross" (UoP) / "netto (+ VAT)" (B2B)
        "time_unit": time_unit.get("longForm"),
    }


def parse_offer(html: str) -> dict | None:
    """Extract a PII-free offer dict from offer-page HTML (pure). None if invalid.

    Kept fields: id, title, company name, cities/regions, seniority, work modes,
    contracts (with salary), and expected/optional technologies. The ``applying`` block
    (recruiter URLs, personal-data clauses) is deliberately ignored.
    """
    data = _extract_next_data(html)
    if not data:
        return None
    offer = data.get("props", {}).get("pageProps", {}).get("offer")
    if not isinstance(offer, dict) or not offer.get("id"):
        return None  # no id -> would break the upsert primary key / idempotency

    attrs = offer.get("attributes", {})
    employment = attrs.get("employment", {})
    workplaces = attrs.get("workplaces") or []
    technologies = offer.get("technologies") or {}

    return {
        "offer_id": offer.get("id"),
        "title": (attrs.get("title") or {}).get("value"),
        "company": (attrs.get("employer") or {}).get("name"),
        # keep city+region paired per workplace (parallel lists would misalign)
        "locations": [
            {"city": w.get("city"), "region": w.get("region")}
            for w in workplaces if w.get("city")
        ],
        "seniority": list(employment.get("positionLevelIds") or []),
        "work_modes": [
            w.get("code") for w in employment.get("detailedWorkModes") or [] if w.get("code")
        ],
        "contracts": [_parse_contract(c) for c in employment.get("typesOfContracts") or []],
        "tech_expected": [
            t.get("name") for t in technologies.get("expected") or [] if t.get("name")
        ],
        "tech_optional": [
            t.get("name") for t in technologies.get("optional") or [] if t.get("name")
        ],
    }


def _spread_sample(urls: list[str], sample_size: int) -> list[str]:
    """Take an evenly spread slice across the sitemap (offers appear ordered)."""
    if sample_size >= len(urls):
        return urls
    step = max(1, len(urls) // sample_size)
    return urls[::step][:sample_size]


def collect_offers(
    sample_size: int = config.DEFAULT_SAMPLE_SIZE,
    session: requests.Session | None = None,
) -> list[dict]:
    """Collect a bounded, spread sample of parsed offers, throttled and PII-free."""
    if sample_size <= 0:
        raise ValueError(
            f"sample_size must be positive (never the whole base), got {sample_size}"
        )
    session = session or _session()
    urls = _spread_sample(fetch_sitemap_urls(session), sample_size)

    offers: list[dict] = []
    for url in urls:
        try:
            html = fetch_offer_html(url, session)
            parsed = parse_offer(html)
            if parsed:
                parsed["offer_url"] = url
                offers.append(parsed)
        except requests.RequestException:
            continue
        finally:
            # throttle on every iteration — including errors, so a 429/503 storm backs off
            time.sleep(config.REQUEST_DELAY_S)
    skipped = len(urls) - len(offers)
    print(f"[collect] {len(urls)} urls -> {len(offers)} parsed, {skipped} skipped")
    return offers
