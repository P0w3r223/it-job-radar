"""Tests for the role-family rule table.

Titles here are taken from the collected snapshot, including the Polish gendered forms
("Analityczka / Analityk", "Programista / Programistka") that a naive substring rule
misses. The families matter because pooling support roles with developer roles is what
made "top technologies for juniors" report active directory and microsoft office.
"""

import pytest

from it_job_radar import config, normalize


@pytest.fixture(scope="module")
def rules():
    return normalize.load_role_families()


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Senior DevSecOps Engineer (Kubernetes, CI/CD)", "devops"),
        ("Informatyk - Administrator IT", "infrastructure"),
        ("Administrator Systemów i Sieci (k/m)", "infrastructure"),
        ("Młodszy Specjalista ds. Wsparcia IT (K/M)", "support"),
        ("Specjalista / Specjalistka ds. sieci komputerowych LAN/WAN", "infrastructure"),
        ("Senior Entra ID & Active Directory Migration Specialist", "infrastructure"),
        ("Lead Developer / Senior Software Engineer (Python, AWS)", "software"),
        ("Starszy specjalista ds. transformacji cyfrowej", "analyst"),
        ("Business Analyst / Calypso Specialist", "analyst"),
        ("Analityczka / Analityk SAP IS-U CRM", "erp"),
        ("Specjalista ds. Hurtowni Danych (k/m)", "data"),
        ("Architekt Rozwiązań (Azure, GCP lub AWS)", "architect"),
        ("Tester Oprogramowania (K/M)", "qa"),
        ("Programista / Programistka Full Stack .NET", "fullstack"),
        ("PL/SQL Developer with GCP (f/m/x)", "data"),
        ("Product Owner (Wolontariat)", "product"),
        ("Programista / Programistka Szablonów Middle", "software"),
        ("Senior Machine Learning Engineer", "ml"),
        ("Android Developer", "mobile"),
        ("Head of Engineering", "management"),
    ],
)
def test_titles_from_the_snapshot_classify(title, expected, rules):
    assert normalize.classify_role_family(title, rules) == expected


def test_order_decides_overlapping_titles(rules):
    """A DevSecOps engineer is devops, and a BI analyst is data — specificity wins."""
    assert normalize.classify_role_family("DevSecOps Security Engineer", rules) == "devops"
    assert normalize.classify_role_family("Business Intelligence Analyst", rules) == "data"
    # bare "administrator" belongs to infrastructure, but only after data and erp have looked
    assert normalize.classify_role_family("Database Administrator", rules) == "data"
    assert normalize.classify_role_family("Administrator SAP Basis", rules) == "erp"
    assert normalize.classify_role_family("Administrator wewnętrznych systemów", rules) == "infrastructure"


def test_the_desk_and_the_machines_are_different_families(rules):
    """The split that motivated adding `infrastructure`, stated as the pair it separates.

    Both titles were "support" while one rule table covered both, which made the family
    mean two jobs at once — the same pooling this file exists to undo, one level down.
    """
    assert normalize.classify_role_family("IT Support Agent (with German)", rules) == "support"
    assert normalize.classify_role_family("Backup Engineer (f/m/x)", rules) == "infrastructure"
    # An overlap resolved deliberately: "informatyk" is the Polish word for the IT person at
    # the desk, but a title that also says "administrator" is describing the machines.
    assert normalize.classify_role_family("Informatyk", rules) == "support"
    assert normalize.classify_role_family("Informatyk - Administrator IT", rules) == "infrastructure"


def test_java_pattern_does_not_swallow_javascript(rules):
    assert normalize.classify_role_family("Senior Java Engineer", rules) == "backend"
    assert normalize.classify_role_family("JavaScript Developer (Vue.js)", rules) == "frontend"


@pytest.mark.parametrize("title", ["", None, "Specjalista ds. Zakupów", "Kucharz"])
def test_unmatched_titles_are_other_not_guessed(title, rules):
    assert normalize.classify_role_family(title, rules) == config.ROLE_FAMILY_OTHER


def test_normalize_offer_attaches_the_family(tmp_path):
    context = normalize.load_normalization()
    offer = {
        "offer_id": "a1", "title": "Tester Oprogramowania", "offer_url": "u",
        "locations": [], "seniority": ["regular"], "work_modes": [],
        "tech_expected": [], "tech_optional": [], "contracts": [],
    }
    assert normalize.normalize_offer(offer, context)["role_family"] == "qa"


def test_head_seniority_is_mapped_and_ranked():
    """It occurs in the source data; unmapped it sorted last in every chart."""
    assert normalize.normalize_seniority("head") == "head"
    assert "head" in config.SENIORITY_ORDER
