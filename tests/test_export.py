"""Tests for the published dataset — redaction is enforced here or not at all.

ADR 0002 turns an internal database into a public download. The rules that keep it from
being a copy of the source's listings are worth exactly as much as the tests that hold
them, so these check the absence of the excluded columns rather than trusting review.
"""

import json

import pandas as pd
import pytest

from it_job_radar import config, db, export, normalize


def _offer(offer_id="a1"):
    """Built the way the pipeline builds one, so every derived column is actually present.

    A hand-written dict leaves `vacancy_key` unset, which made the redaction test pass over
    a NULL column: publishing the key — "senior java engineer|acme sp. z o.o.", the two
    fields ADR 0002 exists to withhold — would not have failed a single test.
    """
    return normalize.normalize_offer(_raw(offer_id), normalize.Normalization(
        tech_aliases={}, role_rules=(("backend", ("java",)),)
    ))


def _raw(offer_id="a1"):
    return {
        "offer_id": offer_id, "title": "Senior Java Engineer", "company": "ACME Sp. z o.o.",
        "offer_url": "https://theprotocol.it/szczegoly/praca/x,oferta,a1",
        "locations": [{"city": "Wrocław", "region": "dolnośląskie"}],
        "seniority": ["senior"], "work_modes": ["remote"],
        "tech_expected": ["java"], "tech_optional": ["docker"],
        "contracts": [{
            "type": "B2B", "kind": "netto (+ VAT)", "currency": "zł",
            "salary_from": 100, "salary_to": 150, "time_unit": "godzinowo",
        }],
    }


