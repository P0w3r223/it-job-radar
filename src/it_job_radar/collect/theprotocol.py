"""theprotocol.it collector: sitemap frame -> offer pages -> parsed offer dicts.

Network I/O (``fetch_*``) is separated from parsing (``parse_offer``, ``offer_id_from_url``
— both pure) so parsing is unit-testable without the network.

The offer id is carried in the URL (``...,oferta,<guid>`` — it equals ``offer.id`` in the
page's ``__NEXT_DATA__``), which is what makes the frame useful: one sitemap request
identifies every live offer without fetching a single offer page. Presence therefore
never needs sampling; only attributes do (ADR 0003).

Etiquette (see docs/research/data-sources.md): a browser User-Agent (the site serves a
stripped page otherwise), throttling between requests, a **bounded fetch budget** rather
than the whole base, and **no personal data** — only offer attributes are kept.

Offer data lives under ``props.pageProps.offer``; salary carries ``kindCode`` = ``gross``
(employment) or ``netto (+ VAT)`` (B2B), which must never be averaged together.
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
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_OFFER_LOC_RE = re.compile(r"<loc>\s*(https://theprotocol\.it/szczegoly/[^<\s]+)\s*</loc>")
_OFFER_ID_RE = re.compile(
    r",oferta,([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)

Entry = tuple[str, str]  # (offer_id, offer_url)


class TheProtocolError(RuntimeError):
    """Raised on unrecoverable collector errors."""


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})
    return session


def offer_id_from_url(url: str) -> str | None:
    """Extract the offer id from an offer URL (pure). None if the URL is not an offer.

    Verified against ``__NEXT_DATA__`` on offers spread across the sitemap: the trailing
    guid is the same id the page reports.
    """
    match = _OFFER_ID_RE.search(url or "")
    return match.group(1) if match else None


def fetch_sitemap_index(session: requests.Session | None = None) -> list[str]:
    """Return the child sitemap URLs listed in the published index.

    Reading the index rather than a hardcoded child keeps the collector correct if the
    source splits its offers across more files.
    """
    session = session or new_session()
    resp = session.get(config.TP_SITEMAP_INDEX_URL, timeout=config.REQUEST_TIMEOUT_S)
    resp.raise_for_status()
    children = _LOC_RE.findall(resp.text)
    if not children:
        raise TheProtocolError(f"no child sitemaps in {config.TP_SITEMAP_INDEX_URL}")
    return children


def fetch_frame(session: requests.Session | None = None) -> list[Entry]:
    """Observe the whole population: every currently listed ``(offer_id, offer_url)``.

    This is the cheap half of the collector — a handful of requests for complete presence
    data. Ids that do not parse are skipped rather than guessed at.
    """
    session = session or new_session()
    children = fetch_sitemap_index(session)
    frame: dict[str, str] = {}
    for child_url in children:
        resp = session.get(child_url, timeout=config.REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        for url in _OFFER_LOC_RE.findall(resp.text):
            offer_id = offer_id_from_url(url)
            if offer_id:
                frame[offer_id] = url
        time.sleep(config.REQUEST_DELAY_S)
    if not frame:
        raise TheProtocolError("sitemap frame is empty — the source layout likely changed")
    return sorted(frame.items())


def fetch_offer_html(url: str, session: requests.Session | None = None) -> str:
    """Fetch a single offer page's HTML."""
    session = session or new_session()
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


def fetch_offers(
    entries: list[Entry], session: requests.Session | None = None
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Fetch and parse the queued offers, throttled and PII-free.

    Returns the parsed offers and one ``(offer_id, fetch_state)`` per attempt, so the
    frame records what happened — including failures, which stay eligible for a retry
    instead of being written off after one bad response.
    """
    session = session or new_session()
    offers: list[dict] = []
    outcomes: list[tuple[str, str]] = []
    for offer_id, url in entries:
        state = config.FETCH_FAILED
        try:
            parsed = parse_offer(fetch_offer_html(url, session))
            if parsed:
                parsed["offer_url"] = url
                offers.append(parsed)
                state = config.FETCH_DONE
        except requests.RequestException:
            pass
        finally:
            outcomes.append((offer_id, state))
            # throttle on every iteration — including errors, so a 429/503 storm backs off
            time.sleep(config.REQUEST_DELAY_S)
    return offers, outcomes
