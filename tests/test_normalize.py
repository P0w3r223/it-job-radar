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


def test_normalize_salary_employment_gross_monthly():
    contract = {
        "type": "umowa o pracę", "salary_from": 15000, "salary_to": 20000,
        "currency": "zł", "kind": "gross", "time_unit": "miesięcznie",
    }
    result = normalize.normalize_salary(contract)
    assert result["kind"] == "employment"
    assert result["monthly_from"] == 15000
    assert result["monthly_to"] == 20000
