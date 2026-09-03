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
import os
import subprocess
import tomllib
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
from packaging.specifiers import SpecifierSet
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "data"


def _snapshots() -> pd.DataFrame:
    return pd.read_parquet(DATA / "snapshots.parquet")


def _manifest() -> dict:
    return json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))


def _git(*args: str) -> subprocess.CompletedProcess:
    """Run git, reporting a missing binary as a failed call rather than raising.

    `subprocess.run` raises `FileNotFoundError` where git is not installed, which turned
    the guard below into the one outcome it exists to avoid: an error instead of a skip.
    A machine with no git cannot answer reachability, which is the same answer a shallow
    clone gives, so it is returned the same way.
    """
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True
        )
    except OSError:
        return subprocess.CompletedProcess(args, returncode=127, stdout="", stderr="")


def _history_is_complete() -> bool:
    """A shallow clone cannot answer reachability, and CI checks out depth 1 by default.

    Reported rather than assumed: the test that needs full history says so and skips,
    instead of passing because `git` returned nothing.
    """
    if _git("rev-parse", "--git-dir").returncode != 0:
        return False
    return _git("rev-parse", "--is-shallow-repository").stdout.strip() == "false"


def _require_history() -> None:
    """Skip where reachability is unanswerable — but never in CI, where it is the point.

    `ci.yml` checks the test job out at `fetch-depth: 0` *for this test*, and the two were
    coupled by nothing but a comment in the YAML. Delete the block and the guard would go
    on reporting a skip, which reads identically to a pass in pytest's summary line — so
    the check could stop running without anything turning red. Under `CI` a shallow
    checkout is a broken workflow, not an environment to accommodate.
    """
    if _history_is_complete():
        return
    if os.environ.get("CI"):
        pytest.fail(
            "Reachability is unanswerable here: the checkout is shallow, or git is "
            "missing. This test needs the full history, which .github/workflows/ci.yml "
            "provides with `fetch-depth: 0` on the test job. Restore it — do not let "
            "this become a skip, which would report as green."
        )
    pytest.skip("shallow clone or no git — reachability is unanswerable here")


def test_every_git_sha_resolves_to_a_commit_in_this_history():
    """A provenance column naming commits nobody can reach is worse than no column.

    It reads as a record and answers as a 404. Reachability is asserted from HEAD rather
    than mere existence: after a rewrite the old commits linger as unreachable objects in
    a local clone, so `git cat-file -e` says yes to hashes a cloner cannot resolve. That
    is the exact false all-clear this test exists to prevent.
    """
    _require_history()

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


def test_the_manifest_names_the_newest_snapshot():
    """Agreeing with the row it names is not enough — it must name the last row.

    The test above pins manifest and parquet to one story about one build, and a stale
    manifest tells that story perfectly about an older one. An export that writes the
    tables and then fails before the manifest leaves exactly that: every row count still
    matches, `verify` still passes — it checks rows and bytes and never asks which
    snapshot — and the page publishes an older build's figures under today's date.
    """
    frame = _snapshots()
    newest = int(frame["snapshot_id"].max())
    assert _manifest()["snapshot"]["id"] == newest, (
        f"manifest names snapshot {_manifest()['snapshot']['id']}, "
        f"but the newest row in the parquet is {newest}"
    )


def test_every_published_parquet_was_written_by_a_supported_pyarrow():
    """The artifact must come from a toolchain this project says it supports.

    This suite exists because defects enter published artifacts *after* the export code
    has written them — and the commit that fixed the last one was itself applied by a
    pyarrow outside the declared range, leaving `snapshots.parquet` naming a writer nine
    files beside it did not. Harmless in that instance: same schema, same SNAPPY, same
    format 2.6, and the pinned reader parses it. The point is that nothing could see it.

    Read from the declaration rather than hardcoded, so the test tracks `pyproject.toml`
    instead of becoming a second place to update.
    """
    declared = [
        d
        for d in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
            "project"
        ]["dependencies"]
        if d.startswith("pyarrow")
    ]
    assert len(declared) == 1, f"expected one pyarrow requirement, found {declared}"
    supported = SpecifierSet(declared[0].removeprefix("pyarrow"))

    published = sorted(DATA.glob("*.parquet"))
    assert published, f"no parquet files under {DATA}"

    wrong = {}
    for path in published:
        created_by = pq.ParquetFile(path).metadata.created_by or ""
        # "parquet-cpp-arrow version 20.0.0" — the writer arrow stamps into every file.
        version = created_by.rsplit(" ", 1)[-1]
        if Version(version) not in supported:
            wrong[path.name] = created_by

    assert not wrong, (
        f"published by a pyarrow outside the declared {supported}: {wrong}"
    )
