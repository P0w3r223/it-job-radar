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

from pathlib import Path

from conftest import tracked

ROOT = Path(__file__).resolve().parents[1]
ADR = ROOT / "docs" / "adr" / "0001_browser-side-analytics-stack.md"
PAGE = ROOT / "docs" / "index.html"
#: How the dropped half is spelled. Not the bare word `browser`: this repository sends a
#: browser User-Agent to get server-rendered data, and five true sentences say so. The
#: retired claim is about *the* browser — one runtime, working over the dataset.
MARKERS = ("wasm", "the browser", "browser-side")
#: How a block says the claim beside it is history. Taken from the ADR rather than invented,
#: and asserted against it below, so the exemption is the decision's own vocabulary.
RETIRED_BY = ("dropped", "reject")


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _blocks(text: str) -> list[str]:
    """Runs of adjacent non-blank lines — a docstring paragraph, a comment run, a TOML array.

    The unit is what a reader takes in at once. A whole-file scope would let one `dropped`
    in a changelog excuse a claim four hundred lines below it; a per-line scope would demand
    every wrapped sentence repeat the correction.
    """
    blocks: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip():
            current.append(line)
        elif current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def _swept() -> list[Path]:
    """Where this repository speaks in the present tense about what it does.

    `docs/adr/`, `docs/plan/`, `docs/ideas/` and `docs/research/` are excluded and it is not
    an oversight: they are dated records carrying a `Date:` header, and a plan step that was
    later abandoned is supposed to still read as it was written. Strip that and the record
    stops being one.
    """
    roots = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "pyproject.toml"]
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


def test_no_source_or_document_states_the_decision_adr_0001_reversed():
    stated = []
    for path in _swept():
        for block in _blocks(_text(path)):
            low = block.lower()
            if any(one in low for one in MARKERS) and not any(
                one in low for one in RETIRED_BY
            ):
                stated.append(f"{path.relative_to(ROOT).as_posix()}: {block.strip()[:90]}")
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
