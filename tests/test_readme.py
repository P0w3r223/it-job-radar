"""The documents, held to what the code and the artifact say.

Two claims the README made and nothing compared: the size of the published dataset, which
read `~250 kB` against a manifest stating 1 244 431 bytes, and the flags the CLI accepts.
`0010` §4 A-3's B row is both.

The unit of documentation here is smaller than in the sibling guards, and that is the whole
finding. `apply-scout` and `auth-log-scan` scope a flag to the *block* that names its
subcommand, which works because their blocks name one subcommand each. This README teaches
all six in a single fenced block, so a block-scoped reader would call `export --out`
documented on the strength of the `site --out` line two rows below it. In a shell
transcript the command is the unit.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
from pathlib import Path
from unittest import mock

import pytest

from it_job_radar import config, pipeline

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
#: How a document refers to the decision that dated a figure. A size stated in a block
#: citing it is history and is allowed to disagree with today's artifact; anywhere else it
#: is a current claim. Spelled two ways because the README uses both.
DATED_BY = ("ADR 0001", "adr/0001")
_SIZE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kB|MB|GB)\b")


class _ParserBuilt(Exception):
    """Raised once `main()` has built its parser, to stop it before it runs anything.

    Not named `...Error`: it is a control signal and the call below is expected to raise it.
    """


@functools.cache
def _read(path: Path) -> str:
    """A file with its line endings folded.

    Every blob here is committed LF; a checkout with `core.autocrlf` set produces CRLF, so
    a guard splitting on `\\n` would carry a stray `\\r` into every comparison it makes.
    """
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _docs() -> list[Path]:
    scope = [README, ROOT / "CLAUDE.md", *sorted((ROOT / "docs").rglob("*.md"))]
    missing = [p.name for p in scope if not p.is_file()]
    assert missing == [], f"the documentation sweep names files that are not there: {missing}"
    assert len(scope) > 2, "the sweep found no docs/ markdown at all"
    return scope


def _units(text: str) -> list[str]:
    """Documentation in the smallest honest scope: a line inside a fence, a paragraph outside.

    A flag is documented *for a subcommand* when something naming that subcommand also names
    the flag, and "also" has to be scoped to something. Prose argues in paragraphs. A shell
    block does not argue at all — it lists commands, and the line is the command.
    """
    units: list[str] = []
    paragraph: list[str] = []
    fenced = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            if paragraph:
                units.append("\n".join(paragraph))
                paragraph = []
            fenced = not fenced
            continue
        if fenced:
            if line.strip():
                units.append(line)
        elif line.strip():
            paragraph.append(line)
        elif paragraph:
            units.append("\n".join(paragraph))
            paragraph = []
    if paragraph:
        units.append("\n".join(paragraph))
    return units


def _named(flag: str, text: str) -> bool:
    """Not `flag in text`: the value of the sweep is the flag nobody has written yet, and
    `--out` reads as documented the moment `--output` is."""
    return re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text) is not None


def _parser() -> argparse.ArgumentParser:
    """The parser `main()` builds, asked for rather than restated.

    `pipeline.main` constructs it inline and returns nothing, and `0010` §3.5 puts a new
    production signature outside a repair pass — so this captures the real object instead of
    extracting a `_build_parser()` for the guard's convenience. A `main()` that stops calling
    `parse_args` fails here loudly, which is the right answer: a sweep reading a parser the
    program no longer uses proves nothing about the program.
    """
    captured: list[argparse.ArgumentParser] = []

    def capture(self, *args, **kwargs):
        captured.append(self)
        raise _ParserBuilt

    with (
        mock.patch.object(argparse.ArgumentParser, "parse_args", capture),
        pytest.raises(_ParserBuilt),
    ):
        pipeline.main([])
    assert len(captured) == 1, "main() no longer builds exactly one parser"
    return captured[0]


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """argparse exposes no public reader for this, and the private one is the whole point:
    a guard that took the subcommand list from a constant would be documenting the list."""
    groups = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(groups) == 1, "the parser's subcommand layout has changed under this guard"
    return dict(groups[0].choices)


def test_the_readme_states_the_dataset_size_the_manifest_states():
    """`~250 kB` against 1 244 431 bytes, and nothing opened the README to notice.

    The figure is the one `pipeline export` prints, which is the artifact's own arithmetic
    rather than this guard's: `manifest['bytes'] / 1024`, and `verify` already holds that
    key to the files beside it. So a re-export that changes the size reddens here and the
    README moves with the data instead of a year after it.
    """
    manifest = json.loads(
        (config.DATASET_DIR / config.MANIFEST_NAME).read_text(encoding="utf-8")
    )
    current = f"{manifest['bytes'] / 1024:.0f} kB"
    assert current in _read(README), (
        f"the README states no current dataset size; the manifest says {current}"
    )

    for unit in _units(_read(README)):
        for value, suffix in _SIZE.findall(unit):
            if f"{value} {suffix}" == current:
                continue
            assert any(one in unit for one in DATED_BY), (
                f"the README states {value} {suffix} as current; the manifest says {current}. "
                f"A figure that is history cites the decision that dated it ({DATED_BY[0]})."
            )


def test_the_decision_that_dates_a_figure_is_a_document_that_exists():
    """The other direction for `DATED_BY`: an exemption answerable to nothing exempts
    everything, and this one is a string two paragraphs of README prose can drift away
    from without any reader noticing."""
    numbered = sorted((ROOT / "docs" / "adr").glob("0001_*.md"))
    assert len(numbered) == 1, f"ADR 0001 is not one document: {numbered}"
    assert any(one in _read(README) for one in DATED_BY), (
        "no README block cites ADR 0001, so the exemption above can no longer fire"
    )


def test_every_flag_the_parser_accepts_is_named_where_its_subcommand_is():
    """`verify --dataset` was named in no document and `export --out` only looked named.

    `--out` belongs to two subcommands and appeared once in nine markdown files, as
    `pipeline site --out docs/` — so a whole-corpus sweep called it documented while a
    reader of `pipeline export --help` had nowhere to read about it. That is
    `apply-scout`'s `--out` in a second repository, and it is why this asks per
    (subcommand, flag) rather than per flag.

    The parser is walked rather than listed, so a flag added later arrives with this guard
    already pointing at it.
    """
    units = [one for path in _docs() for one in _units(_read(path))]
    missing = []
    for name, sub in _subcommands(_parser()).items():
        scoped = [one for one in units if f"pipeline {name}" in one]
        assert scoped, f"no documentation names `pipeline {name}` at all"
        for action in sub._actions:
            flags = action.option_strings
            # The help action whole: filtering `--help` alone leaves `-h` behind and
            # demands the documents name a flag argparse wrote itself.
            if not flags or "--help" in flags:
                continue
            # Every spelling: naming one half of a `-b/--budget` pair leaves the other
            # unfindable, which is this defect in miniature.
            if not all(any(_named(flag, one) for one in scoped) for flag in flags):
                missing.append(f"{name} {'/'.join(flags)}")
    assert missing == [], f"accepted by the parser, documented for no such subcommand: {missing}"
