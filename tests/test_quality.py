"""Tests for the quality metrics and the data contract.

The contract tests deliberately insert *bad* rows: a rule that never fires proves nothing,
so each one is shown catching the thing it exists to catch.
"""

import pytest

from it_job_radar import config, db, normalize, quality

ALIASES = {"react": "React", "reactjs": "React", "python": "Python"}


def _offer(offer_id="a1", **overrides):
    offer = {
        "offer_id": offer_id, "title": "Backend", "company": "ACME", "offer_url": "u",
        "role_family": "backend", "locations": [], "seniority": ["mid"],
        "work_modes": ["remote"], "technologies": {"expected": normalize.normalize_technologies(["python"], {}), "optional": []},
        "salaries": [{
            "contract_type": "B2B", "kind": "b2b", "currency": "PLN",
            "salary_from": 100, "salary_to": 150, "time_unit": "godzinowo",
            "monthly_from": 16000, "monthly_to": 24000,
        }],
    }
    offer.update(overrides)
    return offer


# --- Alias coverage ----------------------------------------------------------


def test_alias_coverage_counts_resolved_names():
    raw = [{"tech_expected": ["ReactJS", "Python"], "tech_optional": ["React"]}]
    coverage = quality.alias_coverage(raw, ALIASES)

    assert (coverage.total, coverage.matched) == (3, 3)
    assert coverage.rate == 1.0
    assert coverage.unmatched == {}


def test_alias_coverage_names_what_the_dictionary_missed():
    raw = [
        {"tech_expected": ["Python", "Comarch XL"], "tech_optional": []},
        {"tech_expected": ["Comarch XL"], "tech_optional": ["Enova365"]},
    ]
    coverage = quality.alias_coverage(raw, ALIASES)

    assert coverage.rate == pytest.approx(1 / 4)
    # ranked by frequency: this is the list that goes into tech_aliases.yaml
    assert coverage.top_unmatched(1) == [("comarch xl", 2)]


def test_alias_coverage_of_nothing_is_not_a_failure():
    assert quality.alias_coverage([], ALIASES).rate == 1.0


def test_stored_alias_coverage_is_measured_against_the_current_dictionary(tmp_path):
    """The metric must move when the dictionary is edited, not only when a fetch happens."""
    conn = db.connect(tmp_path / "t.db")
    offer = _offer(technologies={
        "expected": normalize.normalize_technologies(["ReactJS", "Comarch XL"], ALIASES),
        "optional": [],
    })
    db.write_offers(conn, [offer], "2026-08-12")

    assert quality.stored_alias_coverage(conn, ALIASES).rate == pytest.approx(1 / 2)
    assert quality.stored_alias_coverage(conn, ALIASES).top_unmatched(1) == [("comarch xl", 1)]

    taught = {**ALIASES, "comarch xl": "Comarch XL"}
    assert quality.stored_alias_coverage(conn, taught).rate == 1.0
    conn.close()


def test_alias_coverage_is_part_of_the_snapshot_metrics(tmp_path):
    """It has to ride with the other metrics, or it is recorded on the wrong runs.

    The repair runs on every observation; measuring it beside a fetch would date each
    curation gain to the next collection. Being here also carries it into the manifest.
    """
    conn = db.connect(tmp_path / "t.db")
    offer = _offer(technologies={
        "expected": normalize.normalize_technologies(["ReactJS", "Comarch XL"], ALIASES),
        "optional": [],
    })
    db.write_offers(conn, [offer], "2026-08-12")

    metrics = quality.snapshot_metrics(conn, "2026-08-12", ALIASES)
    coverage = metrics["stored_alias_coverage_rate"]
    assert coverage.value == pytest.approx(1 / 2)
    assert coverage.detail == "comarch xlx1"
    # the old name carried a different definition and must not be continued under it
    assert "alias_coverage_rate" not in metrics
    conn.close()


# --- Snapshot metrics --------------------------------------------------------


