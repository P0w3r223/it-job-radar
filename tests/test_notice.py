"""NOTICE, and the one attribution sentence this repository states in four places.

`LICENSE` grants MIT over the tree. `docs/data/` is not software: it is derived from a third
party's adverts, and a redistributor reading `LICENSE` alone would take a commercial grant
this repository is in no position to give. `NOTICE` states the exception, and these guards
are why it cannot quietly stop being true.

Nothing here repeats the sentence. It is `config.ATTRIBUTION`, `export` writes it into the
manifest and the template renders the manifest — so the page and the manifest were already
derived from it, and the halves carried by nothing were the *committed* copies of each and
the README's, which said the same thing with an em dash where the constant has a comma.

The carve-out names a directory rather than the files under it. That is the same refusal
`NOTICE` makes in prose: the file list is `manifest.json`'s job and it is rewritten on every
export, so a second copy here would go stale the first time a table is added.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from conftest import tracked

from it_job_radar import config

ROOT = Path(__file__).resolve().parents[1]
NOTICE = ROOT / "NOTICE"
README = ROOT / "README.md"
PAGE = ROOT / "docs" / "index.html"
#: The dataset directory as the code knows it, written the way a document writes a path.
#: Derived so that moving `DATASET_DIR` reddens this file instead of leaving `NOTICE`
#: carving out somewhere the data no longer is.
CARVED = config.DATASET_DIR.relative_to(ROOT).as_posix() + "/"


def _folded(path: Path) -> str:
    """A file as one line, so a sentence is found wherever its author wrapped it.

    Every blob here is committed LF and arrives CRLF on a checkout with `core.autocrlf`
    set, which a raw comparison would read as a difference in content. Folding whitespace
    answers that and the wrapping at once: `README.md`, `NOTICE` and the rendered page
    break the attribution in three different places, and none of the three is a claim.
    """
    return " ".join(path.read_bytes().decode("utf-8").split())


def _sentences(text: str) -> list[str]:
    """Folded text split where a full stop is followed by a space.

    Crude, and deliberately so: the one guard that needs it is asking which sentence states
    the carve-out, and a sentence boundary in this file is never anything subtler. A reader
    who adds `e.g.` to NOTICE gets a shorter fragment here, not a wrong verdict — the
    fragment still either names the directory or does not.
    """
    return [one.strip() for one in re.split(r"(?<=\.)\s+", text) if one.strip()]


def _manifest() -> dict:
    return json.loads((config.DATASET_DIR / config.MANIFEST_NAME).read_text(encoding="utf-8"))


def test_the_notice_states_the_attribution_the_code_states():
    assert config.ATTRIBUTION in _folded(NOTICE)


def test_the_notice_carves_out_the_directory_the_code_publishes_to():
    """The sentence stating the exception, not the file and not even the paragraph.

    Two editions of this guard went green over a mutation pointing the carve-out at
    `docs/dataset/`. The first read the whole file, where the closing paragraph mentions the
    right directory in passing. The second read the paragraph — and the very sentence after
    the exception says the file list is `docs/data/manifest.json`'s job, so the substring was
    still there. A carve-out is one sentence, and a sentence naming the wrong directory
    grants MIT over the data while every other mention in the file reads correctly.
    """
    stating = [
        one
        for one in _sentences(_folded(NOTICE))
        if "LICENSE" in one and "except" in one.lower()
    ]
    assert len(stating) == 1, (
        f"NOTICE states {len(stating)} exceptions to LICENSE; this guard reads exactly one"
    )
    assert CARVED in stating[0], (
        f"NOTICE states an exception that does not name {CARVED}, which is where "
        f"config.DATASET_DIR publishes: {stating[0]}"
    )


def test_the_readme_states_the_attribution_and_points_at_the_notice():
    """The README's licence section was the one hand-typed copy of the four.

    It carried an em dash where `config.ATTRIBUTION` has a comma, which is exactly how much
    drift it takes for a sweep looking for the sentence to report it missing — and how
    little it takes for the three statements `0010` §4 A-3 found to stop being one.
    """
    readme = _folded(README)
    assert config.ATTRIBUTION in readme
    assert "(NOTICE)" in readme, "the README's licence section does not link NOTICE"


def test_the_committed_manifest_states_the_attribution():
    """`export` writes this from `config`; nothing until now held the committed copy to it.

    `pipeline verify` checks row counts and total bytes against the files beside the
    manifest and never reads this key, so a manifest published before the sentence moved
    would go on shipping the old one under a page that renders it.
    """
    assert _manifest()["source"]["attribution"] == config.ATTRIBUTION


def test_the_published_page_states_the_attribution():
    """The bytes a reader downloads, not the template that produced them.

    `tests/test_committed_dataset.py` states the reason in its own docstring: every other
    test in this suite checks what the build *would* write. The page in `docs/` is what a
    reader is actually handed, and the footer is where a redistributor looks first.
    """
    assert config.ATTRIBUTION in _folded(PAGE)


def test_no_published_data_file_sits_outside_the_carve_out():
    """The other direction, and the one a reader of `NOTICE` cannot check for themselves.

    A carve-out that names a directory is only as true as the claim that the data is all in
    it. Derived from the tree rather than from a list: a Parquet committed somewhere else is
    published under MIT by `LICENSE` and mentioned by nothing.
    """
    published = tracked("*.parquet")
    assert published, "no Parquet is tracked at all; this guard is reading the wrong tree"
    outside = sorted(one for one in published if not one.startswith(CARVED))
    assert outside == [], f"published data outside the {CARVED} exception NOTICE states"


def test_the_packaging_ships_the_notice_beside_the_licence():
    """A wheel carrying `LICENSE` and not `NOTICE` restates the gap this file closes."""
    packaging = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    files = packaging["project"]["license-files"]
    assert NOTICE.name in files, f"license-files is {files}"
