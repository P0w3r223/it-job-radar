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


OFFER_URL = (
    "https://theprotocol.it/szczegoly/praca/java-developer-krakow"
    ",oferta,f7690000-cabe-56d1-0371-08ded6ad4939"
)


def test_offer_id_is_readable_from_the_url():
    """The whole frame design rests on this: identity without fetching the page."""
    assert theprotocol.offer_id_from_url(OFFER_URL) == "f7690000-cabe-56d1-0371-08ded6ad4939"


@pytest.mark.parametrize(
    "url",
    ["", "https://theprotocol.it/szczegoly/praca/java-developer", "not a url",
     "https://theprotocol.it/szczegoly/praca/x,oferta,not-a-guid"],
)
def test_offer_id_from_url_rejects_non_offers(url):
    assert theprotocol.offer_id_from_url(url) is None


class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


class _FakeSession:
    """Serves canned XML per URL and records what was requested."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url, timeout=None):
        self.requested.append(url)
        return _FakeResponse(self.pages[url])


def _sitemap(*urls):
    locs = "".join(f"<loc>{u}</loc>" for u in urls)
    return f'<?xml version="1.0"?><urlset>{locs}</urlset>'


def test_sitemap_index_is_read_rather_than_hardcoded(monkeypatch):
    monkeypatch.setattr(theprotocol.time, "sleep", lambda _: None)
    session = _FakeSession({
        theprotocol.config.TP_SITEMAP_INDEX_URL: _sitemap("https://x/one.xml", "https://x/two.xml"),
    })
    assert theprotocol.fetch_sitemap_index(session) == ["https://x/one.xml", "https://x/two.xml"]


def test_fetch_frame_unions_children_and_drops_unparsable(monkeypatch):
    monkeypatch.setattr(theprotocol.time, "sleep", lambda _: None)
    other = OFFER_URL.replace("f7690000", "aaaa0000")
    session = _FakeSession({
        theprotocol.config.TP_SITEMAP_INDEX_URL: _sitemap("https://x/one.xml", "https://x/two.xml"),
        "https://x/one.xml": _sitemap(OFFER_URL, "https://theprotocol.it/szczegoly/praca/no-id"),
        "https://x/two.xml": _sitemap(other, OFFER_URL),  # duplicate across children
    })
    frame = theprotocol.fetch_frame(session)

    assert len(frame) == 2  # deduplicated by id, unparsable URL skipped
    assert dict(frame)["f7690000-cabe-56d1-0371-08ded6ad4939"] == OFFER_URL


def test_empty_index_is_an_error_not_an_empty_frame():
    session = _FakeSession({theprotocol.config.TP_SITEMAP_INDEX_URL: "<urlset></urlset>"})
    with pytest.raises(theprotocol.TheProtocolError):
        theprotocol.fetch_sitemap_index(session)
