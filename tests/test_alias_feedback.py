"""The alias feedback loop must close: an alias added today repairs data stored earlier.

`pipeline quality` reports the technology names the dictionary failed to resolve, and the
answer to that report is an edit to `tech_aliases.yaml`. That answer is only worth making
if it reaches the rows already in the database — otherwise the quality metric names a gap
it has no way to close, and every past collection keeps its fragmented spellings for good.
"""

from it_job_radar import config, db, normalize, pipeline
from it_job_radar.normalize import Technology

_ALIASES_BEFORE = "python: [py]\n"
_ALIASES_AFTER = 'python: [py]\n"ci/cd": ["ci / cd", cicd, "continuous integration"]\n'


def _offer(technologies):
    return {
        "offer_id": "a1", "title": "DevOps Engineer", "company": "ACME", "offer_url": "u",
        "locations": [], "seniority": ["mid"], "work_modes": [],
        "technologies": {"expected": technologies, "optional": []},
        "salaries": [],
    }


def _context(tmp_path, aliases: str) -> normalize.Normalization:
    path = tmp_path / "aliases.yaml"
    path.write_text(aliases, encoding="utf-8")
    return normalize.load_normalization(aliases_path=path, roles_path=config.ROLE_FAMILIES_PATH)


def test_adding_an_alias_repairs_offers_collected_before_it(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    before = _context(tmp_path, _ALIASES_BEFORE)

    # collected while the dictionary knew nothing about CI/CD: two spellings, two rows
    raw_names = ["CI / CD", "cicd"]
    db.write_offers(
        conn,
        [_offer(normalize.normalize_technologies(raw_names, before.tech_aliases))],
        "2026-08-12",
    )
    assert set(db.read_table(conn, "offer_technologies")["technology"]) == {"ci / cd", "cicd"}

    # the dictionary learns the technology, and the stored rows are re-resolved and merged
    after = _context(tmp_path, _ALIASES_AFTER)
    assert pipeline._renormalize_technologies(conn, after) == 2

    technologies = db.read_table(conn, "offer_technologies")
    assert list(technologies["technology"]) == ["ci/cd"]
    assert technologies.loc[0, "raw_name"] in raw_names  # provenance survives the repair
    conn.close()


def test_reresolving_without_a_dictionary_change_does_nothing(tmp_path):
    """Idempotence — the repair runs on every observation, so it must be free when correct."""
    conn = db.connect(tmp_path / "t.db")
    context = _context(tmp_path, _ALIASES_AFTER)
    db.write_offers(conn, [_offer([Technology(raw="CI / CD", name="ci/cd")])], "2026-08-12")

    assert pipeline._renormalize_technologies(conn, context) == 0
    assert list(db.read_table(conn, "offer_technologies")["technology"]) == ["ci/cd"]
    conn.close()
