"""Tests for the dataset as committed, rather than as the export code would produce it.

Every other test in this suite builds a synthetic database and checks what `export`
writes from it. That leaves the files a reader actually downloads guarded by nothing —
which is how `snapshots.parquet` came to carry fifteen commit hashes that a history
rewrite had orphaned, while `manifest.json` beside it named the same build differently.
The export code was never at fault and could not have caught it: the defect was applied
to the published artifact after it was written.

So these read `docs/data/` directly.
"""

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"


def _snapshots() -> pd.DataFrame:
    return pd.read_parquet(DATA / "snapshots.parquet")


def _manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True
    )


def _history_is_complete() -> bool:
    """A shallow clone cannot answer reachability, and CI checks out depth 1 by default.

    Reported rather than assumed: the test that needs full history says so and skips,
    instead of passing because `git` returned nothing.
    """
    if _git("rev-parse", "--git-dir").returncode != 0:
        return False
    return _git("rev-parse", "--is-shallow-repository").stdout.strip() == "false"


def test_every_git_sha_resolves_to_a_commit_in_this_history():
    """A provenance column naming commits nobody can reach is worse than no column.

    It reads as a record and answers as a 404. Reachability is asserted from HEAD rather
    than mere existence: after a rewrite the old commits linger as unreachable objects in
    a local clone, so `git cat-file -e` says yes to hashes a cloner cannot resolve. That
    is the exact false all-clear this test exists to prevent.
    """
    if not _history_is_complete():
        pytest.skip("shallow clone or no git — reachability is unanswerable here")

    unreachable = [
        sha
        for sha in sorted(_snapshots()["git_sha"].dropna().unique())
        if _git("merge-base", "--is-ancestor", sha, "HEAD").returncode != 0
    ]
    assert not unreachable, (
        f"{len(unreachable)} hash(es) in snapshots.parquet are not reachable from HEAD: "
        f"{unreachable}"
    )


def test_manifest_names_the_same_commit_as_the_row_it_points_at():
    """The manifest and the parquet describe one build and must not disagree about it.

    They did: the page stamp was repaired in `manifest.json` and the parquet was left
    alone, so snapshot 25 had two different commits depending on which file you opened.
    Needs no git, so it runs everywhere the suite does.
    """
    manifest = _manifest()
    frame = _snapshots()
    row = frame.loc[frame["snapshot_id"] == manifest["snapshot"]["id"]]

    assert len(row) == 1, f"manifest names snapshot {manifest['snapshot']['id']}, absent"
    assert row.iloc[0]["git_sha"] == manifest["git_sha"], (
        f"manifest says {manifest['git_sha']}, the row it names says "
        f"{row.iloc[0]['git_sha']}"
    )


def test_the_first_snapshot_keeps_its_missing_hash():
    """Snapshot 1 predates the stamping and has no commit; a remap must not invent one.

    Pinned because the obvious way to write a bulk rewrite — map every value — turns a
    truthful null into a fabricated provenance record, which is a worse defect than the
    one being fixed.
    """
    frame = _snapshots()
    assert frame.loc[frame["snapshot_id"] == 1, "git_sha"].isna().all()
    assert frame["git_sha"].isna().sum() == 1