@pytest.fixture
def dataset(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.write_offers(conn, [_offer("a1"), _offer("a2")], "2026-08-11")
    db.record_frame(conn, [("a1", "https://theprotocol.it/x,oferta,a1")], "2026-08-11")
    out = tmp_path / "dataset"
    export.write_dataset(conn, out)
    yield conn, out
    conn.close()


def test_identifying_columns_never_reach_the_artifact(dataset):
    _, out = dataset
    excluded = set(config.REDACTED_COLUMNS) | set(config.INTERNAL_COLUMNS)
    for table in config.DATASET_TABLES:
        columns = set(pd.read_parquet(out / f"{table}.parquet").columns)
        leaked = columns & excluded
        assert not leaked, f"{table} leaked {leaked}"


def test_the_vacancy_key_is_published_only_as_a_hash(dataset):
    """The grouping key is built from the title and the company, so it cannot ship as text.

    `vacancy_id` must be there — every published count groups on it — and it must be the
    salted digest of the key, not the key.
    """
    conn, out = dataset
    offers = pd.read_parquet(out / "offers.parquet")
    assert "vacancy_key" not in offers.columns
    assert offers["vacancy_id"].notna().all()

    stored = conn.execute("SELECT vacancy_key FROM offers LIMIT 1").fetchone()[0]
    assert stored  # the fixture really does carry one, or this test proves nothing
    assert set(offers["vacancy_id"]) == {export.hash_offer_id(stored)}


def test_offer_titles_and_employers_are_absent_from_the_bytes(dataset):
    """A stricter check than column names: the strings must not be in the file at all."""
    _, out = dataset
    blob = (out / "offers.parquet").read_bytes().lower()
    # Lowercased on both sides: the vacancy key normalises case, so a case-sensitive scan
    # would have missed exactly the leak this file is here to prevent.
    assert b"senior java engineer" not in blob
    assert b"acme" not in blob


def test_offer_ids_are_hashed_but_stay_joinable(dataset):
    _, out = dataset
    offers = pd.read_parquet(out / "offers.parquet")
    technologies = pd.read_parquet(out / "offer_technologies.parquet")

    assert set(offers["offer_id"]) == {export.hash_offer_id("a1"), export.hash_offer_id("a2")}
    assert "a1" not in set(offers["offer_id"])
    # the hash is applied consistently, so the child tables still join
    assert set(technologies["offer_id"]) <= set(offers["offer_id"])


def test_the_hash_is_stable_across_exports():
    """Longitudinal analysis depends on the same offer hashing the same way every time."""
    assert export.hash_offer_id("a1") == export.hash_offer_id("a1")
    assert export.hash_offer_id("a1") != export.hash_offer_id("a2")
    assert len(export.hash_offer_id("a1")) == config.EXPORT_ID_LENGTH


def test_verify_catches_a_manifest_that_no_longer_describes_its_data(dataset, tmp_path):
    """A stale manifest is invisible to the drift guard, which rebuilds the page from it."""
    conn, out = dataset
    export.publish(conn, out, git_sha="abc1234")
    assert export.verify(out) == []

    manifest_path = out / config.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["rows"]["offers"] += 5
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    problems = export.verify(out)
    assert any("offers" in problem for problem in problems)


def test_internal_provenance_stays_out_of_the_artifact(dataset):
    """`raw_name` is bookkeeping for the repair loop, not part of the published dataset.

    ADR 0002 promises normalized attributes; a raw technology string is source free text,
    and for rows seeded by migration v5 it is not even the original one.
    """
    conn, out = dataset
    export.write_dataset(conn, out)

    technologies = pd.read_parquet(out / "offer_technologies.parquet")
    assert "raw_name" not in technologies.columns
    assert "technology" in technologies.columns  # the normalized name still ships


def test_analysable_columns_survive_redaction(dataset):
    """Redaction must cost listing detail, not market detail."""
    _, out = dataset
    offers = pd.read_parquet(out / "offers.parquet")
    salaries = pd.read_parquet(out / "offer_salaries.parquet")

    assert {"role_family", "collected_date"} <= set(offers.columns)
    assert {"kind", "currency", "monthly_from", "monthly_to"} <= set(salaries.columns)


def test_manifest_carries_provenance_and_measured_trustworthiness(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.start_snapshot(conn, "collect", "2026-08-11", "2026-08-11T10:00:00")
    db.write_offers(conn, [_offer("a1")], "2026-08-11")
    db.record_frame(conn, [("a1", "u1"), ("a2", "u2")], "2026-08-11")
    db.reconcile_fetch_state(conn)

    manifest = export.publish(conn, tmp_path / "out", git_sha="abc1234")

    assert manifest["git_sha"] == "abc1234"
    assert manifest["schema_version"] >= 4
    assert manifest["snapshot"]["observed_date"] == "2026-08-11"
    assert manifest["coverage"] == {
        "offers_listed": 2, "attributes_known": 1, "share": 0.5,
    }
    assert manifest["rows"]["offers"] == 1
    assert manifest["bytes"] > 0
    assert "salary_disclosure_rate" in manifest["quality"]
    # the reader is told what was removed, not left to infer it
    assert set(manifest["redaction"]["columns"]) == set(config.REDACTED_COLUMNS)
    assert config.SOURCE_NAME in manifest["source"]["attribution"]
    conn.close()


def test_manifest_is_written_next_to_the_data(dataset):
    conn, out = dataset
    export.publish(conn, out)
    written = json.loads((out / config.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert written["rows"]["offers"] == 2


def test_publishing_an_oversized_artifact_is_refused(dataset, monkeypatch):
    conn, out = dataset
    monkeypatch.setattr(config, "MAX_ARTIFACT_BYTES", 10)
    with pytest.raises(export.ArtifactTooLarge, match="budget"):
        export.publish(conn, out)


def test_the_artifact_is_faithful_to_the_system_of_record(dataset):
    """Every published table must equal its redacted source, row for row."""
    conn, out = dataset
    for table in config.DATASET_TABLES:
        expected = export.redact(db.read_table(conn, table))
        published = pd.read_parquet(out / f"{table}.parquet")
        pd.testing.assert_frame_equal(
            published.reset_index(drop=True), expected.reset_index(drop=True),
            check_dtype=False,
        )
