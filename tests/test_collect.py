"""Tests for the theprotocol parser (pure, no network)."""

import pytest

from it_job_radar.collect import theprotocol

SAMPLE_HTML = """
<html><head>
<script id="__NEXT_DATA__" type="application/json">
{"props":{"pageProps":{"offer":{
  "id":"abc-123",
  "attributes":{
    "title":{"value":"Backend Developer"},
    "employer":{"name":"ACME"},
    "workplaces":[{"city":"Wrocław","region":"dolnośląskie"}],
    "employment":{
      "positionLevelIds":["mid"],
      "detailedWorkModes":[{"code":"remote"}],
      "typesOfContracts":[
        {"name":"kontrakt B2B","salary":{"from":100,"to":150,"currencyCode":"zł",
          "kindCode":"netto (+ VAT)","timeUnit":{"longForm":"godzinowo"}}},
        {"name":"umowa o pracę","salary":null}
      ]},
    "applying":{"referenceNumber":"SECRET-PII"}
  },
  "technologies":{"expected":[{"name":"Python"}],"optional":[{"name":"Docker"}]}
}}}}
</script>
</head></html>
"""


def test_parse_offer_extracts_pii_free_fields():
    offer = theprotocol.parse_offer(SAMPLE_HTML)
    assert offer["offer_id"] == "abc-123"
    assert offer["title"] == "Backend Developer"
    assert offer["company"] == "ACME"
    assert offer["locations"] == [{"city": "Wrocław", "region": "dolnośląskie"}]
    assert offer["seniority"] == ["mid"]
    assert offer["work_modes"] == ["remote"]
    assert offer["tech_expected"] == ["Python"]
    assert offer["tech_optional"] == ["Docker"]
    # no personal data leaked from the `applying` block
    assert "SECRET-PII" not in str(offer)


def test_parse_offer_contracts_carry_salary_kind():
    offer = theprotocol.parse_offer(SAMPLE_HTML)
    b2b = offer["contracts"][0]
    assert b2b["salary_from"] == 100
    assert b2b["salary_to"] == 150
    assert b2b["currency"] == "zł"
    assert b2b["kind"] == "netto (+ VAT)"
    assert b2b["time_unit"] == "godzinowo"
    # a contract without salary keeps None fields, not a crash
    assert offer["contracts"][1]["salary_from"] is None


def test_parse_offer_invalid_returns_none():
    assert theprotocol.parse_offer("<html>no next data</html>") is None
    assert theprotocol.parse_offer('<script id="__NEXT_DATA__" type="x">{"props":{}}</script>') is None


def test_parse_offer_without_id_returns_none():
    html = SAMPLE_HTML.replace('"id":"abc-123",', "")
    assert theprotocol.parse_offer(html) is None  # no id -> would break the PK


def test_collect_offers_rejects_nonpositive_sample():
    with pytest.raises(ValueError):
        theprotocol.collect_offers(sample_size=0)  # must never pull the whole base


def test_spread_sample_is_bounded_and_spread():
    urls = [f"u{i}" for i in range(1000)]
    sample = theprotocol._spread_sample(urls, 10)
    assert len(sample) == 10
    assert sample[0] == "u0"
    assert sample[1] != "u1"  # spread, not the first 10
