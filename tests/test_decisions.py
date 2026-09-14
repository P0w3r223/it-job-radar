"""A reversed decision, and everything downstream that had not heard.

`ADR 0001` proposed DuckDB-WASM in the reader's browser, measured the bundle at 21-37 MB
against a 241 kB dataset, and amended itself: *"The interactive layer is dropped."* The ADR
is not the defect — it is the model, and this portfolio's practice of recording a correction
rather than quietly making it. The defect is the fan-out. `0010` §4 A-3 found the GitHub
description, one topic and a package docstring still advertising the dropped half; sweeping
for it found **four** in the tree, including a `pyproject.toml` comment and an `export`
docstring that justify a file format by a capability nobody ships.

Which is the argument for a guard rather than a repair: the row was a hand list of what a
reader noticed, and a reader who notices three of four leaves the claim in the source, where
it is trusted most.

The rule is not *never mention it*. It is that the retired claim may appear only where its
retirement appears with it — the shape `ADR 0001` itself uses. The page is held harder: it
is generated, it states current fact, and it has no place to put history.
"""

from __future__ import annotations

import re
from pathlib import Path

from conftest import tracked

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0001_browser-side-analytics-stack.md"
PAGE = ROOT / "docs" / "index.html"
#: How the dropped half is spelled. Not the bare word `browser`: this repository sends a
#: browser User-Agent to get server-rendered data, and five true sentences say so. The
#: retired claim is about *the* browser — one runtime, working over the dataset.
MARKERS = ("wasm", "the browser", "browser-side")
#: How a claim says it is quoting the retirement rather than restating the claim. Taken from
#: the ADR rather than invented, and asserted against it below, so the exemption is the
#: decision's own vocabulary.
RETIRED_BY = ("dropped", "reject")
#: And what it must name alongside one of those. Twelve blocks in this tree use a retirement
#: word and eight of them are about something else entirely — `robots.txt`, residue families,
#: a currency the parser drops — so a bare `dropped` cannot be allowed to excuse a claim it
#: has nothing to do with. One string, and it is the ADR's own title line.
CITES = "ADR 0001"
#: How close the retirement has to sit to the claim. Two lines each way covers a wrapped
#: sentence and a comment run, and deliberately does not cover a whole TOML table: the first
#: edition scoped the exemption to a run of adjacent non-blank lines, and `pyproject.toml`'s
#: `[project]` runs unbroken from `name` to the end of `dependencies` — so one `dropped` in a
#: dependency comment exempted the package `description` twelve lines above it. That
#: description is one of the four sites `0010` §4 A-3 raised, and the guard written to catch
#: it went green over it.
NEARBY = 2


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _prose(lines: list[str]) -> str:
    """Lines joined as one sentence, with comment and markup prefixes dropped.

    A claim that wraps escapes a per-line search, and this repository's own `pyproject.toml`
    comment breaks `in the` / `# browser` across two lines — so the marker is in neither of
    them. The prefixes go with the line breaks because a `#` in the middle of a folded
    sentence is not a word a reader sees.
    """
    return " ".join(re.sub(r"^[\s#*/>!-]*", "", one).strip() for one in lines).lower()


def _stated(path: Path) -> list[str]:
    """Every line claiming the retired half, minus the ones quoting its retirement.

    The scope is a window around the claim rather than the run of non-blank lines holding
    it. What a reader takes in beside a sentence is the sentence's neighbours; a whole TOML
    table is not that, and treating it as one is what let `NEARBY`'s comment happen.
    """
    lines = _text(path).split("\n")
    found = []
    for n in range(len(lines)):
        # Two lines, because a wrapped claim is in neither of its halves.
        if not any(one in _prose(lines[n : n + 2]) for one in MARKERS):
            continue
        window = _prose(lines[max(0, n - NEARBY) : n + NEARBY + 2])
        if CITES.lower() in window and any(one in window for one in RETIRED_BY):
            continue
        found.append(f"{path.relative_to(ROOT).as_posix()}:{n + 1}: {lines[n].strip()[:90]}")
    return found


def _swept() -> list[Path]:
    """Where this repository speaks in the present tense about what it does.

    `docs/adr/`, `docs/plan/`, `docs/ideas/` and `docs/research/` are excluded and it is not
    an oversight: they are dated records carrying a `Date:` header, and a plan step that was
    later abandoned is supposed to still read as it was written. Strip that and the record
    stops being one.

    Everything else tracked that speaks in the present tense is in, and the list is longer
    than the obvious three: `NOTICE` describes the artifact, `ci.yml` carries architecture
    prose in its comments, and the notebook's first markdown cell narrates the design to
    anyone who opens it on GitHub. None of the three carries a marker today, which is what
    makes now the cheap time to put them under the sweep.
    """
    roots = [
        ROOT / "README.md",
        ROOT / "CLAUDE.md",
        ROOT / "pyproject.toml",
        ROOT / "NOTICE",
        ROOT / ".github" / "workflows" / "ci.yml",
        ROOT / "notebooks" / "01_analysis.ipynb",
    ]
    absent = [p.name for p in roots if not p.is_file()]
    assert absent == [], f"the sweep names files that are not there: {absent}"
    sources = [ROOT / one for one in tracked("src")]
    assert len(sources) > 20, f"the source sweep found only {len(sources)} files under src/"
    return roots + sources


def test_the_vocabulary_this_guard_sweeps_for_is_the_decisions_own():
    """Both directions for two registries that would otherwise be this file's invention.

    A marker the ADR does not use is a word someone here thought sounded retired; an
    exemption word the ADR does not use is an excuse this guard hands out on its own
    authority. And the premise above them: `ADR 0001` is amended. Re-adopt the browser half
    and this file should stop demanding, loudly, rather than go on enforcing a decision the
    repository has reversed a second time.
    """
    adr = _text(ADR).lower()
    assert "status:" in adr and "amended" in adr.split("---")[0], (
        "ADR 0001 no longer records an amendment, so the claim below is not retired"
    )
    unused = [one for one in MARKERS if one not in adr]
    assert unused == [], f"{unused} is swept for and ADR 0001 never says it"
    unused = [one for one in RETIRED_BY if one not in adr]
    assert unused == [], f"{unused} exempts a block and ADR 0001 never says it"
    assert CITES.lower() in adr, (
        f"{CITES!r} is how a block claims to be quoting this decision, and the decision "
        "does not call itself that"
    )


def test_no_source_or_document_states_the_decision_adr_0001_reversed():
    stated = [one for path in _swept() for one in _stated(path)]
    assert stated == [], (
        "the browser-side layer ADR 0001 dropped is stated as current fact in:\n"
        + "\n".join(stated)
    )


def test_the_published_page_does_not_mention_the_dropped_layer_at_all():
    """No exemption here. The page is rebuilt from the dataset on every run and says what is
    true today; a sentence explaining what the project once planned would be the only history
    on it, and `0010` §4 A-3's D row is what it costs when a reader believes one."""
    page = _text(PAGE).lower()
    found = [one for one in MARKERS if one in page]
    assert found == [], f"the published page advertises {found}"
