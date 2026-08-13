"""Tests for normalization (technologies, seniority, currency, salary)."""

import pytest

from it_job_radar import normalize


@pytest.fixture(scope="module")
def idx():
    return normalize.load_tech_aliases()


def test_normalize_technology_aliases(idx):
    assert normalize.normalize_technology("ReactJS", idx) == "react"
    assert normalize.normalize_technology("React.js", idx) == "react"
    assert normalize.normalize_technology("react", idx) == "react"
    assert normalize.normalize_technology("Node.js", idx) == "node"
    assert normalize.normalize_technology("K8s", idx) == "kubernetes"


def test_normalize_technology_fuzzy(idx):
    assert normalize.normalize_technology("Postgre", idx) == "postgresql"


def test_normalize_technology_unknown_kept(idx):
    assert normalize.normalize_technology("SomeNicheLangX", idx) == "somenichelangx"


def test_normalize_technologies_keeps_the_raw_name(idx):
    resolved = normalize.normalize_technologies(["ReactJS", "K8s"], idx)
    # ordered by the resolved name, so the row order does not depend on how the offer listed them
    assert [(t.raw, t.name) for t in resolved] == [("K8s", "kubernetes"), ("ReactJS", "react")]


def test_normalize_technologies_dedupes_on_the_resolved_name(idx):
    """Two spellings of one technology are one row for the offer, not two."""
    resolved = normalize.normalize_technologies(["React.js", "ReactJS", "  ", None], idx)
    assert [t.name for t in resolved] == ["react"]
    assert resolved[0].raw == "React.js"  # the first spelling seen is the one recorded


def test_normalize_seniority_polish_quirks():
    assert normalize.normalize_seniority("regular") == "mid"  # PL quirk
    assert normalize.normalize_seniority("młodszy") == "junior"
    assert normalize.normalize_seniority("senior") == "senior"
    assert normalize.normalize_seniority(None) is None


def test_normalize_currency():
    assert normalize.normalize_currency("zł") == "PLN"
    assert normalize.normalize_currency("€") == "EUR"
    assert normalize.normalize_currency(None) is None


def test_normalize_salary_b2b_hourly_scaled_to_monthly():
    contract = {
        "type": "kontrakt B2B", "salary_from": 100, "salary_to": 150,
        "currency": "zł", "kind": "netto (+ VAT)", "time_unit": "godzinowo",
    }
    result = normalize.normalize_salary(contract)
    assert result["kind"] == "b2b"
    assert result["currency"] == "PLN"
    assert result["monthly_from"] == 100 * 160
    assert result["monthly_to"] == 150 * 160


def test_an_impossible_monthly_equivalent_is_withheld_not_guessed():
    """A real offer filed 14 500 PLN as an hourly B2B rate — 2.3 M a month once converted.

    The reported amount and unit are the source's statement and stay untouched; only the
    figure we derived is withdrawn, because publishing it would move a median on its own
    and reinterpreting it as monthly would be us inventing what the employer meant.
    """
    contract = {
        "type": "kontrakt B2B", "salary_from": 14500, "salary_to": 15500,
        "currency": "zł", "kind": "netto (+ VAT)", "time_unit": "godzinowo",
    }
    result = normalize.normalize_salary(contract)
    assert result["salary_from"] == 14500
    assert result["time_unit"] == "godzinowo"
    assert result["monthly_from"] is None
    assert result["monthly_to"] is None


def test_a_high_but_possible_rate_survives():
    """The guard rejects the impossible, not the well-paid: 300 PLN/h is a real rate."""
    contract = {
        "type": "kontrakt B2B", "salary_from": 300, "salary_to": 400,
        "currency": "zł", "kind": "netto (+ VAT)", "time_unit": "godzinowo",
    }
    result = normalize.normalize_salary(contract)
    assert result["monthly_from"] == 300 * 160
    assert result["monthly_to"] == 400 * 160


def test_normalize_salary_employment_gross_monthly():
    contract = {
        "type": "umowa o pracę", "salary_from": 15000, "salary_to": 20000,
        "currency": "zł", "kind": "gross", "time_unit": "miesięcznie",
    }
    result = normalize.normalize_salary(contract)
    assert result["kind"] == "employment"
    assert result["monthly_from"] == 15000
    assert result["monthly_to"] == 20000


def test_normalize_offer_keeps_the_url(idx):
    """Regression: the rebuilt dict silently dropped offer_url, storing NULL for every
    offer collected before 2026-08-11."""
    raw = {
        "offer_id": "a1", "title": "Backend", "company": "ACME",
        "offer_url": "https://theprotocol.it/szczegoly/praca/x,oferta,a1",
        "locations": [], "seniority": ["regular"], "work_modes": ["remote"],
        "tech_expected": ["ReactJS"], "tech_optional": [], "contracts": [],
    }
    context = normalize.Normalization(tech_aliases=idx, role_rules=())
    normalized = normalize.normalize_offer(raw, context)
    assert normalized["offer_url"] == raw["offer_url"]
    assert normalized["seniority"] == ["mid"]  # the Polish quirk still applies