def test_metrics_measure_disclosure_and_thin_strata(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    paid = _offer("paid")
    unpaid = _offer("unpaid", salaries=[{
        "contract_type": "UoP", "kind": None, "currency": None, "salary_from": None,
        "salary_to": None, "time_unit": None, "monthly_from": None, "monthly_to": None,
    }])
    db.write_offers(conn, [paid, unpaid], "2026-08-11")

    metrics = quality.snapshot_metrics(conn, "2026-08-11")
    assert metrics["salary_disclosure_rate"].value == 0.5
    assert metrics["salary_kind_unknown_share"].value == 0.5
    assert metrics["freshness_days"].value == 0
    # "mid" has 2 offers, far below MIN_STRATUM_N -> flagged, with the count in the detail
    assert metrics["strata_below_min_n"].value == 1
    assert "mid=2" in metrics["strata_below_min_n"].detail
    conn.close()


def test_metrics_report_unclassified_and_other_roles(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(
        conn,
        [_offer("a", role_family="other"), _offer("b", role_family="backend"),
         _offer("c", role_family=None)],
        "2026-08-11",
    )

    metrics = quality.snapshot_metrics(conn, "2026-08-11")
    assert metrics["role_family_other_share"].value == pytest.approx(1 / 3)
    assert metrics["role_family_unclassified"].value == 1
    conn.close()


def test_freshness_grows_with_a_stale_database(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [_offer()], "2026-07-17")
    assert quality.snapshot_metrics(conn, "2026-08-11")["freshness_days"].value == 25
    conn.close()


# --- Contract ----------------------------------------------------------------


def test_clean_database_satisfies_the_contract(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [_offer()], "2026-08-11")
    db.record_frame(conn, [("a1", "https://x/a1")], "2026-08-11")

    assert quality.validate_contract(conn) == []
    conn.close()


def test_contract_catches_an_unknown_work_mode(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [_offer(work_modes=["teleportation"])], "2026-08-11")

    violations = quality.validate_contract(conn)
    assert [(v.table, v.rows) for v in violations] == [("offer_work_modes", 1)]
    conn.close()


def test_contract_catches_an_inverted_salary_range(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    broken = _offer(salaries=[{
        "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": 1,
        "salary_to": 2, "time_unit": "monthly", "monthly_from": 30000, "monthly_to": 10000,
    }])
    db.write_offers(conn, [broken], "2026-08-11")

    assert "ordered" in quality.validate_contract(conn)[0].rule
    conn.close()


def test_contract_catches_an_implausible_salary(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    absurd = _offer(salaries=[{
        "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": 5000,
        "salary_to": 6000, "time_unit": "godzinowo",
        # an hourly rate mistaken for a monthly one — the failure mode this rule exists for
        "monthly_from": 800_000, "monthly_to": 960_000,
    }])
    db.write_offers(conn, [absurd], "2026-08-11")

    rules = {v.rule for v in quality.validate_contract(conn)}
    assert any("above the maximum" in rule for rule in rules)
    conn.close()


def test_contract_catches_a_salary_without_its_currency(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    ambiguous = _offer(salaries=[{
        "contract_type": "B2B", "kind": None, "currency": None, "salary_from": 100,
        "salary_to": 150, "time_unit": "monthly", "monthly_from": 16000, "monthly_to": 24000,
    }])
    db.write_offers(conn, [ambiguous], "2026-08-11")

    assert any("currency and kind" in v.rule for v in quality.validate_contract(conn))
    conn.close()


def test_enforce_raises_with_the_offending_rules(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [_offer(seniority=["wizard"])], "2026-08-11")

    with pytest.raises(quality.ContractError, match="offer_seniority"):
        quality.enforce_contract(conn)
    conn.close()


def test_contract_rejects_an_unknown_config_reference(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    bogus = {"tables": {"offers": {"columns": {"title": {"allowed_from": "NOPE"}}}}}

    with pytest.raises(quality.ContractError, match="NOPE"):
        quality.validate_contract(conn, bogus)
    conn.close()


def test_allowed_values_come_from_config_not_a_copy():
    """The contract references config, so the two cannot drift apart."""
    contract = quality.load_contract()
    seniority = contract["tables"]["offer_seniority"]["columns"]["seniority"]
    assert seniority["allowed_from"] == "SENIORITY_ORDER"
    assert "head" in config.SENIORITY_ORDER  # added in phase 1.5, contract follows for free


def test_contract_catches_a_salary_below_the_floor(tmp_path):
    """The half of the guard that actually reached the published page.

    Eleven rows sat at 14-180 PLN "miesięcznie" — hourly rates filed as monthly — dragging
    five medians down. `normalize` and migration v9 both refuse them; until this test the
    gate that stops publication did not.
    """
    conn = db.connect(tmp_path / "t.db")
    hourly_as_monthly = _offer(salaries=[{
        "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": 140,
        "salary_to": 180, "time_unit": "miesięcznie",
        "monthly_from": 140, "monthly_to": 180,
    }])
    db.write_offers(conn, [hourly_as_monthly], "2026-08-11")

    rules = {v.rule for v in quality.validate_contract(conn)}
    assert any("below the minimum" in rule for rule in rules)
    conn.close()


def test_contract_catches_a_unit_the_converter_cannot_read(tmp_path):
    """An unseen unit is withheld silently and then described on the page as a unit error.

    Those are different statements about the employer, so publication stops instead.
    """
    conn = db.connect(tmp_path / "t.db")
    daily = _offer(salaries=[{
        "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": 900,
        "salary_to": 1200, "time_unit": "dziennie", "monthly_from": None, "monthly_to": None,
    }])
    db.write_offers(conn, [daily], "2026-08-11")

    violations = quality.validate_contract(conn)
    assert any(v.table == "offer_salaries" and "time_unit" in v.rule for v in violations)
    conn.close()


def test_the_convertible_units_are_the_ones_the_converter_knows(tmp_path):
    """The contract reads config's tuple rather than repeating it.

    It used to repeat the four strings inline, so adding a unit to `KNOWN_TIME_UNITS`
    changed nothing and the docstring promising they stay in sync was describing a copy.
    """
    for unit in config.KNOWN_TIME_UNITS:
        conn = db.connect(tmp_path / f"{unit}.db")
        ok = _offer(salaries=[{
            "contract_type": "B2B", "kind": "b2b", "currency": "PLN", "salary_from": 100,
            "salary_to": 150, "time_unit": unit, "monthly_from": 16000, "monthly_to": 24000,
        }])
        db.write_offers(conn, [ok], "2026-08-11")
        assert not [v for v in quality.validate_contract(conn) if "time_unit" in v.rule]
        conn.close()


def test_contract_catches_a_series_point_without_its_population(tmp_path):
    """A count means one thing against 681 offers and another against 6603."""
    conn = db.connect(tmp_path / "t.db")
    snapshot = db.start_snapshot(conn, "collect", "2026-08-13", "2026-08-13T10:00:00")
    conn.execute(
        "INSERT INTO snapshot_dimension_metrics (snapshot_id, date, metric, dimension, value, n) "
        "VALUES (?, '2026-08-13', 'technology_vacancies', 'python', 12, 0)",
        (snapshot,),
    )
    conn.commit()

    assert any("population" in v.rule for v in quality.validate_contract(conn))
    conn.close()
